(() => {
  function escapeHTML(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function titleCase(value) {
    return String(value || "")
      .split(" ")
      .filter(Boolean)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  function toneClass(tone) {
    return `status-${tone || "neutral"}`;
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetch(path, { ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (response.status === 401 && data && data.redirect) {
      window.location.href = data.redirect;
      throw new Error(data.message || "Authentication required.");
    }

    if (!response.ok) {
      throw new Error((data && data.message) || `Request failed with status ${response.status}`);
    }

    return data;
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (!button.dataset.defaultLabel) {
      button.dataset.defaultLabel = button.textContent.trim();
    }
    button.disabled = busy;
    button.textContent = busy ? label : button.dataset.defaultLabel;
  }

  function initNav() {
    const toggle = document.querySelector("[data-nav-toggle]");
    const nav = document.getElementById("primary-nav");
    if (!toggle || !nav) return;

    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  function initReveal() {
    const items = document.querySelectorAll("[data-reveal]");
    if (!items.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 },
    );

    items.forEach((item) => observer.observe(item));
  }

  function initFlashMessages() {
    const flashes = document.querySelectorAll(".flash-message");
    if (!flashes.length) return;

    window.setTimeout(() => {
      flashes.forEach((flash) => {
        flash.classList.add("is-dismissing");
      });
    }, 5200);
  }

  window.HealHub = {
    api,
    escapeHTML,
    titleCase,
    toneClass,
    setBusy,
  };

  document.addEventListener("DOMContentLoaded", () => {
    initNav();
    initReveal();
    initFlashMessages();
  });
})();
