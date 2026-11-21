(function () {
  const urlEl = document.getElementById("mcpUrl");
  const copyState = document.getElementById("copyState");
  const grantList = document.getElementById("grantList");
  const workList = document.getElementById("workList");
  const steerList = document.getElementById("steerList");
  const steerSession = document.getElementById("steerSession");
  const steerState = document.getElementById("steerState");
  const candidateNote = document.getElementById("candidateNote");
  const connLabel = document.getElementById("connLabel");
  const whoLabel = document.getElementById("whoLabel");

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function load() {
    const shown = location.origin + "/mcp";
    urlEl.textContent = shown;
    urlEl.dataset.url = shown;
    const me = await fetch("/api/auth/me", { credentials: "same-origin" });
    if (me.status === 401) {
      location.href = "/login?next=/connect";
      return;
    }
    if (!me.ok) {
      connLabel.textContent = "signed out";
      return;
    }
    const who = await me.json();
    connLabel.textContent = "admin";
    whoLabel.textContent = who.user && (who.user.email || who.actor) ? (who.user.email || who.actor) : "admin";
    const res = await fetch("/api/agent/status", { credentials: "same-origin" });
    if (!res.ok) {
      grantList.textContent = "Could not load agent status.";
      return;
    }
    const body = await res.json();
    candidateNote.textContent = body.candidate_onboarded
      ? "Candidate profile is onboarded. The agent can write jobs."
      : "Finish the candidate profile before the agent writes jobs. It can still connect and ask which lanes to run.";
    renderGrants(body.grants || []);
    renderWork(body.loops || [], body.uses || []);
    renderSteers(body.steers || []);
    fillSessions(body.grants || []);
  }

  function renderGrants(grants) {
    if (!grants.length) {
      grantList.className = "home-empty";
      grantList.textContent = "No AI connected yet.";
      return;
    }
    grantList.className = "";
    grantList.innerHTML = "<ul class=\"connect-list\">" + grants.map((grant) => {
      const session = grant.session || {};
      const lanes = (session.lanes || []).join(", ") || "lanes not chosen yet";
      const caps = session.capabilities || {};
      const capText = caps.reported
        ? "browser " + (caps.browser ? "yes" : "no") + " · email " + (caps.email ? "yes" : "no")
        : "capabilities not reported";
      return "<li><strong>" + esc(grant.client_name) + "</strong>"
        + "<div class=\"sub\">" + esc(lanes) + "</div>"
        + "<div class=\"sub\">" + esc(capText) + "</div>"
        + "<div class=\"sub\">last used " + esc(grant.last_used_at || grant.created_at) + "</div>"
        + "<button type=\"button\" class=\"secondary\" data-revoke=\"" + esc(grant.id) + "\">Revoke</button></li>";
    }).join("") + "</ul>";
    grantList.querySelectorAll("[data-revoke]").forEach((button) => {
      button.addEventListener("click", async () => {
        const id = button.getAttribute("data-revoke");
        const res = await fetch("/api/agent/grants/" + id + "/revoke", {
          method: "POST",
          credentials: "same-origin",
          headers: window.Hub.csrfHeaders(),
        });
        if (res.ok) load();
      });
    });
  }

  function renderWork(loops, uses) {
    const parts = [];
    loops.forEach((loop) => {
      parts.push("<li><strong>" + esc(loop.lane) + "</strong> · " + esc(loop.status)
        + "<div class=\"sub\">step " + esc(loop.step) + (loop.goal ? " · " + esc(loop.goal) : "") + "</div></li>");
    });
    uses.forEach((use) => {
      parts.push("<li>" + esc(use.kind) + " · " + esc(use.slug)
        + "<div class=\"sub\">" + esc(use.created_at) + (use.note ? " · " + esc(use.note) : "") + "</div></li>");
    });
    if (!parts.length) {
      workList.className = "home-empty";
      workList.textContent = "Nothing running.";
      return;
    }
    workList.className = "";
    workList.innerHTML = "<ul class=\"connect-list\">" + parts.join("") + "</ul>";
  }

  function renderSteers(steers) {
    if (!steers.length) {
      steerList.className = "home-empty";
      steerList.textContent = "None yet.";
      return;
    }
    steerList.className = "";
    steerList.innerHTML = "<ul class=\"connect-list\">" + steers.map((steer) => {
      return "<li>" + esc(steer.body) + "<div class=\"sub\">" + esc(steer.created_at) + "</div></li>";
    }).join("") + "</ul>";
  }

  function fillSessions(grants) {
    const current = steerSession.value;
    const live = [""];
    const options = ["<option value=\"\">All sessions</option>"];
    grants.forEach((grant) => {
      if (!grant.session) return;
      live.push(grant.session.id);
      options.push("<option value=\"" + esc(grant.session.id) + "\">" + esc(grant.client_name) + "</option>");
    });
    const stale = current && live.indexOf(current) === -1;
    if (stale) {
      options.push("<option value=\"" + esc(current) + "\">Session ended</option>");
    }
    steerSession.innerHTML = options.join("");
    steerSession.value = stale || live.indexOf(current) !== -1 ? current : "";
    steerSession.dataset.ended = stale ? current : "";
    steerSession.dataset.stale = stale ? "1" : "";
  }

  steerSession.addEventListener("change", () => {
    const ended = steerSession.dataset.ended || "";
    steerSession.dataset.stale = ended && steerSession.value === ended ? "1" : "";
  });

  document.getElementById("copyUrl").addEventListener("click", async () => {
    const url = urlEl.dataset.url || urlEl.textContent;
    try {
      await navigator.clipboard.writeText(url);
      copyState.textContent = "Copied.";
    } catch (_err) {
      copyState.textContent = url;
    }
  });

  document.getElementById("steerForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    steerState.textContent = "";
    if (steerSession.dataset.stale === "1") {
      steerState.textContent = "That session ended. Pick another session, or All sessions.";
      return;
    }
    const body = document.getElementById("steerBody").value.trim();
    const sessionId = steerSession.value || null;
    const res = await fetch("/api/agent/steers", {
      method: "POST",
      credentials: "same-origin",
      headers: window.Hub.csrfHeaders(),
      body: JSON.stringify({ body: body, session_id: sessionId }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      steerState.textContent = (payload.detail && (payload.detail.message || payload.detail)) || "Could not save.";
      return;
    }
    document.getElementById("steerBody").value = "";
    steerState.textContent = "Saved. The agent reads it on the next loop.";
    load();
  });

  document.getElementById("logoutBtn").addEventListener("click", () => window.Hub.logout());
  load();
  setInterval(load, 8000);
})();
