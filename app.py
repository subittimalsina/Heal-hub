from __future__ import annotations

import copy
import json
import random
import threading
from datetime import timedelta
from functools import wraps
from pathlib import Path
from statistics import mean
from typing import Any

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


SYMPTOM_LIBRARY: dict[str, dict[str, Any]] = {
    "chest pain": {"weight": 18, "tracks": ["cardiac"], "bed_trigger": True, "icu_trigger": True},
    "shortness of breath": {
        "weight": 20,
        "tracks": ["respiratory"],
        "bed_trigger": True,
        "icu_trigger": True,
    },
    "stroke signs": {"weight": 28, "tracks": ["neuro"], "bed_trigger": True, "icu_trigger": True},
    "major trauma": {"weight": 24, "tracks": ["trauma"], "bed_trigger": True, "icu_trigger": True},
    "bleeding": {"weight": 14, "tracks": ["trauma"], "bed_trigger": True, "icu_trigger": False},
    "fracture": {"weight": 10, "tracks": ["orthopedic"], "bed_trigger": True, "icu_trigger": False},
    "burn": {"weight": 15, "tracks": ["trauma"], "bed_trigger": True, "icu_trigger": False},
    "fever": {"weight": 6, "tracks": ["infectious"], "bed_trigger": False, "icu_trigger": False},
    "cough": {"weight": 5, "tracks": ["respiratory"], "bed_trigger": False, "icu_trigger": False},
    "dehydration": {"weight": 8, "tracks": ["general"], "bed_trigger": False, "icu_trigger": False},
    "sepsis signs": {"weight": 22, "tracks": ["infectious"], "bed_trigger": True, "icu_trigger": True},
    "abdominal pain": {"weight": 9, "tracks": ["general"], "bed_trigger": False, "icu_trigger": False},
    "pregnancy complication": {
        "weight": 17,
        "tracks": ["maternal"],
        "bed_trigger": True,
        "icu_trigger": False,
    },
    "mental distress": {
        "weight": 7,
        "tracks": ["behavioral"],
        "bed_trigger": False,
        "icu_trigger": False,
    },
}

SEVERITY_RULES = {
    "Low": 6,
    "Medium": 16,
    "High": 28,
    "Critical": 40,
}

BP_RULES = {
    "normal": {"weight": 0, "unstable": False},
    "high": {"weight": 6, "unstable": False},
    "low": {"weight": 12, "unstable": True},
    "critical": {"weight": 20, "unstable": True},
}

ARRIVAL_RULES = {
    "walk-in": 0,
    "ambulance": 10,
    "referral": 5,
}

SURGE_SCENARIOS: dict[str, dict[str, Any]] = {
    "mass_casualty": {
        "label": "Mass Casualty Surge",
        "description": "Simulates a highway collision that floods trauma capacity across the network.",
        "symptom_sets": [
            ["major trauma", "bleeding"],
            ["fracture", "bleeding"],
            ["burn", "major trauma"],
            ["chest pain", "major trauma"],
        ],
        "arrival_modes": ["ambulance", "ambulance", "referral", "walk-in"],
    },
    "oxygen_crunch": {
        "label": "Respiratory Oxygen Crunch",
        "description": "Creates a wave of low-oxygen patients that stresses ICU and respiratory coverage.",
        "symptom_sets": [
            ["shortness of breath", "cough"],
            ["shortness of breath", "fever"],
            ["sepsis signs", "shortness of breath"],
            ["shortness of breath", "chest pain"],
        ],
        "arrival_modes": ["walk-in", "walk-in", "ambulance", "referral"],
    },
    "maternal_referrals": {
        "label": "Maternal Referral Cluster",
        "description": "Simulates a spike in referrals requiring rapid maternal triage and transfer decisions.",
        "symptom_sets": [
            ["pregnancy complication", "bleeding"],
            ["pregnancy complication", "dehydration"],
            ["pregnancy complication", "fever"],
        ],
        "arrival_modes": ["referral", "ambulance", "walk-in"],
    },
    "routine_mix": {
        "label": "Routine Random Mix",
        "description": "Generates a mixed stream of general arrivals for quick testing and demo setup.",
        "symptom_sets": [
            ["fever", "cough"],
            ["abdominal pain", "dehydration"],
            ["fracture"],
            ["chest pain"],
            ["mental distress"],
        ],
        "arrival_modes": ["walk-in", "walk-in", "referral"],
    },
}

NAME_POOL = [
    "Aarav",
    "Aasha",
    "Bikash",
    "Deepa",
    "Gita",
    "Hari",
    "Ishita",
    "Janak",
    "Kiran",
    "Laxmi",
    "Milan",
    "Nabin",
    "Pema",
    "Ramesh",
    "Sabina",
    "Tsering",
]

DEMO_USERS: dict[str, dict[str, str]] = {
    "admin": {
        "password": "admin123",
        "display_name": "Admin Control",
        "role": "System Administrator",
    },
    "doctor": {
        "password": "doctor123",
        "display_name": "Dr. Sharma",
        "role": "Clinical Operations Lead",
    },
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def clock_label(total_minutes: int) -> str:
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def clamp(value: int | float, low: int | float, high: int | float) -> int | float:
    return max(low, min(high, value))


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def split_symptoms(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\n", ",").split(",")

    cleaned: list[str] = []
    for item in raw_items:
        symptom = str(item).strip().lower()
        if symptom and symptom not in cleaned:
            cleaned.append(symptom)
    return cleaned


def titlecase_words(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())


def safe_next_url(target: str | None) -> str | None:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


class HealHubEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rng = random.Random(21)
        self._sequence = 0
        self._hospital_blueprints = load_json(DATA_DIR / "hospitals.json")
        self._sample_patients = load_json(DATA_DIR / "sample_patients.json")
        self.hospitals: dict[str, dict[str, Any]] = {}
        self.patients: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.clock_minutes = 7 * 60 + 45
        self.reset(seed_demo=True)

    def reset(self, seed_demo: bool = True) -> dict[str, Any]:
        with self._lock:
            self._sequence = 0
            self.clock_minutes = 7 * 60 + 45
            self.hospitals = {
                hospital["id"]: copy.deepcopy(hospital) for hospital in self._hospital_blueprints
            }
            self.patients = {}
            self.events = []
            self._log_event(
                kind="system",
                title="HealHub command layer initialized",
                detail="The AI coordination engine has been reset for a fresh hospital operations demo.",
                tone="neutral",
            )
            if seed_demo:
                for payload in self._sample_patients:
                    self._register_patient(payload, log_intake=False)
                self._log_event(
                    kind="seed",
                    title="Seeded network scenario loaded",
                    detail="Demo hospitals and patient queues were preloaded to make the dashboard presentation-ready.",
                    tone="neutral",
                )
                self._rebalance()
            return self._build_snapshot()

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return self._build_snapshot()

    def add_patient(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            normalized = self._normalize_payload(raw_payload)
            patient = self._register_patient(normalized, log_intake=True)
            self._rebalance()
            snapshot = self._build_snapshot()
            row = self._patient_row(self.patients[patient["id"]])
            return {
                "message": f"{row['name']} assessed at urgency score {row['urgency_score']} ({row['triage_label']}).",
                "patient": row,
                "state": snapshot,
            }

    def generate_random_patients(
        self,
        count: int,
        scenario: str = "routine_mix",
        origin_hospital: str | None = None,
        surge: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            scenario_data = SURGE_SCENARIOS.get(scenario, SURGE_SCENARIOS["routine_mix"])
            for _ in range(count):
                payload = self._generate_synthetic_patient(scenario, origin_hospital)
                self._register_patient(payload, log_intake=False)

            self._log_event(
                kind="surge" if surge else "simulation",
                title=(
                    f"{scenario_data['label']} activated"
                    if surge
                    else f"{count} random patients generated"
                ),
                detail=(
                    f"{count} new arrivals were injected into the network. "
                    "HealHub re-ranked urgency, treatment order, and transfer recommendations instantly."
                ),
                tone="critical" if surge else "warning",
            )
            self._rebalance()
            return self._build_snapshot()

    def advance_time(self, minutes: int) -> dict[str, Any]:
        with self._lock:
            self.clock_minutes += minutes
            completed = self._complete_treatments()
            self._rebalance()
            self._log_event(
                kind="time",
                title=f"Simulation advanced by {minutes} minutes",
                detail=f"{completed} treatment cycles completed, releasing resources back into the network.",
                tone="neutral",
            )
            return self._build_snapshot()

    def _normalize_payload(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        symptoms = split_symptoms(raw_payload.get("symptoms", []))
        if not symptoms:
            raise ValueError("Add at least one symptom before submitting the intake form.")

        severity_level = str(raw_payload.get("severity_level", "Medium")).strip().title()
        if severity_level not in SEVERITY_RULES:
            severity_level = "Medium"

        blood_pressure_summary = str(
            raw_payload.get("blood_pressure_summary", "Normal")
        ).strip().lower()
        if blood_pressure_summary not in BP_RULES:
            blood_pressure_summary = "normal"

        arrival_mode = str(raw_payload.get("arrival_mode", "walk-in")).strip().lower()
        if arrival_mode not in ARRIVAL_RULES:
            arrival_mode = "walk-in"

        hospital_ids = {hospital["id"] for hospital in self._hospital_blueprints}
        preferred_hospital = raw_payload.get("preferred_hospital") or self._hospital_blueprints[0]["id"]
        if preferred_hospital not in hospital_ids:
            preferred_hospital = self._hospital_blueprints[0]["id"]

        try:
            age = int(raw_payload.get("age", 0))
            heart_rate = int(raw_payload.get("heart_rate", 86))
            oxygen_level = int(raw_payload.get("oxygen_level", 97))
        except (TypeError, ValueError) as exc:
            raise ValueError("Age, heart rate, and oxygen level must be numeric.") from exc

        age = int(clamp(age, 0, 110))
        heart_rate = int(clamp(heart_rate, 30, 220))
        oxygen_level = int(clamp(oxygen_level, 50, 100))

        return {
            "name": str(raw_payload.get("name") or raw_payload.get("patient_name") or "").strip() or None,
            "age": age,
            "symptoms": symptoms,
            "severity_level": severity_level,
            "heart_rate": heart_rate,
            "oxygen_level": oxygen_level,
            "blood_pressure_summary": blood_pressure_summary,
            "arrival_mode": arrival_mode,
            "chronic_disease": as_bool(raw_payload.get("chronic_disease", False)),
            "pregnancy": as_bool(raw_payload.get("pregnancy", False)),
            "notes": str(raw_payload.get("notes", "")).strip()[:320],
            "preferred_hospital": preferred_hospital,
        }

    def _register_patient(self, payload: dict[str, Any], log_intake: bool) -> dict[str, Any]:
        normalized = self._normalize_payload(payload)
        self._sequence += 1
        patient_id = f"HH-{self._sequence:03d}"
        scored = self._score_patient(normalized)
        patient = {
            "id": patient_id,
            "name": normalized["name"] or self._generate_name(),
            "age": normalized["age"],
            "symptoms": normalized["symptoms"],
            "severity_level": normalized["severity_level"],
            "heart_rate": normalized["heart_rate"],
            "oxygen_level": normalized["oxygen_level"],
            "blood_pressure_summary": normalized["blood_pressure_summary"],
            "arrival_mode": normalized["arrival_mode"],
            "chronic_disease": normalized["chronic_disease"],
            "pregnancy": normalized["pregnancy"],
            "notes": normalized["notes"],
            "preferred_hospital": normalized["preferred_hospital"],
            "assigned_hospital": normalized["preferred_hospital"],
            "arrival_minute": self.clock_minutes,
            "wait_minutes": 0,
            "estimated_wait_minutes": 0,
            "status": "waiting",
            "route_mode": "local",
            "recommended_action": "Wait and Monitor",
            "action_detail": "Queued for AI review.",
            "decision_reason": "Awaiting network prioritization.",
            "resource_reasoning": "Resource reasoning will appear after the scheduler runs.",
            "redirect_reason": None,
            "start_minute": None,
            "end_minute": None,
            "wait_before_treatment": None,
            "priority_score": 0,
            **scored,
        }
        self.patients[patient_id] = patient

        if log_intake:
            self._log_event(
                kind="intake",
                title=f"{patient_id} added to intake",
                detail=(
                    f"{patient['name']} entered the system with {patient['triage_label']} priority "
                    f"and urgency score {patient['urgency_score']}."
                ),
                tone=patient["severity_tone"],
            )

        return patient

    def _score_patient(self, payload: dict[str, Any]) -> dict[str, Any]:
        score = 0
        breakdown: list[dict[str, Any]] = []
        care_tracks: set[str] = set()
        bed_trigger = False
        icu_trigger = False

        def add_points(points: int, label: str, detail: str) -> None:
            nonlocal score
            score += points
            breakdown.append({"label": label, "points": points, "detail": detail})

        symptom_points = 0
        for symptom in payload["symptoms"]:
            profile = SYMPTOM_LIBRARY.get(
                symptom,
                {
                    "weight": 7,
                    "tracks": ["general"],
                    "bed_trigger": False,
                    "icu_trigger": False,
                },
            )
            symptom_points += profile["weight"]
            care_tracks.update(profile["tracks"])
            bed_trigger = bed_trigger or profile["bed_trigger"]
            icu_trigger = icu_trigger or profile["icu_trigger"]

        add_points(
            int(clamp(symptom_points, 0, 30)),
            "Symptom burden",
            ", ".join(titlecase_words(symptom) for symptom in payload["symptoms"]),
        )

        add_points(
            SEVERITY_RULES[payload["severity_level"]],
            "Reported severity",
            f"Intake marked as {payload['severity_level']}.",
        )

        age = payload["age"]
        if age >= 75:
            add_points(14, "Age risk", "Older adult with elevated risk of deterioration.")
        elif age >= 60:
            add_points(8, "Age risk", "Age-related risk increase applied.")
        elif age <= 5:
            add_points(10, "Age risk", "Very young child requires faster review.")
        elif age <= 12:
            add_points(6, "Age risk", "Pediatric case receives additional weight.")

        oxygen = payload["oxygen_level"]
        if oxygen <= 85:
            add_points(24, "Oxygen level", "Severely low oxygen saturation.")
            icu_trigger = True
            bed_trigger = True
        elif oxygen <= 89:
            add_points(18, "Oxygen level", "Low oxygen saturation indicates high respiratory risk.")
            icu_trigger = True
            bed_trigger = True
        elif oxygen <= 93:
            add_points(12, "Oxygen level", "Oxygen below preferred range.")
            bed_trigger = True
        elif oxygen <= 95:
            add_points(6, "Oxygen level", "Slight oxygen pressure detected.")

        heart_rate = payload["heart_rate"]
        if heart_rate < 45 or heart_rate > 140:
            add_points(18, "Heart rate", "Marked instability in heart rate.")
            icu_trigger = True
        elif heart_rate < 55 or heart_rate > 120:
            add_points(10, "Heart rate", "Abnormal heart rate needs fast review.")
        elif heart_rate < 60 or heart_rate > 105:
            add_points(6, "Heart rate", "Moderate heart rate deviation.")

        bp_rule = BP_RULES[payload["blood_pressure_summary"]]
        add_points(
            bp_rule["weight"],
            "Blood pressure",
            f"Blood pressure summary recorded as {payload['blood_pressure_summary'].title()}.",
        )
        if payload["blood_pressure_summary"] == "critical":
            icu_trigger = True
            bed_trigger = True

        add_points(
            ARRIVAL_RULES[payload["arrival_mode"]],
            "Arrival mode",
            f"Arrival via {payload['arrival_mode']}.",
        )

        if payload["chronic_disease"]:
            add_points(8, "Comorbidity", "Chronic disease increases deterioration risk.")

        if payload["pregnancy"]:
            add_points(6, "Pregnancy", "Pregnancy flagged for extra safeguarding.")
            bed_trigger = True

        vital_instability = (
            oxygen <= 90
            or heart_rate < 50
            or heart_rate > 125
            or payload["blood_pressure_summary"] in {"low", "critical"}
        )
        if vital_instability:
            add_points(8, "Vital instability", "One or more vitals are unstable.")

        urgency_score = int(clamp(score, 0, 100))
        if urgency_score >= 85:
            triage_label = "Critical"
            severity_tone = "critical"
        elif urgency_score >= 65:
            triage_label = "High"
            severity_tone = "warning"
        elif urgency_score >= 40:
            triage_label = "Medium"
            severity_tone = "neutral"
        else:
            triage_label = "Low"
            severity_tone = "stable"

        bed_need = 1 if bed_trigger or urgency_score >= 40 else 0
        icu_need = 1 if icu_trigger or urgency_score >= 88 else 0
        care_minutes = 20 + len(payload["symptoms"]) * 8 + SEVERITY_RULES[payload["severity_level"]] // 2
        if bed_need:
            care_minutes += 12
        if icu_need:
            care_minutes += 20
        if payload["chronic_disease"]:
            care_minutes += 8

        return {
            "urgency_score": urgency_score,
            "triage_label": triage_label,
            "severity_tone": severity_tone,
            "care_tracks": sorted(care_tracks),
            "doctor_need": 1,
            "bed_need": bed_need,
            "icu_need": icu_need,
            "care_minutes": int(clamp(care_minutes, 25, 180)),
            "score_breakdown": breakdown,
            "vital_instability": vital_instability,
        }

    def _rebalance(self) -> None:
        self._refresh_wait_times()
        self._complete_treatments()

        availability = {
            hospital_id: {
                "doctors": hospital["doctors_on_duty"],
                "beds": hospital["total_beds"],
                "icu": hospital["icu_beds"],
            }
            for hospital_id, hospital in self.hospitals.items()
        }

        for patient in self._patients_by_status("treating"):
            availability[patient["assigned_hospital"]]["doctors"] -= patient["doctor_need"]
            availability[patient["assigned_hospital"]]["beds"] -= patient["bed_need"]
            availability[patient["assigned_hospital"]]["icu"] -= patient["icu_need"]

        queue_counts = {hospital_id: 0 for hospital_id in self.hospitals}
        waiting = self._patients_by_status("waiting")
        waiting.sort(key=self._priority_sort_key, reverse=True)

        for patient in waiting:
            patient["wait_minutes"] = max(0, self.clock_minutes - patient["arrival_minute"])
            patient["priority_score"] = self._priority_score(patient)
            rankings = self._rank_hospitals(patient, availability, queue_counts)
            preferred_reason = self._preferred_blocker(patient, availability, queue_counts)
            immediate_option = next(
                (
                    hospital
                    for hospital in rankings
                    if self._can_treat(patient, availability[hospital["id"]])
                ),
                None,
            )

            if immediate_option:
                free_resources = availability[immediate_option["id"]].copy()
                patient["assigned_hospital"] = immediate_option["id"]
                patient["route_mode"] = (
                    "redirect"
                    if immediate_option["id"] != patient["preferred_hospital"]
                    else "local"
                )
                patient["estimated_wait_minutes"] = 0
                patient["redirect_reason"] = (
                    preferred_reason if patient["route_mode"] == "redirect" else None
                )
                if patient["route_mode"] == "redirect":
                    patient["recommended_action"] = "Redirect to Nearby Hospital"
                    patient["action_detail"] = (
                        f"Transfer to {immediate_option['name']} for immediate treatment."
                    )
                else:
                    patient["recommended_action"] = "Immediate Care"
                    patient["action_detail"] = (
                        f"Treat now at {immediate_option['name']}."
                    )
                patient["decision_reason"] = self._decision_explanation(
                    patient,
                    immediate_option,
                    preferred_reason,
                    immediate=True,
                )
                patient["resource_reasoning"] = self._resource_reasoning(
                    patient,
                    immediate_option,
                    free_resources,
                    preferred_reason,
                )

                availability[immediate_option["id"]]["doctors"] -= patient["doctor_need"]
                availability[immediate_option["id"]]["beds"] -= patient["bed_need"]
                availability[immediate_option["id"]]["icu"] -= patient["icu_need"]
                self._start_treatment(patient, immediate_option)
                continue

            fallback = rankings[0]
            queue_counts[fallback["id"]] += 1
            fallback_resources = availability[fallback["id"]].copy()
            patient["assigned_hospital"] = fallback["id"]
            patient["route_mode"] = (
                "redirect" if fallback["id"] != patient["preferred_hospital"] else "local"
            )
            patient["estimated_wait_minutes"] = self._estimate_eta(
                hospital_id=fallback["id"],
                patient=patient,
                queue_position=queue_counts[fallback["id"]],
                availability=availability,
            )
            patient["redirect_reason"] = preferred_reason if patient["route_mode"] == "redirect" else None
            patient["status"] = "waiting"

            if patient["route_mode"] == "redirect":
                patient["recommended_action"] = "Redirect to Nearby Hospital"
                patient["action_detail"] = (
                    f"Queue at {fallback['name']} to reduce delay."
                )
            else:
                patient["recommended_action"] = "Wait and Monitor"
                patient["action_detail"] = (
                    f"Wait at {fallback['name']} with AI monitoring."
                )

            patient["decision_reason"] = self._decision_explanation(
                patient,
                fallback,
                preferred_reason,
                immediate=False,
            )
            patient["resource_reasoning"] = self._resource_reasoning(
                patient,
                fallback,
                fallback_resources,
                preferred_reason,
            )

    def _start_treatment(self, patient: dict[str, Any], hospital: dict[str, Any]) -> None:
        patient["status"] = "treating"
        patient["start_minute"] = self.clock_minutes
        patient["end_minute"] = self.clock_minutes + patient["care_minutes"]
        patient["wait_before_treatment"] = self.clock_minutes - patient["arrival_minute"]
        self._log_event(
            kind="allocation",
            title=f"{patient['id']} moved to treatment",
            detail=(
                f"{patient['name']} assigned to {hospital['name']} "
                f"with action '{patient['recommended_action']}'."
            ),
            tone=patient["severity_tone"],
        )

    def _complete_treatments(self) -> int:
        completed = 0
        for patient in self._patients_by_status("treating"):
            if patient["end_minute"] is not None and patient["end_minute"] <= self.clock_minutes:
                patient["status"] = "completed"
                patient["recommended_action"] = "Immediate Care"
                patient["action_detail"] = "Treatment completed."
                patient["decision_reason"] = "Resources were released back into the network."
                patient["resource_reasoning"] = "This case is complete and no longer consumes active capacity."
                completed += 1
                self._log_event(
                    kind="discharge",
                    title=f"{patient['id']} completed treatment",
                    detail=(
                        f"{patient['name']} was discharged from "
                        f"{self._hospital_name(patient['assigned_hospital'])}, freeing capacity."
                    ),
                    tone="stable",
                )
        return completed

    def _generate_synthetic_patient(
        self,
        scenario_key: str,
        origin_hospital: str | None,
    ) -> dict[str, Any]:
        scenario = SURGE_SCENARIOS.get(scenario_key, SURGE_SCENARIOS["routine_mix"])
        symptoms = self._rng.choice(scenario["symptom_sets"])
        severity_level = self._derive_severity(symptoms)
        pregnancy = "pregnancy complication" in symptoms
        return {
            "name": self._generate_name(),
            "age": self._synthetic_age(symptoms),
            "symptoms": symptoms,
            "severity_level": severity_level,
            "heart_rate": self._synthetic_heart_rate(symptoms),
            "oxygen_level": self._synthetic_oxygen(symptoms),
            "blood_pressure_summary": self._synthetic_bp(symptoms),
            "arrival_mode": self._rng.choice(scenario["arrival_modes"]),
            "chronic_disease": self._rng.random() < 0.35,
            "pregnancy": pregnancy,
            "notes": "Synthetic simulation patient generated by HealHub.",
            "preferred_hospital": origin_hospital
            or self._rng.choice([hospital["id"] for hospital in self._hospital_blueprints]),
        }

    def _derive_severity(self, symptoms: list[str]) -> str:
        weight_sum = sum(
            SYMPTOM_LIBRARY.get(symptom, {"weight": 7})["weight"] for symptom in symptoms
        )
        if weight_sum >= 32:
            return "Critical"
        if weight_sum >= 22:
            return "High"
        if weight_sum >= 12:
            return "Medium"
        return "Low"

    def _synthetic_age(self, symptoms: list[str]) -> int:
        if "pregnancy complication" in symptoms:
            return self._rng.randint(21, 38)
        return self._rng.randint(7, 82)

    def _synthetic_heart_rate(self, symptoms: list[str]) -> int:
        if any(symptom in symptoms for symptom in ["major trauma", "bleeding", "sepsis signs"]):
            return self._rng.randint(112, 148)
        if "shortness of breath" in symptoms:
            return self._rng.randint(98, 132)
        return self._rng.randint(72, 108)

    def _synthetic_oxygen(self, symptoms: list[str]) -> int:
        if any(symptom in symptoms for symptom in ["shortness of breath", "sepsis signs"]):
            return self._rng.randint(82, 93)
        if "chest pain" in symptoms:
            return self._rng.randint(88, 96)
        return self._rng.randint(93, 99)

    def _synthetic_bp(self, symptoms: list[str]) -> str:
        if any(symptom in symptoms for symptom in ["major trauma", "bleeding", "sepsis signs"]):
            return self._rng.choice(["low", "critical", "high"])
        if "chest pain" in symptoms:
            return self._rng.choice(["high", "normal"])
        return self._rng.choice(list(BP_RULES.keys()))

    def _generate_name(self) -> str:
        return f"{self._rng.choice(NAME_POOL)} {chr(self._rng.randint(65, 90))}."

    def _refresh_wait_times(self) -> None:
        for patient in self.patients.values():
            if patient["status"] == "waiting":
                patient["wait_minutes"] = max(0, self.clock_minutes - patient["arrival_minute"])

    def _priority_score(self, patient: dict[str, Any]) -> float:
        wait_boost = min(patient["wait_minutes"], 120) * 1.3
        ambulance_boost = 7 if patient["arrival_mode"] == "ambulance" else 0
        icu_boost = 10 if patient["icu_need"] else 0
        instability_boost = 8 if patient["vital_instability"] else 0
        return round(
            patient["urgency_score"] + wait_boost + ambulance_boost + icu_boost + instability_boost,
            1,
        )

    def _priority_sort_key(self, patient: dict[str, Any]) -> tuple[float, int, int]:
        return (
            self._priority_score(patient),
            patient["urgency_score"],
            -patient["arrival_minute"],
        )

    def _rank_hospitals(
        self,
        patient: dict[str, Any],
        availability: dict[str, dict[str, int]],
        queue_counts: dict[str, int],
    ) -> list[dict[str, Any]]:
        rankings: list[tuple[float, dict[str, Any]]] = []
        for hospital in self.hospitals.values():
            resources = availability[hospital["id"]]
            specialty_fit = len(set(patient["care_tracks"]) & set(hospital["specialties"]))
            pressure = self._hospital_pressure(hospital["id"])
            queue_position = queue_counts[hospital["id"]] + 1
            eta = self._estimate_eta(hospital["id"], patient, queue_position, availability)
            score = (
                resources["doctors"] * 12
                + resources["beds"] * (8 if patient["bed_need"] else 4)
                + resources["icu"] * (16 if patient["icu_need"] else 5)
                + specialty_fit * 16
                + (12 if hospital["id"] == patient["preferred_hospital"] else 0)
                - queue_counts[hospital["id"]] * 10
                - pressure * 30
                - eta * 0.35
            )
            rankings.append((score, hospital))

        rankings.sort(key=lambda item: item[0], reverse=True)
        return [hospital for _, hospital in rankings]

    def _can_treat(self, patient: dict[str, Any], resources: dict[str, int]) -> bool:
        if resources["doctors"] < patient["doctor_need"]:
            return False
        if resources["beds"] < patient["bed_need"]:
            return False
        if resources["icu"] < patient["icu_need"]:
            return False
        return True

    def _estimate_eta(
        self,
        hospital_id: str,
        patient: dict[str, Any],
        queue_position: int,
        availability: dict[str, dict[str, int]],
    ) -> int:
        if self._can_treat(patient, availability[hospital_id]):
            return 0

        active = [
            current
            for current in self._patients_by_status("treating")
            if current["assigned_hospital"] == hospital_id
        ]
        if not active:
            return max(12, queue_position * 12)

        doctor_release = min(
            max(0, (current["end_minute"] or self.clock_minutes) - self.clock_minutes)
            for current in active
        )
        bed_release = 0
        icu_release = 0

        if patient["bed_need"]:
            bed_candidates = [current for current in active if current["bed_need"]]
            if bed_candidates:
                bed_release = min(
                    max(0, (current["end_minute"] or self.clock_minutes) - self.clock_minutes)
                    for current in bed_candidates
                )

        if patient["icu_need"]:
            icu_candidates = [current for current in active if current["icu_need"]]
            if icu_candidates:
                icu_release = min(
                    max(0, (current["end_minute"] or self.clock_minutes) - self.clock_minutes)
                    for current in icu_candidates
                )

        queue_delay = max(0, queue_position - 1) * 14
        return max(12, doctor_release, bed_release, icu_release) + queue_delay

    def _preferred_blocker(
        self,
        patient: dict[str, Any],
        availability: dict[str, dict[str, int]],
        queue_counts: dict[str, int],
    ) -> str:
        preferred_id = patient["preferred_hospital"]
        resources = availability[preferred_id]
        if resources["icu"] < patient["icu_need"]:
            return "no ICU slot available"
        if resources["doctors"] < patient["doctor_need"]:
            return "no doctor available"
        if resources["beds"] < patient["bed_need"]:
            return "no bed available"

        preferred_eta = self._estimate_eta(
            preferred_id,
            patient,
            queue_counts[preferred_id] + 1,
            availability,
        )
        if preferred_eta > 45:
            return "wait time too high"
        return "local capacity available"

    def _hospital_pressure(self, hospital_id: str) -> float:
        hospital = self.hospitals[hospital_id]
        active = [
            patient
            for patient in self._patients_by_status("treating")
            if patient["assigned_hospital"] == hospital_id
        ]
        waiting = [
            patient
            for patient in self._patients_by_status("waiting")
            if patient["assigned_hospital"] == hospital_id
        ]
        doctor_used = sum(patient["doctor_need"] for patient in active)
        bed_used = sum(patient["bed_need"] for patient in active)
        icu_used = sum(patient["icu_need"] for patient in active)
        queue_ratio = min(len(waiting) / 6, 1)
        doctor_ratio = doctor_used / hospital["doctors_on_duty"]
        bed_ratio = bed_used / hospital["total_beds"]
        icu_ratio = icu_used / hospital["icu_beds"]
        return round(
            doctor_ratio * 0.35 + bed_ratio * 0.35 + icu_ratio * 0.2 + queue_ratio * 0.1,
            2,
        )

    def _decision_explanation(
        self,
        patient: dict[str, Any],
        hospital: dict[str, Any],
        preferred_reason: str,
        immediate: bool,
    ) -> str:
        specialty_fit = len(set(patient["care_tracks"]) & set(hospital["specialties"]))
        if immediate and patient["route_mode"] == "redirect":
            return (
                f"{hospital['name']} can absorb the case immediately and improves network flow. "
                f"Preferred hospital blocker: {preferred_reason}. Specialty matches: {specialty_fit}."
            )
        if immediate:
            return (
                f"{hospital['name']} has capacity right now, so HealHub escalated the patient directly into treatment."
            )
        if patient["route_mode"] == "redirect":
            return (
                f"HealHub recommends queueing at {hospital['name']} because the preferred site is constrained "
                f"by {preferred_reason}, and this option reduces system-level congestion."
            )
        return (
            f"{hospital['name']} remains the best fit, but no immediate slot is free. "
            "HealHub keeps the patient in a monitored queue and rechecks capacity continuously."
        )

    def _resource_reasoning(
        self,
        patient: dict[str, Any],
        hospital: dict[str, Any],
        free_resources: dict[str, int],
        preferred_reason: str,
    ) -> str:
        specialty_fit = len(set(patient["care_tracks"]) & set(hospital["specialties"]))
        return (
            f"{hospital['name']} had {free_resources['doctors']} doctor slots, "
            f"{free_resources['beds']} beds, and {free_resources['icu']} ICU slots available "
            f"when this decision was made. Specialty overlap: {specialty_fit}. "
            f"Preferred-hospital constraint: {preferred_reason}."
        )

    def _build_snapshot(self) -> dict[str, Any]:
        active = self._patients_by_status("treating")
        waiting = self._patients_by_status("waiting")
        completed = self._patients_by_status("completed")

        hospitals_view = []
        total_doctors = 0
        total_doctors_used = 0
        total_beds = 0
        total_beds_used = 0
        total_icu = 0
        total_icu_used = 0

        for hospital in self.hospitals.values():
            treating = [
                patient for patient in active if patient["assigned_hospital"] == hospital["id"]
            ]
            queued = [
                patient for patient in waiting if patient["assigned_hospital"] == hospital["id"]
            ]
            treating.sort(key=lambda patient: patient["end_minute"] or 10**9)
            queued.sort(key=self._priority_sort_key, reverse=True)

            doctors_used = sum(patient["doctor_need"] for patient in treating)
            beds_used = sum(patient["bed_need"] for patient in treating)
            icu_used = sum(patient["icu_need"] for patient in treating)

            total_doctors += hospital["doctors_on_duty"]
            total_doctors_used += doctors_used
            total_beds += hospital["total_beds"]
            total_beds_used += beds_used
            total_icu += hospital["icu_beds"]
            total_icu_used += icu_used

            available_doctors = hospital["doctors_on_duty"] - doctors_used
            available_beds = hospital["total_beds"] - beds_used
            available_icu = hospital["icu_beds"] - icu_used
            pressure = round(self._hospital_pressure(hospital["id"]) * 100)
            next_release = min(
                (
                    max(0, (patient["end_minute"] or self.clock_minutes) - self.clock_minutes)
                    for patient in treating
                ),
                default=0,
            )

            if pressure >= 85 or len(queued) >= 4:
                overload_status = "Overloaded"
                tone = "critical"
            elif pressure >= 65 or len(queued) >= 2:
                overload_status = "Busy"
                tone = "warning"
            else:
                overload_status = "Stable"
                tone = "stable"

            hospitals_view.append(
                {
                    "id": hospital["id"],
                    "name": hospital["name"],
                    "city": hospital["city"],
                    "specialties": hospital["specialties"],
                    "total_beds": hospital["total_beds"],
                    "available_beds": available_beds,
                    "doctors_on_duty": hospital["doctors_on_duty"],
                    "available_doctors": available_doctors,
                    "icu_beds": hospital["icu_beds"],
                    "available_icu": available_icu,
                    "waiting_queue": len(queued),
                    "patients_being_treated": len(treating),
                    "overload_status": overload_status,
                    "severity_tone": tone,
                    "utilization": pressure,
                    "next_release_minutes": next_release,
                    "queue": [self._patient_card(patient) for patient in queued[:4]],
                    "treating": [self._patient_card(patient) for patient in treating[:4]],
                }
            )

        doctor_util = total_doctors_used / total_doctors if total_doctors else 0
        bed_util = total_beds_used / total_beds if total_beds else 0
        icu_util = total_icu_used / total_icu if total_icu else 0
        resource_utilization = round(
            (doctor_util * 0.35 + bed_util * 0.4 + icu_util * 0.25) * 100
        )
        available_beds = max(0, total_beds - total_beds_used)
        available_doctors = max(0, total_doctors - total_doctors_used)
        available_icu = max(0, total_icu - total_icu_used)
        live_total = len(active) + len(waiting)
        redirected_live = sum(
            1
            for patient in active + waiting
            if patient["assigned_hospital"] != patient["preferred_hospital"]
        )

        live_patients = sorted(
            active + waiting,
            key=lambda patient: (
                1 if patient["status"] == "treating" else 0,
                self._priority_score(patient),
                patient["urgency_score"],
            ),
            reverse=True,
        )

        metrics = {
            "total_patients": live_total,
            "total_incoming_patients": len(self.patients),
            "critical_cases": sum(
                1 for patient in active + waiting if patient["triage_label"] == "Critical"
            ),
            "available_beds": available_beds,
            "doctors_on_duty": total_doctors,
            "available_doctors": available_doctors,
            "icu_availability": available_icu,
            "redirected_patients": redirected_live,
            "redirected_cases": redirected_live,
            "average_wait_time": round(mean([patient["wait_minutes"] for patient in waiting]), 1)
            if waiting
            else 0,
            "utilization_rate": resource_utilization,
            "resource_utilization": resource_utilization,
            "waiting_patients": len(waiting),
            "active_treatments": len(active),
            "overloaded_hospitals": sum(
                1 for hospital in hospitals_view if hospital["overload_status"] == "Overloaded"
            ),
            "completed_today": len(completed),
        }

        patients_view = [self._patient_row(patient) for patient in live_patients[:20]]
        default_selected_patient_id = patients_view[0]["id"] if patients_view else None

        return {
            "clock": clock_label(self.clock_minutes),
            "clock_minutes": self.clock_minutes,
            "metrics": metrics,
            "network": {
                "total_beds": total_beds,
                "used_beds": total_beds_used,
                "available_beds": available_beds,
                "total_doctors": total_doctors,
                "used_doctors": total_doctors_used,
                "available_doctors": available_doctors,
                "total_icu": total_icu,
                "used_icu": total_icu_used,
                "available_icu": available_icu,
            },
            "insights": self._build_insights(hospitals_view, metrics),
            "hospitals": hospitals_view,
            "patients": patients_view,
            "events": list(reversed(self.events[-12:])),
            "default_selected_patient_id": default_selected_patient_id,
            "catalog": {
                "symptoms": sorted(SYMPTOM_LIBRARY.keys()),
                "hospitals": [
                    {"id": hospital["id"], "name": hospital["name"]}
                    for hospital in self._hospital_blueprints
                ],
                "severity_levels": list(SEVERITY_RULES.keys()),
                "arrival_modes": list(ARRIVAL_RULES.keys()),
                "blood_pressure_options": [value.title() for value in BP_RULES.keys()],
                "surge_scenarios": [
                    {
                        "id": scenario_id,
                        "label": scenario["label"],
                        "description": scenario["description"],
                    }
                    for scenario_id, scenario in SURGE_SCENARIOS.items()
                ],
            },
        }

    def _build_insights(
        self,
        hospitals: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> list[dict[str, str]]:
        insights: list[dict[str, str]] = []

        if metrics["critical_cases"] > 0 and metrics["waiting_patients"] > 0:
            insights.append(
                {
                    "tone": "critical",
                    "title": "Critical queue requires intervention",
                    "body": (
                        f"{metrics['critical_cases']} critical cases are active across the network, "
                        "and some high-acuity patients are still waiting for scarce capacity."
                    ),
                }
            )

        hottest = max(hospitals, key=lambda hospital: hospital["utilization"], default=None)
        if hottest and hottest["utilization"] >= 80:
            insights.append(
                {
                    "tone": "warning",
                    "title": f"{hottest['name']} is near saturation",
                    "body": (
                        f"Utilization has reached {hottest['utilization']}%, so HealHub is likely "
                        "to redirect medium-acuity arrivals away from this facility."
                    ),
                }
            )

        if metrics["redirected_cases"]:
            insights.append(
                {
                    "tone": "neutral",
                    "title": "Redistribution engine is active",
                    "body": (
                        f"{metrics['redirected_cases']} live cases are being absorbed by alternate hospitals "
                        "to reduce bottlenecks and preserve treatment speed."
                    ),
                }
            )

        if metrics["resource_utilization"] < 55:
            insights.append(
                {
                    "tone": "stable",
                    "title": "System has recovery headroom",
                    "body": "Current capacity can absorb additional referrals or a small test surge without immediate breakdown.",
                }
            )
        elif metrics["resource_utilization"] >= 80:
            insights.append(
                {
                    "tone": "critical",
                    "title": "Network-wide strain is rising",
                    "body": "A new influx would likely increase wait times sharply unless non-critical cases are redirected early.",
                }
            )

        if not insights:
            insights.append(
                {
                    "tone": "stable",
                    "title": "No urgent capacity risk detected",
                    "body": "HealHub is keeping hospital workloads balanced at the moment.",
                }
            )

        return insights[:4]

    def _patient_card(self, patient: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": patient["id"],
            "name": patient["name"],
            "triage_label": patient["triage_label"],
            "urgency_score": patient["urgency_score"],
            "recommended_action": patient["recommended_action"],
            "action_detail": patient["action_detail"],
            "estimated_wait_minutes": patient["estimated_wait_minutes"],
            "severity_tone": patient["severity_tone"],
            "status": patient["status"],
        }

    def _patient_row(self, patient: dict[str, Any]) -> dict[str, Any]:
        remaining = (
            max(0, (patient["end_minute"] or self.clock_minutes) - self.clock_minutes)
            if patient["status"] == "treating"
            else None
        )
        return {
            "id": patient["id"],
            "name": patient["name"],
            "age": patient["age"],
            "symptoms": [titlecase_words(symptom) for symptom in patient["symptoms"]],
            "severity_level": patient["severity_level"],
            "heart_rate": patient["heart_rate"],
            "oxygen_level": patient["oxygen_level"],
            "blood_pressure_summary": patient["blood_pressure_summary"].title(),
            "arrival_mode": patient["arrival_mode"],
            "chronic_disease": patient["chronic_disease"],
            "pregnancy": patient["pregnancy"],
            "notes": patient["notes"],
            "status": patient["status"],
            "urgency_score": patient["urgency_score"],
            "triage_label": patient["triage_label"],
            "priority_score": self._priority_score(patient),
            "recommended_action": patient["recommended_action"],
            "action_detail": patient["action_detail"],
            "assigned_hospital": self._hospital_name(patient["assigned_hospital"]),
            "preferred_hospital": self._hospital_name(patient["preferred_hospital"]),
            "route_mode": patient["route_mode"],
            "estimated_wait_minutes": patient["estimated_wait_minutes"],
            "wait_minutes": patient["wait_minutes"],
            "care_remaining_minutes": remaining,
            "severity_tone": patient["severity_tone"],
            "decision_reason": patient["decision_reason"],
            "resource_reasoning": patient["resource_reasoning"],
            "redirect_reason": patient["redirect_reason"],
            "why_this_decision": {
                "score_breakdown": patient["score_breakdown"],
                "resource_reasoning": patient["resource_reasoning"],
                "decision_reason": patient["decision_reason"],
                "redirect_reason": patient["redirect_reason"],
            },
        }

    def _hospital_name(self, hospital_id: str) -> str:
        hospital = self.hospitals.get(hospital_id)
        return hospital["name"] if hospital else hospital_id

    def _patients_by_status(self, status: str) -> list[dict[str, Any]]:
        return [patient for patient in self.patients.values() if patient["status"] == status]

    def _log_event(self, kind: str, title: str, detail: str, tone: str) -> None:
        self.events.append(
            {
                "kind": kind,
                "title": title,
                "detail": detail,
                "tone": tone,
                "clock": clock_label(self.clock_minutes),
            }
        )
        self.events = self.events[-40:]


app = Flask(__name__)
app.config["SECRET_KEY"] = "healhub-hackathon-secret-key"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
engine = HealHubEngine()


def login_required(view: Any) -> Any:
    @wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if "user" not in session:
            if request.path.startswith("/api/"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Authentication required.",
                            "redirect": url_for("login", next=request.path),
                        }
                    ),
                    401,
                )
            flash("Please log in to access the HealHub dashboard.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


@app.context_processor
def inject_template_state() -> dict[str, Any]:
    return {
        "current_user": session.get("user"),
        "is_logged_in": "user" in session,
    }


@app.get("/")
def landing_page() -> str:
    return render_template(
        "index.html",
        active_page="home",
        body_class="page-landing",
        page_id="home",
        page_title="HealHub | AI-Powered Smart Health Systems",
    )


@app.get("/platform")
def platform_page() -> str:
    return render_template(
        "platform.html",
        active_page="platform",
        body_class="page-platform",
        page_id="platform",
        page_title="HealHub Platform",
    )


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if "user" in session:
        return redirect(url_for("dashboard_page"))

    next_url = safe_next_url(request.args.get("next")) or safe_next_url(request.form.get("next"))

    if request.method == "POST":
        if request.form.get("demo_login"):
            username = "admin"
            password = DEMO_USERS["admin"]["password"]
        else:
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")

        user = DEMO_USERS.get(username)
        if user and user["password"] == password:
            session.permanent = bool(request.form.get("remember_me"))
            session["user"] = {
                "username": username,
                "display_name": user["display_name"],
                "role": user["role"],
            }
            flash(f"Welcome to HealHub, {user['display_name']}.", "success")
            return redirect(next_url or url_for("dashboard_page"))

        flash("Invalid username or password. Try the demo login if needed.", "error")

    return render_template(
        "login.html",
        active_page="login",
        body_class="page-auth",
        page_id="login",
        next_url=next_url or "",
        demo_users=[
            {
                "username": username,
                "password": user["password"],
                "display_name": user["display_name"],
                "role": user["role"],
            }
            for username, user in DEMO_USERS.items()
        ],
        page_title="HealHub Login",
    )


@app.get("/logout")
def logout() -> Any:
    session.pop("user", None)
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("landing_page"))


@app.get("/dashboard")
@login_required
def dashboard_page() -> str:
    return render_template(
        "dashboard.html",
        active_page="dashboard",
        body_class="page-dashboard",
        page_id="dashboard",
        page_title="HealHub Dashboard",
    )


@app.get("/about")
def about_page() -> str:
    return render_template(
        "about.html",
        active_page="about",
        body_class="page-about",
        page_id="about",
        page_title="About HealHub",
    )


@app.get("/api/dashboard-data")
@login_required
def dashboard_data() -> Any:
    return jsonify(engine.get_state())


@app.post("/api/patient-intake")
@login_required
def patient_intake() -> Any:
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        result = engine.add_patient(payload)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True, **result})


@app.post("/api/surge-mode")
@login_required
def surge_mode() -> Any:
    payload = request.get_json(silent=True) or {}
    scenario = str(payload.get("scenario", "mass_casualty"))
    count = int(clamp(int(payload.get("count", 12)), 6, 30))
    origin_hospital = payload.get("origin_hospital") or None
    state = engine.generate_random_patients(
        count=count,
        scenario=scenario,
        origin_hospital=origin_hospital,
        surge=True,
    )
    return jsonify(
        {
            "success": True,
            "message": f"Surge mode activated with {count} simulated arrivals.",
            "state": state,
        }
    )


@app.post("/api/random-patients")
@app.post("/api/generate-random-patients")
@login_required
def generate_random_patients() -> Any:
    payload = request.get_json(silent=True) or {}
    count = int(clamp(int(payload.get("count", 4)), 1, 15))
    scenario = str(payload.get("scenario", "routine_mix"))
    origin_hospital = payload.get("origin_hospital") or None
    state = engine.generate_random_patients(
        count=count,
        scenario=scenario,
        origin_hospital=origin_hospital,
        surge=False,
    )
    return jsonify(
        {
            "success": True,
            "message": f"{count} random patients added to the network.",
            "state": state,
        }
    )


@app.post("/api/advance-time")
@login_required
def advance_time() -> Any:
    payload = request.get_json(silent=True) or {}
    minutes = int(clamp(int(payload.get("minutes", 30)), 5, 180))
    state = engine.advance_time(minutes)
    return jsonify(
        {
            "success": True,
            "message": f"Simulation advanced by {minutes} minutes.",
            "state": state,
        }
    )


@app.post("/api/reset")
@login_required
def reset() -> Any:
    state = engine.reset(seed_demo=True)
    return jsonify({"success": True, "message": "Simulation reset.", "state": state})


if __name__ == "__main__":
    app.run(debug=True)
