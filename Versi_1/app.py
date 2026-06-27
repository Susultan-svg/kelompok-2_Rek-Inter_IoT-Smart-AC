import csv
import io
import logging
import os
import threading
import time

from flask import Flask, Response, jsonify, render_template, request

from ac_iot.config import get_settings
from ac_iot.control import ControlState, decide_automatic_control
from ac_iot.db import (
    ac_command_history,
    connect,
    daily_energy,
    get_ac_state,
    init_db,
    insert_control_event,
    insert_telemetry,
    latest_telemetry,
    save_ac_command,
    telemetry_history,
)
from ac_iot.mqtt_service import MqttService


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

settings = get_settings()
database = connect(settings.database_path)
init_db(database)
database_lock = threading.Lock()

control_state = ControlState(mode=settings.control_mode, setpoint=settings.default_setpoint)
mqtt_service = MqttService(
    host=settings.mqtt_host,
    port=settings.mqtt_port,
    base_topic=settings.mqtt_base_topic,
    username=settings.mqtt_username,
    password=settings.mqtt_password,
    use_tls=settings.mqtt_tls,
    transport=settings.mqtt_transport,
    websocket_path=settings.mqtt_websocket_path,
)

app = Flask(__name__)
command_lock = threading.Lock()
command_counter = int(time.time())


def next_command_id() -> int:
    global command_counter
    with command_lock:
        command_counter += 1
        return command_counter


def handle_telemetry(payload: dict) -> None:
    global control_state

    temperature = payload.get("temperature")
    motion = bool(payload.get("motion", False))
    control_state.ac_on = bool(payload.get("ac_on", control_state.ac_on))

    with database_lock:
        insert_telemetry(database, payload)

    command, reason = decide_automatic_control(control_state, temperature, motion)
    if command:
        mqtt_service.publish_command(command)
        control_state.ac_on = command == "ON"
        with database_lock:
            insert_control_event(database, control_state.mode, command, control_state.setpoint, reason)


def handle_status(payload: dict) -> None:
    if "power" not in payload:
        return

    state = {
        "power": int(bool(payload.get("power"))),
        "temperature": int(payload.get("temperature", 24)),
        "mode": str(payload.get("mode", "COOL")).upper(),
        "fan": str(payload.get("fan", "AUTO")).upper(),
        "swing": str(payload.get("swing", "AUTO")).upper(),
        "eco": int(bool(payload.get("eco", False))),
    }
    with database_lock:
        save_ac_command(database, state, source="device_state")


mqtt_service.telemetry_handler = handle_telemetry
mqtt_service.status_handler = handle_status
if not settings.flask_debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    mqtt_service.start()


@app.get("/")
def index():
    return render_template(
        "index.html",
        base_topic=settings.mqtt_base_topic,
        default_setpoint=control_state.setpoint,
        default_mode=control_state.mode,
    )


@app.get("/api/latest")
def api_latest():
    with database_lock:
        latest = latest_telemetry(database)
        ac_state = get_ac_state(database)
    return jsonify(
        {
            "mqtt_connected": mqtt_service.connected,
            "mqtt_error": mqtt_service.last_error,
            "mqtt_host": settings.mqtt_host,
            "mqtt_port": settings.mqtt_port,
            "mqtt_tls": settings.mqtt_tls,
            "mqtt_transport": settings.mqtt_transport,
            "mqtt_username_configured": bool(settings.mqtt_username and not settings.mqtt_username.startswith("ISI_")),
            "control": {
                "mode": control_state.mode,
                "setpoint": control_state.setpoint,
                "ac_on": control_state.ac_on,
            },
            "ac_remote": ac_state,
            "telemetry": latest,
        }
    )


@app.get("/api/history")
def api_history():
    limit = max(1, min(int(request.args.get("limit", 120)), 1000))
    with database_lock:
        history = telemetry_history(database, limit)
    return jsonify(history)


@app.get("/api/energy/daily")
def api_daily_energy():
    with database_lock:
        rows = daily_energy(database)
    return jsonify(rows)


@app.post("/api/control")
def api_control():
    payload = request.get_json(force=True)
    command = str(payload.get("command", "")).upper()
    if command not in {"ON", "OFF"}:
        return jsonify({"error": "command must be ON or OFF"}), 400

    control_state.mode = "manual"
    control_state.ac_on = command == "ON"
    mqtt_service.publish_mode(control_state.mode)
    mqtt_service.publish_command(command)

    with database_lock:
        insert_control_event(database, control_state.mode, command, control_state.setpoint, "dashboard manual control")

    return jsonify({"ok": True, "mode": control_state.mode, "command": command})


@app.post("/api/mode")
def api_mode():
    payload = request.get_json(force=True)
    mode = str(payload.get("mode", "")).lower()
    if mode not in {"auto", "manual"}:
        return jsonify({"error": "mode must be auto or manual"}), 400

    control_state.mode = mode
    mqtt_service.publish_mode(mode)

    with database_lock:
        insert_control_event(database, control_state.mode, "MODE", control_state.setpoint, f"mode changed to {mode}")

    return jsonify({"ok": True, "mode": control_state.mode})


@app.post("/api/setpoint")
def api_setpoint():
    payload = request.get_json(force=True)
    try:
        setpoint = float(payload.get("setpoint"))
    except (TypeError, ValueError):
        return jsonify({"error": "setpoint must be numeric"}), 400

    if not 16 <= setpoint <= 32:
        return jsonify({"error": "setpoint must be between 16 and 32"}), 400

    control_state.setpoint = setpoint
    mqtt_service.publish_setpoint(setpoint)

    with database_lock:
        insert_control_event(database, control_state.mode, "SETPOINT", control_state.setpoint, "dashboard setpoint update")

    return jsonify({"ok": True, "setpoint": control_state.setpoint})


@app.get("/api/export.csv")
def api_export_csv():
    with database_lock:
        rows = telemetry_history(database, 10000)

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["id", "created_at", "temperature", "humidity", "motion", "voltage", "current", "power", "energy_kwh", "ac_on", "source"],
    )
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ac_telemetry.csv"},
    )


@app.get("/api/ac/state")
def api_ac_state():
    with database_lock:
        state = get_ac_state(database)
    return jsonify({"mqtt_connected": mqtt_service.connected, "state": state})


@app.get("/api/ac/commands")
def api_ac_commands():
    limit = max(1, min(int(request.args.get("limit", 50)), 200))
    with database_lock:
        rows = ac_command_history(database, limit)
    return jsonify(rows)


@app.post("/api/ac/control")
def api_ac_control():
    payload = request.get_json(force=True)
    with database_lock:
        state = get_ac_state(database)

    next_state = {
        "power": int(bool(payload.get("power", state["power"]))),
        "temperature": int(payload.get("temperature", state["temperature"])),
        "mode": str(payload.get("mode", state["mode"])).upper(),
        "fan": str(payload.get("fan", state["fan"])).upper(),
        "swing": str(payload.get("swing", state["swing"])).upper(),
        "eco": int(bool(payload.get("eco", state["eco"]))),
    }

    if next_state["temperature"] < 16 or next_state["temperature"] > 30:
        return jsonify({"error": "temperature must be between 16 and 30"}), 400
    if next_state["mode"] not in {"COOL", "AUTO", "DRY"}:
        return jsonify({"error": "mode must be COOL, AUTO, or DRY"}), 400
    if next_state["fan"] not in {"AUTO", "LOW", "MED", "MAX"}:
        return jsonify({"error": "fan must be AUTO, LOW, MED, or MAX"}), 400
    if next_state["swing"] not in {"AUTO", "HIGH", "MID", "LOW", "LOWEST"}:
        return jsonify({"error": "swing must be AUTO, HIGH, MID, LOW, or LOWEST"}), 400
    if not mqtt_service.connected:
        return jsonify({"error": f"MQTT is not connected: {mqtt_service.last_error}"}), 503

    mqtt_payload = {
        "command_id": next_command_id(),
        "source": "flask_dashboard",
        "power": bool(next_state["power"]),
        "temperature": next_state["temperature"],
        "mode": next_state["mode"],
        "fan": next_state["fan"],
        "swing": next_state["swing"],
        "eco": bool(next_state["eco"]),
    }
    if not mqtt_service.publish_json("remote/command", mqtt_payload):
        return jsonify({"error": mqtt_service.last_error}), 503

    with database_lock:
        save_ac_command(database, next_state)

    return jsonify({
        "ok": True,
        "state": next_state,
        "command_id": mqtt_payload["command_id"],
        "mqtt_topic": f"{settings.mqtt_base_topic}/remote/command",
    })


if __name__ == "__main__":
    app.run(host=settings.flask_host, port=settings.flask_port, debug=settings.flask_debug)
