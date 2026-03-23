# HealHub

HealHub is a polished hackathon-ready web application for the theme **"High-value health systems: leveraging Artificial Intelligence."**

It is not a symptom checker. It is a **smart hospital operations and resource optimization platform** that simulates how AI can improve health system performance across multiple hospitals by:

- prioritizing patients by urgency
- allocating beds, doctors, and ICU capacity
- recommending immediate care, waiting, or redirection
- redistributing patients across hospitals when one site becomes overloaded
- stress-testing the system with emergency surge simulations

## Tech stack

- Frontend: HTML, CSS, JavaScript
- Backend: Python + Flask
- Storage: in-memory runtime state with JSON seed data

## Project structure

```text
app.py
templates/
  base.html
  index.html
  platform.html
  login.html
  dashboard.html
  about.html
static/
  css/
    style.css
  js/
    main.js
    dashboard.js
data/
  hospitals.json
  sample_patients.json
requirements.txt
```

## Demo login

Use the built-in demo accounts:

- `admin / admin123`
- `doctor / doctor123`

You can also use the **Demo Login** button on the login page.

## Main routes

- `/` landing page
- `/platform`
- `/login` authentication page
- `/logout`
- `/dashboard` live operations dashboard
- `/about`
- `/api/patient-intake`
- `/api/dashboard-data`
- `/api/surge-mode`
- `/api/random-patients`
- `/api/reset`
- `/api/generate-random-patients`
- `/api/advance-time`

## Authentication flow

HealHub uses simple Flask session-based authentication for hackathon demos:

1. A user logs in at `/login`
2. Flask verifies the hardcoded demo credentials
3. On success, the app stores the user in `session["user"]`
4. The `/dashboard` route checks the session before rendering
5. If the user is not logged in, `/dashboard` redirects to `/login`
6. Dashboard API routes also require the same session and return an auth error if missing
7. If the user checks **Remember me**, Flask keeps the session alive longer using a permanent session cookie

This keeps the demo lightweight while still showing a real protected dashboard flow.

## How the AI logic works

HealHub uses a lightweight, demo-friendly decision engine:

1. **Urgency scoring**
   - Scores each patient from `0-100`
   - Uses symptoms, intake severity, oxygen level, heart rate, blood pressure, age, chronic disease, pregnancy, and arrival mode
   - Produces a triage label of `Critical`, `High`, `Medium`, or `Low`

2. **Priority ranking**
   - Patients are sorted by urgency plus dynamic wait-time pressure
   - High-risk and unstable patients move up first

3. **Resource allocation**
   - The engine checks available doctors, beds, and ICU slots at each hospital
   - If a hospital can treat immediately, the patient is assigned to treatment
   - Otherwise, the patient is queued or redirected

4. **Smart redistribution**
   - HealHub compares hospitals by live capacity, queue depth, ICU availability, and specialty fit
   - If another hospital can reduce delay or absorb the case better, the system recommends a transfer automatically

5. **Explainable AI**
   - Every patient includes a score breakdown and a "Why this decision?" panel
   - The UI shows both clinical urgency factors and operational resource reasoning

## Demo flow

1. Open the landing page and click **Get Started**
2. Log in using the demo account or the **Demo Login** button
3. Show the seeded live network with three hospitals
4. Register a new patient through the intake form
5. Click **Generate Random Patients** to show routine system pressure
6. Click **Activate Surge Mode** to trigger sudden overload
7. Click **Advance 30 Minutes** to show capacity recovery and queue reshuffling
8. Use the **Why this decision?** panel to explain the AI output to judges

## Setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the Flask app:

```bash
python app.py
```

4. Open `http://127.0.0.1:5000/`

## Hackathon pitch summary

**HealHub** helps healthcare systems do more with less. Instead of diagnosing disease, it focuses on what hospitals struggle with every day: who should be treated first, where they should go, and how to prevent overload when resources are scarce.

For contexts like Nepal, this matters because beds, ICU slots, and specialist attention are limited. HealHub shows how AI can coordinate the whole network, reduce wait times, improve utilization, and make system-level decisions transparent enough for clinicians and administrators to trust.
