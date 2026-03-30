(() => {
  if (document.body.dataset.page !== "dashboard") return;

  const { api, escapeHTML, titleCase, toneClass, setBusy } = window.HealHub;

  const state = {
    catalogLoaded: false,
    selectedPatientId: null,
    snapshot: null,
  };

  const elements = {
    metricGrid: document.getElementById("metric-grid"),
    insightBanner: document.getElementById("insight-banner"),
    insightsList: document.getElementById("insights-list"),
    patientBoard: document.getElementById("patient-board"),
    hospitalGrid: document.getElementById("hospital-grid"),
    networkSummary: document.getElementById("network-summary"),
    eventLog: document.getElementById("event-log"),
    clockValue: document.getElementById("clock-value"),
    pulseTitle: document.getElementById("pulse-title"),
    pulseStatus: document.getElementById("pulse-status"),
    selectedPatientMeta: document.getElementById("selected-patient-meta"),
    scoreBreakdown: document.getElementById("score-breakdown"),
    decisionExplanation: document.getElementById("decision-explanation"),
    symptomChipList: document.getElementById("symptom-chip-list"),
    symptomsInput: document.getElementById("symptoms-input"),
    intakeForm: document.getElementById("intake-form"),
    intakeSubmit: document.getElementById("intake-submit"),
    surgeButton: document.getElementById("surge-button"),
    randomButton: document.getElementById("random-button"),
    advanceButton: document.getElementById("advance-button"),
    resetButton: document.getElementById("reset-button"),
    surgeScenario: document.getElementById("surge-scenario"),
    scenarioDescription: document.getElementById("scenario-description"),
    originHospital: document.getElementById("origin-hospital"),
  };

  function metricTone(key, value) {
    if (key === "critical_cases") {
      if (value >= 5) return "critical";
      if (value >= 2) return "warning";
      return "neutral";
    }
    if (key === "utilization_rate") {
      if (value >= 85) return "critical";
      if (value >= 65) return "warning";
      if (value < 45) return "stable";
      return "neutral";
    }
    if (key === "available_beds" || key === "icu_availability") {
      if (value <= 2) return "critical";
      if (value <= 4) return "warning";
      return "stable";
    }
    if (key === "redirected_patients") {
      return value > 0 ? "warning" : "stable";
    }
    return "neutral";
  }

  function actionBadge(patient) {
    if (patient.status === "treating") {
      return { label: "Immediate Care", tone: "critical" };
    }
    if (patient.route_mode === "redirect") {
      return { label: "Redirected", tone: "warning" };
    }
    if (patient.status === "waiting") {
      return { label: "Waiting", tone: "neutral" };
    }
    return { label: titleCase(patient.status), tone: "stable" };
  }

  function formatMinutes(value) {
    return `${Number(value || 0)}m`;
  }

  function setSystemStatus(message, tone = "neutral", title = "Heal Hub operational status") {
    elements.insightBanner.textContent = message;
    elements.insightBanner.className = `notice-banner ${toneClass(tone)}`;
    elements.pulseTitle.textContent = title;
    elements.pulseStatus.className = `status-chip ${toneClass(tone)}`;
    elements.pulseStatus.textContent = titleCase(tone);
  }

  function renderMetrics(metrics) {
    const cards = [
      {
        key: "total_patients",
        glyph: "PT",
        label: "Total Patients",
        value: metrics.total_patients,
        detail: "Live active and waiting cases across the network",
        note: "Network snapshot",
      },
      {
        key: "critical_cases",
        glyph: "CR",
        label: "Critical Cases",
        value: metrics.critical_cases,
        detail: "High-acuity patients needing rapid coordination",
        note: "Escalation watch",
      },
      {
        key: "available_beds",
        glyph: "BD",
        label: "Available Beds",
        value: metrics.available_beds,
        detail: "Network-wide open bed capacity",
        note: "Capacity open now",
      },
      {
        key: "doctors_on_duty",
        glyph: "DR",
        label: "Doctors on Duty",
        value: metrics.doctors_on_duty,
        detail: "Clinicians available across connected hospitals",
        note: "System staffing",
      },
      {
        key: "icu_availability",
        glyph: "IC",
        label: "ICU Availability",
        value: metrics.icu_availability,
        detail: "Open ICU slots for unstable and critical cases",
        note: "Critical care supply",
      },
      {
        key: "redirected_patients",
        glyph: "RT",
        label: "Redirected Patients",
        value: metrics.redirected_patients,
        detail: "Cases rerouted to reduce overload and delays",
        note: "Load balancing",
      },
      {
        key: "average_wait_time",
        glyph: "WT",
        label: "Average Wait Time",
        value: formatMinutes(metrics.average_wait_time),
        detail: "Mean queue delay for patients still waiting",
        note: "Queue health",
      },
      {
        key: "utilization_rate",
        glyph: "UT",
        label: "Utilization Rate",
        value: `${metrics.utilization_rate}%`,
        detail: "Composite use of beds, doctors, and ICU resources",
        note: "Operational strain",
      },
    ];

    elements.metricGrid.innerHTML = cards
      .map(
        (card) => `
          <article class="metric-card ${toneClass(metricTone(card.key, metrics[card.key]))}">
            <div class="metric-top">
              <span class="metric-glyph">${card.glyph}</span>
              <div class="metric-copy">
                <span class="meta-label">${card.label}</span>
                <span class="metric-note">${escapeHTML(card.note)}</span>
              </div>
            </div>
            <strong class="metric-value">${escapeHTML(card.value)}</strong>
            <p class="subcopy">${escapeHTML(card.detail)}</p>
            <div class="metric-foot">
              <span>${escapeHTML(card.key.replaceAll("_", " "))}</span>
              <span class="metric-pulse"></span>
            </div>
          </article>
        `,
      )
      .join("");
  }

  function renderInsights(insights) {
    if (!insights.length) {
      elements.insightsList.innerHTML = '<div class="empty-state">No urgent system notices right now.</div>';
      return;
    }

    elements.insightsList.innerHTML = insights
      .map(
        (item) => `
          <article class="notice-card ${toneClass(item.tone)}">
            <div class="notice-card-head">
              <span class="status-chip ${toneClass(item.tone)}">${escapeHTML(item.title)}</span>
            </div>
            <p>${escapeHTML(item.body)}</p>
          </article>
        `,
      )
      .join("");
  }

  function renderNetworkSummary(network) {
    const resources = [
      {
        label: "Beds",
        total: network.total_beds,
        used: network.used_beds,
        available: network.available_beds,
      },
      {
        label: "Doctors",
        total: network.total_doctors,
        used: network.used_doctors,
        available: network.available_doctors,
      },
      {
        label: "ICU",
        total: network.total_icu,
        used: network.used_icu,
        available: network.available_icu,
      },
    ];

    elements.networkSummary.innerHTML = resources
      .map((item) => {
        const utilization = item.total ? Math.round((item.used / item.total) * 100) : 0;
        const tone =
          utilization >= 85 ? "critical" : utilization >= 65 ? "warning" : "stable";

        return `
          <article class="resource-summary-card ${toneClass(tone)}">
            <div class="resource-summary-top">
              <div>
                <span class="meta-label">${escapeHTML(item.label)}</span>
                <strong>${escapeHTML(item.available)}</strong>
              </div>
              <span class="status-chip ${toneClass(tone)}">${utilization}% used</span>
            </div>
            <div class="progress-track">
              <span class="progress-fill ${toneClass(tone)}" style="width:${utilization}%"></span>
            </div>
            <div class="resource-summary-foot">
              <p class="subcopy">${item.available} available of ${item.total} total network capacity.</p>
              <span class="resource-mini">${item.used} in use</span>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function renderHospitals(hospitals) {
    elements.hospitalGrid.innerHTML = hospitals
      .map((hospital) => {
        const utilizationTone =
          hospital.utilization >= 85
            ? "critical"
            : hospital.utilization >= 65
              ? "warning"
              : hospital.utilization >= 40
                ? "stable"
                : "neutral";
        const queueMarkup = hospital.queue.length
          ? hospital.queue
              .map(
                (patient) => `
                  <div class="mini-case">
                    <strong>${escapeHTML(patient.id)} | ${escapeHTML(patient.name)}</strong>
                    <span class="status-chip ${toneClass(patient.severity_tone)}">${escapeHTML(patient.triage_label)}</span>
                    <p>${escapeHTML(patient.recommended_action)} | ETA ${patient.estimated_wait_minutes}m</p>
                  </div>
                `,
              )
              .join("")
          : '<div class="empty-state">No patients are currently waiting at this facility.</div>';

        const treatingMarkup = hospital.treating.length
          ? hospital.treating
              .map(
                (patient) => `
                  <div class="mini-case">
                    <strong>${escapeHTML(patient.id)} | ${escapeHTML(patient.name)}</strong>
                    <span class="status-chip ${toneClass(patient.severity_tone)}">${escapeHTML(patient.triage_label)}</span>
                    <p>${escapeHTML(patient.action_detail)}</p>
                  </div>
                `,
              )
              .join("")
          : '<div class="empty-state">No active treatment slots are occupied here.</div>';

        return `
          <article class="hospital-card ${toneClass(utilizationTone)}">
            <div class="hospital-head">
              <div>
                <strong>${escapeHTML(hospital.name)}</strong>
                <p class="hospital-meta">${escapeHTML(hospital.city)} | ${escapeHTML(hospital.specialties.join(", "))}</p>
              </div>
              <div class="hospital-badges">
                <span class="status-chip ${toneClass(utilizationTone)}">${hospital.utilization}% utilized</span>
                <span class="status-chip ${toneClass(hospital.severity_tone)}">${escapeHTML(hospital.overload_status)}</span>
              </div>
            </div>
            <div class="progress-track">
              <span class="progress-fill ${toneClass(utilizationTone)}" style="width:${hospital.utilization}%"></span>
            </div>
            <div class="resource-matrix">
              <div>
                <span class="meta-label">Beds</span>
                <strong>${hospital.available_beds}/${hospital.total_beds}</strong>
                <small>available</small>
              </div>
              <div>
                <span class="meta-label">Doctors</span>
                <strong>${hospital.available_doctors}/${hospital.doctors_on_duty}</strong>
                <small>available</small>
              </div>
              <div>
                <span class="meta-label">ICU</span>
                <strong>${hospital.available_icu}/${hospital.icu_beds}</strong>
                <small>available</small>
              </div>
            </div>
            <div class="resource-matrix">
              <div>
                <span class="meta-label">Queue</span>
                <strong>${hospital.waiting_queue}</strong>
                <small>patients waiting</small>
              </div>
              <div>
                <span class="meta-label">Treating</span>
                <strong>${hospital.patients_being_treated}</strong>
                <small>active now</small>
              </div>
              <div>
                <span class="meta-label">Next release</span>
                <strong>${hospital.next_release_minutes}m</strong>
                <small>estimated</small>
              </div>
            </div>
            <div class="hospital-list-grid">
              <div class="hospital-list">
                <div class="hospital-list-head">
                  <div class="meta-label">Waiting queue</div>
                  <span class="resource-mini">${hospital.waiting_queue}</span>
                </div>
                ${queueMarkup}
              </div>
              <div class="hospital-list">
                <div class="hospital-list-head">
                  <div class="meta-label">Patients being treated</div>
                  <span class="resource-mini">${hospital.patients_being_treated}</span>
                </div>
                ${treatingMarkup}
              </div>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function renderPatients(patients) {
    if (!patients.length) {
      elements.patientBoard.innerHTML = '<div class="empty-state">No live patients in the simulation.</div>';
      return;
    }

    elements.patientBoard.innerHTML = patients
      .map((patient, index) => {
        const badge = actionBadge(patient);
        const waitText =
          patient.status === "treating"
            ? `${patient.care_remaining_minutes}m remaining`
            : `${patient.estimated_wait_minutes}m estimated wait`;

        return `
          <article class="patient-card ${patient.id === state.selectedPatientId ? "active" : ""}" data-patient-id="${escapeHTML(patient.id)}">
            <div class="patient-head">
              <div class="patient-heading-block">
                <div class="patient-priority-wrap">
                  <span class="priority-badge">#${index + 1}</span>
                  <span class="meta-label">Priority rank</span>
                </div>
                <strong>${escapeHTML(patient.id)} | ${escapeHTML(patient.name)}</strong>
                <p class="subcopy">${escapeHTML(patient.age)} years | ${escapeHTML(patient.symptoms.join(", "))}</p>
              </div>
              <div class="patient-route">
                <span class="status-chip ${toneClass(patient.severity_tone)}">${escapeHTML(patient.triage_label)}</span>
                <span class="status-chip status-neutral">Score ${patient.urgency_score}</span>
                <span class="status-chip ${toneClass(badge.tone)}">${badge.label}</span>
              </div>
            </div>
            <div class="patient-signals">
              <span>O2 ${escapeHTML(patient.oxygen_level)}%</span>
              <span>HR ${escapeHTML(patient.heart_rate)}</span>
              <span>BP ${escapeHTML(patient.blood_pressure_summary)}</span>
              <span>Arrival ${escapeHTML(titleCase(patient.arrival_mode))}</span>
            </div>
            <div class="patient-detail-grid">
              <div class="patient-detail-card">
                <span class="meta-label">Recommended action</span>
                <div class="patient-line"><strong>${escapeHTML(patient.recommended_action)}</strong> | ${escapeHTML(patient.action_detail)}</div>
              </div>
              <div class="patient-detail-card">
                <span class="meta-label">Assigned hospital</span>
                <div class="patient-line">${escapeHTML(patient.assigned_hospital)}${patient.route_mode === "redirect" ? ` (from ${escapeHTML(patient.preferred_hospital)})` : ""}</div>
              </div>
            </div>
            <div class="patient-reason">${escapeHTML(patient.decision_reason)}</div>
            <div class="patient-footer mono">${escapeHTML(patient.status.toUpperCase())} | ${escapeHTML(waitText)}</div>
          </article>
        `;
      })
      .join("");
  }

  function renderDecisionPanel(patient) {
    if (!patient) {
      elements.selectedPatientMeta.innerHTML = '<div class="empty-state">Select a patient to inspect the AI reasoning.</div>';
      elements.scoreBreakdown.innerHTML = "";
      elements.decisionExplanation.innerHTML = "";
      return;
    }

    const badge = actionBadge(patient);

    elements.selectedPatientMeta.innerHTML = `
      <span class="meta-label">Selected patient</span>
      <strong>${escapeHTML(patient.id)} | ${escapeHTML(patient.name)}</strong>
      <p>${escapeHTML(patient.triage_label)} | urgency ${patient.urgency_score} | assigned to ${escapeHTML(patient.assigned_hospital)}</p>
      <div class="patient-route">
        <span class="status-chip ${toneClass(patient.severity_tone)}">${escapeHTML(patient.triage_label)}</span>
        <span class="status-chip ${toneClass(badge.tone)}">${badge.label}</span>
      </div>
    `;

    elements.scoreBreakdown.innerHTML = patient.why_this_decision.score_breakdown
      .map(
        (item) => `
          <div class="breakdown-item">
            <div>
              <strong>${escapeHTML(item.label)}</strong>
              <p class="subcopy">${escapeHTML(item.detail)}</p>
            </div>
            <span class="breakdown-points">+${item.points}</span>
          </div>
        `,
      )
      .join("");

    elements.decisionExplanation.innerHTML = `
      <div>
        <span class="meta-label">Decision reasoning</span>
        <p>${escapeHTML(patient.why_this_decision.decision_reason)}</p>
      </div>
      <div>
        <span class="meta-label">Resource availability</span>
        <p>${escapeHTML(patient.why_this_decision.resource_reasoning)}</p>
      </div>
      <div>
        <span class="meta-label">Redirect trigger</span>
        <p>${escapeHTML(patient.why_this_decision.redirect_reason || "No redirect was needed for this patient.")}</p>
      </div>
    `;
  }

  function renderEvents(events) {
    if (!events.length) {
      elements.eventLog.innerHTML = '<div class="empty-state">Operational events will appear here.</div>';
      return;
    }

    elements.eventLog.innerHTML = events
      .map(
        (event) => `
          <article class="event-card">
            <div class="event-head">
              <div class="event-heading-block">
                <span class="meta-label">${escapeHTML(titleCase(event.kind))}</span>
                <strong>${escapeHTML(event.title)}</strong>
              </div>
              <span class="status-chip ${toneClass(event.tone)}">${escapeHTML(event.clock)}</span>
            </div>
            <p>${escapeHTML(event.detail)}</p>
          </article>
        `,
      )
      .join("");
  }

  function syncTextareaFromChips() {
    const active = [...document.querySelectorAll(".chip.active")].map((chip) => chip.dataset.symptom);
    elements.symptomsInput.value = active.join(", ");
  }

  function syncChipsFromTextarea() {
    const seeded = elements.symptomsInput.value
      .split(",")
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean);

    document.querySelectorAll(".chip").forEach((chip) => {
      chip.classList.toggle("active", seeded.includes(chip.dataset.symptom));
    });
  }

  function populateCatalog(catalog) {
    if (!catalog || state.catalogLoaded) return;

    elements.symptomChipList.innerHTML = catalog.symptoms
      .map(
        (symptom) => `
          <button type="button" class="chip" data-symptom="${escapeHTML(symptom)}">
            ${escapeHTML(titleCase(symptom))}
          </button>
        `,
      )
      .join("");

    syncChipsFromTextarea();

    elements.symptomChipList.addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      chip.classList.toggle("active");
      syncTextareaFromChips();
    });

    elements.symptomsInput.addEventListener("input", syncChipsFromTextarea);

    document.getElementById("severity-level").innerHTML = catalog.severity_levels
      .map((option) => `<option value="${escapeHTML(option)}" ${option === "High" ? "selected" : ""}>${escapeHTML(option)}</option>`)
      .join("");

    document.getElementById("arrival-mode").innerHTML = catalog.arrival_modes
      .map((option) => `<option value="${escapeHTML(option)}">${escapeHTML(titleCase(option))}</option>`)
      .join("");

    document.getElementById("blood-pressure-summary").innerHTML = catalog.blood_pressure_options
      .map((option) => `<option value="${escapeHTML(option)}">${escapeHTML(option)}</option>`)
      .join("");

    const hospitalOptions = catalog.hospitals
      .map((hospital) => `<option value="${escapeHTML(hospital.id)}">${escapeHTML(hospital.name)}</option>`)
      .join("");

    document.getElementById("preferred-hospital").innerHTML = hospitalOptions;
    elements.originHospital.insertAdjacentHTML("beforeend", hospitalOptions);

    elements.surgeScenario.innerHTML = catalog.surge_scenarios
      .map((scenario) => `<option value="${escapeHTML(scenario.id)}">${escapeHTML(scenario.label)}</option>`)
      .join("");

    const updateScenarioDescription = () => {
      const scenario = catalog.surge_scenarios.find((item) => item.id === elements.surgeScenario.value);
      elements.scenarioDescription.textContent = scenario
        ? scenario.description
        : "Load a surge scenario to force rapid reprioritization and redistribution.";
    };

    elements.surgeScenario.addEventListener("change", updateScenarioDescription);
    updateScenarioDescription();
    state.catalogLoaded = true;
  }

  function readSymptoms() {
    return elements.symptomsInput.value
      .split(",")
      .map((symptom) => symptom.trim())
      .filter(Boolean);
  }

  function applySnapshot(snapshot) {
    state.snapshot = snapshot;
    populateCatalog(snapshot.catalog);
    elements.clockValue.textContent = snapshot.clock;
    renderMetrics(snapshot.metrics);
    renderInsights(snapshot.insights);
    renderNetworkSummary(snapshot.network);
    renderHospitals(snapshot.hospitals);
    renderEvents(snapshot.events);

    if (!state.selectedPatientId && snapshot.default_selected_patient_id) {
      state.selectedPatientId = snapshot.default_selected_patient_id;
    }
    if (!snapshot.patients.some((patient) => patient.id === state.selectedPatientId)) {
      state.selectedPatientId = snapshot.default_selected_patient_id;
    }

    renderPatients(snapshot.patients);
    renderDecisionPanel(
      snapshot.patients.find((patient) => patient.id === state.selectedPatientId) || null,
    );

    if (snapshot.metrics.overloaded_hospitals > 0) {
      setSystemStatus(
        "One or more hospitals are overloaded. Heal Hub is redistributing demand now.",
        "critical",
        "Network strain rising",
      );
    } else if (snapshot.metrics.waiting_patients > 0) {
      setSystemStatus(
        "Patients are waiting for capacity. The AI engine is balancing urgency and release timing.",
        "warning",
        "Queue pressure detected",
      );
    } else {
      setSystemStatus(
        "The network is balanced and ready to absorb new patients.",
        "stable",
        "System operating normally",
      );
    }
  }

  async function refreshDashboard() {
    const snapshot = await api("/api/dashboard-data");
    applySnapshot(snapshot);
  }

  async function handleIntake(event) {
    event.preventDefault();
    const symptoms = readSymptoms();
    if (!symptoms.length) {
      setSystemStatus("Add at least one symptom before submitting intake.", "warning", "Intake needs more data");
      return;
    }

    const payload = {
      name: document.getElementById("patient-name").value,
      age: Number(document.getElementById("patient-age").value),
      symptoms,
      severity_level: document.getElementById("severity-level").value,
      oxygen_level: Number(document.getElementById("oxygen-level").value),
      heart_rate: Number(document.getElementById("heart-rate").value),
      blood_pressure_summary: document.getElementById("blood-pressure-summary").value.toLowerCase(),
      arrival_mode: document.getElementById("arrival-mode").value,
      preferred_hospital: document.getElementById("preferred-hospital").value,
      chronic_disease: document.getElementById("chronic-disease").checked,
      pregnancy: document.getElementById("pregnancy").checked,
      notes: document.getElementById("notes").value,
    };

    setBusy(elements.intakeSubmit, true, "Adding Patient...");
    try {
      const response = await api("/api/patient-intake", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.selectedPatientId = response.patient.id;
      applySnapshot(response.state);
      setSystemStatus(response.message, response.patient.severity_tone, "Patient intake processed");
      document.getElementById("patient-name").value = "";
      document.getElementById("notes").value = "";
    } finally {
      setBusy(elements.intakeSubmit, false);
    }
  }

  async function handleRandomPatients() {
    setBusy(elements.randomButton, true, "Generating...");
    try {
      const response = await api("/api/random-patients", {
        method: "POST",
        body: JSON.stringify({
          scenario: elements.surgeScenario.value,
          count: Number(document.getElementById("random-count").value || 4),
          origin_hospital: elements.originHospital.value || null,
        }),
      });
      applySnapshot(response.state);
      setSystemStatus(response.message, "warning", "Random arrivals generated");
    } finally {
      setBusy(elements.randomButton, false);
    }
  }

  async function handleSurge() {
    setBusy(elements.surgeButton, true, "Activating...");
    try {
      const response = await api("/api/surge-mode", {
        method: "POST",
        body: JSON.stringify({
          scenario: elements.surgeScenario.value,
          count: Number(document.getElementById("random-count").value || 12),
          origin_hospital: elements.originHospital.value || null,
        }),
      });
      applySnapshot(response.state);
      setSystemStatus(response.message, "critical", "Emergency surge mode active");
    } finally {
      setBusy(elements.surgeButton, false);
    }
  }

  async function handleAdvanceTime() {
    setBusy(elements.advanceButton, true, "Advancing...");
    try {
      const response = await api("/api/advance-time", {
        method: "POST",
        body: JSON.stringify({ minutes: 30 }),
      });
      applySnapshot(response.state);
      setSystemStatus(response.message, "neutral", "Simulation advanced");
    } finally {
      setBusy(elements.advanceButton, false);
    }
  }

  async function handleReset() {
    setBusy(elements.resetButton, true, "Resetting...");
    try {
      const response = await api("/api/reset", { method: "POST" });
      state.selectedPatientId = null;
      applySnapshot(response.state);
      setSystemStatus(response.message, "stable", "Simulation reset complete");
    } finally {
      setBusy(elements.resetButton, false);
    }
  }

  function bindEvents() {
    elements.intakeForm.addEventListener("submit", (event) => {
      handleIntake(event).catch((error) => {
        setSystemStatus(error.message, "critical", "Intake request failed");
      });
    });

    elements.randomButton.addEventListener("click", () => {
      handleRandomPatients().catch((error) => {
        setSystemStatus(error.message, "critical", "Random patient generation failed");
      });
    });

    elements.surgeButton.addEventListener("click", () => {
      handleSurge().catch((error) => {
        setSystemStatus(error.message, "critical", "Surge simulation failed");
      });
    });

    elements.advanceButton.addEventListener("click", () => {
      handleAdvanceTime().catch((error) => {
        setSystemStatus(error.message, "critical", "Time advance failed");
      });
    });

    elements.resetButton.addEventListener("click", () => {
      handleReset().catch((error) => {
        setSystemStatus(error.message, "critical", "Reset failed");
      });
    });

    elements.patientBoard.addEventListener("click", (event) => {
      const card = event.target.closest("[data-patient-id]");
      if (!card || !state.snapshot) return;
      state.selectedPatientId = card.dataset.patientId;
      renderPatients(state.snapshot.patients);
      renderDecisionPanel(
        state.snapshot.patients.find((patient) => patient.id === state.selectedPatientId) || null,
      );
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    refreshDashboard().catch((error) => {
      setSystemStatus(error.message, "critical", "Unable to load dashboard");
    });
    window.setInterval(() => {
      refreshDashboard().catch(() => {});
    }, 20000);
  });
})();
