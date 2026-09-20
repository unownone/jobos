(() => {
  const AMBER = "#e0992d";
  const AMBER_HOT = "#f3bc5a";
  const GOOD = "#3f9d7a";
  const INK = "#f3eee3";
  const DIM = "#cbb892";
  const CHASSIS = "#0b1220";

  let funnelChart = null;
  let agentChart = null;

  function csrfToken() {
    const hit = document.cookie.split("; ").find((c) => c.startsWith("hub_csrf="));
    return hit ? decodeURIComponent(hit.split("=").slice(1).join("=")) : "";
  }

  function headers() {
    const h = { "Content-Type": "application/json" };
    const csrf = csrfToken();
    if (csrf) h["X-CSRF"] = csrf;
    return h;
  }

  async function api(path) {
    const res = await fetch(path, { credentials: "same-origin", headers: headers() });
    if (res.status === 401) {
      location.href = "/login?next=/home";
      throw new Error("unauthorized");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail || data));
    }
    return data;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"'`]/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
      "`": "&#96;",
    }[c]));
  }

  function pill(status) {
    return `<span class="pill ${escapeHtml(status || "")}">${escapeHtml(status || "")}</span>`;
  }

  function dayLabel(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toISOString().slice(0, 10);
  }

  function themeCharts() {
    if (!window.Chart) return;
    Chart.defaults.color = DIM;
    Chart.defaults.borderColor = "rgba(224, 153, 45, 0.32)";
    Chart.defaults.font.family = '"Red Hat Text", "Segoe UI", sans-serif';
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.legend.labels.color = DIM;
  }

  function renderFunnel(funnel) {
    const canvas = document.getElementById("funnelChart");
    const labels = ["Found", "Applied", "Outreached"];
    const values = [funnel.found || 0, funnel.applied || 0, funnel.outreached || 0];
    const colors = [AMBER, GOOD, AMBER_HOT];
    const legend = document.getElementById("funnelLegend");
    if (legend) {
      legend.innerHTML = labels.map((label, i) =>
        `<li><i style="background:${colors[i]}"></i>${escapeHtml(label)} <b>${values[i]}</b></li>`
      ).join("");
    }
    if (!window.Chart) {
      canvas.replaceWith(Object.assign(document.createElement("p"), {
        className: "home-empty",
        textContent: labels.map((l, i) => `${l}: ${values[i]}`).join(" · "),
      }));
      return;
    }
    if (funnelChart) funnelChart.destroy();
    funnelChart = new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: colors,
          borderWidth: 0,
          barPercentage: 0.62,
          categoryPercentage: 0.78,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: CHASSIS,
            titleColor: INK,
            bodyColor: DIM,
            borderColor: AMBER,
            borderWidth: 1,
          },
        },
        scales: {
          x: {
            beginAtZero: true,
            ticks: { precision: 0, color: DIM },
            grid: { color: "rgba(224, 153, 45, 0.12)" },
          },
          y: {
            ticks: { color: INK },
            grid: { display: false },
          },
        },
      },
    });
  }

  function renderAgents(agents) {
    const canvas = document.getElementById("agentChart");
    const total = agents.total || 0;
    const working = agents.working || 0;
    const idle = Math.max(0, total - working);
    if (!window.Chart) {
      canvas.replaceWith(Object.assign(document.createElement("p"), {
        className: "home-empty",
        textContent: `${working} working · ${total} total`,
      }));
      return;
    }
    if (agentChart) agentChart.destroy();
    agentChart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["Working now", "Not working"],
        datasets: [{
          data: total === 0 ? [0, 1] : [working, idle],
          backgroundColor: [AMBER, "rgba(203, 184, 146, 0.38)"],
          borderColor: [AMBER_HOT, "rgba(203, 184, 146, 0.9)"],
          borderWidth: 1,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            backgroundColor: CHASSIS,
            titleColor: INK,
            bodyColor: DIM,
            borderColor: AMBER,
            borderWidth: 1,
            callbacks: {
              label(ctx) {
                if (total === 0) return "No agents yet";
                return ` ${ctx.label}: ${ctx.parsed}`;
              },
            },
          },
        },
      },
    });
    const workingEl = document.getElementById("agentWorking");
    const subEl = document.getElementById("agentWorkingSub");
    if (workingEl) workingEl.textContent = String(working);
    if (subEl) subEl.textContent = total === 1 ? "of 1 agent" : `of ${total} agents`;
  }

  function renderOldest(oldest) {
    const body = document.getElementById("oldestBody");
    const daysEl = document.getElementById("kpiOldestDays");
    const sub = document.getElementById("kpiOldestSub");
    if (!oldest) {
      daysEl.textContent = "—";
      sub.textContent = "No open jobs in the pipeline";
      body.innerHTML = `<p class="home-empty">Pipeline is empty. Discovery POSTs rows; then they age here.</p>`;
      return;
    }
    const days = oldest.days_in_pipeline;
    daysEl.textContent = days == null ? "—" : String(days);
    sub.textContent = days == null ? "Age unknown" : (days === 1 ? "1 day in pipeline" : `${days} days in pipeline`);
    const posted = oldest.posted_at
      ? `Posted ${escapeHtml(dayLabel(oldest.posted_at))}`
      : "Posted date unknown";
    const found = oldest.created_at ? `found ${escapeHtml(dayLabel(oldest.created_at))}` : "";
    const pay = oldest.pay ? escapeHtml(oldest.pay) : "Pay not stated";
    body.innerHTML = `
      <div class="co">${escapeHtml(oldest.company)}</div>
      <div>${escapeHtml(oldest.title)} ${pill(oldest.status)}</div>
      <div class="meta">
        <span>${posted}</span>
        <span>${found}</span>
        <span>${pay}</span>
        ${oldest.location ? `<span>${escapeHtml(oldest.location)}</span>` : ""}
      </div>
      <p class="row" style="margin:0.7rem 0 0">
        <a href="/board">${escapeHtml(oldest.id)}</a>
      </p>
    `;
  }

  async function boot() {
    const conn = document.getElementById("connStatus");
    const label = document.getElementById("connLabel");
    try {
      const me = await api("/api/whoami");
      const who = ((me.user && me.user.display_name) || me.actor || me.user_id || "admin") +
        " · " + (me.kind || me.role || "admin");
      document.getElementById("whoLabel").textContent = who;
      conn.classList.add("on");
      label.textContent = "signed in";
      const data = await api("/api/dashboard");
      document.getElementById("kpiFoundToday").textContent = String(data.today.found);
      document.getElementById("kpiAppliedToday").textContent = String(data.today.applied);
      themeCharts();
      renderFunnel(data.funnel || {});
      renderAgents(data.agents || {});
      renderOldest(data.oldest_in_pipeline);
    } catch (err) {
      conn.classList.remove("on");
      label.textContent = "sign in required";
      if (String(err.message || "").includes("unauthorized")) return;
      document.getElementById("oldestBody").textContent = err.message;
    }
  }

  document.getElementById("logoutBtn").addEventListener("click", async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", headers: headers() });
    } catch (_err) { /* still leave */ }
    location.href = "/login";
  });

  boot();
})();
