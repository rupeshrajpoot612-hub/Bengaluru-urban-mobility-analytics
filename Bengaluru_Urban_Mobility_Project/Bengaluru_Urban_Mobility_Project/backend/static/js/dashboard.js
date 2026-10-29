// Bengaluru Urban Mobility dashboard: role switcher (User / Driver / Admin),
// Chart.js rendering, trip planner and demand forms.

const VEHICLE_VAR = { bike: "--series-1", auto: "--series-2", cab: "--series-3" };
const VEHICLE_LABEL = { bike: "Bike", auto: "Auto", cab: "Cab" };
const DAY_TYPE_VAR = { weekday: "--series-7", weekend: "--series-5" };
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOUR_LABELS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));
const ROLES = ["user", "driver", "admin"];
const STATUS_CLASS = { CRITICAL: "critical", SEVERE: "serious", MODERATE: "warning" };

const state = {
  role: "user",
  data: {},          // role -> payload from /api/dashboard?role=
  rendered: {},      // role -> true once charts are drawn for the current theme
  charts: {},        // role -> [Chart]
  health: null,
};

// ---------- helpers ----------
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function vehicleColor(v) { return cssVar(VEHICLE_VAR[v]); }
function withAlpha(hex, a) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const fmtInt = (n) => Number(n).toLocaleString("en-IN");
const fmtInr = (n) => `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const fmtHour = (h) => `${String(h).padStart(2, "0")}:00`;
function fmtCrore(n) {
  return n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr` : `₹${(n / 1e5).toFixed(1)} L`;
}
function haversineKm(a, b) {
  const R = 6371, r = Math.PI / 180;
  const dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
function statusChip(cls, label) {
  return `<span class="status ${cls}">${esc(label)}</span>`;
}
function surgeClass(s) { return s >= 1.5 ? "serious" : s > 1.0 ? "warning" : "good"; }

function buildTable(container, columns, rows) {
  const thead = `<thead><tr>${columns.map((c) => `<th class="${c.num ? "num" : ""}">${c.label}</th>`).join("")}</tr></thead>`;
  const tbody = `<tbody>${rows.map((r) =>
    `<tr>${columns.map((c) => {
      const v = r[c.key];
      return `<td class="${c.num ? "num" : ""} ${c.nowrap ? "nowrap" : ""}">${c.html ? c.html(v, r) : esc(c.fmt ? c.fmt(v, r) : v)}</td>`;
    }).join("")}</tr>`
  ).join("")}</tbody>`;
  container.innerHTML = `<table class="data-table">${thead}${tbody}</table>`;
}

function renderHeatmap(container, rowLabels, colLabels, matrix, { highlightCol = null, tip }) {
  const max = Math.max(...matrix.flat(), 1);
  let html = '<table class="heatmap-table"><thead><tr><th class="row-label"></th>';
  colLabels.forEach((c, j) => { html += `<th class="${j === highlightCol ? "now" : ""}">${esc(c)}</th>`; });
  html += "</tr></thead><tbody>";
  rowLabels.forEach((row, i) => {
    html += `<tr><td class="row-label">${esc(row)}</td>`;
    matrix[i].forEach((v, j) => {
      const alpha = 0.06 + 0.9 * (v / max);
      html += `<td style="background: rgba(var(--seq-rgb), ${alpha.toFixed(3)})" title="${esc(tip(row, j, v))}"></td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table>";
  html += '<div class="heat-legend"><span>Fewer</span><span class="ramp"></span><span>More trips</span></div>';
  container.innerHTML = html;
}

// ---------- Chart.js ----------
function applyChartTheme() {
  Chart.defaults.color = cssVar("--text-secondary");
  Chart.defaults.borderColor = cssVar("--gridline");
  Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', sans-serif";
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.boxHeight = 8;
  Chart.defaults.plugins.tooltip.backgroundColor = cssVar("--surface-1");
  Chart.defaults.plugins.tooltip.titleColor = cssVar("--text-primary");
  Chart.defaults.plugins.tooltip.bodyColor = cssVar("--text-secondary");
  Chart.defaults.plugins.tooltip.borderColor = cssVar("--border");
  Chart.defaults.plugins.tooltip.borderWidth = 1;
}

function scales({ yTitle, xTitle, stacked = false, beginAtZero = true, horizontal = false } = {}) {
  const value = {
    grid: { color: cssVar("--gridline") },
    border: { display: false },
    beginAtZero,
    stacked,
    title: yTitle ? { display: true, text: yTitle } : undefined,
  };
  const category = {
    grid: { display: false },
    border: { color: cssVar("--baseline") },
    stacked,
    title: xTitle ? { display: true, text: xTitle } : undefined,
  };
  return horizontal ? { x: value, y: category } : { x: category, y: value };
}

function lineDataset(label, data, color, extra = {}) {
  return {
    label, data, borderColor: color, backgroundColor: color,
    borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.3, ...extra,
  };
}

function addChart(role, canvasId, config) {
  const chart = new Chart(document.getElementById(canvasId), config);
  (state.charts[role] = state.charts[role] || []).push(chart);
  return chart;
}

const lineOpts = (yTitle, extra = {}) => ({
  interaction: { mode: "index", intersect: false },
  scales: scales({ yTitle, xTitle: "Hour of day", beginAtZero: false }),
  ...extra,
});

// ---------- Theme ----------
const THEMES = ["auto", "light", "dark"];
function getStoredTheme() {
  try { return localStorage.getItem("blr-theme") || "auto"; } catch (e) { return "auto"; }
}
function setTheme(theme) {
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("blr-theme", theme); } catch (e) { /* storage unavailable */ }
  document.getElementById("theme-toggle").textContent = `Theme: ${theme[0].toUpperCase()}${theme.slice(1)}`;
}
document.getElementById("theme-toggle").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf(getStoredTheme()) + 1) % THEMES.length];
  setTheme(next);
  rerenderAll();
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (getStoredTheme() === "auto") rerenderAll();
});
function rerenderAll() {
  ROLES.forEach((r) => {
    (state.charts[r] || []).forEach((c) => c.destroy());
    state.charts[r] = [];
    state.rendered[r] = false;
  });
  applyChartTheme();
  showRole(state.role);
}

// ---------- Role switching ----------
document.querySelectorAll(".role-btn").forEach((btn) => {
  btn.addEventListener("click", () => showRole(btn.dataset.role));
});

async function showRole(role) {
  state.role = role;
  document.querySelectorAll(".role-btn").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.role === role)));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${role}`));
  if (location.hash !== `#${role}`) history.replaceState(null, "", `#${role}`);

  if (!state.health || !state.health.dashboard_data_ready) return;
  if (!state.data[role]) {
    const res = await fetch(`/api/dashboard?role=${role}`);
    if (!res.ok) { showBanner((await res.json()).error || "Could not load dashboard data."); return; }
    state.data[role] = await res.json();
  }
  if (!state.rendered[role]) {
    RENDERERS[role](state.data[role]);
    state.rendered[role] = true;
  }
}

function showBanner(msg) {
  const banner = document.getElementById("status-banner");
  banner.textContent = msg;
  banner.classList.remove("hidden");
}

// ---------- Shared form setup ----------
function fillSelects(zones) {
  document.querySelectorAll(".zone-select").forEach((sel) => {
    if (sel.options.length) return;
    sel.innerHTML = zones.map((z) => `<option value="${esc(z.name)}">${esc(z.name)}</option>`).join("");
  });
  const today = (new Date().getDay() + 6) % 7;
  document.querySelectorAll(".day-select").forEach((sel) => {
    if (sel.options.length) return;
    sel.innerHTML = DAY_NAMES.map((d, i) => `<option value="${i}" ${i === today ? "selected" : ""}>${d}</option>`).join("");
  });
}

function kpiCards(container, cards) {
  container.innerHTML = cards.map(([label, value, sub, isText]) =>
    `<div class="kpi-card"><h3>${esc(label)}</h3><p class="value${isText ? " text" : ""}">${esc(value)}</p>${sub ? `<p class="sub">${esc(sub)}</p>` : ""}</div>`
  ).join("");
}

// ======================================================================== USER
function renderUser(payload) {
  const { common, user } = payload;
  fillSelects(common.zones);
  const pickup = document.getElementById("trip-pickup");
  const dropoff = document.getElementById("trip-dropoff");
  if (!pickup.dataset.init) {
    pickup.value = "Koramangala";
    dropoff.value = "Whitefield";
    pickup.dataset.init = "1";
  }
  const m = common.models.duration;
  document.getElementById("trip-model-note").textContent =
    `ETA: Random Forest regressor (MAE ${m.mae_minutes} min, R² ${m.r2_score}) · Surge: demand-level classifier · Fares: bike / auto / cab rate cards`;

  renderHotspots();

  addChart("user", "chart-user-surge", {
    type: "line",
    data: {
      labels: HOUR_LABELS,
      datasets: [
        lineDataset("Weekday", user.surge_by_hour.weekday, cssVar(DAY_TYPE_VAR.weekday)),
        lineDataset("Weekend", user.surge_by_hour.weekend, cssVar(DAY_TYPE_VAR.weekend)),
      ],
    },
    options: lineOpts("Surge multiplier (×)", {
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}×` } } },
    }),
  });

  addChart("user", "chart-user-minkm", {
    type: "line",
    data: {
      labels: HOUR_LABELS,
      datasets: common.vehicles.map((v) => lineDataset(VEHICLE_LABEL[v], user.minutes_per_km_by_hour[v], vehicleColor(v))),
    },
    options: lineOpts("Minutes per km", {
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)} min/km` } } },
    }),
  });

  const rows = user.distance_categories.map((cat) => {
    const row = { category: cat };
    common.vehicles.forEach((v) => {
      const r = user.estimates_by_distance.find((e) => e.distance_category === cat && e.vehicle_type === v);
      row[v] = r ? `${fmtInr(r.avg_fare_inr)} · ${Math.round(r.avg_duration_min)} min` : "—";
    });
    return row;
  });
  buildTable(document.getElementById("table-user-estimates"),
    [{ key: "category", label: "Trip length" },
     ...common.vehicles.map((v) => ({ key: v, label: VEHICLE_LABEL[v], num: true, nowrap: true }))],
    rows);
}

function selectedTripHour() {
  const t = document.getElementById("trip-time").value || "09:30";
  return parseInt(t.split(":")[0], 10);
}

function renderHotspots() {
  const payload = state.data.user;
  if (!payload) return;
  const { zones } = payload.common;
  const grid = payload.user.zone_hour_demand;
  const hour = selectedTripHour();
  const origin = zones.find((z) => z.name === document.getElementById("trip-pickup").value) || zones[0];
  const items = zones
    .map((z, i) => ({ ...z, km: haversineKm(origin, z), demand: grid.matrix[i][hour] }))
    .sort((a, b) => a.km - b.km)
    .slice(0, 5);
  const maxDemand = Math.max(...grid.matrix.map((r) => r[hour]), 1);
  document.getElementById("hotspot-note").textContent =
    `Hubs nearest to ${origin.name} at ${fmtHour(hour)}, with average ride requests per hour.`;
  document.getElementById("hotspot-list").innerHTML = items.map((z, i) => `
    <li>
      <span class="rank">${i + 1}</span>
      <div>
        <div>${esc(z.name)}</div>
        <div class="meta">${z.km < 0.05 ? "Your pickup hub" : `${z.km.toFixed(1)} km away (straight line)`}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(100 * z.demand / maxDemand).toFixed(0)}%"></div></div>
      </div>
      <span class="num">${z.demand.toFixed(1)}/hr</span>
    </li>`).join("");
}

["trip-pickup", "trip-time"].forEach((id) => document.getElementById(id).addEventListener("change", renderHotspots));
document.getElementById("trip-swap").addEventListener("click", () => {
  const p = document.getElementById("trip-pickup"), d = document.getElementById("trip-dropoff");
  [p.value, d.value] = [d.value, p.value];
  renderHotspots();
});

document.getElementById("form-trip").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const [hour, minute] = (f.get("time") || "09:30").split(":").map((x) => parseInt(x, 10));
  const payload = {
    pickup_zone: f.get("pickup_zone"),
    dropoff_zone: f.get("dropoff_zone"),
    hour, minute,
    day_of_week: f.get("day_of_week"),
    distance_km: f.get("distance_km"),
    is_raining: f.get("is_raining") ? 1 : 0,
  };
  const box = document.getElementById("trip-result");
  const res = await fetch("/api/predict/trip", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const j = await res.json();
  box.classList.remove("hidden");
  if (!res.ok) {
    document.getElementById("trip-context").innerHTML = `<strong>Error:</strong> ${esc(j.error)}`;
    document.getElementById("trip-compare").innerHTML = "";
    return;
  }

  const trafficCls = { low: "good", med: "warning", high: "serious" }[j.traffic_level];
  const trafficText = { low: "Light traffic", med: "Moderate traffic", high: "Heavy traffic" }[j.traffic_level];
  document.getElementById("trip-context").innerHTML = `
    <span><strong>${esc(j.pickup_zone)} → ${esc(j.dropoff_zone)}</strong></span>
    <span>${j.distance_km} km (${esc(j.distance_source)})</span>
    <span>${DAY_NAMES[j.day_of_week]} ${String(j.hour).padStart(2, "0")}:${String(j.minute).padStart(2, "0")}${j.is_peak_hour ? " · peak hour" : ""}${j.is_night ? " · night" : ""}${j.is_raining ? " · raining" : ""}</span>
    <span>${statusChip(trafficCls, `${trafficText} (${j.traffic_factor}×)`)}</span>
    <span>Pickup demand: <strong>${esc(j.pickup_demand_level)}</strong></span>
    <span>${statusChip(surgeClass(j.surge_multiplier), `Surge ${j.surge_multiplier.toFixed(2)}×`)}</span>`;

  document.getElementById("trip-compare").innerHTML = j.options.map((o) => {
    const b = o.breakdown;
    const tags = [];
    if (o.vehicle_type === j.cheapest) tags.push('<span class="tag">Cheapest</span>');
    if (o.vehicle_type === j.fastest) tags.push('<span class="tag">Fastest</span>');
    tags.push(statusChip(surgeClass(j.surge_multiplier), j.surge_multiplier > 1 ? `Surge ${j.surge_multiplier.toFixed(2)}×` : "No surge"));
    const row = (label, v) => `<div class="breakdown-row"><span>${label}</span><span>${v}</span></div>`;
    return `
      <div class="ride-card">
        <div class="ride-head"><span class="swatch" style="background:${vehicleColor(o.vehicle_type)}"></span>${VEHICLE_LABEL[o.vehicle_type]}</div>
        <div class="ride-metrics">
          <div><div class="metric-label">ETA</div><div class="metric-value">${Math.round(o.eta_min)} min</div></div>
          <div><div class="metric-label">Fare</div><div class="metric-value">${fmtInr(o.fare_inr)}</div></div>
        </div>
        <div class="tags">${tags.join("")}</div>
        <details class="breakdown">
          <summary>Fare breakdown</summary>
          ${row("Base fare", fmtInr(b.base))}
          ${row(`Distance (₹${b.per_km_rate}/km)`, fmtInr(b.distance_charge))}
          ${row(`Traffic delay (${b.delay_minutes} min)`, fmtInr(b.delay_charge))}
          ${b.night_surcharge > 0 ? row("Night surcharge", fmtInr(b.night_surcharge)) : ""}
          ${b.surge_charge > 0 ? row(`Surge ${j.surge_multiplier.toFixed(2)}×`, fmtInr(b.surge_charge)) : ""}
          <p class="muted">ETA model error ≈ ±${o.model_mae_min} min</p>
        </details>
      </div>`;
  }).join("");
});

// ====================================================================== DRIVER
function renderDriver(payload) {
  const { common, driver } = payload;
  fillSelects(common.zones);
  const vSel = document.getElementById("driver-vehicle");
  const hSel = document.getElementById("driver-hour");
  if (!vSel.options.length) {
    vSel.innerHTML = common.vehicles.map((v) => `<option value="${v}">${VEHICLE_LABEL[v]}</option>`).join("");
    vSel.value = "auto";
    hSel.innerHTML = HOUR_LABELS.map((h, i) => `<option value="${i}">${h}:00</option>`).join("");
    hSel.value = String(new Date().getHours());
    vSel.addEventListener("change", () => updateDriver(true));
    hSel.addEventListener("change", () => updateDriver(true));
  }
  const dm = common.models.demand;
  document.getElementById("demand-model-note").textContent =
    `Random Forest classifier on MapReduce Job 4 output · accuracy ${(dm.accuracy * 100).toFixed(1)}%`;

  addChart("driver", "chart-driver-earning", {
    type: "line",
    data: {
      labels: HOUR_LABELS,
      datasets: common.vehicles.map((v) => lineDataset(VEHICLE_LABEL[v], driver.fare_per_min_by_hour[v], vehicleColor(v))),
    },
    options: lineOpts("₹ per trip-minute", {
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ₹${c.parsed.y.toFixed(2)}/min` } } },
    }),
  });

  state.projectionChart = addChart("driver", "chart-driver-projection", {
    type: "bar",
    data: { labels: HOUR_LABELS, datasets: [{ label: "Trips per day", data: [], borderRadius: 4 }] },
    options: {
      scales: scales({ yTitle: "Trips per day", xTitle: "Hour of day" }),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.parsed.y.toFixed(1)} trips/day` } } },
    },
  });

  const ym = driver.yield_matrix;
  const maxYield = Math.max(...ym.values.flat());
  buildTable(document.getElementById("table-yield"),
    [{ key: "bucket", label: "Trip duration" },
     ...ym.vehicles.map((v, j) => ({
       key: v, label: VEHICLE_LABEL[v], num: true,
       html: (val) => `<span style="display:inline-block;min-width:64px;padding:2px 6px;border-radius:4px;background:rgba(var(--seq-rgb),${(0.08 + 0.5 * val / maxYield).toFixed(2)})">₹${val.toFixed(2)}</span>`,
     }))],
    ym.buckets.map((b, i) => Object.fromEntries([["bucket", b], ...ym.vehicles.map((v, j) => [v, ym.values[i][j]])])));

  updateDriver(false);
}

function updateDriver(fromControl) {
  const payload = state.data.driver;
  if (!payload) return;
  const { common, driver } = payload;
  const v = document.getElementById("driver-vehicle").value;
  const hour = parseInt(document.getElementById("driver-hour").value, 10);
  const trips = driver.trips_per_day_by_hour[v];
  const fpm = driver.fare_per_min_by_hour[v];
  const busiest = trips.indexOf(Math.max(...trips));
  const bestYield = fpm.indexOf(Math.max(...fpm));

  kpiCards(document.getElementById("kpi-driver"), [
    [`${VEHICLE_LABEL[v]} trips at ${fmtHour(hour)}`, fmtInt(Math.round(trips[hour])), "city-wide, per day"],
    ["₹ per trip-minute", `₹${fpm[hour].toFixed(2)}`, `at ${fmtHour(hour)}`],
    ["Busiest hour", fmtHour(busiest), `${Math.round(trips[busiest])} trips/day`],
    ["Best ₹/min hour", fmtHour(bestYield), `₹${fpm[bestYield].toFixed(2)}/min`],
  ]);

  // Where to position: zones ranked by expected ride value at this hour.
  const grid = driver.zone_hour_demand;
  const ranked = grid.zones
    .map((z, i) => ({ zone: z, demand: grid.matrix[i][hour], fare: driver.zone_hour_avg_fare[i][hour] }))
    .map((r) => ({ ...r, value: r.demand * r.fare }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);
  const maxValue = Math.max(...ranked.map((r) => r.value), 1);
  document.getElementById("position-note").textContent =
    `Ranked by total fare value requested per hour (requests × average fare) at ${fmtHour(hour)}, all vehicle types.`;
  document.getElementById("position-list").innerHTML = ranked.map((r, i) => `
    <li>
      <span class="rank">${i + 1}</span>
      <div>
        <div>${esc(r.zone)}</div>
        <div class="meta">${r.demand.toFixed(1)} requests/hr · avg fare ${fmtInr(r.fare)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${(100 * r.value / maxValue).toFixed(0)}%"></div></div>
      </div>
      <span class="num" title="Fare value requested per hour in this zone">${fmtInr(r.value)}/hr</span>
    </li>`).join("");

  renderHeatmap(document.getElementById("heatmap-driver"), grid.zones, HOUR_LABELS, grid.matrix, {
    highlightCol: hour,
    tip: (zone, h, val) => `${zone} ${fmtHour(h)} — ${val.toFixed(1)} trips/hr`,
  });

  const color = vehicleColor(v);
  const ds = state.projectionChart.data.datasets[0];
  ds.data = trips;
  ds.label = `${VEHICLE_LABEL[v]} trips per day`;
  ds.backgroundColor = trips.map((_, i) => (i === hour ? color : withAlpha(color, 0.4)));
  state.projectionChart.update(fromControl ? undefined : "none");
  document.getElementById("projection-note").textContent =
    `${VEHICLE_LABEL[v]} — average trips per day; ${fmtHour(hour)} highlighted · Source: MapReduce Job 1`;

  document.getElementById("corridor-note").textContent =
    `Top ${VEHICLE_LABEL[v]} corridors by ₹ per trip-minute (corridors with 150+ trips)`;
  buildTable(document.getElementById("table-corridors"),
    [{ key: "pickup_zone", label: "Corridor", fmt: (_, r) => `${r.pickup_zone} → ${r.dropoff_zone}` },
     { key: "avg_fare_inr", label: "Avg fare", num: true, fmt: fmtInr },
     { key: "avg_duration_min", label: "Avg min", num: true, fmt: (x) => Math.round(x) },
     { key: "fare_per_min", label: "₹/min", num: true, fmt: (x) => x.toFixed(2) }],
    driver.top_corridors[v] || []);
}

document.getElementById("form-demand").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const box = document.getElementById("result-demand");
  const res = await fetch("/api/predict/demand", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pickup_zone: f.get("pickup_zone"), hour: f.get("hour"),
      day_of_week: f.get("day_of_week"), is_raining: f.get("is_raining") ? 1 : 0,
    }),
  });
  const j = await res.json();
  box.classList.remove("hidden");
  if (!res.ok) { box.innerHTML = `<p class="headline">Error</p><p>${esc(j.error)}</p>`; return; }
  const probs = ["High", "Medium", "Low"].filter((k) => k in j.probabilities)
    .map((k) => `<div class="prob-row"><span>${k}</span><span>${(j.probabilities[k] * 100).toFixed(1)}%</span></div>`).join("");
  box.innerHTML = `
    <p class="headline">${esc(j.predicted_demand_level)} demand</p>
    <p>${statusChip(surgeClass(j.surge_multiplier), `Surge ${j.surge_multiplier.toFixed(2)}×`)}${j.is_peak_hour ? " · peak hour" : ""}</p>
    ${probs}
    <p class="muted" style="margin-top:8px">Model accuracy ≈ ${(j.model_accuracy * 100).toFixed(1)}%</p>`;
});

// ======================================================================= ADMIN
function renderAdmin(payload) {
  const { common, admin } = payload;
  const k = common.kpis;
  const mr = admin.mapreduce;
  document.getElementById("admin-intro").textContent =
    `System-wide view over ${k.days_covered} days (${k.date_range.start.slice(0, 10)} to ${k.date_range.end.slice(0, 10)}). ${common.data_note}`;

  kpiCards(document.getElementById("kpi-admin"), [
    ["Total trips", fmtInt(k.total_trips)],
    ["Revenue", fmtCrore(k.total_revenue_inr)],
    ["Avg fare", fmtInr(k.avg_fare_inr)],
    ["Avg speed", `${k.avg_speed_kmph} km/h`],
    ["Avg surge", `${k.avg_surge}×`],
    ["Peak hour", fmtHour(k.peak_hour)],
    ["Busiest zone", k.busiest_zone, null, true],
    ["Critical corridors", k.critical_corridors, "peak avg < 13.75 km/h"],
  ]);

  const vehicles = common.vehicles;
  const vColors = vehicles.map(vehicleColor);
  const surface = cssVar("--surface-1");

  addChart("admin", "chart-admin-modeshare", {
    type: "doughnut",
    data: {
      labels: admin.mode_share.map((m) => VEHICLE_LABEL[m.vehicle_type]),
      datasets: [{ data: admin.mode_share.map((m) => m.trips), backgroundColor: vColors, borderColor: surface, borderWidth: 2 }],
    },
    options: {
      cutout: "62%",
      plugins: {
        legend: {
          position: "right",
          labels: {
            generateLabels: (chart) => chart.data.labels.map((l, i) => ({
              text: `${l}  ${(admin.mode_share[i].share * 100).toFixed(1)}%`,
              fillStyle: vColors[i], strokeStyle: vColors[i], pointStyle: "rect", index: i,
              fontColor: cssVar("--text-secondary"),
            })),
          },
        },
        tooltip: { callbacks: { label: (c) => `${c.label}: ${fmtInt(c.parsed)} trips (${(admin.mode_share[c.dataIndex].share * 100).toFixed(1)}%)` } },
      },
    },
  });

  addChart("admin", "chart-admin-revenue", {
    type: "bar",
    data: {
      labels: admin.mode_share.map((m) => VEHICLE_LABEL[m.vehicle_type]),
      datasets: [{ label: "Revenue", data: admin.mode_share.map((m) => m.revenue_inr / 1e5), backgroundColor: vColors, borderRadius: 4 }],
    },
    options: {
      scales: scales({ yTitle: "₹ lakh" }),
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => `${fmtCrore(admin.mode_share[c.dataIndex].revenue_inr)} · avg fare ${fmtInr(admin.mode_share[c.dataIndex].avg_fare_inr)}` } },
      },
    },
  });

  addChart("admin", "chart-admin-job1", {
    type: "bar",
    data: {
      labels: HOUR_LABELS,
      datasets: vehicles.map((v, i) => ({
        label: VEHICLE_LABEL[v], data: mr.job1_modal_demand_by_hour.by_vehicle[v],
        backgroundColor: vColors[i], borderColor: surface, borderWidth: { top: 2 }, borderSkipped: false,
        borderRadius: i === vehicles.length - 1 ? { topLeft: 4, topRight: 4 } : 0,
      })),
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: scales({ yTitle: "Trips", xTitle: "Hour of day", stacked: true }),
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } } },
    },
  });

  const job2Chart = addChart("admin", "chart-admin-job2", {
    type: "bar",
    data: { labels: common.zones.map((z) => z.name), datasets: [] },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: scales({}),
      plugins: {},
    },
  });
  const metricSel = document.getElementById("job2-metric");
  const drawJob2 = () => {
    const metric = metricSel.value;
    const isFare = metric === "avg_fare_inr";
    job2Chart.data.datasets = vehicles.map((v, i) => ({
      label: VEHICLE_LABEL[v],
      data: common.zones.map((z) => (mr.job2_avg_duration_and_fare_by_zone.find((r) => r.pickup_zone === z.name && r.vehicle_type === v) || {})[metric] ?? 0),
      backgroundColor: vColors[i], borderColor: surface, borderWidth: 1, borderRadius: 4,
    }));
    job2Chart.options.scales = scales({ yTitle: isFare ? "Average fare (₹)" : "Average duration (min)" });
    job2Chart.options.plugins.tooltip = {
      callbacks: { label: (c) => `${c.dataset.label}: ${isFare ? fmtInr(c.parsed.y) : `${c.parsed.y.toFixed(1)} min`}` },
    };
    job2Chart.update();
  };
  metricSel.onchange = drawJob2;
  drawJob2();

  addChart("admin", "chart-admin-congestion", {
    type: "line",
    data: {
      labels: HOUR_LABELS,
      datasets: [
        lineDataset("Weekday", admin.congestion_by_hour.weekday, cssVar(DAY_TYPE_VAR.weekday)),
        lineDataset("Weekend", admin.congestion_by_hour.weekend, cssVar(DAY_TYPE_VAR.weekend)),
      ],
    },
    options: lineOpts("Traffic factor (×)", {
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}×` } } },
    }),
  });

  addChart("admin", "chart-admin-speed", {
    type: "line",
    data: { labels: HOUR_LABELS, datasets: vehicles.map((v, i) => lineDataset(VEHICLE_LABEL[v], admin.speed_by_hour[v], vColors[i])) },
    options: lineOpts("km/h", {
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)} km/h` } } },
    }),
  });

  // Dot plot (not bars): speeds cluster at 13-15 km/h, so a zero-based bar
  // would hide the differences; a dot's position doesn't need a zero baseline.
  const allCorridors = mr.job3_top_congestion_corridors;
  const slow = allCorridors.slice(0, 25);
  const statusColor = (s) => cssVar(`--${STATUS_CLASS[s]}`);
  const speeds = allCorridors.map((r) => r.avg_speed_kmph);
  addChart("admin", "chart-admin-job3", {
    type: "line",
    data: {
      labels: slow.map((r) => `${r.pickup_zone} → ${r.dropoff_zone}`),
      datasets: [{
        label: "Avg peak speed", data: slow.map((r) => r.avg_speed_kmph), showLine: false,
        pointRadius: 6, pointHoverRadius: 8, pointBorderColor: surface, pointBorderWidth: 2,
        pointBackgroundColor: slow.map((r) => statusColor(r.bottleneck_status)),
      }],
    },
    options: {
      indexAxis: "y",
      scales: {
        x: {
          type: "linear",
          min: Math.floor(Math.min(...speeds)) - 1,
          max: Math.ceil(Math.max(...speeds)) + 1,
          grid: { color: cssVar("--gridline") },
          border: { display: false },
          title: { display: true, text: "Average peak-hour speed (km/h) — axis spans slowest to fastest of all 90 corridors" },
        },
        y: { grid: { display: false }, border: { color: cssVar("--baseline") } },
      },
      plugins: {
        legend: {
          display: true,
          labels: {
            generateLabels: () => ["CRITICAL", "SEVERE", "MODERATE"].map((s) => ({
              text: s[0] + s.slice(1).toLowerCase(), fillStyle: statusColor(s), strokeStyle: statusColor(s),
              pointStyle: "circle", fontColor: cssVar("--text-secondary"),
            })),
          },
          onClick: () => {},
        },
        tooltip: {
          callbacks: {
            label: (c) => {
              const r = slow[c.dataIndex];
              return [`${r.bottleneck_status}: ${r.avg_speed_kmph.toFixed(1)} km/h`,
                      `Avg delay ${r.avg_delay_min.toFixed(1)} min (${(r.delay_share * 100).toFixed(0)}% of trip)`,
                      `${fmtInt(r.peak_trips)} peak trips`];
            },
          },
        },
      },
    },
  });

  addChart("admin", "chart-admin-rain", {
    type: "bar",
    data: {
      labels: vehicles.map((v) => VEHICLE_LABEL[v]),
      datasets: [
        { label: "Dry", data: admin.rain_impact_min_per_km.dry, backgroundColor: cssVar("--baseline"), borderRadius: 4, borderColor: surface, borderWidth: 1 },
        { label: "Rain", data: admin.rain_impact_min_per_km.rain, backgroundColor: cssVar("--series-7"), borderRadius: 4, borderColor: surface, borderWidth: 1 },
      ],
    },
    options: {
      scales: scales({ yTitle: "Minutes per km" }),
      plugins: {
        tooltip: {
          callbacks: {
            label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)} min/km`,
            afterBody: (items) => {
              const i = items[0].dataIndex;
              const d = admin.rain_impact_min_per_km;
              return `Rain slows ${items[0].label} by ${(((d.rain[i] / d.dry[i]) - 1) * 100).toFixed(0)}%`;
            },
          },
        },
      },
    },
  });

  addChart("admin", "chart-admin-zone-revenue", {
    type: "bar",
    data: {
      labels: admin.revenue_by_zone.zones,
      datasets: vehicles.map((v, i) => ({
        label: VEHICLE_LABEL[v], data: admin.revenue_by_zone.by_vehicle[v].map((x) => x / 1e5),
        backgroundColor: vColors[i], borderColor: surface, borderWidth: { right: 2 }, borderSkipped: false,
        borderRadius: i === vehicles.length - 1 ? { topRight: 4, bottomRight: 4 } : 0,
      })),
    },
    options: {
      indexAxis: "y",
      interaction: { mode: "index", intersect: false },
      scales: scales({ yTitle: "₹ lakh", stacked: true, horizontal: true }),
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ₹${c.parsed.x.toFixed(1)} L` } } },
    },
  });

  renderHeatmap(document.getElementById("heatmap-admin"), admin.heatmap.days.map((d) => d.slice(0, 3)), HOUR_LABELS, admin.heatmap.matrix, {
    tip: (day, h, v) => `${day} ${fmtHour(h)} — ${fmtInt(v)} trips`,
  });

  // ---- MapReduce tables ----
  const j1 = mr.job1_modal_demand_by_hour;
  buildTable(document.getElementById("mr-job1"),
    [{ key: "hour", label: "Hour", fmt: fmtHour },
     ...vehicles.map((v) => ({ key: v, label: VEHICLE_LABEL[v], num: true, fmt: fmtInt })),
     { key: "total", label: "Total", num: true, fmt: fmtInt }],
    j1.hours.map((h) => {
      const row = { hour: h, total: 0 };
      vehicles.forEach((v) => { row[v] = j1.by_vehicle[v][h]; row.total += row[v]; });
      return row;
    }));

  buildTable(document.getElementById("mr-job2"),
    [{ key: "pickup_zone", label: "Zone" },
     { key: "vehicle_type", label: "Vehicle", fmt: (v) => VEHICLE_LABEL[v] },
     { key: "trip_count", label: "Trips", num: true, fmt: fmtInt },
     { key: "avg_duration_min", label: "Avg min", num: true, fmt: (x) => x.toFixed(1) },
     { key: "avg_fare_inr", label: "Avg fare", num: true, fmt: fmtInr }],
    mr.job2_avg_duration_and_fare_by_zone);

  buildTable(document.getElementById("mr-job3"),
    [{ key: "pickup_zone", label: "Corridor", fmt: (_, r) => `${r.pickup_zone} → ${r.dropoff_zone}` },
     { key: "peak_trips", label: "Peak trips", num: true, fmt: fmtInt },
     { key: "avg_speed_kmph", label: "Avg km/h", num: true, fmt: (x) => x.toFixed(1) },
     { key: "avg_duration_min", label: "Avg min", num: true, fmt: (x) => x.toFixed(1) },
     { key: "avg_delay_min", label: "Avg delay", num: true, fmt: (x) => `${x.toFixed(1)} min` },
     { key: "delay_share", label: "Delay share", num: true, fmt: (x) => `${(x * 100).toFixed(0)}%` },
     { key: "bottleneck_status", label: "Status", html: (s) => statusChip(STATUS_CLASS[s], s[0] + s.slice(1).toLowerCase()) }],
    mr.job3_top_congestion_corridors);

  const j4 = mr.job4_demand_dataset;
  document.getElementById("mr-job4-note").textContent =
    `${fmtInt(j4.rows)} (date, hour, zone) cells. Classes: Low ≤ ${j4.thresholds.q33} trips, Medium ≤ ${j4.thresholds.q66}, High above — ` +
    `Low ${fmtInt(j4.class_counts.Low)} / Medium ${fmtInt(j4.class_counts.Medium)} / High ${fmtInt(j4.class_counts.High)}. Full file: outputs/mapreduce/job4_demand_dataset.csv`;
  buildTable(document.getElementById("mr-job4"),
    [{ key: "pickup_date", label: "Date" },
     { key: "hour", label: "Hour", fmt: fmtHour },
     { key: "pickup_zone", label: "Zone" },
     { key: "is_raining", label: "Rain", fmt: (x) => (x ? "Yes" : "No") },
     { key: "trip_demand", label: "Trips", num: true }],
    j4.sample);

  const d = common.models.duration, m = common.models.demand;
  const topFeatures = Object.entries(d.feature_importance).sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([f, v]) => `${f} (${(v * 100).toFixed(0)}%)`).join(", ");
  document.getElementById("ml-metrics").innerHTML = `
    <p><strong>Model A — Trip duration (Random Forest regressor)</strong></p>
    <div class="prob-row"><span>MAE</span><span>${d.mae_minutes} min</span></div>
    <div class="prob-row"><span>R²</span><span>${d.r2_score}</span></div>
    ${vehicles.map((v) => `<div class="prob-row"><span>MAE — ${VEHICLE_LABEL[v]}</span><span>${d.mae_minutes_by_vehicle[v]} min</span></div>`).join("")}
    <div class="prob-row"><span>Physics formula alone (baseline)</span><span>${d.physics_only_mae_minutes} min</span></div>
    <p class="muted">Learns actual ÷ physics ETA, so predictions scale with distance for every vehicle. Top features: ${esc(topFeatures)} · ${fmtInt(d.training_rows)} trips</p>
    <p style="margin-top:16px"><strong>Model B — Zone demand level (Random Forest classifier)</strong></p>
    <div class="prob-row"><span>Accuracy</span><span>${(m.accuracy * 100).toFixed(1)}%</span></div>
    <div class="prob-row"><span>Weighted F1</span><span>${m.f1_weighted}</span></div>
    <p class="muted">${fmtInt(m.training_rows)} demand cells from MapReduce Job 4 · drives surge (Low 1.0× / Medium 1.1× / High 1.3×, +0.2× peak, +0.3× rain, capped 2.2×)</p>`;
}

const RENDERERS = { user: renderUser, driver: renderDriver, admin: renderAdmin };

// ---------- Boot ----------
async function boot() {
  setTheme(getStoredTheme());
  applyChartTheme();
  try {
    state.health = await (await fetch("/api/health")).json();
  } catch (e) {
    state.health = { dashboard_data_ready: false, duration_model_ready: false, demand_model_ready: false };
  }
  if (!state.health.dashboard_data_ready) {
    showBanner("Pipeline outputs not found yet. Run: python pipeline/run_all.py, then reload this page.");
  } else if (!state.health.duration_model_ready || !state.health.demand_model_ready) {
    showBanner("Models not trained yet — predictions are disabled. Run: python pipeline/run_all.py");
  }
  const fromHash = location.hash.replace("#", "");
  await showRole(ROLES.includes(fromHash) ? fromHash : "user");
}

boot();
