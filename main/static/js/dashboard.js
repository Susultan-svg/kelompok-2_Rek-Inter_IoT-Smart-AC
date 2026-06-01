const state = {
  history: [],
  mode: window.DASHBOARD_CONFIG.defaultMode,
  setpoint: window.DASHBOARD_CONFIG.defaultSetpoint,
  remoteDirty: false,
  sendingRemote: false
};

const els = {
  mqttStatus: document.getElementById("mqttStatus"),
  temperature: document.getElementById("temperature"),
  humidity: document.getElementById("humidity"),
  power: document.getElementById("power"),
  energy: document.getElementById("energy"),
  motion: document.getElementById("motion"),
  acStatus: document.getElementById("acStatus"),
  powerSelect: document.getElementById("powerSelect"),
  remoteTempInput: document.getElementById("remoteTempInput"),
  remoteModeSelect: document.getElementById("remoteModeSelect"),
  remoteFanSelect: document.getElementById("remoteFanSelect"),
  remoteSwingSelect: document.getElementById("remoteSwingSelect"),
  ecoSelect: document.getElementById("ecoSelect"),
  remoteSaved: document.getElementById("remoteSaved"),
  sendRemoteBtn: document.getElementById("sendRemoteBtn"),
  quickOnBtn: document.getElementById("quickOnBtn"),
  quickOffBtn: document.getElementById("quickOffBtn"),
  historyBody: document.getElementById("historyBody"),
  commandBody: document.getElementById("commandBody"),
  lastUpdate: document.getElementById("lastUpdate"),
  chart: document.getElementById("realtimeChart")
};

function fmt(value, suffix = "", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return `${Number(value).toFixed(digits)}${suffix}`;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "request failed");
  }
  return response.json();
}

function renderLatest(data) {
  const telemetry = data.telemetry || {};
  const control = data.control || {};

  if (data.mqtt_connected) {
    els.mqttStatus.textContent = "MQTT: connected";
    els.mqttStatus.title = `${data.mqtt_host}:${data.mqtt_port}`;
  } else if (!data.mqtt_username_configured) {
    els.mqttStatus.textContent = "MQTT: set credentials";
    els.mqttStatus.title = "Isi MQTT_USERNAME dan MQTT_PASSWORD di .env";
  } else {
    els.mqttStatus.textContent = "MQTT: offline";
    els.mqttStatus.title = data.mqtt_error || `${data.mqtt_host}:${data.mqtt_port}`;
  }
  els.mqttStatus.className = `mqtt-pill ${data.mqtt_connected ? "ok" : "bad"}`;
  els.temperature.textContent = fmt(telemetry.temperature, " °C");
  els.humidity.textContent = fmt(telemetry.humidity, " %RH");
  els.power.textContent = fmt(telemetry.power, " W");
  els.energy.textContent = fmt(telemetry.energy_kwh, " kWh", 3);
  els.motion.textContent = telemetry.motion ? "Terdeteksi" : "Kosong";
  const remote = data.ac_remote || {};
  els.acStatus.textContent = remote.power || control.ac_on || telemetry.ac_on ? "ON" : "OFF";
  els.acStatus.className = remote.power || control.ac_on || telemetry.ac_on ? "ok" : "bad";
  renderRemoteState(remote);
}

function renderTable(history) {
  els.historyBody.innerHTML = history.slice(-20).reverse().map((row) => `
    <tr>
      <td>${row.created_at || "--"}</td>
      <td>${fmt(row.temperature, " °C")}</td>
      <td>${fmt(row.humidity, " %RH")}</td>
      <td>${fmt(row.power, " W")}</td>
      <td>${fmt(row.current, " A", 2)}</td>
      <td>${fmt(row.voltage, " V")}</td>
      <td>${row.motion ? "Ya" : "Tidak"}</td>
      <td>${row.ac_on ? "ON" : "OFF"}</td>
    </tr>
  `).join("");
  els.lastUpdate.textContent = new Date().toLocaleTimeString("id-ID");
}

function drawChart(history) {
  const canvas = els.chart;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const pad = 48;
  const plotW = width - pad * 2;
  const plotH = height - pad * 2;

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#dbe2ed";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, pad);
  ctx.lineTo(pad, height - pad);
  ctx.lineTo(width - pad, height - pad);
  ctx.stroke();

  if (!history.length) return;

  const points = history.slice(-80);
  const temps = points.map((p) => Number(p.temperature)).filter(Number.isFinite);
  const humidities = points.map((p) => Number(p.humidity)).filter(Number.isFinite);
  const minTemp = Math.min(16, ...temps);
  const maxTemp = Math.max(35, ...temps);
  const minHumidity = Math.min(0, ...humidities);
  const maxHumidity = Math.max(100, ...humidities);

  drawLine(ctx, points, "temperature", minTemp, maxTemp, "#2563eb", pad, plotW, plotH, height);
  drawLine(ctx, points, "humidity", minHumidity, maxHumidity, "#059669", pad, plotW, plotH, height);

  ctx.fillStyle = "#657085";
  ctx.font = "12px Segoe UI, Arial";
  ctx.fillText(`${maxTemp.toFixed(0)}°C`, 8, pad + 4);
  ctx.fillText(`${minTemp.toFixed(0)}°C`, 8, height - pad);
  ctx.fillText(`${maxHumidity.toFixed(0)}%`, width - pad + 8, pad + 4);
  ctx.fillText(`${minHumidity.toFixed(0)}%`, width - pad + 8, height - pad);

  const firstLabel = formatTimeLabel(points[0]?.created_at);
  const lastLabel = formatTimeLabel(points[points.length - 1]?.created_at);
  ctx.fillText(firstLabel, pad, height - 12);
  ctx.fillText(lastLabel, width - pad - ctx.measureText(lastLabel).width, height - 12);

  ctx.save();
  ctx.translate(16, height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Suhu (C)", 0, 0);
  ctx.restore();

  ctx.save();
  ctx.translate(width - 12, height / 2);
  ctx.rotate(Math.PI / 2);
  ctx.fillText("Kelembapan (%RH)", 0, 0);
  ctx.restore();
}

function formatTimeLabel(value) {
  if (!value) return "--:--";
  const parsed = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return String(value).slice(11, 16);
  return parsed.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function drawLine(ctx, points, key, min, max, color, pad, plotW, plotH, height) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();

  points.forEach((point, index) => {
    const raw = Number(point[key]);
    if (!Number.isFinite(raw)) return;
    const x = pad + (index / Math.max(points.length - 1, 1)) * plotW;
    const y = height - pad - ((raw - min) / Math.max(max - min, 1)) * plotH;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });

  ctx.stroke();
}

async function refresh() {
  const [latestResponse, historyResponse] = await Promise.all([
    fetch("/api/latest"),
    fetch("/api/history?limit=120")
  ]);
  const latest = await latestResponse.json();
  const history = await historyResponse.json();
  state.history = history;
  renderLatest(latest);
  renderTable(history);
  drawChart(history);
}

function renderRemoteState(remote) {
  if (!remote || Object.keys(remote).length === 0) return;
  if (state.remoteDirty || state.sendingRemote) return;
  els.powerSelect.value = String(Number(remote.power || 0));
  els.remoteTempInput.value = remote.temperature ?? 16;
  els.remoteModeSelect.value = remote.mode || "COOL";
  els.remoteFanSelect.value = remote.fan || "AUTO";
  els.remoteSwingSelect.value = remote.swing || "AUTO";
  els.ecoSelect.value = String(Number(remote.eco || 0));
}

[
  els.powerSelect,
  els.remoteTempInput,
  els.remoteModeSelect,
  els.remoteFanSelect,
  els.remoteSwingSelect,
  els.ecoSelect
].forEach((input) => {
  input.addEventListener("change", () => {
    state.remoteDirty = true;
    els.remoteSaved.textContent = "Belum dikirim";
  });
  input.addEventListener("input", () => {
    state.remoteDirty = true;
    els.remoteSaved.textContent = "Belum dikirim";
  });
});

async function refreshCommands() {
  const response = await fetch("/api/ac/commands?limit=20");
  const commands = await response.json();
  els.commandBody.innerHTML = commands.map((row) => `
    <tr>
      <td>${row.created_at || "--"}</td>
      <td>${row.power ? "ON" : "OFF"}</td>
      <td>${row.temperature} °C</td>
      <td>${row.mode}</td>
      <td>${row.fan}</td>
      <td>${row.swing}</td>
      <td>${row.eco ? "ON" : "OFF"}</td>
    </tr>
  `).join("");
}

function currentRemotePayload(overrides = {}) {
  return {
    power: Number(els.powerSelect.value),
    temperature: Number(els.remoteTempInput.value),
    mode: els.remoteModeSelect.value,
    fan: els.remoteFanSelect.value,
    swing: els.remoteSwingSelect.value,
    eco: Number(els.ecoSelect.value),
    ...overrides
  };
}

async function sendRemote(overrides = {}) {
  state.sendingRemote = true;
  try {
    const result = await postJson("/api/ac/control", currentRemotePayload(overrides));
    els.remoteSaved.textContent = `MQTT: ${result.mqtt_topic}`;
    state.remoteDirty = false;
    renderRemoteState(result.state);
    await refresh();
    await refreshCommands();
  } finally {
    state.sendingRemote = false;
  }
}

els.sendRemoteBtn.addEventListener("click", () => sendRemote().catch(console.error));
els.quickOnBtn.addEventListener("click", () => sendRemote({ power: 1 }).catch(console.error));
els.quickOffBtn.addEventListener("click", () => sendRemote({ power: 0 }).catch(console.error));

refresh().catch(console.error);
refreshCommands().catch(console.error);
setInterval(() => refresh().catch(console.error), 3000);
setInterval(() => refreshCommands().catch(console.error), 5000);
