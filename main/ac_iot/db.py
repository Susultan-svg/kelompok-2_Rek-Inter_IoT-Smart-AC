import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
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

CREATE TABLE IF NOT EXISTS ac_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    power INTEGER NOT NULL DEFAULT 0,
    temperature INTEGER NOT NULL DEFAULT 16,
    mode TEXT NOT NULL DEFAULT 'COOL',
    fan TEXT NOT NULL DEFAULT 'AUTO',
    swing TEXT NOT NULL DEFAULT 'AUTO',
    eco INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'dashboard'
);

CREATE TABLE IF NOT EXISTS ac_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    power INTEGER NOT NULL DEFAULT 0,
    temperature INTEGER NOT NULL DEFAULT 16,
    mode TEXT NOT NULL DEFAULT 'COOL',
    fan TEXT NOT NULL DEFAULT 'AUTO',
    swing TEXT NOT NULL DEFAULT 'AUTO',
    eco INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_telemetry_created_at ON telemetry(created_at);
CREATE INDEX IF NOT EXISTS idx_control_events_created_at ON control_events(created_at);
CREATE INDEX IF NOT EXISTS idx_ac_commands_created_at ON ac_commands(created_at);
"""


def connect(database_path: str) -> sqlite3.Connection:
    db_path = Path(database_path)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    _ensure_column(connection, "telemetry", "humidity", "REAL")
    connection.execute(
        """
        INSERT OR IGNORE INTO ac_state
        (id, power, temperature, mode, fan, swing, eco)
        VALUES (1, 0, 16, 'COOL', 'AUTO', 'AUTO', 0)
        """
    )
    connection.commit()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def insert_telemetry(connection: sqlite3.Connection, data: dict[str, Any], source: str = "mqtt") -> None:
    connection.execute(
        """
        INSERT INTO telemetry
        (temperature, humidity, motion, voltage, current, power, energy_kwh, ac_on, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("temperature"),
            data.get("humidity"),
            int(bool(data.get("motion", False))),
            data.get("voltage"),
            data.get("current"),
            data.get("power"),
            data.get("energy_kwh"),
            int(bool(data.get("ac_on", False))),
            source,
        ),
    )
    connection.commit()


def insert_control_event(
    connection: sqlite3.Connection,
    mode: str,
    command: str,
    setpoint: float | None = None,
    reason: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO control_events (mode, command, setpoint, reason)
        VALUES (?, ?, ?, ?)
        """,
        (mode, command, setpoint, reason),
    )
    connection.commit()


def latest_telemetry(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM telemetry ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def telemetry_history(connection: sqlite3.Connection, limit: int = 120) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM telemetry
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def daily_energy(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            date(created_at) AS date,
            MIN(energy_kwh) AS first_kwh,
            MAX(energy_kwh) AS last_kwh,
            MAX(energy_kwh) - MIN(energy_kwh) AS used_kwh,
            AVG(power) AS avg_power
        FROM telemetry
        WHERE energy_kwh IS NOT NULL
        GROUP BY date(created_at)
        ORDER BY date(created_at) DESC
        LIMIT 14
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_ac_state(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM ac_state WHERE id = 1").fetchone()
    return dict(row) if row else {
        "power": 0,
        "temperature": 16,
        "mode": "COOL",
        "fan": "AUTO",
        "swing": "AUTO",
        "eco": 0,
    }


def save_ac_command(connection: sqlite3.Connection, state: dict[str, Any], source: str = "dashboard") -> None:
    connection.execute(
        """
        INSERT INTO ac_commands
        (power, temperature, mode, fan, swing, eco, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(bool(state["power"])),
            int(state["temperature"]),
            state["mode"],
            state["fan"],
            state["swing"],
            int(bool(state["eco"])),
            source,
        ),
    )
    connection.execute(
        """
        UPDATE ac_state
        SET updated_at = CURRENT_TIMESTAMP,
            power = ?,
            temperature = ?,
            mode = ?,
            fan = ?,
            swing = ?,
            eco = ?
        WHERE id = 1
        """,
        (
            int(bool(state["power"])),
            int(state["temperature"]),
            state["mode"],
            state["fan"],
            state["swing"],
            int(bool(state["eco"])),
        ),
    )
    connection.commit()


def ac_command_history(connection: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM ac_commands
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
