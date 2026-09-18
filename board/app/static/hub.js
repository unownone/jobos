(function () {
  function csrfToken() {
    const hit = document.cookie.split("; ").find((c) => c.startsWith("hub_csrf="));
    return hit ? decodeURIComponent(hit.split("=").slice(1).join("=")) : "";
  }

  function csrfHeaders(extra) {
    const headers = { "Content-Type": "application/json" };
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF"] = csrf;
    return Object.assign(headers, extra || {});
  }

  async function logout() {
    try {
      await fetch("/api/auth/logout", { method: "POST", headers: csrfHeaders() });
    } catch (_err) {
      /* still leave */
    }
    location.href = "/login";
  }

  function markActive() {
    const path = location.pathname.replace(/\/$/, "") || "/";
    document.querySelectorAll("[data-nav]").forEach((el) => {
      const nav = el.getAttribute("data-nav");
      let on = path === nav;
      if (nav === "/admin" && (path === "/admin" || path === "/admin/invites")) on = true;
      el.classList.toggle("is-active", on);
      if (on) el.setAttribute("aria-current", "page");
      else el.removeAttribute("aria-current");
    });
  }

  function closeMore() {
    const more = document.getElementById("hubMore");
    if (more) more.classList.remove("open");
  }

  function bind() {
    markActive();
    document.querySelectorAll("[data-hub-logout]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        logout();
      });
    });
    document.querySelectorAll("[data-hub-more]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        const more = document.getElementById("hubMore");
        if (!more) return;
        more.classList.toggle("open");
      });
    });
    document.querySelectorAll("[data-hub-more-close]").forEach((el) => {
      el.addEventListener("click", () => closeMore());
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeMore();
    });
  }

  window.Hub = {
    csrfToken,
    csrfHeaders,
    logout,
    markActive,
    closeMore,
    setTicketOpen(open) {
      document.body.classList.toggle("ticket-open", Boolean(open));
      const backdrop = document.getElementById("ticketBackdrop");
      if (backdrop) backdrop.hidden = !open;
    },
    setBoardPane(pane) {
      document.body.classList.toggle("pane-presence", pane === "presence");
      document.querySelectorAll("[data-board-pane]").forEach((btn) => {
        btn.classList.toggle("on", btn.dataset.boardPane === pane);
      });
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
