CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sensor_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    suhu REAL,
    kelembaban REAL,
    presence BOOLEAN,
    ac_status TEXT,
    mode TEXT,
    setpoint INTEGER,
    esp32_status TEXT
);

CREATE TABLE IF NOT EXISTS ac_events (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    perintah TEXT,
    waktu_perintah TIMESTAMPTZ
);
