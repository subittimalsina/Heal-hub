from __future__ import annotations

import copy
import json
import random
import threading
from datetime import datetime, timedelta
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
from uuid import uuid4


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
        "role": "admin",
        "headline": "System Administrator",
    },
    "doctor": {
        "password": "doctor123",
        "display_name": "Dr. Sharma",
        "role": "doctor",
        "headline": "Clinical Operations Lead",
    },
    "patient": {
        "password": "patient123",
        "display_name": "Aasha G.",
        "role": "patient",
        "headline": "Patient Portal",
    },
}
LOGIN_ENABLED_USERNAMES = ("patient", "doctor")

PRESCRIPTIONS_PATH = DATA_DIR / "prescriptions.json"
DOCTOR_NOTES_PATH = DATA_DIR / "doctor_notes.json"

PORTAL_PATIENTS: dict[str, dict[str, Any]] = {
    "patient": {
        "id": "patient-aasha",
        "username": "patient",
        "display_name": "Aasha G.",
        "age": 74,
        "doctor_name": "Dr. Sharma",
        "doctor_username": "doctor",
        "hospital": "Kathmandu General Hospital",
        "primary_track": "cardiovascular",
        "risk_label": "Elevated cardiometabolic risk",
        "summary": "Needs close BP and glucose monitoring with medication adherence support.",
        "next_follow_up": "2026-04-05",
        "conditions": ["Hypertension", "Type 2 diabetes risk", "Shortness of breath history"],
        "care_goals": [
            "Keep blood pressure stable",
            "Support medication adherence",
            "Escalate quickly if chest symptoms return",
        ],
    }
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_portal_records() -> None:
    if not PRESCRIPTIONS_PATH.exists():
        save_json(
            PRESCRIPTIONS_PATH,
            [
                {
                    "id": "rx-001",
                    "patient_username": "patient",
                    "doctor_username": "doctor",
                    "doctor_name": "Dr. Sharma",
                    "medicine_name": "Amlodipine",
                    "dosage": "5 mg",
                    "frequency": "Once daily",
                    "duration": "30 days",
                    "purpose": "Blood pressure support",
                    "instructions": "Take after breakfast and track BP twice weekly.",
                    "warnings": "Seek urgent care if chest pain worsens or fainting occurs.",
                    "refill_status": "Refill due in 12 days",
                    "created_at": "2026-03-25 09:10",
                },
                {
                    "id": "rx-002",
                    "patient_username": "patient",
                    "doctor_username": "doctor",
                    "doctor_name": "Dr. Sharma",
                    "medicine_name": "Metformin",
                    "dosage": "500 mg",
                    "frequency": "Twice daily",
                    "duration": "30 days",
                    "purpose": "Glucose control",
                    "instructions": "Take with meals and hydrate well.",
                    "warnings": "Pause and seek review if severe vomiting or dehydration occurs.",
                    "refill_status": "In active cycle",
                    "created_at": "2026-03-24 17:45",
                },
            ],
        )
    if not DOCTOR_NOTES_PATH.exists():
        save_json(
            DOCTOR_NOTES_PATH,
            [
                {
                    "id": "note-001",
                    "patient_username": "patient",
                    "doctor_username": "doctor",
                    "note": "BP still fluctuates. Continue adherence coaching and maintain low-salt diet.",
                    "risk_level": "high",
                    "diagnosis_tags": ["cardiovascular", "diabetes_risk"],
                    "created_at": "2026-03-25 09:15",
                }
            ],
        )


def portal_patient_for_user(user: dict[str, Any] | None) -> dict[str, Any]:
    if not user:
        return PORTAL_PATIENTS["patient"]
    return PORTAL_PATIENTS.get(user.get("username", ""), PORTAL_PATIENTS["patient"])


def patient_prescriptions(username: str) -> list[dict[str, Any]]:
    prescriptions = load_records(PRESCRIPTIONS_PATH)
    items = [item for item in prescriptions if item.get("patient_username") == username]
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def patient_notes(username: str) -> list[dict[str, Any]]:
    notes = load_records(DOCTOR_NOTES_PATH)
    items = [item for item in notes if item.get("patient_username") == username]
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def ai_triage_summary(symptoms: list[str]) -> dict[str, Any]:
    lowered = [item.lower() for item in symptoms]
    track = "general wellness"
    urgency = "Routine review"
    guidance = ["Keep symptoms logged and monitor for change."]

    if any(term in lowered for term in ["chest pain", "shortness of breath"]):
        track = "cardiovascular and diabetes"
        urgency = "Prompt clinical review"
        guidance = [
            "Check blood pressure, pulse, and oxygen level promptly.",
            "Escalate urgently if chest pain is severe, persistent, or paired with fainting.",
        ]
    elif any(term in lowered for term in ["fever", "cough", "sepsis signs"]):
        track = "infectious disease"
        urgency = "Rapid assessment"
        guidance = [
            "Review fever duration, respiratory symptoms, and exposure history.",
            "Use isolation precautions if symptoms suggest a transmissible infection.",
        ]
    elif any(term in lowered for term in ["mental distress"]):
        track = "mental health"
        urgency = "Supportive follow-up"
        guidance = [
            "Ask about sleep, stress load, and immediate safety concerns.",
            "Offer clinician review if distress is escalating or persistent.",
        ]

    return {
        "track": track,
        "urgency": urgency,
        "guidance": guidance,
        "disclaimer": "Heal Hub AI highlights risk patterns and next-step guidance only. It does not provide a diagnosis.",
    }


def build_ai_agent_result(symptom_text: str) -> dict[str, Any]:
    symptoms = split_symptoms(symptom_text)
    summary = ai_triage_summary(symptoms)
    return {
        "symptoms": symptoms,
        "summary": summary,
        "headline": f"Likely priority track: {summary['track'].title()}",
    }


def role_dashboard_endpoint(user: dict[str, Any]) -> str:
    role = user.get("role")
    if role == "doctor":
        return "doctor_dashboard_page"
    if role == "patient":
        return "patient_dashboard_page"
    return "dashboard_page"


seed_portal_records()


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


def build_mood_check_result(
    feeling: str,
    stress_level: int,
    sleep_hours: float,
    energy_level: str,
) -> dict[str, Any]:
    actions: list[str] = []

    if stress_level >= 4:
        actions.append("Take five quiet minutes for breathing, meditation, or a short reset.")

    if sleep_hours < 6:
        actions.append("Protect your next sleep window and keep the rest of the day lighter.")

    if energy_level == "low":
        actions.append("Prioritize hydration, a simple meal, and gentle movement instead of heavy tasks.")
    elif energy_level == "high":
        actions.append("Use the extra energy for a steady walk or another calming routine that keeps momentum going.")

    if feeling in {"anxious", "overwhelmed", "sad", "lonely"}:
        actions.append("Reach out to someone you trust and avoid carrying the day on your own.")
    elif feeling in {"calm", "hopeful", "good"}:
        actions.append("Keep the routines that are already helping you feel stable today.")

    if not actions:
        actions.append("Keep a balanced rhythm today with water, meals, movement, and a short check-in tonight.")

    if stress_level >= 4 or sleep_hours < 5 or energy_level == "low":
        title = "Take a gentler recovery day."
        summary = (
            "Your check-in suggests that recovery support matters today. Aim for lower stress,"
            " better rest, and simple routines that help you settle."
        )
        tone = "warning"
        status_label = "Needs reset"
    elif stress_level <= 2 and sleep_hours >= 7 and energy_level in {"steady", "high"}:
        title = "You are in a strong recovery zone."
        summary = (
            "Your signals look fairly balanced today. Keep the habits that are supporting your"
            " mood, sleep, and energy."
        )
        tone = "stable"
        status_label = "Well balanced"
    else:
        title = "A small reset could help today."
        summary = (
            "Your check-in looks mixed, which is normal. A few supportive routines can help you"
            " stay steady without overloading yourself."
        )
        tone = "neutral"
        status_label = "Moderate load"

    return {
        "title": title,
        "summary": summary,
        "tone": tone,
        "status_label": status_label,
        "actions": actions,
    }


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
                title="Heal Hub command layer initialized",
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
                    "Heal Hub re-ranked urgency, treatment order, and transfer recommendations instantly."
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
            "notes": "Synthetic simulation patient generated by Heal Hub.",
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
                f"{hospital['name']} has capacity right now, so Heal Hub escalated the patient directly into treatment."
            )
        if patient["route_mode"] == "redirect":
            return (
                f"Heal Hub recommends queueing at {hospital['name']} because the preferred site is constrained "
                f"by {preferred_reason}, and this option reduces system-level congestion."
            )
        return (
            f"{hospital['name']} remains the best fit, but no immediate slot is free. "
            "Heal Hub keeps the patient in a monitored queue and rechecks capacity continuously."
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
                        f"Utilization has reached {hottest['utilization']}%, so Heal Hub is likely "
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
                    "body": "Heal Hub is keeping hospital workloads balanced at the moment.",
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
            flash("Please log in to access the Heal Hub dashboard.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


@app.context_processor
def inject_template_state() -> dict[str, Any]:
    return {
        "current_user": session.get("user"),
        "is_logged_in": "user" in session,
        "demo_users": [
            {
                "username": username,
                "password": user["password"],
                "display_name": user["display_name"],
                "role": user["role"],
                "headline": user.get("headline", user["role"].title()),
            }
            for username in LOGIN_ENABLED_USERNAMES
            for user in [DEMO_USERS[username]]
        ],
    }


@app.get("/")
def landing_page() -> str:
    return render_template(
        "index.html",
        active_page="home",
        body_class="page-landing",
        page_id="home",
        page_title="Heal Hub | Stories, Support, and Smarter Care",
        platform_snapshot=build_platform_snapshot(),
        featured_movies=MOVIES_DATA[:4],
        featured_therapists=THERAPISTS_DATA[:3],
        featured_groups=COMMUNITY_GROUPS[:3],
        featured_safety_cards=SAFETY_CARDS[:3],
    )


@app.get("/platform")
def platform_page() -> Any:
    return redirect(url_for("landing_page"))


@app.route("/ai-agent", methods=["GET", "POST"])
def ai_agent_page() -> str:
    symptom_text = ""
    agent_result: dict[str, Any] | None = None
    if request.method == "POST":
        symptom_text = request.form.get("symptoms", "").strip()
        if symptom_text:
            agent_result = build_ai_agent_result(symptom_text)
    return render_template(
        "ai_agent.html",
        active_page="ai-agent",
        body_class="page-ai-agent",
        page_id="ai-agent",
        page_title="Heal Hub AI Agent",
        symptom_text=symptom_text,
        agent_result=agent_result,
    )


@app.get("/medicine-search")
def medicine_search_page() -> str:
    return render_template(
        "medicine_search.html",
        active_page="medicine-search",
        body_class="page-medicine-search",
        page_id="medicine-search",
        page_title="Heal Hub Medicine Search",
    )


@app.get("/wellness")
def wellness_page() -> str:
    return render_template(
        "wellness.html",
        active_page="wellness",
        body_class="page-wellness",
        page_id="wellness",
        page_title="Heal Hub Wellness",
    )


@app.route("/mood-check", methods=["GET", "POST"])
def mood_check_page() -> str:
    form_values = {
        "feeling": "calm",
        "stress_level": 3,
        "sleep_hours": 7,
        "energy_level": "steady",
    }
    mood_result: dict[str, Any] | None = None

    if request.method == "POST":
        feeling = str(request.form.get("feeling", "calm")).strip().lower() or "calm"
        energy_level = str(request.form.get("energy_level", "steady")).strip().lower() or "steady"

        try:
            stress_level = int(request.form.get("stress_level", 3))
        except (TypeError, ValueError):
            stress_level = 3

        try:
            sleep_hours = float(request.form.get("sleep_hours", 7))
        except (TypeError, ValueError):
            sleep_hours = 7.0

        stress_level = int(clamp(stress_level, 1, 5))
        sleep_hours = float(clamp(sleep_hours, 0, 24))

        form_values = {
            "feeling": feeling,
            "stress_level": stress_level,
            "sleep_hours": sleep_hours,
            "energy_level": energy_level,
        }
        mood_result = build_mood_check_result(
            feeling=feeling,
            stress_level=stress_level,
            sleep_hours=sleep_hours,
            energy_level=energy_level,
        )

    return render_template(
        "mood_check.html",
        active_page="mood-check",
        body_class="page-mood-check",
        page_id="mood-check",
        page_title="Heal Hub Mood Check",
        form_values=form_values,
        mood_result=mood_result,
    )


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if "user" in session:
        existing_user = session["user"]
        if existing_user.get("role") in {"doctor", "patient"}:
            return redirect(url_for(role_dashboard_endpoint(existing_user)))
        session.pop("user", None)
        flash("Previous session was cleared. Please sign in again.", "info")

    next_url = safe_next_url(request.args.get("next")) or safe_next_url(request.form.get("next"))
    enabled_demo_users = {username: DEMO_USERS[username] for username in LOGIN_ENABLED_USERNAMES}

    if request.method == "POST":
        selected_role = request.form.get("role", "patient").strip().lower() or "patient"
        if selected_role not in enabled_demo_users:
            flash("Only patient and doctor login are enabled right now.", "error")
        else:
            if request.form.get("demo_login"):
                username = selected_role
                password = enabled_demo_users[username]["password"]
            else:
                username = request.form.get("username", "").strip().lower()
                password = request.form.get("password", "")

            user = enabled_demo_users.get(username)
            if user and user["password"] == password and user["role"] == selected_role:
                session.permanent = bool(request.form.get("remember_me"))
                session["user"] = {
                    "username": username,
                    "display_name": user["display_name"],
                    "role": user["role"],
                    "headline": user.get("headline", user["role"].title()),
                }
                flash(f"Welcome to Heal Hub, {user['display_name']}.", "success")
                if next_url:
                    return redirect(next_url)
                return redirect(url_for(role_dashboard_endpoint(session["user"])))

            flash("Invalid username, password, or role combination. Use one of the doctor or patient demo accounts shown below.", "error")

    return render_template(
        "login.html",
        active_page="login",
        body_class="page-auth",
        page_id="login",
        next_url=next_url or "",
        page_title="Heal Hub Login",
    )


@app.get("/logout")
def logout() -> Any:
    session.pop("user", None)
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("landing_page"))


@app.get("/dashboard")
@login_required
def dashboard_page() -> Any:
    user = session.get("user", {})
    if user.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard_page"))
    if user.get("role") == "patient":
        return redirect(url_for("patient_dashboard_page"))
    session.pop("user", None)
    flash("Please sign in as a patient or doctor.", "info")
    return redirect(url_for("login"))


@app.route("/doctor/dashboard", methods=["GET", "POST"])
@login_required
def doctor_dashboard_page() -> Any:
    user = session.get("user", {})
    if user.get("role") != "doctor":
        flash("Doctor access is required for that page.", "error")
        return redirect(url_for("dashboard_page"))

    if request.method == "POST":
        patient_username = request.form.get("patient_username", "patient").strip() or "patient"
        prescriptions = load_records(PRESCRIPTIONS_PATH)
        prescriptions.insert(0, {
            "id": f"rx-{int(datetime.utcnow().timestamp())}",
            "patient_username": patient_username,
            "doctor_username": user.get("username"),
            "doctor_name": user.get("display_name"),
            "medicine_name": request.form.get("medicine_name", "").strip(),
            "dosage": request.form.get("dosage", "").strip(),
            "frequency": request.form.get("frequency", "").strip(),
            "duration": request.form.get("duration", "").strip(),
            "purpose": request.form.get("purpose", "").strip(),
            "instructions": request.form.get("instructions", "").strip(),
            "warnings": request.form.get("warnings", "").strip(),
            "refill_status": request.form.get("refill_status", "In active cycle").strip(),
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        })
        save_json(PRESCRIPTIONS_PATH, prescriptions)
        flash("Prescription added to the patient portal.", "success")
        return redirect(url_for("doctor_dashboard_page"))

    dashboard_context = build_doctor_dashboard_context(user)
    return render_template(
        "doctor_dashboard.html",
        active_page="dashboard",
        body_class="page-dashboard",
        page_id="doctor-dashboard",
        page_title="Doctor Dashboard",
        **dashboard_context,
    )


@app.get("/patient/dashboard")
@login_required
def patient_dashboard_page() -> Any:
    user = session.get("user", {})
    if user.get("role") != "patient":
        flash("Patient access is required for that page.", "error")
        return redirect(url_for("dashboard_page"))

    dashboard_context = build_patient_dashboard_context(user)
    return render_template(
        "patient_dashboard.html",
        active_page="dashboard",
        body_class="page-dashboard",
        page_id="patient-dashboard",
        page_title="Patient Dashboard",
        **dashboard_context,
    )


@app.get("/about")
def about_page() -> str:
    return render_template(
        "about.html",
        active_page="about",
        body_class="page-about",
        page_id="about",
        page_title="About Heal Hub",
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


# ═══════════════════════════════════════════════════════════════
# PART 2 — HEALING MOVIES & SERIES
# ═══════════════════════════════════════════════════════════════

MOVIES_DATA: list[dict[str, Any]] = [
    {
        "id": "mov-001", "title": "Inside Out 2", "type": "movie",
        "genre": "Animation, Family", "year": 2024,
        "categories": ["inner child", "mental wellness", "self-growth"],
        "description": "Riley navigates new emotions as she enters her teenage years, discovering that growing up means embracing complexity.",
        "why_helps": "Helps viewers understand and accept complex emotions, showing that all feelings have value in our personal growth journey.",
        "mood_tags": ["emotional awareness", "self-acceptance", "growing up"],
        "poster_emoji": "🧠",
    },
    {
        "id": "mov-002", "title": "Soul", "type": "movie",
        "genre": "Animation, Drama", "year": 2020,
        "categories": ["inspiration", "self-growth", "healing"],
        "description": "A music teacher discovers what it truly means to have a soul and finds purpose beyond achievement.",
        "why_helps": "Reminds us that life's meaning comes from everyday moments, not just big accomplishments. Perfect for anyone feeling lost or purposeless.",
        "mood_tags": ["purpose", "mindfulness", "joy"],
        "poster_emoji": "🎵",
    },
    {
        "id": "mov-003", "title": "The Pursuit of Happyness", "type": "movie",
        "genre": "Drama, Biography", "year": 2006,
        "categories": ["motivation", "life struggles", "inspiration"],
        "description": "A struggling salesman takes custody of his son as he battles homelessness while pursuing a career as a stockbroker.",
        "why_helps": "A powerful story of resilience and determination that shows how persistence through hardship can lead to transformation.",
        "mood_tags": ["resilience", "hope", "determination"],
        "poster_emoji": "💪",
    },
    {
        "id": "mov-004", "title": "Little Women", "type": "movie",
        "genre": "Drama, Romance", "year": 2019,
        "categories": ["women empowerment", "friendship", "self-growth"],
        "description": "Four sisters come of age in America during the Civil War era, each finding their own path in a world that limits women.",
        "why_helps": "Celebrates female ambition, sisterhood, and the courage to define your own life on your own terms.",
        "mood_tags": ["empowerment", "sisterhood", "courage"],
        "poster_emoji": "📖",
    },
    {
        "id": "mov-005", "title": "Good Will Hunting", "type": "movie",
        "genre": "Drama", "year": 1997,
        "categories": ["healing", "mental wellness", "self-growth"],
        "description": "A janitor at MIT has a gift for mathematics but needs help from a psychologist to find direction in life.",
        "why_helps": "Shows the transformative power of therapy and human connection in overcoming childhood trauma and self-sabotage.",
        "mood_tags": ["therapy", "vulnerability", "breakthrough"],
        "poster_emoji": "🍎",
    },
    {
        "id": "mov-006", "title": "Coco", "type": "movie",
        "genre": "Animation, Family", "year": 2017,
        "categories": ["inner child", "healing", "friendship"],
        "description": "A young boy journeys to the Land of the Dead to discover the truth about his family's history and his own dreams.",
        "why_helps": "A beautiful exploration of family bonds, memory, and following your passion even when others disapprove.",
        "mood_tags": ["family", "memory", "passion"],
        "poster_emoji": "🎸",
    },
    {
        "id": "mov-007", "title": "Wild", "type": "movie",
        "genre": "Drama, Adventure", "year": 2014,
        "categories": ["healing", "self-growth", "women empowerment"],
        "description": "A woman hikes the Pacific Crest Trail alone to recover from personal tragedy and self-destructive behavior.",
        "why_helps": "Demonstrates how physical challenge and solitude can become powerful tools for emotional healing and self-discovery.",
        "mood_tags": ["healing journey", "nature", "self-discovery"],
        "poster_emoji": "🥾",
    },
    {
        "id": "mov-008", "title": "The Secret Life of Walter Mitty", "type": "movie",
        "genre": "Adventure, Comedy", "year": 2013,
        "categories": ["inspiration", "motivation", "self-growth"],
        "description": "A daydreamer embarks on a real-world adventure that surpasses anything he could have imagined.",
        "why_helps": "Inspires viewers to step out of their comfort zone and live the adventures they've only dreamed about.",
        "mood_tags": ["adventure", "courage", "living fully"],
        "poster_emoji": "🌍",
    },
    {
        "id": "mov-009", "title": "Ted Lasso", "type": "series",
        "genre": "Comedy, Drama", "year": 2020,
        "categories": ["motivation", "friendship", "mental wellness"],
        "description": "An American football coach is hired to manage a British soccer team despite having no experience, winning hearts with optimism.",
        "why_helps": "Shows how kindness, vulnerability, and genuine care for others can transform toxic environments into supportive communities.",
        "mood_tags": ["kindness", "optimism", "team spirit"],
        "poster_emoji": "⚽",
    },
    {
        "id": "mov-010", "title": "Maid", "type": "series",
        "genre": "Drama", "year": 2021,
        "categories": ["women empowerment", "life struggles", "motivation"],
        "description": "A young mother escapes an abusive relationship and works as a house cleaner to provide for her daughter.",
        "why_helps": "A raw, honest portrayal of survival and strength that validates the struggles of women rebuilding their lives.",
        "mood_tags": ["survival", "strength", "motherhood"],
        "poster_emoji": "🏠",
    },
    {
        "id": "mov-011", "title": "Heartstopper", "type": "series",
        "genre": "Romance, Drama", "year": 2022,
        "categories": ["friendship", "inner child", "self-growth"],
        "description": "Two British teens discover their unlikely friendship might be something more, navigating identity and acceptance.",
        "why_helps": "A gentle, affirming story about self-acceptance, true friendship, and the courage to be yourself.",
        "mood_tags": ["acceptance", "identity", "gentle love"],
        "poster_emoji": "💛",
    },
    {
        "id": "mov-012", "title": "Forrest Gump", "type": "movie",
        "genre": "Drama, Romance", "year": 1994,
        "categories": ["inspiration", "life struggles", "healing"],
        "description": "A man with a low IQ accomplishes great things in life while his true love eludes him.",
        "why_helps": "Teaches that kindness, simplicity, and perseverance matter more than intelligence or status.",
        "mood_tags": ["simplicity", "perseverance", "love"],
        "poster_emoji": "🏃",
    },
    {
        "id": "mov-013", "title": "Encanto", "type": "movie",
        "genre": "Animation, Musical", "year": 2021,
        "categories": ["inner child", "healing", "friendship"],
        "description": "A young Colombian woman discovers that being the only 'ordinary' member of her magical family might be her greatest strength.",
        "why_helps": "Explores family pressure, generational trauma, and the healing power of being seen for who you truly are.",
        "mood_tags": ["family healing", "self-worth", "belonging"],
        "poster_emoji": "🦋",
    },
    {
        "id": "mov-014", "title": "A Beautiful Mind", "type": "movie",
        "genre": "Drama, Biography", "year": 2001,
        "categories": ["mental wellness", "motivation", "healing"],
        "description": "The story of mathematician John Nash and his struggle with schizophrenia while making groundbreaking contributions.",
        "why_helps": "Destigmatizes mental health challenges and shows that brilliance and vulnerability can coexist.",
        "mood_tags": ["mental health", "genius", "love"],
        "poster_emoji": "🧮",
    },
    {
        "id": "mov-015", "title": "Eat Pray Love", "type": "movie",
        "genre": "Drama, Romance", "year": 2010,
        "categories": ["self-growth", "healing", "women empowerment"],
        "description": "After a painful divorce, a woman travels the world to rediscover herself through food, spirituality, and love.",
        "why_helps": "Encourages taking time for self-discovery and shows that healing often requires stepping away from the familiar.",
        "mood_tags": ["self-discovery", "travel", "renewal"],
        "poster_emoji": "🌺",
    },
    {
        "id": "mov-016", "title": "It's Okay to Not Be Okay", "type": "series",
        "genre": "Romance, Drama", "year": 2020,
        "categories": ["mental wellness", "healing", "friendship"],
        "description": "A psychiatric ward caretaker and a children's book author with antisocial personality disorder heal each other's emotional wounds.",
        "why_helps": "Beautifully normalizes mental health struggles and shows that healing happens through genuine human connection.",
        "mood_tags": ["mental health", "connection", "healing"],
        "poster_emoji": "🌙",
    },
]

# In-memory user movie interactions (for demo)
USER_MOVIE_DATA: dict[str, dict[str, Any]] = {
    "patient": {
        "watched": ["mov-001", "mov-002", "mov-006", "mov-009", "mov-013"],
        "want_to_watch": ["mov-003", "mov-007", "mov-015"],
        "favorites": ["mov-002", "mov-006", "mov-013"],
        "interests": ["healing", "inner child", "self-growth", "mental wellness"],
        "history": [
            {
                "movie_id": "mov-013",
                "watched_on": "2026-03-28",
                "reflection": "This helped me feel less alone in family pressure and reminded me that softness is still strength.",
                "mood_after": "belonging",
            },
            {
                "movie_id": "mov-009",
                "watched_on": "2026-03-25",
                "reflection": "The kindness in this story gave me a hopeful reset after a heavy week.",
                "mood_after": "optimism",
            },
            {
                "movie_id": "mov-002",
                "watched_on": "2026-03-21",
                "reflection": "It helped me slow down and remember that purpose can live inside ordinary moments.",
                "mood_after": "calm",
            },
        ],
        "check_in": "Looking for stories that feel healing, hopeful, and gently energizing.",
    }
}

MOVIE_CATEGORIES = [
    "motivation", "healing", "self-growth", "inner child", "friendship",
    "women empowerment", "life struggles", "mental wellness", "inspiration",
]


@app.get("/movies")
def movies_page() -> str:
    category = request.args.get("category", "").strip().lower()
    search_q = request.args.get("q", "").strip().lower()
    filtered = MOVIES_DATA
    if category:
        filtered = [m for m in filtered if category in m["categories"]]
    if search_q:
        filtered = [m for m in filtered if search_q in m["title"].lower() or search_q in m["description"].lower()]

    user = session.get("user")
    user_data = {}
    movie_profile = None
    if user:
        username = user.get("username", "")
        user_data = ensure_user_movie_profile(username)
        movie_profile = build_movie_profile(username)

    return render_template(
        "movies.html",
        active_page="movies",
        body_class="page-movies",
        page_id="movies",
        page_title="Healing Through Stories | Heal Hub",
        movies=filtered,
        categories=MOVIE_CATEGORIES,
        selected_category=category,
        search_q=search_q,
        user_movie_data=user_data,
        movie_profile=movie_profile,
        mood_match=movie_profile["mood_match"] if movie_profile else MOVIES_DATA[0],
        featured_story_arc=filtered[:3],
    )


@app.post("/api/movie-action")
@login_required
def movie_action() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    movie_id = payload.get("movie_id", "")
    action = payload.get("action", "")  # watched, want_to_watch, favorite, remove

    data = ensure_user_movie_profile(username)

    if action == "watched":
        if movie_id not in data["watched"]:
            data["watched"].append(movie_id)
        append_watch_history(data, movie_id)
        if movie_id in data["want_to_watch"]:
            data["want_to_watch"].remove(movie_id)
    elif action == "want_to_watch":
        if movie_id not in data["want_to_watch"]:
            data["want_to_watch"].append(movie_id)
    elif action == "favorite":
        if movie_id not in data["favorites"]:
            data["favorites"].append(movie_id)
        if movie_id not in data["watched"]:
            data["watched"].append(movie_id)
        append_watch_history(data, movie_id)
    elif action == "remove":
        for lst in [data["watched"], data["want_to_watch"], data["favorites"]]:
            if movie_id in lst:
                lst.remove(movie_id)
        data["history"] = [
            item for item in data.get("history", []) if item.get("movie_id") != movie_id
        ]

    return jsonify({"success": True, "data": data, "summary": build_movie_profile(username)})


# ═══════════════════════════════════════════════════════════════
# PART 3 — DOCTOR / THERAPIST BOOKING
# ═══════════════════════════════════════════════════════════════

THERAPISTS_DATA: list[dict[str, Any]] = [
    {
        "id": "th-001", "name": "Dr. Anita Sharma", "specialty": "Clinical Psychologist",
        "rating": 4.9, "reviews": 127, "experience": "12 years",
        "availability": "Mon, Wed, Fri — 10:00 AM to 4:00 PM",
        "bio": "Specializes in anxiety, depression, and trauma recovery. Uses CBT and mindfulness-based approaches.",
        "avatar_emoji": "👩‍⚕️", "tags": ["anxiety", "depression", "trauma", "CBT"],
    },
    {
        "id": "th-002", "name": "Dr. Rajesh Patel", "specialty": "Psychiatrist",
        "rating": 4.8, "reviews": 98, "experience": "15 years",
        "availability": "Tue, Thu — 9:00 AM to 3:00 PM",
        "bio": "Expert in mood disorders, PTSD, and medication management. Compassionate and evidence-based care.",
        "avatar_emoji": "👨‍⚕️", "tags": ["mood disorders", "PTSD", "medication"],
    },
    {
        "id": "th-003", "name": "Dr. Priya Adhikari", "specialty": "Counseling Therapist",
        "rating": 4.7, "reviews": 84, "experience": "8 years",
        "availability": "Mon–Fri — 11:00 AM to 6:00 PM",
        "bio": "Focuses on relationship issues, self-esteem, and life transitions. Warm, empathetic approach.",
        "avatar_emoji": "👩‍💼", "tags": ["relationships", "self-esteem", "life transitions"],
    },
    {
        "id": "th-004", "name": "Dr. Suman Gurung", "specialty": "Women's Wellness Therapist",
        "rating": 4.9, "reviews": 112, "experience": "10 years",
        "availability": "Mon, Wed, Sat — 9:00 AM to 2:00 PM",
        "bio": "Dedicated to women's mental health, postpartum support, and empowerment counseling. Safe and supportive space.",
        "avatar_emoji": "🌸", "tags": ["women's health", "postpartum", "empowerment"],
    },
    {
        "id": "th-005", "name": "Dr. Bikram Thapa", "specialty": "Family Therapist",
        "rating": 4.6, "reviews": 73, "experience": "11 years",
        "availability": "Tue, Thu, Sat — 10:00 AM to 5:00 PM",
        "bio": "Helps families navigate conflict, communication challenges, and generational patterns with compassion.",
        "avatar_emoji": "👨‍👩‍👧", "tags": ["family", "communication", "conflict resolution"],
    },
    {
        "id": "th-006", "name": "Dr. Maya Lama", "specialty": "Art & Expressive Therapist",
        "rating": 4.8, "reviews": 65, "experience": "7 years",
        "availability": "Wed, Fri — 1:00 PM to 7:00 PM",
        "bio": "Uses creative arts, music, and storytelling as therapeutic tools. Ideal for those who find traditional talk therapy challenging.",
        "avatar_emoji": "🎨", "tags": ["art therapy", "music therapy", "creative healing"],
    },
]

BOOKINGS_DATA: list[dict[str, Any]] = [
    {
        "id": "bk-001", "patient_username": "patient", "therapist_id": "th-001",
        "patient_name": "Aasha G.",
        "therapist_name": "Dr. Anita Sharma", "date": "2026-04-02", "time": "10:30 AM",
        "status": "confirmed", "notes": "Follow-up session on anxiety management",
    },
    {
        "id": "bk-002", "patient_username": "riya-demo", "therapist_id": "th-004",
        "patient_name": "Riya T.", "therapist_name": "Dr. Suman Gurung",
        "date": "2026-04-03", "time": "01:00 PM", "status": "requested",
        "notes": "Support around boundary-setting, burnout recovery, and rebuilding confidence.",
    },
    {
        "id": "bk-003", "patient_username": "mina-demo", "therapist_id": "th-006",
        "patient_name": "Mina R.", "therapist_name": "Dr. Maya Lama",
        "date": "2026-04-04", "time": "05:30 PM", "status": "confirmed",
        "notes": "Expressive therapy check-in focused on grief processing and creative routines.",
    },
]

DOCTOR_CLIENTS_DATA: list[dict[str, Any]] = [
    {
        "username": "patient",
        "display_name": "Aasha G.",
        "focus": "Rebuilding emotional steadiness after repeated stress and health uncertainty.",
        "status": "Active follow-up",
        "next_step": "Blend grounding tools with healing-story reflections that reinforce hope and belonging.",
        "recent_observation": "Responds well to gentle, family-centered stories and safe community spaces.",
    },
    {
        "username": "riya-demo",
        "display_name": "Riya T.",
        "focus": "Burnout recovery, sleep repair, and confidence after difficult relationship boundaries.",
        "status": "Booking requested",
        "next_step": "Encourage low-pressure routines, women-focused support, and motivational story prompts.",
        "recent_observation": "Prefers stories with women empowerment, travel, and second-chance themes.",
        "top_categories": ["women empowerment", "self-growth", "motivation"],
        "favorite_titles": ["Wild", "Eat Pray Love"],
        "mood_themes": ["renewal", "self-discovery", "courage"],
    },
    {
        "username": "mina-demo",
        "display_name": "Mina R.",
        "focus": "Creative recovery, grief support, and reconnecting with joy after isolation.",
        "status": "Session confirmed",
        "next_step": "Use expressive arts, supportive circles, and light weekly goals instead of intense plans.",
        "recent_observation": "Lights up around music, inner-child content, and validating group discussion.",
        "top_categories": ["inner child", "healing", "friendship"],
        "favorite_titles": ["Coco", "Encanto", "Heartstopper"],
        "mood_themes": ["memory", "belonging", "gentle love"],
    },
]


@app.get("/therapists")
def therapists_page() -> str:
    user = session.get("user")
    user_bookings = []
    movie_profile = None
    if user:
        username = user.get("username", "")
        user_bookings = [b for b in BOOKINGS_DATA if b.get("patient_username") == username]
        movie_profile = build_movie_profile(username)

    return render_template(
        "therapists.html",
        active_page="therapists",
        body_class="page-therapists",
        page_id="therapists",
        page_title="Book a Therapist | Heal Hub",
        therapists=THERAPISTS_DATA,
        bookings=user_bookings,
        movie_profile=movie_profile,
        women_support_therapists=[therapist for therapist in THERAPISTS_DATA if "women" in therapist["specialty"].lower()][:2],
    )


@app.post("/api/book-therapist")
@login_required
def book_therapist() -> Any:
    user = session.get("user", {})
    payload = request.get_json(silent=True) or {}
    therapist_id = payload.get("therapist_id", "")
    date = payload.get("date", "")
    time_slot = payload.get("time", "")
    notes = payload.get("notes", "")

    therapist = next((t for t in THERAPISTS_DATA if t["id"] == therapist_id), None)
    if not therapist:
        return jsonify({"success": False, "message": "Therapist not found."}), 400

    booking = {
        "id": f"bk-{uuid4().hex[:8]}",
        "patient_username": user.get("username", "patient"),
        "patient_name": user.get("display_name", "Heal Hub Member"),
        "therapist_id": therapist_id,
        "therapist_name": therapist["name"],
        "date": date or "2026-04-05",
        "time": time_slot or "10:00 AM",
        "status": "confirmed",
        "notes": notes,
    }
    BOOKINGS_DATA.append(booking)
    return jsonify({"success": True, "booking": booking, "message": f"Appointment booked with {therapist['name']}."})


# Therapist insight view (for doctor dashboard)
def get_patient_insights(username: str) -> dict[str, Any]:
    """Generate soft therapeutic insights from movie preferences."""
    movie_profile = build_movie_profile(username)
    watched_movies = movie_profile["watched_movies"]
    fav_movies = movie_profile["favorite_movies"]

    return {
        "movies_watched": len(watched_movies),
        "favorites_count": len(fav_movies),
        "top_categories": movie_profile["top_categories"][:4],
        "interests": movie_profile["profile"].get("interests", []),
        "mood_themes": movie_profile["mood_themes"][:8],
        "favorite_titles": [m["title"] for m in fav_movies],
        "watched_titles": [m["title"] for m in watched_movies[:6]],
        "story_preference_summary": movie_profile["mood_influence_summary"],
        "insight_note": "These patterns may reflect emotional themes the client resonates with. Use as gentle conversation starters, not diagnostic conclusions.",
    }


# ═══════════════════════════════════════════════════════════════
# PART 4 — COMMUNITY FEATURE
# ═══════════════════════════════════════════════════════════════

COMMUNITY_GROUPS: list[dict[str, Any]] = [
    {
        "id": "grp-001", "name": "Anxiety Support Circle",
        "description": "A safe space for people managing anxiety to share experiences and coping strategies.",
        "icon": "💙", "members": 234, "category": "mental health",
    },
    {
        "id": "grp-002", "name": "Healing After Heartbreak",
        "description": "Support for those recovering from breakups, divorce, or loss of a loved one.",
        "icon": "💔", "members": 189, "category": "emotional healing",
    },
    {
        "id": "grp-003", "name": "Women's Support Circle",
        "description": "A women-only space for sharing, empowerment, and mutual support.",
        "icon": "🌸", "members": 312, "category": "women's wellness",
    },
    {
        "id": "grp-004", "name": "Stress & Burnout Recovery",
        "description": "For professionals and students dealing with chronic stress and burnout.",
        "icon": "🔥", "members": 156, "category": "stress management",
    },
    {
        "id": "grp-005", "name": "Self-Growth Club",
        "description": "Share books, movies, habits, and ideas that help you grow as a person.",
        "icon": "🌱", "members": 278, "category": "personal growth",
    },
    {
        "id": "grp-006", "name": "Safe Space Discussions",
        "description": "Open, moderated discussions about life challenges in a judgment-free zone.",
        "icon": "🕊️", "members": 198, "category": "general support",
    },
]

COMMUNITY_POSTS: list[dict[str, Any]] = [
    {
        "id": "post-001", "group_id": "grp-001", "author": "Kiran M.",
        "content": "Today was really hard. My anxiety spiked during a meeting and I had to step out. Does anyone else struggle with work anxiety?",
        "timestamp": "2026-03-29 09:15", "likes": 24, "replies": [
            {"author": "Pema S.", "content": "You're not alone. I've been there too. Taking a break is brave, not weak. 💙", "timestamp": "2026-03-29 09:32"},
            {"author": "Deepa R.", "content": "I keep a grounding exercise on my phone for moments like that. Happy to share if you'd like!", "timestamp": "2026-03-29 10:01"},
        ],
    },
    {
        "id": "post-002", "group_id": "grp-002", "author": "Sabina T.",
        "content": "It's been 3 months since my breakup and some days are still so hard. But I watched 'Wild' last night and it reminded me that healing is a journey, not a destination.",
        "timestamp": "2026-03-28 20:45", "likes": 41, "replies": [
            {"author": "Ishita K.", "content": "That movie changed my perspective too. You're doing amazing. One day at a time. 🌿", "timestamp": "2026-03-28 21:10"},
        ],
    },
    {
        "id": "post-003", "group_id": "grp-003", "author": "Laxmi G.",
        "content": "I finally set a boundary with someone who was draining my energy. It was scary but I feel lighter. Sending strength to everyone here. 🌸",
        "timestamp": "2026-03-29 11:30", "likes": 56, "replies": [
            {"author": "Gita P.", "content": "So proud of you! Setting boundaries is one of the hardest but most important things we can do.", "timestamp": "2026-03-29 11:48"},
            {"author": "Aasha G.", "content": "This inspires me. I need to do the same. Thank you for sharing. 💪", "timestamp": "2026-03-29 12:05"},
        ],
    },
    {
        "id": "post-004", "group_id": "grp-005", "author": "Milan B.",
        "content": "Just finished reading 'Atomic Habits' and started a 5-minute morning meditation. Small steps, big changes. What's one small habit that changed your life?",
        "timestamp": "2026-03-27 14:20", "likes": 33, "replies": [
            {"author": "Nabin K.", "content": "Journaling before bed. It helps me process the day and sleep better.", "timestamp": "2026-03-27 15:00"},
            {"author": "Tsering L.", "content": "Walking 20 minutes after lunch. Simple but it transformed my energy levels.", "timestamp": "2026-03-27 16:30"},
        ],
    },
    {
        "id": "post-005", "group_id": "grp-004", "author": "Bikash R.",
        "content": "I burned out so badly last year that I couldn't get out of bed for weeks. If you're feeling overwhelmed, please take it seriously. Your body is trying to tell you something.",
        "timestamp": "2026-03-28 08:00", "likes": 67, "replies": [
            {"author": "Ramesh D.", "content": "Thank you for sharing this. I'm in that phase right now and needed to hear this.", "timestamp": "2026-03-28 08:45"},
        ],
    },
    {
        "id": "post-006", "group_id": "grp-006", "author": "Hari S.",
        "content": "Sometimes I feel like I'm the only one struggling while everyone else has it figured out. Then I come here and realize we're all just doing our best. Thank you all. 🕊️",
        "timestamp": "2026-03-29 07:00", "likes": 89, "replies": [
            {"author": "Janak T.", "content": "Nobody has it all figured out. We're all works in progress. You belong here. ❤️", "timestamp": "2026-03-29 07:22"},
            {"author": "Kiran M.", "content": "This community has been a lifeline for me. You're never alone.", "timestamp": "2026-03-29 08:10"},
        ],
    },
]

USER_COMMUNITY_DATA: dict[str, dict[str, Any]] = {
    "patient": {
        "joined_groups": ["grp-001", "grp-003", "grp-005"],
        "posts_count": 3,
        "support_given": 12,
        "support_received": 18,
        "comfort_topics": ["boundaries", "hopeful stories", "gentle routines"],
    }
}


@app.get("/community")
def community_page() -> str:
    group_id = request.args.get("group", "").strip()
    user = session.get("user")
    user_community = {}
    community_profile = None
    if user:
        username = user.get("username", "")
        user_community = USER_COMMUNITY_DATA.get(username, {})
        community_profile = build_community_profile(username)

    if group_id:
        group = next((g for g in COMMUNITY_GROUPS if g["id"] == group_id), None)
        posts = [p for p in COMMUNITY_POSTS if p["group_id"] == group_id]
    else:
        group = None
        posts = COMMUNITY_POSTS[:6]

    return render_template(
        "community.html",
        active_page="community",
        body_class="page-community",
        page_id="community",
        page_title="Community Support | Heal Hub",
        groups=COMMUNITY_GROUPS,
        selected_group=group,
        posts=posts,
        user_community=user_community,
        community_profile=community_profile,
    )


@app.post("/api/community-post")
@login_required
def community_post() -> Any:
    user = session.get("user", {})
    payload = request.get_json(silent=True) or {}
    group_id = payload.get("group_id", "grp-006")
    content = payload.get("content", "").strip()

    if not content:
        return jsonify({"success": False, "message": "Post content cannot be empty."}), 400

    post = {
        "id": f"post-{uuid4().hex[:8]}",
        "group_id": group_id,
        "author": user.get("display_name", "Anonymous"),
        "content": content,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "likes": 0,
        "replies": [],
    }
    COMMUNITY_POSTS.insert(0, post)
    community = USER_COMMUNITY_DATA.setdefault(
        user.get("username", "patient"),
        {"joined_groups": [], "posts_count": 0, "support_given": 0, "support_received": 0, "comfort_topics": []},
    )
    community["posts_count"] = community.get("posts_count", 0) + 1
    if group_id not in community.get("joined_groups", []):
        community.setdefault("joined_groups", []).append(group_id)
    return jsonify({"success": True, "post": post})


@app.post("/api/community-reply")
@login_required
def community_reply() -> Any:
    user = session.get("user", {})
    payload = request.get_json(silent=True) or {}
    post_id = payload.get("post_id", "")
    content = payload.get("content", "").strip()

    if not content:
        return jsonify({"success": False, "message": "Reply cannot be empty."}), 400

    post = next((p for p in COMMUNITY_POSTS if p["id"] == post_id), None)
    if not post:
        return jsonify({"success": False, "message": "Post not found."}), 404

    reply = {
        "author": user.get("display_name", "Anonymous"),
        "content": content,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
    }
    post["replies"].append(reply)
    return jsonify({"success": True, "reply": reply})


@app.post("/api/community-react")
@login_required
def community_react() -> Any:
    payload = request.get_json(silent=True) or {}
    post_id = payload.get("post_id", "")
    post = next((item for item in COMMUNITY_POSTS if item["id"] == post_id), None)
    if not post:
        return jsonify({"success": False, "message": "Post not found."}), 404

    post["likes"] = post.get("likes", 0) + 1
    return jsonify({"success": True, "likes": post["likes"]})


# ═══════════════════════════════════════════════════════════════
# PART 5 — WOMEN'S SAFE SPACE
# ═══════════════════════════════════════════════════════════════

SAFETY_CARDS: list[dict[str, Any]] = [
    {
        "title": "Recognizing Manipulation",
        "icon": "🚩",
        "content": "Learn to identify common manipulation tactics: love-bombing, gaslighting, isolation from friends, and guilt-tripping. Trust your instincts — if something feels wrong, it probably is.",
        "category": "awareness",
    },
    {
        "title": "Digital Safety Basics",
        "icon": "🔒",
        "content": "Protect your online presence: use strong passwords, enable two-factor authentication, be cautious about sharing personal photos, and review privacy settings regularly.",
        "category": "digital safety",
    },
    {
        "title": "Setting Healthy Boundaries",
        "icon": "🛡️",
        "content": "You have the right to say no. Healthy boundaries protect your emotional energy. Practice saying: 'I'm not comfortable with that' — it's a complete sentence.",
        "category": "boundaries",
    },
    {
        "title": "Safe AI Interactions",
        "icon": "🤖",
        "content": "Be mindful when sharing personal information with AI chatbots. Never share passwords, financial details, or intimate content. AI should support you, not replace real human connection.",
        "category": "digital safety",
    },
    {
        "title": "How to Ask for Help",
        "icon": "🤝",
        "content": "Reaching out is strength, not weakness. Talk to someone you trust, contact a helpline, or visit a local support center. You deserve support and you are not alone.",
        "category": "support",
    },
    {
        "title": "Understanding Consent",
        "icon": "💜",
        "content": "Consent must be freely given, reversible, informed, enthusiastic, and specific. It applies to physical contact, sharing information, and digital interactions.",
        "category": "boundaries",
    },
    {
        "title": "Warning Signs of Unsafe Relationships",
        "icon": "⚠️",
        "content": "Watch for: controlling behavior, jealousy disguised as love, threats, monitoring your phone, isolating you from support systems, and making you feel responsible for their emotions.",
        "category": "awareness",
    },
    {
        "title": "Self-Care During Difficult Times",
        "icon": "🌿",
        "content": "When going through hard times: maintain basic routines, stay connected with safe people, limit social media if it triggers you, and be gentle with yourself.",
        "category": "wellbeing",
    },
]

SUPPORT_RESOURCES: list[dict[str, Any]] = [
    {"name": "National Women's Helpline", "contact": "1145 (Nepal)", "type": "helpline"},
    {"name": "Crisis Text Line", "contact": "Text HOME to 741741", "type": "text support"},
    {"name": "Women's Rehabilitation Center", "contact": "WOREC Nepal", "type": "organization"},
    {"name": "Maiti Nepal", "contact": "Anti-trafficking support", "type": "organization"},
]


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            items.append(cleaned)
    return items


def ensure_user_movie_profile(username: str) -> dict[str, Any]:
    profile = USER_MOVIE_DATA.setdefault(username, {})
    profile.setdefault("watched", [])
    profile.setdefault("want_to_watch", [])
    profile.setdefault("favorites", [])
    profile.setdefault("interests", [])
    profile.setdefault("history", [])
    profile.setdefault("check_in", "Looking for stories that feel steady, hopeful, and kind.")
    return profile


def movie_catalog() -> dict[str, dict[str, Any]]:
    return {movie["id"]: movie for movie in MOVIES_DATA}


def append_watch_history(profile: dict[str, Any], movie_id: str) -> None:
    catalog = movie_catalog()
    movie = catalog.get(movie_id)
    if not movie:
        return

    history = profile.setdefault("history", [])
    existing = next((item for item in history if item.get("movie_id") == movie_id), None)
    entry = {
        "movie_id": movie_id,
        "watched_on": datetime.utcnow().strftime("%Y-%m-%d"),
        "reflection": movie["why_helps"],
        "mood_after": (movie.get("mood_tags") or ["steady"])[0],
    }
    if existing:
        history.remove(existing)
    history.insert(0, entry)


def recommended_movies_for_profile(profile: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    watched_ids = set(profile.get("watched", []))
    favorite_ids = set(profile.get("favorites", []))
    interest_set = set(profile.get("interests", []))

    category_counts: dict[str, int] = {}
    for movie in MOVIES_DATA:
        if movie["id"] in watched_ids or movie["id"] in favorite_ids:
            for category in movie["categories"]:
                category_counts[category] = category_counts.get(category, 0) + 1

    def score(movie: dict[str, Any]) -> tuple[int, int]:
        overlap = len(interest_set.intersection(movie["categories"]))
        familiarity = sum(category_counts.get(category, 0) for category in movie["categories"])
        comfort_bonus = 1 if movie["type"] == "series" else 0
        return overlap * 4 + familiarity + comfort_bonus, movie["year"]

    ranked = [
        movie
        for movie in sorted(MOVIES_DATA, key=score, reverse=True)
        if movie["id"] not in watched_ids
    ]
    return ranked[:limit]


def build_movie_profile(username: str) -> dict[str, Any]:
    profile = ensure_user_movie_profile(username)
    catalog = movie_catalog()
    watched_movies = [catalog[movie_id] for movie_id in profile["watched"] if movie_id in catalog]
    want_movies = [catalog[movie_id] for movie_id in profile["want_to_watch"] if movie_id in catalog]
    favorite_movies = [catalog[movie_id] for movie_id in profile["favorites"] if movie_id in catalog]

    category_counts: dict[str, int] = {}
    for movie in watched_movies:
        for category in movie["categories"]:
            category_counts[category] = category_counts.get(category, 0) + 1

    top_categories = sorted(category_counts.items(), key=lambda item: item[1], reverse=True)
    mood_themes = dedupe_preserving_order(
        [tag for movie in watched_movies + favorite_movies for tag in movie.get("mood_tags", [])]
    )

    raw_history = list(profile.get("history", []))
    if not raw_history:
        raw_history = [
            {
                "movie_id": movie["id"],
                "watched_on": "2026-03-20",
                "reflection": movie["why_helps"],
                "mood_after": (movie.get("mood_tags") or ["steady"])[0],
            }
            for movie in watched_movies[:3]
        ]

    recently_watched: list[dict[str, Any]] = []
    for entry in raw_history:
        movie = catalog.get(entry.get("movie_id", ""))
        if movie:
            recently_watched.append({**entry, "movie": movie})

    recommended_movies = recommended_movies_for_profile(profile)
    top_labels = [titlecase_words(category) for category, _ in top_categories[:3]]
    mood_summary = (
        f"You often choose {', '.join(top_labels)} stories that offer comfort, perspective, and forward motion."
        if top_labels
        else "Your story journey is still open. A few thoughtful films or series can help shape it."
    )

    personal_profile = (
        "A reflective, hope-seeking viewer who recharges through emotionally warm stories and meaningful character growth."
        if top_labels
        else "A curious viewer exploring what kinds of stories bring the most comfort and inspiration."
    )

    return {
        "profile": profile,
        "watched_movies": watched_movies,
        "want_movies": want_movies,
        "favorite_movies": favorite_movies,
        "watched_count": len(watched_movies),
        "favorites_count": len(favorite_movies),
        "top_categories": top_categories,
        "top_category_labels": top_labels,
        "mood_themes": mood_themes,
        "recently_watched": recently_watched[:4],
        "recommended_movies": recommended_movies,
        "mood_influence_summary": mood_summary,
        "personal_profile": personal_profile,
        "mood_match": recommended_movies[0] if recommended_movies else None,
    }


def build_community_profile(username: str) -> dict[str, Any]:
    profile = USER_COMMUNITY_DATA.setdefault(
        username,
        {"joined_groups": [], "posts_count": 0, "support_given": 0, "support_received": 0, "comfort_topics": []},
    )
    joined_ids = set(profile.get("joined_groups", []))
    joined_groups = [group for group in COMMUNITY_GROUPS if group["id"] in joined_ids]
    recent_discussions = [
        post for post in COMMUNITY_POSTS if not joined_ids or post["group_id"] in joined_ids
    ][:4]
    recommended_groups = [group for group in COMMUNITY_GROUPS if group["id"] not in joined_ids][:3]
    trending_topics = dedupe_preserving_order(
        [group["category"] for group in COMMUNITY_GROUPS] + profile.get("comfort_topics", [])
    )[:5]

    return {
        "profile": profile,
        "joined_groups": joined_groups,
        "recent_discussions": recent_discussions,
        "recommended_groups": recommended_groups,
        "trending_topics": trending_topics,
        "safe_circle": next((group for group in COMMUNITY_GROUPS if group["id"] == "grp-003"), None),
        "support_summary": (
            f"You are active in {len(joined_groups)} support circles and have received "
            f"{profile.get('support_received', 0)} supportive responses so far."
        ),
    }


def build_platform_snapshot() -> dict[str, Any]:
    confirmed_bookings = [
        booking for booking in BOOKINGS_DATA if booking.get("status", "").lower() == "confirmed"
    ]
    return {
        "stories_count": len(MOVIES_DATA),
        "therapists_count": len(THERAPISTS_DATA),
        "groups_count": len(COMMUNITY_GROUPS),
        "community_posts_count": len(COMMUNITY_POSTS),
        "confirmed_bookings": len(confirmed_bookings),
        "resources_count": len(SUPPORT_RESOURCES),
        "women_circle_members": next(
            (group["members"] for group in COMMUNITY_GROUPS if group["id"] == "grp-003"),
            0,
        ),
    }


def build_patient_dashboard_context(user: dict[str, Any]) -> dict[str, Any]:
    username = user.get("username", "patient")
    portal_patient = portal_patient_for_user(user)
    prescriptions = patient_prescriptions(username)
    notes = patient_notes(username)
    ai_summary = ai_triage_summary(["chest pain", "shortness of breath"])
    movie_profile = build_movie_profile(username)
    community_profile = build_community_profile(username)
    bookings = [booking for booking in BOOKINGS_DATA if booking.get("patient_username") == username]
    latest_booking = bookings[0] if bookings else None
    quick_actions = [
        {"label": "Explore healing movies", "href": url_for("movies_page")},
        {"label": "Book therapist", "href": url_for("therapists_page")},
        {"label": "Join support group", "href": url_for("community_page")},
        {"label": "Visit safe space", "href": url_for("safe_space_page")},
    ]

    return {
        "portal_patient": portal_patient,
        "prescriptions": prescriptions,
        "notes": notes,
        "ai_summary": ai_summary,
        "movie_profile": movie_profile,
        "community_profile": community_profile,
        "bookings": bookings,
        "latest_booking": latest_booking,
        "recommended_movies": movie_profile["recommended_movies"],
        "watched_movies": movie_profile["watched_movies"],
        "fav_movies": movie_profile["favorite_movies"],
        "top_categories": movie_profile["top_categories"],
        "movie_data": movie_profile["profile"],
        "growth_timeline": movie_profile["recently_watched"],
        "safety_highlights": SAFETY_CARDS[:3],
        "quick_actions": quick_actions,
        "wellness_summary": {
            "headline": "Stories, safe community, and guided support are all moving in the right direction.",
            "story_summary": movie_profile["mood_influence_summary"],
            "community_summary": community_profile["support_summary"],
            "booking_status": latest_booking["status"].title() if latest_booking else "Ready to schedule",
        },
    }


def build_doctor_client_cards() -> list[dict[str, Any]]:
    client_cards: list[dict[str, Any]] = []
    patient_movie_profile = build_movie_profile("patient")
    patient_community = build_community_profile("patient")
    patient_booking = next(
        (booking for booking in BOOKINGS_DATA if booking.get("patient_username") == "patient"),
        None,
    )

    for client in DOCTOR_CLIENTS_DATA:
        if client["username"] == "patient":
            client_cards.append(
                {
                    "display_name": client["display_name"],
                    "focus": client["focus"],
                    "status": client["status"],
                    "next_step": client["next_step"],
                    "recent_observation": client["recent_observation"],
                    "top_categories": patient_movie_profile["top_category_labels"][:3],
                    "favorite_titles": [movie["title"] for movie in patient_movie_profile["favorite_movies"][:3]],
                    "mood_themes": patient_movie_profile["mood_themes"][:4],
                    "joined_groups": [group["name"] for group in patient_community["joined_groups"][:3]],
                    "booking": patient_booking,
                }
            )
            continue

        booking = next(
            (item for item in BOOKINGS_DATA if item.get("patient_username") == client["username"]),
            None,
        )
        client_cards.append(
            {
                "display_name": client["display_name"],
                "focus": client["focus"],
                "status": client["status"],
                "next_step": client["next_step"],
                "recent_observation": client["recent_observation"],
                "top_categories": [titlecase_words(category) for category in client.get("top_categories", [])],
                "favorite_titles": client.get("favorite_titles", []),
                "mood_themes": client.get("mood_themes", []),
                "joined_groups": [],
                "booking": booking,
            }
        )

    return client_cards


def build_doctor_dashboard_context(user: dict[str, Any]) -> dict[str, Any]:
    portal_patient = PORTAL_PATIENTS["patient"]
    patient_story_profile = build_movie_profile("patient")
    patient_community = build_community_profile("patient")
    doctor_bookings = sorted(
        BOOKINGS_DATA,
        key=lambda booking: (booking.get("date", ""), booking.get("time", "")),
    )

    return {
        "portal_patient": portal_patient,
        "prescriptions": patient_prescriptions("patient"),
        "notes": patient_notes("patient"),
        "ai_summary": ai_triage_summary(["chest pain", "shortness of breath"]),
        "patient_insights": get_patient_insights("patient"),
        "patient_story_profile": patient_story_profile,
        "patient_community": patient_community,
        "bookings": doctor_bookings,
        "doctor_clients": build_doctor_client_cards(),
        "quick_actions": [
            {"label": "Open story library", "href": url_for("movies_page")},
            {"label": "Review bookings", "href": url_for("therapists_page")},
            {"label": "Check community", "href": url_for("community_page")},
        ],
        "safety_highlights": SAFETY_CARDS[:3],
        "doctor_summary": {
            "headline": f"{user.get('display_name', 'Doctor')} is reviewing story-based emotional cues alongside care planning.",
            "insight_note": "These are lightweight conversation aids that help understand emotional resonance. They are not diagnoses.",
        },
    }


@app.post("/api/movie-interests")
@login_required
def movie_interests() -> Any:
    user = session.get("user", {})
    payload = request.get_json(silent=True) or {}
    raw_interests = payload.get("interests", [])
    interests = [
        item for item in dedupe_preserving_order([str(value).strip().lower() for value in raw_interests])
        if item in MOVIE_CATEGORIES
    ]

    profile = ensure_user_movie_profile(user.get("username", "patient"))
    profile["interests"] = interests[:5]
    return jsonify({"success": True, "profile": build_movie_profile(user.get("username", "patient"))})


@app.get("/safe-space")
def safe_space_page() -> str:
    return render_template(
        "safe_space.html",
        active_page="safe-space",
        body_class="page-safe-space",
        page_id="safe-space",
        page_title="Women's Wellness & Safety Hub | Heal Hub",
        safety_cards=SAFETY_CARDS,
        support_resources=SUPPORT_RESOURCES,
        women_circle=next((group for group in COMMUNITY_GROUPS if group["id"] == "grp-003"), None),
        featured_therapists=[therapist for therapist in THERAPISTS_DATA if "women" in therapist["specialty"].lower()][:2],
    )

if __name__ == "__main__":
    app.run(debug=True)
