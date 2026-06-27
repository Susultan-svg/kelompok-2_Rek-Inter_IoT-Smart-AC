const TOKEN_KEY = "smart_ac_token";
let tempChart = null;
let humidityChart = null;

function token() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function message(text) {
  const box = document.getElementById("message");
  if (box) box.textContent = text;
}

function requireAuth() {
  if (!token()) {
    window.location.href = "/";
  }
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  window.location.href = "/";
}

async function login() {
  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;
  const res = await fetch("/api/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username, password})
  });
  const data = await res.json();
  if (data.token) {
    localStorage.setItem(TOKEN_KEY, data.token);
    window.location.href = "/mode";
    return;
  }
  message(data.pesan || "Login gagal");
}

async function registerUser() {
  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;
  const res = await fetch("/api/register", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username, password})
  });
  const data = await res.json();
  message(data.pesan || data.status);
}

async function authPost(url, body) {
  requireAuth();
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token()}`
    },
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok) {
    message(data.pesan || "Request gagal");
    return null;
  }
  message(data.pesan || data.status || "Berhasil");
  return data;
}

async function chooseMode(mode) {
  const data = await authPost("/api/mode", {mode});
  if (!data) return;
  window.location.href = mode === "AUTO" ? "/automatic" : "/manual";
}

async function sendControl(command) {
  await authPost("/api/control", {command});
  await refreshLatest();
}

async function setSetpoint() {
  const setpoint = document.getElementById("setpoint").value;
  await authPost("/api/setpoint", {setpoint});
  await refreshLatest();
}

async function sendSetTemperature() {
  const temperature = document.getElementById("setpoint").value;
  await authPost("/api/control", {command: "SET_TEMP", temperature});
  await refreshLatest();
}

function formatNumber(value, suffix) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return "-";
  return `${number.toFixed(1)} ${suffix}`;
}

async function refreshLatest() {
  const res = await fetch("/api/latest");
  const data = await res.json();

  const suhu = document.getElementById("suhu");
  const kelembapan = document.getElementById("kelembapan");
  const presence = document.getElementById("presence");
  const acStatus = document.getElementById("ac_status");
  const setpoint = document.getElementById("setpoint");

  if (suhu) suhu.textContent = formatNumber(data.suhu, "C");
  if (kelembapan) kelembapan.textContent = formatNumber(data.kelembapan ?? data.kelembaban, "%");
  if (presence) presence.textContent = data.presence || data.motion === 1 ? "Ya" : "Tidak";
  if (acStatus) acStatus.textContent = data.ac_status || "-";
  if (setpoint && data.setpoint !== undefined && document.activeElement !== setpoint) {
    setpoint.value = data.setpoint;
  }
}

function buildChart(canvasId, label, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === "undefined") return null;
  return new Chart(canvas, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        borderColor: color,
        backgroundColor: `${color}22`,
        borderWidth: 2,
        fill: true,
        tension: 0.35
      }]
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      responsive: true,
      scales: {
        x: {ticks: {maxTicksLimit: 8}},
        y: {beginAtZero: false}
      }
    }
  });
}

async function refreshHistory() {
  const res = await fetch("/api/history?limit=60");
  const rows = await res.json();
  const labels = rows.map((row) => {
    if (!row.timestamp) return "";
    return new Date(row.timestamp).toLocaleTimeString("id-ID", {hour: "2-digit", minute: "2-digit"});
  });
  const temps = rows.map((row) => row.suhu);
  const hums = rows.map((row) => row.kelembapan ?? row.kelembaban);

  if (tempChart) {
    tempChart.data.labels = labels;
    tempChart.data.datasets[0].data = temps;
    tempChart.update();
  }
  if (humidityChart) {
    humidityChart.data.labels = labels;
    humidityChart.data.datasets[0].data = hums;
    humidityChart.update();
  }
}

async function startDashboard(expectedMode) {
  requireAuth();
  await authPost("/api/mode", {mode: expectedMode});
  tempChart = buildChart("tempChart", "Suhu (C)", "#0f766e");
  humidityChart = buildChart("humidityChart", "Kelembapan (%)", "#2563eb");
  await refreshLatest();
  await refreshHistory();
  setInterval(refreshLatest, 2000);
  setInterval(refreshHistory, 5000);
}
