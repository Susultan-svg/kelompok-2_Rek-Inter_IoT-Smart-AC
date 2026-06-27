import datetime
import json
import os
import ssl

import certifi
import psycopg2
from flask import Flask, jsonify, render_template, request
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
from flask_mqtt import Mqtt
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)

app.config["MQTT_BROKER_URL"] = os.getenv(
    "MQTT_HOST", "588b45b14a3644ab9b3d9b8f040f1f8d.s1.eu.hivemq.cloud"
)
app.config["MQTT_BROKER_PORT"] = int(os.getenv("MQTT_PORT", "8883"))
app.config["MQTT_USERNAME"] = os.getenv("MQTT_USERNAME", "esp32_sensor")
app.config["MQTT_PASSWORD"] = os.getenv("MQTT_PASSWORD", "Esp32gacor")
app.config["MQTT_TLS_ENABLED"] = True
app.config["MQTT_CLIENT_ID"] = os.getenv("MQTT_CLIENT_ID", "web-dashboard-smart-ac")
app.config["MQTT_KEEPALIVE"] = 60
app.config["MQTT_REFRESH_TIME"] = 1.0
app.config["MQTT_TLS_CA_CERTS"] = certifi.where()
app.config["MQTT_TLS_VERSION"] = ssl.PROTOCOL_TLSv1_2
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "change-this-secret-key")

jwt = JWTManager(app)
mqtt = Mqtt(app)

TOPIC_TELEMETRY = "home/ac/telemetry"
TOPIC_STATUS = "home/ac/status"
TOPIC_PRESENCE = "home/ac/presence"
TOPIC_COMMAND = "home/ac/command"
TOPIC_MODE = "home/ac/mode"
TOPIC_SETPOINT = "home/ac/setpoint"

current_state = {
    "suhu": None,
    "kelembaban": None,
    "presence": False,
    "ac_status": "OFF",
    "mode": "AUTO",
    "setpoint": 24,
    "broker_status": "DOWN",
    "esp32_status": "OFFLINE",
}


def get_db_connection():
    db_uri = os.environ.get("DB_URL")
    if not db_uri:
        raise RuntimeError("DB_URL environment variable is required")
    return psycopg2.connect(db_uri)


def log_sensor_data():
    if current_state["suhu"] is None or current_state["kelembaban"] is None:
        return

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sensor_log
                    (suhu, kelembaban, presence, ac_status, mode, setpoint, esp32_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        current_state["suhu"],
                        current_state["kelembaban"],
                        current_state["presence"],
                        current_state["ac_status"],
                        current_state["mode"],
                        current_state["setpoint"],
                        current_state["esp32_status"],
                    ),
                )
    finally:
        conn.close()


@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    if rc == 0:
        current_state["broker_status"] = "OK"
        mqtt.subscribe(TOPIC_TELEMETRY)
        mqtt.subscribe(TOPIC_STATUS)
        mqtt.subscribe(TOPIC_PRESENCE)
        print("web connected to HiveMQ")
    else:
        current_state["broker_status"] = "DOWN"
        print(f"web mqtt connect failed rc={rc}")


@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    try:
        data = json.loads(message.payload.decode("utf-8"))
    except json.JSONDecodeError:
        return

    if message.topic == TOPIC_TELEMETRY:
        for key in ("suhu", "kelembaban", "presence", "ac_status", "mode", "setpoint", "esp32_status"):
            if key in data:
                current_state[key] = data[key]
        try:
            log_sensor_data()
        except Exception as exc:
            print(f"database log failed: {exc}")

    elif message.topic == TOPIC_STATUS:
        for key in ("ac_status", "mode", "setpoint", "esp32_status"):
            if key in data:
                current_state[key] = data[key]

    elif message.topic == TOPIC_PRESENCE and "presence" in data:
        current_state["presence"] = bool(data["presence"])


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"status": "gagal", "pesan": "Username dan password wajib diisi"}), 400

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, generate_password_hash(password)),
                )
        return jsonify({"status": "sukses", "pesan": "Registrasi berhasil"}), 201
    except psycopg2.errors.UniqueViolation:
        return jsonify({"status": "gagal", "pesan": "Username sudah terpakai"}), 400
    finally:
        conn.close()


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
    finally:
        conn.close()

    if user and check_password_hash(user["password_hash"], password):
        return jsonify({"status": "sukses", "token": create_access_token(identity=username)})

    return jsonify({"status": "gagal", "pesan": "Username atau password salah"}), 401


@app.route("/api/latest", methods=["GET"])
def get_latest():
    return jsonify(current_state)


@app.route("/api/history", methods=["GET"])
def get_history():
    try:
        limit = min(500, max(1, int(request.args.get("limit", 100))))
    except ValueError:
        limit = 100

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT timestamp, suhu, kelembaban, presence, ac_status, mode, setpoint
                FROM sensor_log
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    return jsonify([dict(row) for row in reversed(rows)])


@app.route("/api/control", methods=["POST"])
@jwt_required()
def control_ac():
    data = request.json or {}
    command = str(data.get("command") or data.get("perintah") or "").upper()

    if command not in {"ON", "OFF", "SET_TEMP"}:
        return jsonify({"status": "gagal", "pesan": "Command tidak valid"}), 400

    payload = {"command": command}
    if command == "SET_TEMP":
        try:
            payload["temperature"] = max(16, min(30, int(data.get("temperature"))))
        except (TypeError, ValueError):
            return jsonify({"status": "gagal", "pesan": "Temperature tidak valid"}), 400

    mqtt.publish(TOPIC_COMMAND, json.dumps(payload))

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO ac_events (perintah, waktu_perintah) VALUES (%s, %s)",
                    (json.dumps(payload), datetime.datetime.now()),
                )
    finally:
        conn.close()

    return jsonify({"status": "sukses", "pesan": "Command terkirim", "payload": payload})


@app.route("/api/mode", methods=["POST"])
@jwt_required()
def set_mode():
    data = request.json or {}
    mode = str(data.get("mode", "")).upper()
    if mode not in {"AUTO", "MANUAL"}:
        return jsonify({"status": "gagal", "pesan": "Mode harus AUTO atau MANUAL"}), 400

    current_state["mode"] = mode
    mqtt.publish(TOPIC_MODE, json.dumps({"mode": mode}))
    return jsonify({"status": "sukses", "mode": mode})


@app.route("/api/setpoint", methods=["POST"])
@jwt_required()
def set_setpoint():
    data = request.json or {}
    try:
        setpoint = max(16, min(30, int(data.get("setpoint"))))
    except (TypeError, ValueError):
        return jsonify({"status": "gagal", "pesan": "Setpoint tidak valid"}), 400

    current_state["setpoint"] = setpoint
    mqtt.publish(TOPIC_SETPOINT, json.dumps({"setpoint": setpoint}))
    return jsonify({"status": "sukses", "setpoint": setpoint})


@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify(
        {
            "broker_status": current_state["broker_status"],
            "esp32_status": current_state["esp32_status"],
            "mode": current_state["mode"],
            "ac_status": current_state["ac_status"],
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")))
