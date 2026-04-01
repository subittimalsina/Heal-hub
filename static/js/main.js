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
    const navShell = nav.closest(".nav-shell");

    function isMobileNav() {
      return window.innerWidth <= 1320;
    }

    function closeNav() {
      nav.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    }

    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(open));
    });

    nav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", closeNav);
    });

    document.addEventListener("click", (event) => {
      if (!isMobileNav()) return;
      if (!nav.classList.contains("is-open")) return;
      if (navShell && navShell.contains(event.target)) return;
      closeNav();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeNav();
      }
    });

    window.addEventListener("resize", () => {
      if (!isMobileNav()) {
        closeNav();
      }
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

  function initAiFabDrag() {
    const fab = document.querySelector("[data-ai-fab]");
    if (!fab) return;

    const storageKey = "healhub.aiFab.position";
    const viewportPadding = 12;
    let dragState = null;
    let suppressClick = false;

    function clampPosition(left, top) {
      const width = fab.offsetWidth || 74;
      const height = fab.offsetHeight || 74;
      const maxLeft = Math.max(viewportPadding, window.innerWidth - width - viewportPadding);
      const maxTop = Math.max(viewportPadding, window.innerHeight - height - viewportPadding);

      return {
        left: Math.min(Math.max(viewportPadding, left), maxLeft),
        top: Math.min(Math.max(viewportPadding, top), maxTop),
      };
    }

    function applyPosition(left, top, persist = true) {
      const next = clampPosition(left, top);
      fab.style.left = `${next.left}px`;
      fab.style.top = `${next.top}px`;
      fab.style.right = "auto";
      fab.style.bottom = "auto";
      if (persist) {
        try {
          localStorage.setItem(storageKey, JSON.stringify(next));
        } catch (_error) {
          // Ignore storage failures and keep the button usable.
        }
      }
    }

    function restorePosition() {
      try {
        const raw = localStorage.getItem(storageKey);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed.left !== "number" || typeof parsed.top !== "number") return;
        applyPosition(parsed.left, parsed.top, false);
      } catch (_error) {
        // Ignore malformed saved positions.
      }
    }

    function endDrag(pointerId) {
      if (!dragState || dragState.pointerId !== pointerId) return;
      fab.classList.remove("is-dragging");
      try {
        fab.releasePointerCapture(pointerId);
      } catch (_error) {
        // Ignore if capture was already released.
      }
      if (dragState.moved) {
        suppressClick = true;
        window.setTimeout(() => {
          suppressClick = false;
        }, 180);
        applyPosition(dragState.left, dragState.top, true);
      }
      dragState = null;
    }

    restorePosition();

    fab.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;

      const rect = fab.getBoundingClientRect();
      dragState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originLeft: rect.left,
        originTop: rect.top,
        left: rect.left,
        top: rect.top,
        moved: false,
      };
      fab.classList.add("is-dragging");
      fab.setPointerCapture(event.pointerId);
    });

    fab.addEventListener("pointermove", (event) => {
      if (!dragState || dragState.pointerId !== event.pointerId) return;

      const deltaX = event.clientX - dragState.startX;
      const deltaY = event.clientY - dragState.startY;
      if (Math.abs(deltaX) > 4 || Math.abs(deltaY) > 4) {
        dragState.moved = true;
      }

      const next = clampPosition(dragState.originLeft + deltaX, dragState.originTop + deltaY);
      dragState.left = next.left;
      dragState.top = next.top;
      fab.style.left = `${next.left}px`;
      fab.style.top = `${next.top}px`;
      fab.style.right = "auto";
      fab.style.bottom = "auto";
    });

    fab.addEventListener("pointerup", (event) => {
      endDrag(event.pointerId);
    });

    fab.addEventListener("pointercancel", (event) => {
      endDrag(event.pointerId);
    });

    fab.addEventListener("click", (event) => {
      if (suppressClick) {
        event.preventDefault();
      }
    });

    window.addEventListener("resize", () => {
      const rect = fab.getBoundingClientRect();
      if (fab.style.left || fab.style.top) {
        applyPosition(rect.left, rect.top, true);
      }
    });
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
    initAiFabDrag();
  });
})();
