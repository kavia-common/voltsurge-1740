/**
 * VoltSurge Frontend SPA (static HTML/CSS/JS).
 *
 * Responsibilities:
 * - Parse CSV header client-side for column mapping UI (preview only).
 * - Upload CSV file to backend with mapping as query params.
 * - Fetch summary/data/anomalies for a session and render dashboard:
 *   - Summary stats
 *   - Chart.js time-series chart (energy kWh)
 *   - Anomaly alerts list
 */

/** @typedef {{ timestamp: string, energy_kwh: number, is_anomaly?: boolean }} DataPoint */
/** @typedef {{ timestamp: string, energy_kwh: number, baseline_avg_kwh: number, threshold_kwh: number, ratio: number }} Anomaly */

const els = {
  apiBaseUrl: document.getElementById("apiBaseUrl"),
  btnHealth: document.getElementById("btnHealth"),
  healthPill: document.getElementById("healthPill"),

  btnReset: document.getElementById("btnReset"),

  csvFile: document.getElementById("csvFile"),
  delimiter: document.getElementById("delimiter"),
  headersCount: document.getElementById("headersCount"),
  headersList: document.getElementById("headersList"),

  timestampCol: document.getElementById("timestampCol"),
  energyCol: document.getElementById("energyCol"),
  unitCol: document.getElementById("unitCol"),

  btnUpload: document.getElementById("btnUpload"),
  uploadStatus: document.getElementById("uploadStatus"),

  statSession: document.getElementById("statSession"),
  statCreated: document.getElementById("statCreated"),
  statBaseline: document.getElementById("statBaseline"),
  statAnomalies: document.getElementById("statAnomalies"),
  statThreshold: document.getElementById("statThreshold"),
  statRowsReceived: document.getElementById("statRowsReceived"),
  statRowsCleaned: document.getElementById("statRowsCleaned"),
  statTotal: document.getElementById("statTotal"),
  statMinMax: document.getElementById("statMinMax"),

  btnRefresh: document.getElementById("btnRefresh"),
  btnClearSession: document.getElementById("btnClearSession"),

  alertsEmpty: document.getElementById("alertsEmpty"),
  alertsList: document.getElementById("alertsList"),

  debugJson: document.getElementById("debugJson"),

  energyChart: document.getElementById("energyChart"),
};

const state = {
  headers: /** @type {string[]} */ ([]),
  sessionId: /** @type {string | null} */ (null),
  summary: /** @type {any | null} */ (null),
  data: /** @type {DataPoint[]} */ ([]),
  anomalies: /** @type {Anomaly[]} */ ([]),
  chart: /** @type {any | null} */ (null),
};

function getApiBaseUrl() {
  const raw = (els.apiBaseUrl.value || "").trim();
  return raw.replace(/\/+$/, "");
}

// PUBLIC_INTERFACE
function setStatus(message, tone = "neutral") {
  /** Set upload status message with tone. */
  els.uploadStatus.textContent = message || "";
  els.uploadStatus.dataset.tone = tone;
}

// PUBLIC_INTERFACE
function setHealthPill(text, kind = "neutral") {
  /** Update the health pill status. */
  els.healthPill.textContent = text;
  els.healthPill.classList.remove("pill-neutral", "pill-ok", "pill-bad");
  if (kind === "ok") els.healthPill.classList.add("pill-ok");
  else if (kind === "bad") els.healthPill.classList.add("pill-bad");
  else els.healthPill.classList.add("pill-neutral");
}

function formatNumber(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
  return Number(x).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function safeJsonStringify(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

async function httpJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let parsed = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  if (!res.ok) {
    const bodySnippet = text?.slice(0, 2000) ?? "";
    const err = new Error(`HTTP ${res.status} ${res.statusText}${bodySnippet ? ` — ${bodySnippet}` : ""}`);
    // @ts-ignore
    err.status = res.status;
    // @ts-ignore
    err.bodyText = text;
    throw err;
  }
  return parsed;
}

function parseCsvHeader(text, delimiter) {
  // Minimal header parser for mapping UX (not a full CSV parser).
  // Handles UTF-8 BOM and uses first non-empty line as header row.
  const cleaned = text.replace(/^\uFEFF/, "");
  const lines = cleaned.split(/\r?\n/).map((l) => l.trim());
  const headerLine = lines.find((l) => l.length > 0);
  if (!headerLine) return [];
  // Naive split: adequate for typical headers; quoted delimiters in header names are uncommon.
  return headerLine
    .split(delimiter)
    .map((h) => h.trim().replace(/^"(.+)"$/, "$1"))
    .filter(Boolean);
}

function renderHeadersChips(headers) {
  els.headersList.innerHTML = "";
  if (!headers.length) return;
  for (const h of headers) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = h;
    els.headersList.appendChild(chip);
  }
}

function findBestHeader(headers, candidates) {
  const normalized = headers.map((h) => ({ raw: h, key: h.toLowerCase().replace(/\s+/g, "") }));
  for (const cand of candidates) {
    const target = cand.toLowerCase().replace(/\s+/g, "");
    const exact = normalized.find((x) => x.key === target);
    if (exact) return exact.raw;
  }
  // Fallback: contains match
  for (const cand of candidates) {
    const target = cand.toLowerCase().replace(/\s+/g, "");
    const contains = normalized.find((x) => x.key.includes(target));
    if (contains) return contains.raw;
  }
  return null;
}

function fillSelect(selectEl, headers, placeholder) {
  selectEl.innerHTML = "";
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = placeholder;
  selectEl.appendChild(opt0);

  for (const h of headers) {
    const opt = document.createElement("option");
    opt.value = h;
    opt.textContent = h;
    selectEl.appendChild(opt);
  }
  selectEl.disabled = headers.length === 0;
}

function setSelectValue(selectEl, value) {
  if (!value) return;
  const exists = [...selectEl.options].some((o) => o.value === value);
  if (exists) selectEl.value = value;
}

function canUpload() {
  return (
    !!els.csvFile.files?.[0] &&
    !!els.timestampCol.value &&
    !!els.energyCol.value &&
    !!els.unitCol.value
  );
}

function updateUploadButton() {
  els.btnUpload.disabled = !canUpload();
}

function resetDashboardUi() {
  state.sessionId = null;
  state.summary = null;
  state.data = [];
  state.anomalies = [];
  els.debugJson.textContent = "";
  els.btnRefresh.disabled = true;
  els.btnClearSession.disabled = true;

  els.statSession.textContent = "—";
  els.statCreated.textContent = "—";
  els.statBaseline.textContent = "—";
  els.statAnomalies.textContent = "—";
  els.statThreshold.textContent = "—";
  els.statRowsReceived.textContent = "—";
  els.statRowsCleaned.textContent = "—";
  els.statTotal.textContent = "—";
  els.statMinMax.textContent = "—";

  els.alertsList.innerHTML = "";
  els.alertsEmpty.style.display = "block";

  renderChart([], []);
}

function renderSummary(summary) {
  // We support both the expected onboarding fields and any extra fields the backend might include.
  const sessionId = summary?.session_id ?? "—";
  const createdAt = summary?.created_at ?? summary?.created_time ?? null;

  const baseline = summary?.baseline_avg_kwh;
  const threshold = baseline !== undefined && baseline !== null ? baseline * 1.2 : null;

  els.statSession.textContent = sessionId;
  els.statCreated.textContent = createdAt ? `Created: ${createdAt}` : "—";

  els.statBaseline.textContent = formatNumber(baseline, 3);
  els.statAnomalies.textContent = summary?.anomalies_count ?? "—";
  els.statThreshold.textContent = threshold !== null ? `Threshold: ${formatNumber(threshold, 3)} kWh` : "—";

  els.statRowsReceived.textContent = summary?.rows_received ?? "—";
  els.statRowsCleaned.textContent = summary?.rows_cleaned ?? "—";

  // Optional stats if backend provides them
  const total = summary?.total_energy_kwh ?? summary?.total_kwh ?? null;
  const min = summary?.min_energy_kwh ?? summary?.min_kwh ?? null;
  const max = summary?.max_energy_kwh ?? summary?.max_kwh ?? null;

  els.statTotal.textContent = total !== null ? formatNumber(total, 3) : "—";
  els.statMinMax.textContent =
    min !== null && max !== null ? `${formatNumber(min, 3)} / ${formatNumber(max, 3)}` : "—";
}

function renderAlerts(anomalies) {
  els.alertsList.innerHTML = "";
  if (!anomalies || anomalies.length === 0) {
    els.alertsEmpty.style.display = "block";
    return;
  }
  els.alertsEmpty.style.display = "none";

  for (const a of anomalies) {
    const li = document.createElement("li");
    li.className = "alert";

    const title = document.createElement("div");
    title.className = "alert-title";

    const left = document.createElement("strong");
    left.textContent = "Anomaly detected";

    const right = document.createElement("span");
    right.textContent = a.timestamp ?? "—";

    const body = document.createElement("div");
    body.className = "alert-body";
    const energy = a.energy_kwh ?? a.energy ?? null;
    const ratio = a.ratio ?? null;
    const threshold = a.threshold_kwh ?? null;

    body.textContent = `Energy: ${formatNumber(energy, 3)} kWh` +
      (threshold !== null ? ` (threshold ${formatNumber(threshold, 3)} kWh)` : "") +
      (ratio !== null ? ` • ratio ${formatNumber(ratio, 2)}×` : "");

    title.appendChild(left);
    title.appendChild(right);
    li.appendChild(title);
    li.appendChild(body);

    els.alertsList.appendChild(li);
  }
}

function renderChart(dataPoints, anomalies) {
  const labels = dataPoints.map((d) => d.timestamp);
  const values = dataPoints.map((d) => d.energy_kwh);

  const anomalyTimestamps = new Set((anomalies || []).map((a) => a.timestamp));
  const pointColors = dataPoints.map((d) => (anomalyTimestamps.has(d.timestamp) ? "#ff4d67" : "rgba(91, 140, 255, 0.95)"));
  const pointRadius = dataPoints.map((d) => (anomalyTimestamps.has(d.timestamp) ? 5 : 2));

  const dataset = {
    label: "Energy (kWh)",
    data: values,
    borderColor: "rgba(91, 140, 255, 0.9)",
    backgroundColor: "rgba(91, 140, 255, 0.18)",
    tension: 0.25,
    pointBackgroundColor: pointColors,
    pointBorderColor: "rgba(255,255,255,0.25)",
    pointRadius,
    pointHoverRadius: 6,
    fill: true,
  };

  if (state.chart) {
    state.chart.data.labels = labels;
    state.chart.data.datasets = [dataset];
    state.chart.update();
    return;
  }

  // eslint-disable-next-line no-undef
  state.chart = new Chart(els.energyChart, {
    type: "line",
    data: { labels, datasets: [dataset] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: "#eaf0ff" } },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${formatNumber(ctx.parsed.y, 3)} kWh`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: "rgba(234, 240, 255, 0.75)", maxRotation: 0, autoSkip: true },
          grid: { color: "rgba(255, 255, 255, 0.06)" },
        },
        y: {
          ticks: { color: "rgba(234, 240, 255, 0.75)" },
          grid: { color: "rgba(255, 255, 255, 0.06)" },
        },
      },
    },
  });
}

async function refreshSessionFromBackend() {
  if (!state.sessionId) return;

  const base = getApiBaseUrl();
  const summaryUrl = `${base}/sessions/${encodeURIComponent(state.sessionId)}/summary`;
  const dataUrl = `${base}/sessions/${encodeURIComponent(state.sessionId)}/data?limit=100000&offset=0`;
  const anomaliesUrl = `${base}/sessions/${encodeURIComponent(state.sessionId)}/anomalies`;

  setStatus("Refreshing dashboard…", "neutral");
  try {
    const [summary, data, anomalies] = await Promise.all([
      httpJson(summaryUrl),
      httpJson(dataUrl),
      httpJson(anomaliesUrl),
    ]);

    state.summary = summary;
    state.data = Array.isArray(data) ? data : (data?.items ?? []);
    state.anomalies = Array.isArray(anomalies) ? anomalies : (anomalies?.items ?? []);

    renderSummary(state.summary);
    renderAlerts(state.anomalies);

    // Some backends may include is_anomaly flags in /data; we still highlight based on /anomalies timestamps.
    renderChart(state.data, state.anomalies);

    els.debugJson.textContent = safeJsonStringify({ summary, data_preview: state.data.slice(0, 5), anomalies });
    setStatus("Dashboard updated.", "ok");
  } catch (err) {
    console.error(err);
    setStatus(err?.message || "Failed to refresh.", "bad");
  }
}

async function uploadAndProcess() {
  const file = els.csvFile.files?.[0];
  if (!file) return;

  const base = getApiBaseUrl();
  const timestampCol = els.timestampCol.value;
  const energyCol = els.energyCol.value;
  const unitCol = els.unitCol.value;

  if (!timestampCol || !energyCol || !unitCol) {
    setStatus("Please map timestamp, energy, and unit columns.", "bad");
    return;
  }

  const qs = new URLSearchParams({
    timestamp_col: timestampCol,
    energy_col: energyCol,
    unit_col: unitCol,
  });

  const url = `${base}/upload?${qs.toString()}`;
  const form = new FormData();
  form.append("file", file, file.name);

  setStatus("Uploading & processing…", "neutral");
  els.btnUpload.disabled = true;

  try {
    const summary = await httpJson(url, {
      method: "POST",
      body: form,
    });

    state.sessionId = summary?.session_id ?? null;
    state.summary = summary;

    if (!state.sessionId) {
      setStatus("Upload succeeded but no session_id returned by backend.", "bad");
      els.debugJson.textContent = safeJsonStringify(summary);
      return;
    }

    renderSummary(summary);
    els.btnRefresh.disabled = false;
    els.btnClearSession.disabled = false;

    els.debugJson.textContent = safeJsonStringify(summary);

    // Follow-up fetch for full dashboard view.
    await refreshSessionFromBackend();
  } catch (err) {
    console.error(err);
    setStatus(err?.message || "Upload failed.", "bad");
  } finally {
    updateUploadButton();
  }
}

async function testHealth() {
  const base = getApiBaseUrl();
  setHealthPill("Testing…", "neutral");
  try {
    const data = await httpJson(`${base}/health`);
    setHealthPill("Connected", "ok");
    els.debugJson.textContent = safeJsonStringify({ health: data });
  } catch (err) {
    console.error(err);
    setHealthPill("Error", "bad");
    els.debugJson.textContent = safeJsonStringify({ error: err?.message || String(err) });
  }
}

async function clearSession() {
  if (!state.sessionId) return;
  const base = getApiBaseUrl();
  const url = `${base}/sessions/${encodeURIComponent(state.sessionId)}`;
  setStatus("Clearing session…", "neutral");
  try {
    await httpJson(url, { method: "DELETE" });
    setStatus("Session cleared.", "ok");
    resetDashboardUi();
  } catch (err) {
    console.error(err);
    setStatus(err?.message || "Failed to clear session.", "bad");
  }
}

function resetAll() {
  // Reset mapping + preview + dashboard.
  state.headers = [];
  els.csvFile.value = "";
  els.headersCount.textContent = "No file selected";
  els.headersList.innerHTML = "";

  for (const sel of [els.timestampCol, els.energyCol, els.unitCol]) {
    sel.innerHTML = "";
    sel.disabled = true;
  }
  updateUploadButton();
  setStatus("");
  setHealthPill("Not tested", "neutral");
  resetDashboardUi();
}

async function onFileSelected() {
  const file = els.csvFile.files?.[0];
  state.headers = [];
  els.headersList.innerHTML = "";
  els.headersCount.textContent = "Reading…";
  setStatus("");

  for (const sel of [els.timestampCol, els.energyCol, els.unitCol]) {
    sel.disabled = true;
    sel.innerHTML = "";
  }
  updateUploadButton();

  if (!file) {
    els.headersCount.textContent = "No file selected";
    return;
  }

  // Read a small prefix; enough to cover header line.
  const slice = file.slice(0, 64 * 1024);
  const text = await slice.text();
  const delimiter = els.delimiter.value === "\\t" ? "\t" : els.delimiter.value;
  const headers = parseCsvHeader(text, delimiter);

  state.headers = headers;
  if (!headers.length) {
    els.headersCount.textContent = "No headers detected";
    setStatus("Could not detect headers from CSV preview. Ensure the first line contains header names.", "bad");
    return;
  }

  els.headersCount.textContent = `${headers.length} header(s) detected`;
  renderHeadersChips(headers);

  fillSelect(els.timestampCol, headers, "Select timestamp column…");
  fillSelect(els.energyCol, headers, "Select energy column…");
  fillSelect(els.unitCol, headers, "Select unit column…");

  // Best-effort default mapping.
  setSelectValue(els.timestampCol, findBestHeader(headers, ["timestamp", "time", "datetime", "date_time", "date"]));
  setSelectValue(els.energyCol, findBestHeader(headers, ["energy", "usage", "consumption", "kwh", "value"]));
  setSelectValue(els.unitCol, findBestHeader(headers, ["unit", "uom", "units"]));

  updateUploadButton();
}

function wireEvents() {
  els.btnHealth.addEventListener("click", testHealth);
  els.btnReset.addEventListener("click", resetAll);

  els.csvFile.addEventListener("change", onFileSelected);
  els.delimiter.addEventListener("change", () => {
    // Re-run header parsing if a file is already selected.
    if (els.csvFile.files?.[0]) onFileSelected();
  });

  for (const sel of [els.timestampCol, els.energyCol, els.unitCol]) {
    sel.addEventListener("change", updateUploadButton);
  }

  els.btnUpload.addEventListener("click", uploadAndProcess);
  els.btnRefresh.addEventListener("click", refreshSessionFromBackend);
  els.btnClearSession.addEventListener("click", clearSession);
}

(function init() {
  wireEvents();
  resetDashboardUi();
  updateUploadButton();
})();
