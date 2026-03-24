const medicineDemoData = [
  {
    id: 1,
    facility: {
      name: "MedPlus Pharmacy",
      address: "Thamel, Kathmandu",
      lat: 27.7172,
      lng: 85.324,
      phone: "+977-1-4700123",
    },
    medicine: { name: "Insulin Glargine" },
    quantity: 15,
    price: 1200,
    status: "AVAILABLE",
    distance: 1.2,
    refillEta: "3 days",
    deliveryAvailable: true,
    updated: "Feb 12, 2026 7:42 AM",
  },
  {
    id: 2,
    facility: {
      name: "City Hospital",
      address: "Lazimpat, Kathmandu",
      lat: 27.715,
      lng: 85.322,
      phone: "+977-1-4420123",
    },
    medicine: { name: "Insulin Glargine" },
    quantity: 0,
    price: 1250,
    status: "LIMITED",
    distance: 0.8,
    refillEta: "1 day",
    deliveryAvailable: false,
    updated: "Feb 12, 2026 6:30 AM",
  },
  {
    id: 3,
    facility: {
      name: "Health Pharmacy",
      address: "Patan Hospital Road",
      lat: 27.6848,
      lng: 85.3297,
      phone: "+977-1-5520123",
    },
    medicine: { name: "Insulin Glargine" },
    quantity: -1,
    price: null,
    status: "OUT_OF_STOCK",
    distance: 3.5,
    refillEta: "5 days",
    deliveryAvailable: false,
    updated: "Feb 11, 2026 4:15 PM",
  },
  {
    id: 4,
    facility: {
      name: "LifeCare Medical",
      address: "Boudha, Kathmandu",
      lat: 27.7211,
      lng: 85.354,
      phone: "+977-1-4480123",
    },
    medicine: { name: "Paracetamol 500mg" },
    quantity: 45,
    price: 25,
    status: "AVAILABLE",
    distance: 2.1,
    refillEta: null,
    deliveryAvailable: true,
    updated: "Feb 12, 2026 7:00 AM",
  },
  {
    id: 5,
    facility: {
      name: "Everest Pharmacy",
      address: "Koteshwor",
      lat: 27.6894,
      lng: 85.348,
      phone: "+977-1-4460123",
    },
    medicine: { name: "Amoxicillin 500mg" },
    quantity: 30,
    price: 80,
    status: "AVAILABLE",
    distance: 4.2,
    refillEta: null,
    deliveryAvailable: false,
    updated: "Feb 12, 2026 6:45 AM",
  },
];

const medicineMapState = {
  center: [27.7172, 85.324],
  instance: null,
  markers: [],
};

document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page !== "medicine-search") {
    return;
  }

  const searchForm = document.getElementById("medicineSearchForm");
  const searchButton = document.getElementById("searchBtn");
  const resultsList = document.getElementById("resultsList");

  if (!searchForm || !searchButton || !resultsList) {
    return;
  }

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    handleMedicineSearch();
  });

  resultsList.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-facility-id]");

    if (!trigger) {
      return;
    }

    const facilityId = Number(trigger.dataset.facilityId);
    openMedicineFacility(facilityId);
  });
});

function handleMedicineSearch() {
  const input = document.getElementById("searchInput");
  const button = document.getElementById("searchBtn");

  if (!input || !button) {
    return;
  }

  const query = input.value.trim().toLowerCase();
  const rawQuery = input.value.trim();

  if (!query) {
    input.focus();
    return;
  }

  toggleMedicineState("loading", true);
  toggleMedicineState("results", false);
  toggleMedicineState("empty", false);
  toggleMedicineState("map", false);

  button.disabled = true;
  button.textContent = "Searching...";

  window.setTimeout(() => {
    const results = medicineDemoData
      .filter((item) => item.medicine.name.toLowerCase().includes(query))
      .sort((left, right) => left.distance - right.distance);

    toggleMedicineState("loading", false);

    if (results.length > 0) {
      renderMedicineResults(results, rawQuery);
      toggleMedicineState("results", true);
      toggleMedicineState("map", true);
      renderMedicineMap(results);
    } else {
      toggleMedicineState("empty", true);
    }

    button.disabled = false;
    button.textContent = "Search Again";
  }, 1200);
}

function renderMedicineResults(results, query) {
  const resultsList = document.getElementById("resultsList");
  const heading = document.getElementById("resultsHeading");

  if (!resultsList || !heading) {
    return;
  }

  heading.textContent = `${results.length} match${results.length === 1 ? "" : "es"} for "${query}"`;
  resultsList.innerHTML = results.map((item) => createMedicineCard(item)).join("");
}

function createMedicineCard(item) {
  const statusClass = getMedicineStatusClass(item.status);
  const priceMarkup = item.price
    ? `<div class="medicine-result-price">NPR ${item.price.toLocaleString()}</div>`
    : "";
  const quantityMarkup =
    item.quantity > 0
      ? `<div class="medicine-result-quantity">📦 ${item.quantity} units available</div>`
      : "";
  const deliveryMarkup = item.deliveryAvailable
    ? '<span class="medicine-detail-chip">🚚 Delivery available</span>'
    : "";
  const refillMarkup = item.refillEta
    ? `<span class="medicine-detail-chip">⏰ Refill: ${item.refillEta}</span>`
    : "";
  const phoneMarkup = item.facility.phone
    ? `<span class="medicine-detail-chip">📞 ${item.facility.phone}</span>`
    : "";

  return `
    <button class="medicine-result-card surface" type="button" data-facility-id="${item.id}">
      <div class="medicine-result-top">
        <div class="medicine-result-title-wrap">
          <h3 class="medicine-result-title">${item.facility.name}</h3>
          <p class="medicine-result-address">${item.facility.address}</p>
        </div>
        <span class="medicine-status-badge ${statusClass}">${formatMedicineStatus(item.status)}</span>
      </div>
      <div class="medicine-result-distance">📍 ${item.distance.toFixed(1)} km away</div>
      ${quantityMarkup}
      ${priceMarkup}
      <div class="medicine-result-details">
        ${deliveryMarkup}
        ${refillMarkup}
        ${phoneMarkup}
      </div>
      <div class="medicine-updated">
        <span>Updated ${item.updated}</span>
        <strong>Demo data</strong>
      </div>
    </button>
  `;
}

function renderMedicineMap(results) {
  const mapElement = document.getElementById("map");

  if (!mapElement || typeof window.L === "undefined") {
    return;
  }

  if (!medicineMapState.instance) {
    medicineMapState.instance = window.L.map("map").setView(medicineMapState.center, 13);

    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(medicineMapState.instance);
  }

  medicineMapState.markers.forEach((marker) => marker.remove());
  medicineMapState.markers = [];

  results.forEach((item) => {
    const marker = window.L.marker([item.facility.lat, item.facility.lng])
      .bindPopup(createMedicinePopup(item))
      .addTo(medicineMapState.instance);

    medicineMapState.markers.push(marker);
  });

  medicineMapState.instance.setView(medicineMapState.center, 13);

  window.setTimeout(() => {
    medicineMapState.instance.invalidateSize();
  }, 100);
}

function createMedicinePopup(item) {
  return `
    <div class="medicine-popup">
      <div class="medicine-popup-title">${item.facility.name}</div>
      <div class="medicine-popup-copy">${item.medicine.name}</div>
      <span class="medicine-status-badge ${getMedicineStatusClass(item.status)}">
        ${formatMedicineStatus(item.status)}
      </span>
    </div>
  `;
}

function openMedicineFacility(id) {
  window.alert(
    `Opening facility details for ID: ${id}\n\n📞 Call to confirm stock before traveling.\n\n*Demo only`
  );
}

function formatMedicineStatus(status) {
  return status.replaceAll("_", " ");
}

function getMedicineStatusClass(status) {
  if (status === "AVAILABLE") {
    return "medicine-status-available";
  }

  if (status === "LIMITED") {
    return "medicine-status-limited";
  }

  return "medicine-status-out";
}

function toggleMedicineState(section, isVisible) {
  const idMap = {
    loading: "loadingSection",
    results: "resultsSection",
    empty: "noResultsSection",
    map: "mapSection",
  };

  const element = document.getElementById(idMap[section]);

  if (!element) {
    return;
  }

  element.hidden = !isVisible;
}
