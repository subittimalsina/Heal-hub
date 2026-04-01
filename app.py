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
from werkzeug.utils import secure_filename


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
USER_PROFILES_PATH = DATA_DIR / "user_profiles.json"
PROFILE_UPLOAD_DIR = BASE_DIR / "static" / "uploads" / "profiles"
ALLOWED_PROFILE_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

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
    items = [dict(item) for item in prescriptions if item.get("patient_username") == username]
    for item in items:
        doctor_profile = account_profile_for_username(str(item.get("doctor_username", "")).strip())
        if doctor_profile:
            item["doctor_name"] = doctor_profile.get("display_name", item.get("doctor_name", "Doctor"))
            item["doctor_avatar"] = doctor_profile.get("avatar", "🩺")
            item["doctor_avatar_image"] = doctor_profile.get("avatar_image", "")
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def patient_notes(username: str) -> list[dict[str, Any]]:
    notes = load_records(DOCTOR_NOTES_PATH)
    items = [dict(item) for item in notes if item.get("patient_username") == username]
    for item in items:
        doctor_profile = account_profile_for_username(str(item.get("doctor_username", "")).strip())
        if doctor_profile:
            item["doctor_name"] = doctor_profile.get("display_name", item.get("doctor_name", "Doctor"))
            item["doctor_avatar"] = doctor_profile.get("avatar", "🩺")
            item["doctor_avatar_image"] = doctor_profile.get("avatar_image", "")
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
        "global_search_q": request.args.get("q", "").strip() if request.endpoint == "search_page" else "",
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
        page_title="Heal Hub | Start Here",
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
def wellness_page() -> Any:
    return redirect(url_for("mood_check_page"))


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

    if request.method == "POST" and request.form.get("dashboard_action") == "update_profile":
        try:
            update_dashboard_profile(user)
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            flash("Doctor profile updated.", "success")
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


@app.route("/patient/dashboard", methods=["GET", "POST"])
@login_required
def patient_dashboard_page() -> Any:
    user = session.get("user", {})
    if user.get("role") != "patient":
        flash("Patient access is required for that page.", "error")
        return redirect(url_for("dashboard_page"))

    if request.method == "POST" and request.form.get("dashboard_action") == "update_profile":
        try:
            update_dashboard_profile(user)
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            flash("Patient profile updated.", "success")
        return redirect(url_for("patient_dashboard_page"))

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
    {
        "id": "mov-017", "title": "Ocean's Eleven", "type": "movie",
        "genre": "Heist, Comedy", "year": 2001,
        "categories": ["heist", "crime", "comedy"],
        "description": "Danny Ocean assembles a sharp team to pull off a high-risk casino heist in Las Vegas.",
        "why_helps": "A stylish, team-driven story that can feel energizing when you need confidence, wit, and momentum.",
        "mood_tags": ["teamwork", "confidence", "strategy"],
        "poster_emoji": "🕴️",
        "poster_image": "images/20260203-105153313.webp",
    },
    {
        "id": "mov-018", "title": "Final Destination", "type": "movie",
        "genre": "Supernatural Horror", "year": 2000,
        "categories": ["horror", "thriller", "supernatural"],
        "description": "After escaping a deadly premonition, a group of teens are pursued by a mysterious force of fate.",
        "why_helps": "For thriller fans, it delivers high tension and suspenseful pacing that can create a strong adrenaline release.",
        "mood_tags": ["suspense", "survival", "adrenaline"],
        "poster_emoji": "💀",
        "poster_image": "images/88c987248d96.webp",
    },
    {
        "id": "mov-019", "title": "Aadu 3: One Last Ride - Part 1", "type": "movie",
        "genre": "Fantasy, Comedy", "year": 2026,
        "categories": ["fantasy", "comedy", "action"],
        "description": "The third Aadu chapter pushes Shaji Pappan and his crew into chaotic, time-bending comedy adventure.",
        "why_helps": "Its energetic humor and absurd momentum can lift mood when you want something playful and loud.",
        "mood_tags": ["chaos comedy", "adventure", "fun reset"],
        "poster_emoji": "🐐",
        "poster_image": "images/8e9c8deaf00f.webp",
    },
    {
        "id": "mov-020", "title": "The Bride!", "type": "movie",
        "genre": "Gothic Romance", "year": 2026,
        "categories": ["gothic", "romance", "horror"],
        "description": "A modern gothic take inspired by Bride of Frankenstein, blending haunting emotion with dark romance.",
        "why_helps": "Works for viewers who process emotion through intense atmosphere, symbolism, and dramatic character arcs.",
        "mood_tags": ["dark romance", "identity", "intense mood"],
        "poster_emoji": "🧟‍♀️",
        "poster_image": "images/bgchkvjg25t1e46otfki.webp",
    },
    {
        "id": "mov-021", "title": "Malcolm in the Middle: Life's Still Unfair", "type": "series",
        "genre": "Sitcom, Comedy", "year": 2026,
        "categories": ["sitcom", "family", "comedy"],
        "description": "A four-part comedy revival that returns Malcolm and his family to their signature chaotic dynamic.",
        "why_helps": "A light family-comedy option when you need laughs, familiarity, and low-pressure comfort.",
        "mood_tags": ["nostalgia", "family chaos", "comfort laugh"],
        "poster_emoji": "📺",
        "poster_image": "images/malcolm-in-the-middle-movie-poster_1767025507.webp",
    },
    {
        "id": "mov-022", "title": "Dhurandhar", "type": "movie",
        "genre": "Spy Action Thriller", "year": 2025,
        "categories": ["spy", "action", "thriller"],
        "description": "An espionage thriller led by Ranveer Singh, built around covert missions, high stakes, and conflict.",
        "why_helps": "Best when you want fast, high-intensity focus with action-heavy pacing and tension.",
        "mood_tags": ["high stakes", "mission tension", "intense pace"],
        "poster_emoji": "🕵️",
        "poster_image": "images/qevfn4ejkplkdzqk0blr.webp",
    },
    {
        "id": "mov-023", "title": "Jesus Revolution", "type": "movie",
        "genre": "Christian Drama", "year": 2023,
        "categories": ["faith", "drama", "inspiration"],
        "description": "A coming-of-age faith drama set during the Jesus movement in late 1960s California.",
        "why_helps": "Offers hopeful themes around belonging, purpose, and spiritual reflection for viewers who seek that lens.",
        "mood_tags": ["hope", "purpose", "community"],
        "poster_emoji": "✝️",
        "poster_image": "images/w24t9qw8l7h2bquozv5h.webp",
    },
]


MOVIE_POSTER_EMOJI_BY_CATEGORY: dict[str, str] = {
    "action": "🔥",
    "adventure": "🧭",
    "anime": "⚔️",
    "biography": "📘",
    "comedy": "😄",
    "crime": "🕵️",
    "documentary": "🎬",
    "drama": "🎭",
    "family": "🏡",
    "fantasy": "✨",
    "history": "🏛️",
    "horror": "👻",
    "music": "🎵",
    "musical": "🎤",
    "mystery": "🧩",
    "romance": "💞",
    "sci-fi": "🚀",
    "sport": "🏅",
    "thriller": "⚡",
    "war": "🛡️",
}


def _load_poster_catalog_from_metadata(seed_movies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build movies catalog from poster metadata generated from manifest + OMDb."""
    metadata_path = DATA_DIR / "poster_catalog_metadata.json"
    posters_dir = BASE_DIR / "static" / "images" / "posters"

    if not metadata_path.exists():
        return [movie for movie in seed_movies if movie.get("poster_image")]

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [movie for movie in seed_movies if movie.get("poster_image")]

    items = payload.get("items", [])
    if not isinstance(items, list):
        return [movie for movie in seed_movies if movie.get("poster_image")]

    catalog: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_files: set[str] = set()

    for index, raw in enumerate(items, start=1):
        title = str(raw.get("title", "")).strip()
        poster_file = str(raw.get("file", "")).strip()
        if not title or not poster_file:
            continue
        if title.lower() in seen_titles or poster_file in seen_files:
            continue
        if not (posters_dir / poster_file).exists():
            continue

        raw_type = str(raw.get("type", "movie")).strip().lower()
        media_type = "series" if raw_type == "series" else "movie"

        genres = []
        for entry in raw.get("genres", []):
            cleaned = str(entry).strip().lower()
            if cleaned == "animation":
                cleaned = "anime"
            if cleaned and cleaned not in genres:
                genres.append(cleaned)
        if not genres:
            genres = ["drama"]

        raw_genre_display = str(raw.get("genre_display", "")).strip()
        if raw_genre_display:
            genre_parts = [part.strip() for part in raw_genre_display.split(",") if part.strip()]
            normalized_parts = ["Anime" if part.lower() == "animation" else part for part in genre_parts]
            genre_display = ", ".join(normalized_parts) if normalized_parts else ", ".join(g.title() for g in genres[:3])
        else:
            genre_display = ", ".join(g.title() for g in genres[:3])

        try:
            year = int(raw.get("year", 0) or 0)
        except (TypeError, ValueError):
            year = 0

        description = str(raw.get("description", "")).strip() or f"{title} is a {media_type} title in {genre_display}."
        why_helps = str(raw.get("why_helps", "")).strip() or (
            "A well-crafted story that can support reflection, focus, or emotional reset."
        )

        mood_tags = genres[:3] or ["steady"]
        primary = genres[0]

        movie = {
            "id": f"mov-{index:03d}",
            "title": title,
            "type": media_type,
            "genre": genre_display,
            "year": year,
            "categories": genres[:3],
            "description": description,
            "why_helps": why_helps,
            "mood_tags": mood_tags,
            "poster_emoji": MOVIE_POSTER_EMOJI_BY_CATEGORY.get(primary, "🎬"),
            "poster_image": f"images/posters/{poster_file}",
        }
        catalog.append(movie)
        seen_titles.add(title.lower())
        seen_files.add(poster_file)

    return catalog if catalog else [movie for movie in seed_movies if movie.get("poster_image")]


def _build_movie_categories(catalog: list[dict[str, Any]], limit: int = 24) -> list[str]:
    counts: dict[str, int] = {}
    allowed = set(MOVIE_POSTER_EMOJI_BY_CATEGORY.keys())
    for movie in catalog:
        for category in movie.get("categories", []):
            key = str(category).strip().lower()
            if not key or key not in allowed:
                continue
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        return ["drama", "comedy", "action", "romance"]

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [category for category, _ in ordered[:limit]]


# Replace the legacy seed list with poster-backed catalog and remove no-poster entries.
MOVIES_DATA = _load_poster_catalog_from_metadata(MOVIES_DATA)

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

MOVIE_CATEGORIES = _build_movie_categories(MOVIES_DATA)


@app.get("/movies")
def movies_page() -> str:
    category = request.args.get("category", "").strip().lower()
    search_q = request.args.get("q", "").strip().lower()
    try:
        page_number = int(request.args.get("page", "1") or "1")
    except ValueError:
        page_number = 1

    filtered = MOVIES_DATA
    if category:
        filtered = [m for m in filtered if category in m["categories"]]
    if search_q:
        filtered = [m for m in filtered if search_q in m["title"].lower() or search_q in m["description"].lower()]

    # Prioritize entries that have uploaded poster images so new poster-based movies surface first.
    filtered = sorted(filtered, key=lambda movie: 0 if movie.get("poster_image") else 1)

    per_page = 18
    total_results = len(filtered)
    total_pages = max(1, (total_results + per_page - 1) // per_page)
    page_number = max(1, min(page_number, total_pages))
    start_index = (page_number - 1) * per_page
    end_index = start_index + per_page
    page_movies = filtered[start_index:end_index]

    def movies_href(page: int) -> str:
        params: dict[str, Any] = {}
        if category:
            params["category"] = category
        if search_q:
            params["q"] = search_q
        if page > 1:
            params["page"] = page
        return url_for("movies_page", **params) + "#story-library"

    showing_from = start_index + 1 if total_results else 0
    showing_to = min(end_index, total_results)

    user = session.get("user")
    user_data = {}
    movie_profile = None
    if user:
        username = user.get("username", "")
        user_data = ensure_user_movie_profile(username)
        movie_profile = build_movie_profile(username)

    spotlight_movie = movie_profile["mood_match"] if movie_profile else (filtered[0] if filtered else MOVIES_DATA[0])
    if not spotlight_movie or not spotlight_movie.get("poster_image"):
        spotlight_movie = (
            next((movie for movie in filtered if movie.get("poster_image")), None)
            or next((movie for movie in MOVIES_DATA if movie.get("poster_image")), None)
            or spotlight_movie
        )

    return render_template(
        "movies.html",
        active_page="movies",
        body_class="page-movies",
        page_id="movies",
        page_title="Healing Through Stories | Heal Hub",
        movies=page_movies,
        total_results=total_results,
        showing_from=showing_from,
        showing_to=showing_to,
        page_number=page_number,
        total_pages=total_pages,
        has_prev_page=page_number > 1,
        has_next_page=page_number < total_pages,
        prev_page_href=movies_href(page_number - 1),
        next_page_href=movies_href(page_number + 1),
        categories=MOVIE_CATEGORIES,
        selected_category=category,
        search_q=search_q,
        user_movie_data=user_data,
        movie_profile=movie_profile,
        mood_match=spotlight_movie,
        featured_story_arc=filtered[:3],
    )


@app.get("/search")
def search_page() -> str:
    query = request.args.get("q", "").strip()
    needle = query.lower()

    movie_results: list[dict[str, Any]] = []
    people_results: list[dict[str, Any]] = []
    community_results: list[dict[str, Any]] = []

    if needle:
        movie_results = [
            movie
            for movie in MOVIES_DATA
            if needle in movie.get("title", "").lower()
            or needle in movie.get("description", "").lower()
            or needle in movie.get("genre", "").lower()
            or needle in " ".join(movie.get("categories", [])).lower()
        ]
        movie_results.sort(
            key=lambda movie: (
                needle not in movie.get("title", "").lower(),
                0 if movie.get("poster_image") else 1,
                -(movie.get("year") or 0),
            )
        )
        movie_results = movie_results[:8]

        current_username = (session.get("user") or {}).get("username", "")
        people_results = []
        for username, profile in PATIENT_PROFILES.items():
            if current_username and username == current_username:
                continue
            haystack = " ".join(
                [
                    str(profile.get("display_name", "")),
                    str(profile.get("bio", "")),
                    str(profile.get("location", "")),
                    " ".join(profile.get("interests", [])),
                    " ".join(profile.get("badges", [])),
                ]
            ).lower()
            if needle in haystack:
                people_results.append(profile)
        people_results.sort(
            key=lambda profile: (
                needle not in profile.get("display_name", "").lower(),
                profile.get("display_name", ""),
            )
        )
        people_results = people_results[:8]

        group_lookup = {group["id"]: group for group in COMMUNITY_GROUPS}
        for group in COMMUNITY_GROUPS:
            haystack = " ".join(
                [
                    str(group.get("name", "")),
                    str(group.get("description", "")),
                    str(group.get("category", "")),
                ]
            ).lower()
            if needle in haystack:
                community_results.append(
                    {
                        "kind": "group",
                        "title": group.get("name", "Community Group"),
                        "subtitle": f"{group.get('members', 0)} members",
                        "snippet": group.get("description", ""),
                        "href": url_for("community_page", group=group.get("id")) + "#community-feed",
                        "icon": group.get("icon", "🫂"),
                    }
                )

        for post in COMMUNITY_POSTS:
            haystack = " ".join(
                [
                    str(post.get("author", "")),
                    str(post.get("content", "")),
                ]
            ).lower()
            if needle in haystack:
                group = group_lookup.get(post.get("group_id", ""), {})
                content = str(post.get("content", ""))
                snippet = content if len(content) <= 160 else f"{content[:157].rstrip()}..."
                community_results.append(
                    {
                        "kind": "post",
                        "title": f"{post.get('author', 'Member')} in {group.get('name', 'Community')}",
                        "subtitle": post.get("timestamp", ""),
                        "snippet": snippet,
                        "href": (
                            url_for("community_page", group=post.get("group_id", ""), post_q=query)
                            + "#community-feed"
                        ),
                        "icon": "💬",
                    }
                )

        community_results = community_results[:10]

    total_results = len(movie_results) + len(people_results) + len(community_results)
    return render_template(
        "search.html",
        active_page="search",
        body_class="page-search",
        page_id="search",
        page_title=f"Search • {query} | Heal Hub" if query else "Search | Heal Hub",
        query=query,
        movie_results=movie_results,
        people_results=people_results,
        community_results=community_results,
        total_results=total_results,
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
        "id": "th-001", "name": "Dr. Aarav Sharma", "specialty": "Clinical Psychologist",
        "rating": 4.9, "reviews": 127, "experience": "12 years",
        "availability": "Mon, Wed, Fri — 10:00 AM to 4:00 PM",
        "bio": "Specializes in anxiety, depression, and trauma recovery. Uses CBT and mindfulness-based approaches.",
        "avatar_emoji": "👨‍⚕️",
        "avatar_image": "images/doctor1.png",
        "languages": ["English", "Hindi", "Nepali"],
        "is_top_choice": True,
        "tags": ["anxiety", "depression", "trauma", "CBT"],
    },
    {
        "id": "th-002", "name": "Dr. Nisha Patel", "specialty": "Psychiatrist",
        "rating": 4.8, "reviews": 98, "experience": "15 years",
        "availability": "Tue, Thu — 9:00 AM to 3:00 PM",
        "bio": "Expert in mood disorders, PTSD, and medication management. Compassionate and evidence-based care.",
        "avatar_emoji": "👩‍⚕️",
        "avatar_image": "images/doctor2.png",
        "languages": ["English", "Hindi"],
        "is_top_choice": False,
        "tags": ["mood disorders", "PTSD", "medication"],
    },
    {
        "id": "th-003", "name": "Dr. Rajiv Adhikari", "specialty": "Counseling Therapist",
        "rating": 4.7, "reviews": 84, "experience": "8 years",
        "availability": "Mon–Fri — 11:00 AM to 6:00 PM",
        "bio": "Focuses on relationship issues, self-esteem, and life transitions. Warm, empathetic approach.",
        "avatar_emoji": "👨‍⚕️",
        "avatar_image": "images/doctor3.png",
        "languages": ["English", "Nepali"],
        "is_top_choice": False,
        "tags": ["relationships", "self-esteem", "life transitions"],
    },
    {
        "id": "th-004", "name": "Dr. Suman Gurung", "specialty": "Stress & Burnout Therapist",
        "rating": 4.8, "reviews": 112, "experience": "10 years",
        "availability": "Mon, Wed, Sat — 9:00 AM to 2:00 PM",
        "bio": "Helps people recover from burnout, emotional fatigue, and work stress with practical care plans.",
        "avatar_emoji": "👨‍⚕️",
        "avatar_image": "images/doctor4.jpg",
        "languages": ["English", "Nepali"],
        "is_top_choice": False,
        "tags": ["stress", "burnout", "resilience", "creative routines"],
    },
    {
        "id": "th-005", "name": "Dr. Anita Thapa", "specialty": "Family Therapist",
        "rating": 4.7, "reviews": 73, "experience": "11 years",
        "availability": "Tue, Thu, Sat — 10:00 AM to 5:00 PM",
        "bio": "Helps families navigate conflict, communication challenges, and generational patterns with compassion.",
        "avatar_emoji": "👩‍⚕️",
        "avatar_image": "images/doctor5.jpg",
        "languages": ["English", "Nepali"],
        "is_top_choice": False,
        "tags": ["family", "communication", "conflict resolution"],
    },
    {
        "id": "th-006", "name": "Dr. Maya Lama", "specialty": "Women's Wellness Therapist",
        "rating": 4.9, "reviews": 65, "experience": "7 years",
        "availability": "Wed, Fri — 1:00 PM to 7:00 PM",
        "bio": "Dedicated to women's mental health, postpartum support, and empowerment counseling in a safe environment.",
        "avatar_emoji": "👩‍⚕️",
        "avatar_image": "images/doctor6.jpg",
        "languages": ["English", "Hindi", "Nepali"],
        "is_top_choice": True,
        "tags": ["women's health", "postpartum", "empowerment"],
    },
    {
        "id": "th-007", "name": "Dr. Bikram Rai", "specialty": "Trauma Recovery Therapist",
        "rating": 4.9, "reviews": 94, "experience": "9 years",
        "availability": "Mon, Thu, Sun — 12:00 PM to 7:00 PM",
        "bio": "Supports people through trauma-informed recovery with grounding, resilience planning, and gentle progress tracking.",
        "avatar_emoji": "🩺",
        "avatar_image": "images/doctor7.jpg",
        "languages": ["English", "Nepali"],
        "is_top_choice": True,
        "tags": ["trauma", "grounding", "resilience"],
    },
]

BOOKINGS_DATA: list[dict[str, Any]] = [
    {
        "id": "bk-001", "patient_username": "patient", "therapist_id": "th-001",
        "patient_name": "Aasha G.",
        "therapist_name": "Dr. Aarav Sharma", "date": "2026-04-02", "time": "10:30 AM",
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
    focus_filters = [
        {"key": "all", "label": "All"},
        {"key": "anxiety", "label": "Anxiety"},
        {"key": "relationships", "label": "Relationships"},
        {"key": "trauma", "label": "Trauma"},
        {"key": "women", "label": "Women's Care"},
        {"key": "family", "label": "Family"},
        {"key": "creative", "label": "Creative"},
    ]
    valid_focus = {item["key"] for item in focus_filters}
    selected_focus = request.args.get("focus", "all").strip().lower()
    if selected_focus not in valid_focus:
        selected_focus = "all"

    focus_keywords: dict[str, list[str]] = {
        "anxiety": ["anxiety", "stress", "cbt", "mindfulness"],
        "relationships": ["relationship", "self-esteem", "life transitions", "communication"],
        "trauma": ["trauma", "ptsd", "grief", "resilience"],
        "women": ["women", "postpartum", "empowerment"],
        "family": ["family", "communication", "conflict"],
        "creative": ["creative", "art", "music", "expressive"],
    }

    def matches_focus(therapist: dict[str, Any]) -> bool:
        if selected_focus == "all":
            return True
        haystack = f"{therapist.get('specialty', '')} {' '.join(therapist.get('tags', []))}".lower()
        return any(keyword in haystack for keyword in focus_keywords.get(selected_focus, []))

    filtered_therapists = [therapist for therapist in THERAPISTS_DATA if matches_focus(therapist)]
    sorted_therapists = sorted(
        filtered_therapists,
        key=lambda therapist: (
            not therapist.get("is_top_choice", False),
            -float(therapist.get("rating", 0)),
            therapist.get("name", ""),
        ),
    )
    top_doctors = sorted(
        THERAPISTS_DATA,
        key=lambda therapist: (
            not therapist.get("is_top_choice", False),
            -float(therapist.get("rating", 0)),
            therapist.get("name", ""),
        ),
    )[:7]

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
        therapists=sorted_therapists,
        top_doctors=top_doctors,
        focus_filters=focus_filters,
        selected_focus=selected_focus,
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


# ═══════════════════════════════════════════════════════════════
# PART 4.5 — PATIENT PROFILES, MESSAGING & CONNECTIONS
# ═══════════════════════════════════════════════════════════════

PATIENT_PROFILES: dict[str, dict[str, Any]] = {
    "patient": {
        "username": "patient",
        "display_name": "Aasha G.",
        "age": 74,
        "avatar": "👵",
        "bio": "Seeking steady healing and supportive community. Love stories with heart and family themes.",
        "location": "Kathmandu",
        "interests": ["healing", "inner child", "self-growth", "mental wellness", "family"],
        "conditions": ["Hypertension", "Type 2 diabetes risk"],
        "joined_communities": ["grp-001", "grp-003", "grp-005"],
        "movie_preferences": {
            "favorites": ["Coco", "Encanto", "Ted Lasso"],
            "watched_count": 13,
            "interested_in": ["healing", "women empowerment", "self-growth"],
        },
        "connection_status": "Open to friendship",
        "badges": ["Active Listener", "Community Helper", "Story Lover"],
        "member_since": "2026-01-15",
    },
    "riya-demo": {
        "username": "riya-demo",
        "display_name": "Riya T.",
        "age": 31,
        "avatar": "👩‍💼",
        "bio": "Recovering from burnout. Looking for like-minded people navigating life transitions.",
        "location": "Pokhara",
        "interests": ["self-growth", "motivation", "women empowerment", "travel"],
        "conditions": ["Burnout", "Sleep issues"],
        "joined_communities": ["grp-004", "grp-005", "grp-003"],
        "movie_preferences": {
            "favorites": ["Wild", "Eat Pray Love", "The Secret Life of Walter Mitty"],
            "watched_count": 8,
            "interested_in": ["self-growth", "women empowerment"],
        },
        "connection_status": "Open to friendship",
        "badges": ["Self-Care Advocate", "Community Builder"],
        "member_since": "2026-02-01",
    },
    "mina-demo": {
        "username": "mina-demo",
        "display_name": "Mina R.",
        "age": 28,
        "avatar": "🎨",
        "bio": "Artist & creative healer. Finding joy in connection and creative expression.",
        "location": "Kathmandu",
        "interests": ["inner child", "healing", "friendship", "creativity"],
        "conditions": ["Grief", "Social anxiety"],
        "joined_communities": ["grp-001", "grp-006", "grp-005"],
        "movie_preferences": {
            "favorites": ["Coco", "Encanto", "Heartstopper"],
            "watched_count": 11,
            "interested_in": ["healing", "inner child"],
        },
        "connection_status": "Open to friendship",
        "badges": ["Creative Connector", "Empathy Champion"],
        "member_since": "2026-02-10",
    },
    "pema-demo": {
        "username": "pema-demo",
        "display_name": "Pema S.",
        "age": 35,
        "avatar": "👩",
        "bio": "Supporting others through anxiety and building brave communities.",
        "location": "Lalitpur",
        "interests": ["mental wellness", "anxiety support", "friendship", "mindfulness"],
        "conditions": ["Anxiety disorder"],
        "joined_communities": ["grp-001", "grp-006"],
        "movie_preferences": {
            "favorites": ["Soul", "Heartstopper", "Good Will Hunting"],
            "watched_count": 9,
            "interested_in": ["mental wellness", "healing"],
        },
        "connection_status": "Open to friendship",
        "badges": ["Anxiety Warrior", "Supportive Friend"],
        "member_since": "2026-01-25",
    },
}


def editable_profile_defaults() -> dict[str, dict[str, Any]]:
    patient_profile = PATIENT_PROFILES.get("patient", {})
    doctor_user = DEMO_USERS.get("doctor", {})
    patient_user = DEMO_USERS.get("patient", {})
    return {
        "patient": {
            "username": "patient",
            "role": "patient",
            "display_name": str(patient_profile.get("display_name", patient_user.get("display_name", "Patient"))),
            "headline": str(patient_user.get("headline", "Patient Portal")),
            "bio": str(patient_profile.get("bio", "Tell people a little about yourself.")),
            "location": str(patient_profile.get("location", "Kathmandu")),
            "avatar": str(patient_profile.get("avatar", "🙂")),
            "avatar_image": str(patient_profile.get("avatar_image", "")),
        },
        "doctor": {
            "username": "doctor",
            "role": "doctor",
            "display_name": str(doctor_user.get("display_name", "Doctor")),
            "headline": str(doctor_user.get("headline", "Clinical Operations Lead")),
            "bio": "Primary doctor linked to the patient dashboard for follow-ups, care-plan questions, and medication support.",
            "location": "Clinical Operations",
            "avatar": "🩺",
            "avatar_image": "",
        },
    }


def load_user_profiles() -> dict[str, dict[str, Any]]:
    profiles = copy.deepcopy(editable_profile_defaults())
    if not USER_PROFILES_PATH.exists():
        return profiles

    stored = load_json(USER_PROFILES_PATH)
    if not isinstance(stored, dict):
        return profiles

    for username, values in stored.items():
        if username not in profiles or not isinstance(values, dict):
            continue
        for key in ("display_name", "headline", "bio", "location", "avatar", "avatar_image"):
            if key in values:
                profiles[username][key] = str(values.get(key, "")).strip()
    return profiles


def save_user_profiles(profiles: dict[str, dict[str, Any]]) -> None:
    save_json(USER_PROFILES_PATH, profiles)


def account_profile_for_username(username: str) -> dict[str, Any] | None:
    cleaned = str(username).strip()
    if not cleaned:
        return None

    profiles = load_user_profiles()
    if cleaned in profiles:
        return copy.deepcopy(profiles[cleaned])

    if cleaned in PATIENT_PROFILES:
        patient = PATIENT_PROFILES[cleaned]
        return {
            "username": cleaned,
            "role": "patient",
            "display_name": str(patient.get("display_name", cleaned)),
            "headline": "Patient Portal",
            "bio": str(patient.get("bio", "")),
            "location": str(patient.get("location", "")),
            "avatar": str(patient.get("avatar", "🙂")),
            "avatar_image": str(patient.get("avatar_image", "")),
        }

    if cleaned in DEMO_USERS:
        demo_user = DEMO_USERS[cleaned]
        return {
            "username": cleaned,
            "role": str(demo_user.get("role", "")),
            "display_name": str(demo_user.get("display_name", cleaned)),
            "headline": str(demo_user.get("headline", demo_user.get("role", ""))),
            "bio": "",
            "location": "",
            "avatar": "🙂",
            "avatar_image": "",
        }

    return None


def sync_user_profiles() -> dict[str, dict[str, Any]]:
    profiles = load_user_profiles()
    save_user_profiles(profiles)

    patient_profile = profiles.get("patient", {})
    if patient_profile:
        DEMO_USERS.setdefault("patient", {}).update(
            {
                "display_name": patient_profile.get("display_name", DEMO_USERS.get("patient", {}).get("display_name", "Patient")),
                "headline": patient_profile.get("headline", DEMO_USERS.get("patient", {}).get("headline", "Patient Portal")),
            }
        )
        PATIENT_PROFILES.setdefault("patient", {}).update(
            {
                "display_name": patient_profile.get("display_name", "Patient"),
                "bio": patient_profile.get("bio", ""),
                "location": patient_profile.get("location", ""),
                "avatar": patient_profile.get("avatar", "🙂"),
                "avatar_image": patient_profile.get("avatar_image", ""),
            }
        )
        if "patient" in PORTAL_PATIENTS:
            PORTAL_PATIENTS["patient"]["display_name"] = patient_profile.get("display_name", PORTAL_PATIENTS["patient"].get("display_name", "Patient"))
        for booking in BOOKINGS_DATA:
            if booking.get("patient_username") == "patient":
                booking["patient_name"] = patient_profile.get("display_name", booking.get("patient_name", "Patient"))
        for client in DOCTOR_CLIENTS_DATA:
            if client.get("username") == "patient":
                client["display_name"] = patient_profile.get("display_name", client.get("display_name", "Patient"))

    doctor_profile = profiles.get("doctor", {})
    if doctor_profile:
        DEMO_USERS.setdefault("doctor", {}).update(
            {
                "display_name": doctor_profile.get("display_name", DEMO_USERS.get("doctor", {}).get("display_name", "Doctor")),
                "headline": doctor_profile.get("headline", DEMO_USERS.get("doctor", {}).get("headline", "Clinical Operations Lead")),
            }
        )
        for portal_patient in PORTAL_PATIENTS.values():
            if portal_patient.get("doctor_username") == "doctor":
                portal_patient["doctor_name"] = doctor_profile.get("display_name", portal_patient.get("doctor_name", "Doctor"))

    return profiles


def clean_profile_line(value: str, max_length: int) -> str:
    return " ".join(str(value).strip().split())[:max_length]


def clean_profile_bio(value: str, max_length: int) -> str:
    return str(value).strip()[:max_length]


def save_profile_image(file_storage: Any, username: str) -> str:
    filename = secure_filename(str(getattr(file_storage, "filename", "") or ""))
    if not filename:
        return ""

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_PROFILE_IMAGE_EXTENSIONS:
        raise ValueError("Use a PNG, JPG, JPEG, WEBP, or GIF image for the profile picture.")

    PROFILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_name = f"{username}-{uuid4().hex[:10]}.{suffix}"
    target_path = PROFILE_UPLOAD_DIR / target_name
    file_storage.save(target_path)
    return f"uploads/profiles/{target_name}"


def update_dashboard_profile(user: dict[str, Any]) -> dict[str, Any]:
    username = str(user.get("username", "")).strip()
    if username not in {"patient", "doctor"}:
        raise ValueError("Only the patient and doctor demo accounts can edit dashboard profiles right now.")

    profiles = load_user_profiles()
    existing = profiles.get(username) or editable_profile_defaults().get(username, {})
    uploaded_image = request.files.get("avatar_image")
    avatar_image = existing.get("avatar_image", "")
    if uploaded_image and getattr(uploaded_image, "filename", ""):
        avatar_image = save_profile_image(uploaded_image, username)

    updated = {
        **existing,
        "display_name": clean_profile_line(request.form.get("display_name", existing.get("display_name", "")), 80)
        or existing.get("display_name", username.title()),
        "headline": clean_profile_line(request.form.get("headline", existing.get("headline", "")), 90)
        or existing.get("headline", user.get("role", "").title()),
        "location": clean_profile_line(request.form.get("location", existing.get("location", "")), 80)
        or existing.get("location", ""),
        "bio": clean_profile_bio(request.form.get("bio", existing.get("bio", "")), 280)
        or existing.get("bio", ""),
        "avatar": clean_profile_line(request.form.get("avatar", existing.get("avatar", "🙂")), 12)
        or existing.get("avatar", "🙂"),
        "avatar_image": avatar_image,
    }
    profiles[username] = updated
    save_user_profiles(profiles)
    sync_user_profiles()

    session_user = dict(session.get("user", {}))
    session_user["display_name"] = updated["display_name"]
    session_user["headline"] = updated["headline"]
    session["user"] = session_user
    session.modified = True
    return updated


def therapist_profile_for_chat(therapist_id: str) -> dict[str, Any] | None:
    therapist = next((item for item in THERAPISTS_DATA if item.get("id") == therapist_id), None)
    if not therapist:
        return None

    return {
        "username": therapist["id"],
        "display_name": therapist["name"],
        "avatar": therapist.get("avatar_emoji", "🩺"),
        "avatar_image": therapist.get("avatar_image", ""),
        "bio": therapist.get("bio", "Therapist on the Heal Hub care team."),
        "location": therapist.get("specialty", "Therapist"),
        "interests": therapist.get("tags", []),
        "joined_communities": [],
        "connection_status": "Therapist",
        "member_since": "",
        "role": "doctor",
        "profile_href": url_for("therapists_page"),
        "profile_link_label": "View therapists",
    }


def doctor_profile_for_chat(username: str) -> dict[str, Any] | None:
    if username != "doctor" or username not in DEMO_USERS:
        return None

    profile = account_profile_for_username(username) or {}
    user = DEMO_USERS[username]
    return {
        "username": username,
        "display_name": profile.get("display_name", user.get("display_name", "Doctor")),
        "avatar": profile.get("avatar", "🩺"),
        "avatar_image": profile.get("avatar_image", ""),
        "bio": profile.get("bio", "Primary doctor linked to the patient dashboard for follow-ups, care-plan questions, and prescription support."),
        "location": profile.get("location", "Clinical Operations"),
        "interests": ["follow-up care", "medication support", "patient guidance"],
        "joined_communities": [],
        "connection_status": "Doctor",
        "member_since": "",
        "role": "doctor",
        "headline": profile.get("headline", user.get("headline", "Clinical Operations Lead")),
        "profile_href": "",
        "profile_link_label": "",
    }


def message_partner_profile(username: str) -> dict[str, Any] | None:
    patient_profile = PATIENT_PROFILES.get(username)
    if patient_profile:
        return {
            **patient_profile,
            "role": "patient",
            "profile_href": url_for("view_patient_profile", username=username),
            "profile_link_label": "View profile",
        }

    doctor_profile = doctor_profile_for_chat(username)
    if doctor_profile:
        return doctor_profile

    return therapist_profile_for_chat(username)


def messageable_partner_usernames(user: dict[str, Any]) -> set[str]:
    current_username = user.get("username", "")
    allowed = set(USER_CONNECTIONS.get(current_username, {}).get("friends", []))
    role = user.get("role", "")

    if role == "patient":
        portal_patient = portal_patient_for_user(user)
        doctor_username = str(portal_patient.get("doctor_username", "")).strip()
        if doctor_username:
            allowed.add(doctor_username)

        for booking in BOOKINGS_DATA:
            if booking.get("patient_username") == current_username and booking.get("therapist_id"):
                allowed.add(str(booking["therapist_id"]).strip())

    if role == "doctor":
        allowed.update(
            booking.get("patient_username", "")
            for booking in BOOKINGS_DATA
            if booking.get("patient_username")
        )
        allowed.update(PORTAL_PATIENTS.keys())

    allowed.discard("")
    allowed.discard(current_username)
    return {username for username in allowed if message_partner_profile(username)}


def can_message_partner(user: dict[str, Any], partner_username: str) -> bool:
    cleaned = str(partner_username).strip()
    if not cleaned or cleaned == user.get("username", ""):
        return False
    return cleaned in messageable_partner_usernames(user)


sync_user_profiles()

MESSAGES_DATA: list[dict[str, Any]] = [
    {
        "id": "msg-001",
        "from_user": "riya-demo",
        "to_user": "patient",
        "from_display": "Riya T.",
        "content": "Hi Aasha! I loved your post about finding peace with uncertainty. It really resonated with me.",
        "timestamp": "2026-03-29 14:30",
        "read": True,
    },
    {
        "id": "msg-002",
        "from_user": "patient",
        "to_user": "riya-demo",
        "from_display": "Aasha G.",
        "content": "Thank you so much! I'd love to hear about your story too. Would be nice to connect.",
        "timestamp": "2026-03-29 15:45",
        "read": True,
    },
    {
        "id": "msg-003",
        "from_user": "mina-demo",
        "to_user": "patient",
        "from_display": "Mina R.",
        "content": "Your thoughts about stories helping with healing really inspired me. Want to chat about favorite movies? 🎬",
        "timestamp": "2026-03-28 10:20",
        "read": False,
    },
]

USER_CONNECTIONS: dict[str, dict[str, Any]] = {
    "patient": {
        "friends": ["riya-demo", "mina-demo"],
        "requests_received": ["pema-demo"],
        "requests_sent": [],
        "blocked": [],
    },
    "riya-demo": {
        "friends": ["patient"],
        "requests_received": [],
        "requests_sent": [],
        "blocked": [],
    },
    "mina-demo": {
        "friends": ["patient"],
        "requests_received": [],
        "requests_sent": [],
        "blocked": [],
    },
    "pema-demo": {
        "friends": [],
        "requests_received": [],
        "requests_sent": ["patient"],
        "blocked": [],
    },
}




COMMUNITY_GROUP_ENHANCEMENTS: dict[str, dict[str, Any]] = {
    "grp-001": {
        "pace": "Gentle check-ins",
        "session": "Tue & Sat • 7:00 PM",
        "host": "Peer-led + clinician reviewed",
        "focus_tags": ["grounding", "work anxiety", "breath resets"],
    },
    "grp-002": {
        "pace": "Soft landing space",
        "session": "Mon & Thu • 8:15 PM",
        "host": "Story-guided circle",
        "focus_tags": ["heartbreak", "grief", "starting over"],
    },
    "grp-003": {
        "pace": "Empowering + private",
        "session": "Wed • 6:30 PM",
        "host": "Moderated women-only circle",
        "focus_tags": ["boundaries", "confidence", "belonging"],
    },
    "grp-004": {
        "pace": "Practical reset",
        "session": "Fri • 7:45 PM",
        "host": "Burnout recovery coach",
        "focus_tags": ["stress relief", "rest", "work-life balance"],
    },
    "grp-005": {
        "pace": "Reflective growth",
        "session": "Sun • 10:00 AM",
        "host": "Habit + story exchange",
        "focus_tags": ["habits", "motivation", "small wins"],
    },
    "grp-006": {
        "pace": "Open and welcoming",
        "session": "Daily • drop-in threads",
        "host": "Community team present",
        "focus_tags": ["gentle support", "life updates", "safe sharing"],
    },
}

COMMUNITY_EVENTS: list[dict[str, Any]] = [
    {
        "id": "evt-001",
        "group_id": "grp-006",
        "title": "Evening check-in circle",
        "time_label": "Tonight • 7:30 PM",
        "format": "Drop-in",
        "host": "Mina R.",
        "description": "A calm 45-minute group for anyone needing a softer landing after a long day.",
        "capacity_note": "7 seats left",
    },
    {
        "id": "evt-002",
        "group_id": "grp-004",
        "title": "Burnout reset workshop",
        "time_label": "Tomorrow • 6:00 PM",
        "format": "Guided session",
        "host": "Riya T.",
        "description": "Practical routines for coming down from overwork without guilt.",
        "capacity_note": "12 seats left",
    },
    {
        "id": "evt-003",
        "group_id": "grp-003",
        "title": "Boundaries practice room",
        "time_label": "Thursday • 8:00 PM",
        "format": "Role-play circle",
        "host": "Laxmi G.",
        "description": "Supportive scripts and gentle rehearsal for hard conversations.",
        "capacity_note": "Private circle",
    },
    {
        "id": "evt-004",
        "group_id": "grp-005",
        "title": "Small wins Sunday",
        "time_label": "Sunday • 10:00 AM",
        "format": "Community ritual",
        "host": "Heal Hub Team",
        "description": "Share one tiny thing that moved you forward this week.",
        "capacity_note": "Open to all",
    },
]

COMMUNITY_PROMPT_LIBRARY: list[dict[str, str]] = [
    {
        "label": "Ask for support",
        "kind": "help",
        "mood": "anxious",
        "text": "I'm carrying something heavy today and could really use a few gentle ideas or kind words about...",
    },
    {
        "label": "Share a win",
        "kind": "win",
        "mood": "hopeful",
        "text": "A small win I'm proud of today is...",
    },
    {
        "label": "Reflect honestly",
        "kind": "discussion",
        "mood": "steady",
        "text": "Something I noticed about myself lately is...",
    },
    {
        "label": "Offer a resource",
        "kind": "resource",
        "mood": "grateful",
        "text": "Something that supported me recently and might help someone else here is...",
    },
]

COMMUNITY_GUIDELINES: list[dict[str, str]] = [
    {
        "title": "Lead with empathy",
        "detail": "Respond to the feeling first, then offer one gentle suggestion if it is welcome.",
    },
    {
        "title": "Protect privacy",
        "detail": "Keep identifying details light. Use anonymous posting whenever that feels safer.",
    },
    {
        "title": "Support over fixing",
        "detail": "This space values reflection, validation, and care more than pressure or judgment.",
    },
]

COMMUNITY_POST_KIND_OPTIONS: list[dict[str, str]] = [
    {"id": "discussion", "label": "Discussion"},
    {"id": "help", "label": "Ask for help"},
    {"id": "win", "label": "Small win"},
    {"id": "event", "label": "Event"},
    {"id": "resource", "label": "Helpful resource"},
]

COMMUNITY_MOOD_OPTIONS: list[dict[str, str]] = [
    {"id": "steady", "label": "Steady"},
    {"id": "hopeful", "label": "Hopeful"},
    {"id": "anxious", "label": "Anxious"},
    {"id": "overwhelmed", "label": "Overwhelmed"},
    {"id": "grateful", "label": "Grateful"},
]

COMMUNITY_REACTION_OPTIONS: list[dict[str, str]] = [
    {"id": "support", "emoji": "💙", "label": "Support"},
    {"id": "relate", "emoji": "🤝", "label": "Relate"},
    {"id": "celebrate", "emoji": "🌟", "label": "Celebrate"},
    {"id": "insight", "emoji": "💡", "label": "Insight"},
]


def community_group_index() -> dict[str, dict[str, Any]]:
    return {group["id"]: group for group in COMMUNITY_GROUPS}


def normalize_community_kind(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "reflection": "discussion",
        "reflect": "discussion",
        "question": "help",
        "ask": "help",
        "ask_for_help": "help",
        "support": "help",
    }
    raw = aliases.get(raw, raw)
    allowed = {"discussion", "help", "win", "event", "resource"}
    return raw if raw in allowed else "discussion"


def community_kind_label(kind: str) -> str:
    return {
        "discussion": "Discussion",
        "help": "Ask for help",
        "win": "Small win",
        "event": "Event",
        "resource": "Helpful resource",
    }.get(kind, "Discussion")


def normalize_community_mood(value: Any) -> str:
    raw = str(value or "").strip().lower()
    allowed = {"steady", "hopeful", "anxious", "overwhelmed", "grateful"}
    return raw if raw in allowed else "steady"


def community_mood_label(mood: str) -> str:
    return {
        "steady": "Steady",
        "hopeful": "Hopeful",
        "anxious": "Anxious",
        "overwhelmed": "Overwhelmed",
        "grateful": "Grateful",
    }.get(mood, "Steady")


def parse_demo_timestamp(value: Any) -> datetime:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return datetime(2026, 3, 1, 9, 0)


def community_author_badge(author: str) -> str:
    clean_author = str(author or "").strip()
    for profile in PATIENT_PROFILES.values():
        if profile.get("display_name") == clean_author:
            return profile.get("avatar", "💬")
    if clean_author.lower().startswith("anonymous"):
        return "🌙"
    return "💬"


def infer_post_author_username(post: dict[str, Any]) -> str:
    explicit = str(post.get("author_username", "")).strip()
    if explicit:
        return explicit
    author = str(post.get("author", "")).strip().lower()
    for username, profile in PATIENT_PROFILES.items():
        if profile.get("display_name", "").strip().lower() == author:
            return username
    if author and not author.startswith("anonymous"):
        slug = "".join(char if char.isalnum() else "-" for char in author).strip("-")
        if slug:
            return f"name:{slug}"
    return ""


def infer_community_post_tags(content: str, group_id: str, kind: str, mood: str) -> list[str]:
    content_lower = content.lower()
    group = community_group_index().get(group_id, {})
    tags = [str(group.get("category", "support")).strip()]

    if kind == "help" or "?" in content:
        tags.insert(0, "asking for support")
    if kind == "discussion":
        tags.insert(0, "open discussion")
    if kind == "win" or any(word in content_lower for word in ["win", "proud", "lighter", "progress", "boundary"]):
        tags.insert(0, "small win")
    if kind == "event":
        tags.insert(0, "event invite")
    if kind == "resource":
        tags.insert(0, "helpful resource")

    if mood in {"anxious", "overwhelmed"}:
        tags.append("gentle replies")
    if mood in {"hopeful", "grateful"}:
        tags.append("hopeful energy")
    if any(word in content_lower for word in ["meeting", "work", "office", "burnout", "job"]):
        tags.append("work life")
    if any(word in content_lower for word in ["boundary", "boundaries"]):
        tags.append("boundaries")
    if any(word in content_lower for word in ["grief", "loss", "breakup", "heartbreak"]):
        tags.append("grief care")
    if any(word in content_lower for word in ["routine", "habit", "meditation", "journal", "walk"]):
        tags.append("daily rituals")

    return dedupe_preserving_order([tag for tag in tags if tag])[:4]


def ensure_community_post_shape(post: dict[str, Any]) -> dict[str, Any]:
    post["kind"] = normalize_community_kind(post.get("kind"))
    post["mood"] = normalize_community_mood(post.get("mood"))
    post["anonymous"] = as_bool(post.get("anonymous", False))

    try:
        likes = int(post.get("likes", 0) or 0)
    except (TypeError, ValueError):
        likes = 0

    reactions = post.get("reactions") if isinstance(post.get("reactions"), dict) else {}
    normalized_reactions = {
        "support": likes,
        "relate": 0,
        "celebrate": 0,
        "insight": 0,
    }
    for key in normalized_reactions:
        try:
            normalized_reactions[key] = int(reactions.get(key, normalized_reactions[key]) or 0)
        except (TypeError, ValueError):
            normalized_reactions[key] = normalized_reactions[key]
    if normalized_reactions["support"] < likes:
        normalized_reactions["support"] = likes

    post["reactions"] = normalized_reactions
    post["likes"] = normalized_reactions["support"]

    try:
        post["bookmarks"] = int(post.get("bookmarks", 0) or 0)
    except (TypeError, ValueError):
        post["bookmarks"] = 0

    post["author_username"] = infer_post_author_username(post)
    if not post.get("author"):
        post["author"] = "Anonymous member" if post["anonymous"] else "Heal Hub Member"

    tag_values = [str(item).strip() for item in post.get("tags", []) if str(item).strip()]
    post["tags"] = tag_values or infer_community_post_tags(
        str(post.get("content", "")),
        str(post.get("group_id", "")),
        post["kind"],
        post["mood"],
    )

    replies = post.setdefault("replies", [])
    for reply in replies:
        reply["avatar"] = community_author_badge(reply.get("author", ""))
    return post


def serialize_community_post(post: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(ensure_community_post_shape(post))
    normalized["reaction_total"] = sum(int(value) for value in normalized.get("reactions", {}).values())
    normalized["reply_count"] = len(normalized.get("replies", []))
    normalized["kind_label"] = community_kind_label(normalized["kind"])
    normalized["mood_label"] = community_mood_label(normalized["mood"])
    normalized["author_badge"] = community_author_badge(normalized.get("author", ""))
    normalized["group"] = community_group_index().get(normalized.get("group_id", ""), {})
    normalized["care_note"] = (
        "This post is asking for support. Begin with validation, then offer one gentle idea."
        if normalized["kind"] == "help"
        else "Celebrate the progress before adding advice."
        if normalized["kind"] == "win"
        else "Confirm timing, tone, and practical details so people can join with confidence."
        if normalized["kind"] == "event"
        else "Reflect what feels true or useful before trying to solve anything."
    )
    return normalized


def default_community_profile() -> dict[str, Any]:
    return {
        "joined_groups": [],
        "posts_count": 0,
        "support_given": 0,
        "support_received": 0,
        "comfort_topics": [],
        "saved_posts_count": 0,
        "muted_users": [],
    }


def build_community_group_cards(username: str = "", selected_group_id: str = "") -> list[dict[str, Any]]:
    user_profile = PATIENT_PROFILES.get(username, {})
    community_state = USER_COMMUNITY_DATA.get(username, default_community_profile())
    joined_ids = set(community_state.get("joined_groups", []))
    comfort_topics = [str(item).strip().lower() for item in community_state.get("comfort_topics", []) if str(item).strip()]
    user_interests = [str(item).strip().lower() for item in user_profile.get("interests", []) if str(item).strip()]

    cards: list[dict[str, Any]] = []
    for base_group in COMMUNITY_GROUPS:
        group = copy.deepcopy(base_group)
        enhancements = COMMUNITY_GROUP_ENHANCEMENTS.get(group["id"], {})
        group.update(enhancements)
        focus_tags = [str(item).strip() for item in enhancements.get("focus_tags", []) if str(item).strip()]
        group["focus_tags"] = focus_tags or [group.get("category", "support")]
        group["is_joined"] = group["id"] in joined_ids

        score = 0
        if group["is_joined"]:
            score += 36
        if selected_group_id and selected_group_id == group["id"]:
            score += 8
        if group.get("category", "").lower() in user_interests:
            score += 20
        haystack = " ".join(group["focus_tags"]).lower() + " " + group.get("description", "").lower()
        for topic in comfort_topics:
            if topic and topic in haystack:
                score += 8
        group["match_score"] = score
        group["match_label"] = "Already in your map" if group["is_joined"] else "Great match" if score >= 24 else "Worth exploring"
        group["match_reason"] = (
            "You already belong here, so you can jump straight into the current conversation."
            if group["is_joined"]
            else "This circle overlaps with your interests or comfort topics."
            if score >= 24
            else "A thoughtful space if you want to branch into something new."
        )
        cards.append(group)

    cards.sort(key=lambda item: (not item.get("is_joined", False), -item.get("match_score", 0), -item.get("members", 0)))
    return cards


def build_community_events(selected_group_id: str = "") -> list[dict[str, Any]]:
    group_lookup = community_group_index()
    events: list[dict[str, Any]] = []
    for raw_event in COMMUNITY_EVENTS:
        event = copy.deepcopy(raw_event)
        event["group"] = group_lookup.get(event.get("group_id", ""), {})
        event["is_selected_group"] = bool(selected_group_id and selected_group_id == event.get("group_id"))
        events.append(event)
    events.sort(key=lambda item: (not item.get("is_selected_group", False), item.get("time_label", ""), item.get("title", "")))
    return events


def build_people_discovery(
    username: str,
    my_connections: dict[str, Any],
    people_q: str = "",
    people_interest: str = "",
    selected_group_id: str = "",
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    current_profile = PATIENT_PROFILES.get(username, {})
    current_interests = {str(item).strip().lower() for item in current_profile.get("interests", []) if str(item).strip()}
    current_groups = set(current_profile.get("joined_communities", []))
    current_location = str(current_profile.get("location", "")).strip().lower()

    raw_people: list[dict[str, Any]] = []
    interest_options: set[str] = set()
    for profile_username, profile in PATIENT_PROFILES.items():
        if profile_username == username:
            continue
        if profile_username in my_connections.get("blocked", []):
            continue

        person = copy.deepcopy(profile)
        if profile_username in my_connections.get("friends", []):
            relationship_status = "connected"
        elif profile_username in my_connections.get("requests_sent", []):
            relationship_status = "request_sent"
        elif profile_username in my_connections.get("requests_received", []):
            relationship_status = "request_received"
        else:
            relationship_status = "discover"

        person_interests = [str(item).strip() for item in person.get("interests", []) if str(item).strip()]
        shared_interests = [item for item in person_interests if item.lower() in current_interests]
        shared_group_ids = current_groups.intersection(person.get("joined_communities", []))
        shared_groups = [group["name"] for group in COMMUNITY_GROUPS if group["id"] in shared_group_ids]
        same_location = current_location and current_location == str(person.get("location", "")).strip().lower()

        match_score = len(shared_groups) * 18 + len(shared_interests) * 10 + (6 if same_location else 0)
        if selected_group_id and selected_group_id in person.get("joined_communities", []):
            match_score += 10

        person["relationship_status"] = relationship_status
        person["shared_interests"] = shared_interests[:3]
        person["shared_groups"] = shared_groups[:2]
        person["match_score"] = match_score
        person["match_reason"] = (
            f"{len(shared_groups)} shared circles and {len(shared_interests)} shared interests."
            if shared_groups or shared_interests
            else "A fresh connection outside your current circles."
        )
        person["same_location"] = same_location

        interest_options.update(item.lower() for item in person_interests)
        raw_people.append(person)

    recommended_people = sorted(
        raw_people,
        key=lambda person: (
            person.get("relationship_status") not in {"request_received", "connected"},
            -person.get("match_score", 0),
            person.get("display_name", ""),
        ),
    )[:3]
    request_cards = [person for person in recommended_people if person.get("relationship_status") == "request_received"]
    if not request_cards:
        request_cards = [person for person in raw_people if person.get("relationship_status") == "request_received"][:3]

    filtered_people = raw_people
    if people_q:
        filtered_people = [
            person for person in filtered_people
            if people_q in person.get("display_name", "").lower()
            or people_q in person.get("bio", "").lower()
            or people_q in person.get("location", "").lower()
            or people_q in " ".join(person.get("interests", [])).lower()
        ]

    if people_interest:
        filtered_people = [
            person for person in filtered_people
            if people_interest in [item.lower() for item in person.get("interests", [])]
        ]

    relationship_rank = {"request_received": 0, "connected": 1, "discover": 2, "request_sent": 3}
    filtered_people = sorted(
        filtered_people,
        key=lambda person: (
            relationship_rank.get(person.get("relationship_status", "discover"), 4),
            -person.get("match_score", 0),
            person.get("display_name", ""),
        ),
    )
    return filtered_people, sorted(interest_options), recommended_people, request_cards


def build_filtered_community_posts(
    group_id: str = "",
    feed_filter: str = "all",
    sort_by: str = "recent",
    post_q: str = "",
    joined_ids: set[str] | None = None,
    muted_author_usernames: set[str] | None = None,
) -> list[dict[str, Any]]:
    joined_ids = joined_ids or set()
    muted_author_usernames = muted_author_usernames or set()
    posts = [serialize_community_post(post) for post in COMMUNITY_POSTS]

    if muted_author_usernames:
        posts = [
            post for post in posts
            if str(post.get("author_username", "")).strip() not in muted_author_usernames
        ]

    if group_id:
        posts = [post for post in posts if post.get("group_id") == group_id]

    if feed_filter == "joined":
        posts = [post for post in posts if post.get("group_id") in joined_ids]
    elif feed_filter == "questions":
        posts = [post for post in posts if post.get("kind") in {"help", "question"} or "?" in post.get("content", "")]
    elif feed_filter == "wins":
        posts = [post for post in posts if post.get("kind") == "win"]
    elif feed_filter == "events":
        posts = [post for post in posts if post.get("kind") == "event"]
    elif feed_filter == "trending":
        posts = [post for post in posts if post.get("reaction_total", 0) >= 40 or post.get("reply_count", 0) >= 2]
    elif feed_filter == "saved":
        posts = [post for post in posts if post.get("bookmarks", 0) > 0]

    if post_q:
        needle = post_q.lower()
        posts = [
            post for post in posts
            if needle in post.get("content", "").lower()
            or needle in post.get("author", "").lower()
            or needle in " ".join(post.get("tags", [])).lower()
            or needle in str((post.get("group") or {}).get("name", "")).lower()
        ]

    if sort_by == "supported":
        posts.sort(
            key=lambda post: (post.get("reaction_total", 0), post.get("likes", 0), parse_demo_timestamp(post.get("timestamp"))),
            reverse=True,
        )
    elif sort_by == "discussed":
        posts.sort(
            key=lambda post: (post.get("reply_count", 0), post.get("reaction_total", 0), parse_demo_timestamp(post.get("timestamp"))),
            reverse=True,
        )
    elif sort_by == "saved":
        posts.sort(
            key=lambda post: (post.get("bookmarks", 0), post.get("reaction_total", 0), parse_demo_timestamp(post.get("timestamp"))),
            reverse=True,
        )
    else:
        posts.sort(key=lambda post: parse_demo_timestamp(post.get("timestamp")), reverse=True)

    return posts



@app.get("/community")
def community_page() -> str:
    group_id = request.args.get("group", "").strip()
    people_q = request.args.get("people_q", "").strip().lower()
    people_interest = request.args.get("people_interest", "").strip().lower()
    feed_filter = request.args.get("feed", "all").strip().lower() or "all"
    sort_by = request.args.get("sort", "recent").strip().lower() or "recent"
    post_q = request.args.get("post_q", "").strip()

    valid_feed_filters = {"all", "joined", "questions", "wins", "events", "trending", "saved"}
    valid_sort_options = {"recent", "supported", "discussed", "saved"}
    if feed_filter not in valid_feed_filters:
        feed_filter = "all"
    if sort_by not in valid_sort_options:
        sort_by = "recent"

    user = session.get("user")
    user_community = {}
    community_profile = None
    people_results: list[dict[str, Any]] = []
    people_interest_options: list[str] = []
    my_connections = {"friends": [], "requests_sent": [], "requests_received": [], "blocked": []}
    recommended_people: list[dict[str, Any]] = []
    request_cards: list[dict[str, Any]] = []
    joined_ids: set[str] = set()
    muted_author_usernames: set[str] = set()

    username = ""
    if user:
        username = user.get("username", "")
        user_community = USER_COMMUNITY_DATA.get(username, default_community_profile())
        community_profile = build_community_profile(username)
        my_connections = USER_CONNECTIONS.get(username, my_connections)
        joined_ids = set((community_profile or {}).get("profile", {}).get("joined_groups", []))
        muted_author_usernames = {
            str(item).strip()
            for item in (community_profile or {}).get("profile", {}).get("muted_users", [])
            if str(item).strip()
        }
        people_results, people_interest_options, recommended_people, request_cards = build_people_discovery(
            username,
            my_connections,
            people_q=people_q,
            people_interest=people_interest,
            selected_group_id=group_id,
        )

    group_cards = build_community_group_cards(username=username, selected_group_id=group_id)
    group_lookup = {group["id"]: group for group in group_cards}
    selected_group = group_lookup.get(group_id)

    posts = build_filtered_community_posts(
        group_id=group_id,
        feed_filter=feed_filter,
        sort_by=sort_by,
        post_q=post_q,
        joined_ids=joined_ids,
        muted_author_usernames=muted_author_usernames,
    )

    def community_href(**kwargs: Any) -> str:
        params: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value not in {None, ""}:
                params[key] = value
        return url_for("community_page", **params)

    feed_filters = [
        {
            "id": "all",
            "label": "All conversations",
            "active": feed_filter == "all",
            "href": community_href(group=group_id, feed="all", sort=sort_by, post_q=post_q) + "#community-feed",
        },
        {
            "id": "joined",
            "label": "My circles",
            "active": feed_filter == "joined",
            "href": community_href(group=group_id, feed="joined", sort=sort_by, post_q=post_q) + "#community-feed",
        },
        {
            "id": "questions",
            "label": "Support asks",
            "active": feed_filter == "questions",
            "href": community_href(group=group_id, feed="questions", sort=sort_by, post_q=post_q) + "#community-feed",
        },
        {
            "id": "wins",
            "label": "Small wins",
            "active": feed_filter == "wins",
            "href": community_href(group=group_id, feed="wins", sort=sort_by, post_q=post_q) + "#community-feed",
        },
        {
            "id": "events",
            "label": "Events",
            "active": feed_filter == "events",
            "href": community_href(group=group_id, feed="events", sort=sort_by, post_q=post_q) + "#community-feed",
        },
        {
            "id": "trending",
            "label": "Trending",
            "active": feed_filter == "trending",
            "href": community_href(group=group_id, feed="trending", sort=sort_by, post_q=post_q) + "#community-feed",
        },
        {
            "id": "saved",
            "label": "Saved",
            "active": feed_filter == "saved",
            "href": community_href(group=group_id, feed="saved", sort=sort_by, post_q=post_q) + "#community-feed",
        },
    ]

    return render_template(
        "community.html",
        active_page="community",
        body_class="page-community",
        page_id="community",
        page_title="Community Support | Heal Hub",
        groups=COMMUNITY_GROUPS,
        group_cards=group_cards,
        group_lookup=group_lookup,
        selected_group=selected_group,
        posts=posts,
        user_community=user_community,
        community_profile=community_profile,
        people_results=people_results,
        people_q=people_q,
        people_interest=people_interest,
        people_interest_options=people_interest_options,
        my_connections=my_connections,
        recommended_people=recommended_people,
        request_cards=request_cards,
        upcoming_events=build_community_events(group_id),
        community_guidelines=COMMUNITY_GUIDELINES,
        community_prompts=COMMUNITY_PROMPT_LIBRARY,
        community_post_kind_options=COMMUNITY_POST_KIND_OPTIONS,
        community_mood_options=COMMUNITY_MOOD_OPTIONS,
        community_reaction_options=COMMUNITY_REACTION_OPTIONS,
        feed_filters=feed_filters,
        feed_filter=feed_filter,
        sort_by=sort_by,
        post_q=post_q,
    )



@app.post("/api/community-post")
@login_required
def community_post() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    group_id = str(payload.get("group_id", "grp-006")).strip() or "grp-006"
    if group_id not in community_group_index():
        group_id = "grp-006"

    content = str(payload.get("content", "")).strip()
    post_kind = normalize_community_kind(payload.get("post_kind"))
    mood = normalize_community_mood(payload.get("mood"))
    anonymous = as_bool(payload.get("anonymous", False))
    prompt_label = str(payload.get("prompt_label", "")).strip()

    if not content:
        return jsonify({"success": False, "message": "Post content cannot be empty."}), 400

    post = {
        "id": f"post-{uuid4().hex[:8]}",
        "group_id": group_id,
        "author": "Anonymous member" if anonymous else user.get("display_name", "Anonymous"),
        "author_username": "" if anonymous else username,
        "content": content,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "likes": 0,
        "replies": [],
        "kind": post_kind,
        "mood": mood,
        "anonymous": anonymous,
        "reactions": {"support": 0, "relate": 0, "celebrate": 0, "insight": 0},
        "bookmarks": 0,
        "tags": infer_community_post_tags(content, group_id, post_kind, mood),
    }
    if prompt_label:
        post["tags"] = dedupe_preserving_order([prompt_label] + post["tags"])[:4]

    COMMUNITY_POSTS.insert(0, ensure_community_post_shape(post))
    community = USER_COMMUNITY_DATA.setdefault(username, default_community_profile())
    community["posts_count"] = community.get("posts_count", 0) + 1
    if group_id not in community.get("joined_groups", []):
        community.setdefault("joined_groups", []).append(group_id)

    if username in PATIENT_PROFILES and group_id not in PATIENT_PROFILES[username].get("joined_communities", []):
        PATIENT_PROFILES[username].setdefault("joined_communities", []).append(group_id)

    return jsonify({"success": True, "post": serialize_community_post(post)})



@app.post("/api/community-reply")
@login_required
def community_reply() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    post_id = payload.get("post_id", "")
    content = str(payload.get("content", "")).strip()

    if not content:
        return jsonify({"success": False, "message": "Reply cannot be empty."}), 400

    post = next((p for p in COMMUNITY_POSTS if p["id"] == post_id), None)
    if not post:
        return jsonify({"success": False, "message": "Post not found."}), 404

    ensure_community_post_shape(post)
    reply = {
        "author": user.get("display_name", "Anonymous"),
        "content": content,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "avatar": community_author_badge(user.get("display_name", "")),
    }
    post["replies"].append(reply)

    replier_state = USER_COMMUNITY_DATA.setdefault(username, default_community_profile())
    replier_state["support_given"] = replier_state.get("support_given", 0) + 1

    author_username = infer_post_author_username(post)
    if author_username and author_username != username:
        author_state = USER_COMMUNITY_DATA.setdefault(author_username, default_community_profile())
        author_state["support_received"] = author_state.get("support_received", 0) + 1

    return jsonify({
        "success": True,
        "reply": reply,
        "reply_count": len(post.get("replies", [])),
    })



@app.post("/api/community-react")
@login_required
def community_react() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    post_id = payload.get("post_id", "")
    reaction_type = str(payload.get("reaction_type", "support")).strip().lower() or "support"
    if reaction_type not in {item["id"] for item in COMMUNITY_REACTION_OPTIONS}:
        reaction_type = "support"

    post = next((item for item in COMMUNITY_POSTS if item["id"] == post_id), None)
    if not post:
        return jsonify({"success": False, "message": "Post not found."}), 404

    ensure_community_post_shape(post)
    post["reactions"][reaction_type] = post["reactions"].get(reaction_type, 0) + 1
    post["likes"] = post["reactions"]["support"]

    giver_state = USER_COMMUNITY_DATA.setdefault(username, default_community_profile())
    giver_state["support_given"] = giver_state.get("support_given", 0) + 1

    author_username = infer_post_author_username(post)
    if author_username and author_username != username:
        receiver_state = USER_COMMUNITY_DATA.setdefault(author_username, default_community_profile())
        receiver_state["support_received"] = receiver_state.get("support_received", 0) + 1

    return jsonify({
        "success": True,
        "reaction_type": reaction_type,
        "reactions": post["reactions"],
        "reaction_total": sum(post["reactions"].values()),
        "likes": post["likes"],
    })



@app.post("/api/community-bookmark")
@login_required
def community_bookmark() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    post_id = payload.get("post_id", "")

    post = next((item for item in COMMUNITY_POSTS if item["id"] == post_id), None)
    if not post:
        return jsonify({"success": False, "message": "Post not found."}), 404

    ensure_community_post_shape(post)
    post["bookmarks"] = post.get("bookmarks", 0) + 1

    saver_state = USER_COMMUNITY_DATA.setdefault(username, default_community_profile())
    saver_state["saved_posts_count"] = saver_state.get("saved_posts_count", 0) + 1

    return jsonify({
        "success": True,
        "bookmarks": post["bookmarks"],
    })



COMMUNITY_REPORTS: list[dict[str, Any]] = []


@app.post("/api/community-report")
@login_required
def community_report() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    post_id = str(payload.get("post_id", "")).strip()
    reason = str(payload.get("reason", "Needs moderator review")).strip() or "Needs moderator review"

    post = next((item for item in COMMUNITY_POSTS if item["id"] == post_id), None)
    if not post:
        return jsonify({"success": False, "message": "Post not found."}), 404

    COMMUNITY_REPORTS.append({
        "id": f"report-{uuid4().hex[:8]}",
        "post_id": post_id,
        "reported_by": username,
        "reason": reason[:120],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
    })
    return jsonify({"success": True, "message": "Thanks. This post was sent to moderation review."})


@app.post("/api/community-mute")
@login_required
def community_mute() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    author_username = str(payload.get("author_username", "")).strip()
    if not author_username:
        return jsonify({"success": False, "message": "Author not provided."}), 400
    if author_username == username:
        return jsonify({"success": False, "message": "You cannot mute yourself."}), 400

    community = USER_COMMUNITY_DATA.setdefault(username, default_community_profile())
    muted_users = community.setdefault("muted_users", [])
    if author_username not in muted_users:
        muted_users.append(author_username)

    connection_state = USER_CONNECTIONS.setdefault(
        username,
        {"friends": [], "requests_sent": [], "requests_received": [], "blocked": []},
    )
    blocked = connection_state.setdefault("blocked", [])
    if author_username not in blocked:
        blocked.append(author_username)

    return jsonify({"success": True, "message": "Author muted. You will not see their posts in community feed."})


@app.post("/api/join-community")
@login_required
def join_community() -> Any:
    user = session.get("user", {})
    username = user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    group_id = str(payload.get("group_id", "")).strip()
    group = next((g for g in COMMUNITY_GROUPS if g["id"] == group_id), None)
    if not group:
        return jsonify({"success": False, "message": "Group not found."}), 404

    joined_for_profile = False
    if username in PATIENT_PROFILES:
        profile = PATIENT_PROFILES[username]
        if group_id not in profile.get("joined_communities", []):
            profile.setdefault("joined_communities", []).append(group_id)
            joined_for_profile = True

    community = USER_COMMUNITY_DATA.setdefault(username, default_community_profile())
    if group_id not in community.get("joined_groups", []):
        community.setdefault("joined_groups", []).append(group_id)
        joined_for_profile = True

    if joined_for_profile:
        group["members"] = int(group.get("members", 0)) + 1

    return jsonify({
        "success": True,
        "message": f"You've joined {group['name']}!",
        "group": group,
        "joined_groups_count": len(community.get("joined_groups", [])),
    })


@app.get("/patients")
@login_required
def browse_patients() -> str:
    """People discovery is merged into the community page."""
    search_q = request.args.get("q", "").strip()
    interest = request.args.get("interest", "").strip()
    return redirect(url_for("community_page", people_q=search_q, people_interest=interest) + "#community-people")


@app.get("/patient/<username>")
@login_required
def view_patient_profile(username: str) -> Any:
    """View another patient's profile."""
    current_user = session.get("user", {})
    current_username = current_user.get("username", "patient")

    if username == current_username:
        return redirect(url_for("patient_dashboard_page"))

    patient = PATIENT_PROFILES.get(username)
    if not patient:
        flash("Patient profile not found.", "error")
        return redirect(url_for("browse_patients"))

    my_connections = USER_CONNECTIONS.get(current_username, {
        "friends": [],
        "requests_sent": [],
        "requests_received": [],
        "blocked": [],
    })

    connection_status = "none"
    if username in my_connections.get("friends", []):
        connection_status = "connected"
    elif username in my_connections.get("requests_sent", []):
        connection_status = "request_sent"
    elif username in my_connections.get("requests_received", []):
        connection_status = "request_received"

    patient_communities = set(patient.get("joined_communities", []))
    current_communities = set(
        PATIENT_PROFILES.get(current_username, {}).get("joined_communities", [])
    )
    shared_group_ids = patient_communities.intersection(current_communities)
    shared_communities = [
        g for g in COMMUNITY_GROUPS if g["id"] in shared_group_ids
    ]

    patient_movie_interests = set(patient.get("movie_preferences", {}).get("interested_in", []))
    current_movie_interests = set(
        PATIENT_PROFILES.get(current_username, {}).get("interests", [])
    )
    shared_interests = patient_movie_interests.intersection(current_movie_interests)

    return render_template(
        "patient_profile.html",
        active_page="patients",
        body_class="page-patient-profile",
        page_id="patient-profile",
        page_title=f"{patient['display_name']}'s Profile | Heal Hub",
        patient_profile=patient,
        current_user=current_user,
        connection_status=connection_status,
        shared_communities=shared_communities,
        shared_interests=list(shared_interests),
        my_connections=my_connections,
    )


@app.post("/api/send-connection-request")
@login_required
def send_connection_request() -> Any:
    """Send a friend request to another patient."""
    current_user = session.get("user", {})
    current_username = current_user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    target_username = payload.get("target_username", "")

    if target_username == current_username:
        return jsonify({"success": False, "message": "Cannot send request to yourself."}), 400

    if target_username not in PATIENT_PROFILES:
        return jsonify({"success": False, "message": "User not found."}), 404

    my_connections = USER_CONNECTIONS.setdefault(current_username, {
        "friends": [],
        "requests_sent": [],
        "requests_received": [],
        "blocked": [],
    })
    target_connections = USER_CONNECTIONS.setdefault(target_username, {
        "friends": [],
        "requests_sent": [],
        "requests_received": [],
        "blocked": [],
    })

    if target_username in my_connections.get("friends", []):
        return jsonify({"success": False, "message": "Already connected with this user."}), 400

    if target_username in my_connections.get("requests_sent", []):
        return jsonify({"success": False, "message": "Request already sent."}), 400

    if target_username not in my_connections.get("requests_sent", []):
        my_connections.setdefault("requests_sent", []).append(target_username)
    if current_username not in target_connections.get("requests_received", []):
        target_connections.setdefault("requests_received", []).append(current_username)

    return jsonify({
        "success": True,
        "message": f"Connection request sent to {PATIENT_PROFILES[target_username]['display_name']}!",
    })


@app.post("/api/accept-connection")
@login_required
def accept_connection() -> Any:
    """Accept a friend request."""
    current_user = session.get("user", {})
    current_username = current_user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    from_username = str(payload.get("from_username", "")).strip()

    if not from_username:
        return jsonify({"success": False, "message": "Missing user to accept."}), 400

    if from_username == current_username:
        return jsonify({"success": False, "message": "Cannot accept yourself."}), 400

    if from_username not in PATIENT_PROFILES:
        return jsonify({"success": False, "message": "User not found."}), 404

    my_connections = USER_CONNECTIONS.setdefault(current_username, {
        "friends": [],
        "requests_sent": [],
        "requests_received": [],
        "blocked": [],
    })
    from_connections = USER_CONNECTIONS.setdefault(from_username, {
        "friends": [],
        "requests_sent": [],
        "requests_received": [],
        "blocked": [],
    })

    if from_username not in my_connections.get("requests_received", []):
        return jsonify({"success": False, "message": "No pending request from this user."}), 400

    my_connections["requests_received"].remove(from_username)
    if current_username in from_connections.get("requests_sent", []):
        from_connections["requests_sent"].remove(current_username)

    if from_username not in my_connections.get("friends", []):
        my_connections.setdefault("friends", []).append(from_username)
    if current_username not in from_connections.get("friends", []):
        from_connections.setdefault("friends", []).append(current_username)

    return jsonify({
        "success": True,
        "message": f"Connected with {PATIENT_PROFILES[from_username]['display_name']}!",
    })


@app.post("/api/send-message")
@login_required
def send_message() -> Any:
    """Send a message to an allowed patient or doctor conversation partner."""
    current_user = session.get("user", {})
    current_username = current_user.get("username", "patient")
    payload = request.get_json(silent=True) or {}
    to_username = str(payload.get("to_username", "")).strip()
    content = payload.get("content", "").strip()

    if not content:
        return jsonify({"success": False, "message": "Message cannot be empty."}), 400

    if to_username == current_username:
        return jsonify({"success": False, "message": "Cannot message yourself."}), 400

    if not message_partner_profile(to_username):
        return jsonify({"success": False, "message": "User not found."}), 404

    if not can_message_partner(current_user, to_username):
        return jsonify({"success": False, "message": "You do not have messaging access for this user."}), 403

    message = {
        "id": f"msg-{uuid4().hex[:8]}",
        "from_user": current_username,
        "to_user": to_username,
        "from_display": current_user.get("display_name", "Anonymous"),
        "content": content,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "read": False,
    }
    MESSAGES_DATA.append(message)

    return jsonify({
        "success": True,
        "message": "Message sent!",
        "message_obj": message,
    })


@app.get("/api/messages-thread")
@login_required
def get_messages_thread() -> Any:
    """Fetch one conversation thread for the current user."""
    current_user = session.get("user", {})
    current_username = current_user.get("username", "patient")
    partner_username = request.args.get("user", "").strip()

    if not partner_username:
        return jsonify({"success": False, "message": "Missing conversation user."}), 400

    if partner_username == current_username:
        return jsonify({"success": False, "message": "Cannot open a thread with yourself."}), 400

    if not message_partner_profile(partner_username):
        return jsonify({"success": False, "message": "User not found."}), 404

    if not can_message_partner(current_user, partner_username):
        return jsonify({"success": False, "message": "You do not have access to this conversation."}), 403

    thread_messages = sorted([
        msg for msg in MESSAGES_DATA
        if (
            msg.get("from_user") == current_username
            and msg.get("to_user") == partner_username
        ) or (
            msg.get("from_user") == partner_username
            and msg.get("to_user") == current_username
        )
    ], key=lambda item: item.get("timestamp", ""))

    for msg in thread_messages:
        if msg.get("to_user") == current_username and not msg.get("read"):
            msg["read"] = True

    return jsonify({
        "success": True,
        "messages": thread_messages,
    })


@app.get("/messages")
@login_required
def view_messages() -> str:
    """View all messages for current user."""
    current_user = session.get("user", {})
    current_username = current_user.get("username", "patient")
    requested_partner = request.args.get("user", "").strip()

    my_messages = [
        msg for msg in MESSAGES_DATA
        if msg.get("to_user") == current_username or msg.get("from_user") == current_username
    ]

    allowed_partners = messageable_partner_usernames(current_user)
    conversations: dict[str, dict[str, Any]] = {}
    for msg in sorted(my_messages, key=lambda m: m.get("timestamp", ""), reverse=True):
        partner = msg.get("from_user") if msg.get("to_user") == current_username else msg.get("to_user")
        if partner not in conversations:
            partner_profile = message_partner_profile(partner)
            conversations[partner] = {
                "partner_username": partner,
                "partner_profile": partner_profile,
                "messages": [],
                "unread_count": 0,
            }

        conversations[partner]["messages"].append(msg)
        if msg.get("to_user") == current_username and not msg.get("read"):
            conversations[partner]["unread_count"] += 1

    for convo in conversations.values():
        convo["messages"] = sorted(convo["messages"], key=lambda item: item.get("timestamp", ""))
        convo["latest_message"] = convo["messages"][-1] if convo["messages"] else None

    if (
        requested_partner
        and requested_partner not in conversations
        and requested_partner in allowed_partners
        and message_partner_profile(requested_partner)
    ):
        conversations[requested_partner] = {
            "partner_username": requested_partner,
            "partner_profile": message_partner_profile(requested_partner),
            "messages": [],
            "unread_count": 0,
            "latest_message": None,
        }

    conversation_items = sorted(
        conversations.values(),
        key=lambda convo: (convo.get("latest_message") or {}).get("timestamp", ""),
        reverse=True,
    )

    selected_partner = requested_partner if requested_partner in conversations else ""
    if not selected_partner and conversation_items:
        selected_partner = conversation_items[0]["partner_username"]
    selected_conversation = conversations.get(selected_partner)
    current_profile = message_partner_profile(current_username) or PATIENT_PROFILES.get(current_username, {})
    selected_profile = (selected_conversation or {}).get("partner_profile", {}) or {}
    shared_interests = sorted(
        set(current_profile.get("interests", [])).intersection(set(selected_profile.get("interests", [])))
    )
    groups_lookup = {group["id"]: group for group in COMMUNITY_GROUPS}
    shared_group_ids = set(current_profile.get("joined_communities", [])).intersection(
        set(selected_profile.get("joined_communities", []))
    )
    shared_groups = sorted([
        groups_lookup[group_id]["name"] for group_id in shared_group_ids if group_id in groups_lookup
    ])

    if selected_partner:
        for msg in my_messages:
            if (
                msg.get("to_user") == current_username
                and msg.get("from_user") == selected_partner
            ):
                msg["read"] = True

    return render_template(
        "messages.html",
        active_page="messages",
        body_class="page-messages",
        page_id="messages",
        page_title="Messages | Heal Hub",
        conversations=conversations,
        conversation_items=conversation_items,
        selected_partner=selected_partner,
        selected_conversation=selected_conversation,
        shared_interests=shared_interests,
        shared_groups=shared_groups,
        current_user=current_user,
    )


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

    valid_ids = {movie["id"] for movie in MOVIES_DATA}
    for key in ("watched", "want_to_watch", "favorites"):
        profile[key] = [movie_id for movie_id in profile.get(key, []) if movie_id in valid_ids]

    profile["history"] = [
        item for item in profile.get("history", [])
        if str(item.get("movie_id", "")) in valid_ids
    ]

    if not profile.get("interests"):
        profile["interests"] = MOVIE_CATEGORIES[:4]
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
    profile = USER_COMMUNITY_DATA.setdefault(username, default_community_profile())
    joined_ids = set(profile.get("joined_groups", []))
    joined_groups = [group for group in build_community_group_cards(username) if group["id"] in joined_ids]
    recommended_groups = [group for group in build_community_group_cards(username) if group["id"] not in joined_ids][:3]
    recent_discussions = [
        serialize_community_post(post)
        for post in COMMUNITY_POSTS
        if not joined_ids or post.get("group_id") in joined_ids
    ][:4]

    trending_topics = dedupe_preserving_order(
        [group["category"] for group in COMMUNITY_GROUPS]
        + profile.get("comfort_topics", [])
        + [tag for post in recent_discussions for tag in post.get("tags", [])]
    )[:6]

    support_received = int(profile.get("support_received", 0) or 0)
    support_given = int(profile.get("support_given", 0) or 0)
    posts_count = int(profile.get("posts_count", 0) or 0)
    saved_posts_count = int(profile.get("saved_posts_count", 0) or 0)
    momentum_score = len(joined_groups) * 8 + posts_count * 10 + support_given + support_received + saved_posts_count * 3
    support_streak = max(3, min(21, len(joined_groups) * 2 + posts_count + max(1, support_given // 3 or 1)))
    next_event = build_community_events(joined_groups[0]["id"] if joined_groups else "")[:1]
    hot_conversation = max(
        recent_discussions,
        key=lambda post: (post.get("reaction_total", 0), post.get("reply_count", 0)),
        default=None,
    )

    return {
        "profile": profile,
        "joined_groups": joined_groups,
        "recent_discussions": recent_discussions,
        "recommended_groups": recommended_groups,
        "trending_topics": trending_topics,
        "safe_circle": next((group for group in COMMUNITY_GROUPS if group["id"] == "grp-003"), None),
        "support_summary": (
            f"You are active in {len(joined_groups)} support circles and have received "
            f"{support_received} supportive responses so far."
        ),
        "support_streak": support_streak,
        "saved_posts_count": saved_posts_count,
        "momentum_score": momentum_score,
        "highlight_message": (
            "You are steadily building a warm support network through honest posts and gentle follow-through."
            if momentum_score >= 45
            else "You are growing a dependable support rhythm — every thoughtful interaction counts."
        ),
        "hot_conversation": hot_conversation,
        "next_event": next_event[0] if next_event else None,
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
    account_profile = account_profile_for_username(username) or {}
    portal_patient = portal_patient_for_user(user)
    prescriptions = patient_prescriptions(username)
    notes = patient_notes(username)
    ai_summary = ai_triage_summary(["chest pain", "shortness of breath"])
    movie_profile = build_movie_profile(username)
    community_profile = build_community_profile(username)
    bookings = sorted(
        [booking for booking in BOOKINGS_DATA if booking.get("patient_username") == username],
        key=lambda booking: (booking.get("date", ""), booking.get("time", "")),
    )
    pending_statuses = {"requested", "pending", "awaiting review"}
    pending_review_bookings = [
        booking for booking in bookings
        if str(booking.get("status", "")).strip().lower() in pending_statuses
    ]
    upcoming_bookings = [
        booking for booking in bookings
        if str(booking.get("status", "")).strip().lower() not in pending_statuses
    ]
    latest_booking = upcoming_bookings[0] if upcoming_bookings else bookings[0] if bookings else None
    doctor_chat_target = (
        str((latest_booking or {}).get("therapist_id", "")).strip()
        or str(portal_patient.get("doctor_username", "")).strip()
    )
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
        "upcoming_bookings": upcoming_bookings,
        "pending_review_bookings": pending_review_bookings,
        "latest_booking": latest_booking,
        "doctor_chat_target": doctor_chat_target,
        "account_profile": account_profile,
        "recommended_movies": movie_profile["recommended_movies"],
        "watched_movies": movie_profile["watched_movies"],
        "watched_story_history": movie_profile["recently_watched"],
        "fav_movies": movie_profile["favorite_movies"],
        "top_categories": movie_profile["top_categories"],
        "movie_data": movie_profile["profile"],
        "growth_timeline": movie_profile["recently_watched"],
        "joined_groups": community_profile["joined_groups"],
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
    doctor_profile = account_profile_for_username(user.get("username", "doctor")) or {}
    portal_patient = PORTAL_PATIENTS["patient"]
    focus_patient_profile = account_profile_for_username(portal_patient.get("username", "patient")) or PATIENT_PROFILES.get("patient", {})
    patient_story_profile = build_movie_profile("patient")
    patient_community = build_community_profile("patient")
    doctor_bookings = sorted(
        BOOKINGS_DATA,
        key=lambda booking: (booking.get("date", ""), booking.get("time", "")),
    )
    pending_statuses = {"requested", "pending", "awaiting review"}
    pending_review_bookings = [
        booking for booking in doctor_bookings
        if str(booking.get("status", "")).strip().lower() in pending_statuses
    ]
    upcoming_bookings = [
        booking for booking in doctor_bookings
        if str(booking.get("status", "")).strip().lower() not in pending_statuses
    ]
    latest_booking = upcoming_bookings[0] if upcoming_bookings else doctor_bookings[0] if doctor_bookings else None

    return {
        "doctor_profile": doctor_profile,
        "portal_patient": portal_patient,
        "ai_summary": ai_triage_summary(["chest pain", "shortness of breath"]),
        "patient_insights": get_patient_insights("patient"),
        "patient_story_profile": patient_story_profile,
        "patient_community": patient_community,
        "bookings": doctor_bookings,
        "upcoming_bookings": upcoming_bookings,
        "pending_review_bookings": pending_review_bookings,
        "latest_booking": latest_booking,
        "focus_patient_profile": focus_patient_profile,
        "focus_patient_story_history": patient_story_profile["recently_watched"],
        "focus_joined_groups": patient_community["joined_groups"],
        "patient_chat_target": portal_patient.get("username", "patient"),
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
