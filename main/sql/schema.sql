CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    temperature REAL,
    humidity REAL,
    motion INTEGER NOT NULL DEFAULT 0,
    voltage REAL,
    current REAL,
    power REAL,
    energy_kwh REAL,
    ac_on INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'mqtt'
);

CREATE TABLE IF NOT EXISTS control_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mode TEXT NOT NULL,
    command TEXT NOT NULL,
    setpoint REAL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_telemetry_created_at ON telemetry(created_at);
CREATE INDEX IF NOT EXISTS idx_control_events_created_at ON control_events(created_at);
