import json
import os
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import certifi
import cv2
import paho.mqtt.client as mqtt
import serial


MQTT_HOST = os.getenv("MQTT_HOST", "588b45b14a3644ab9b3d9b8f040f1f8d.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "esp32_sensor")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "Esp32gacor")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "raspberry-edge-smart-ac")

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))

FACE_CHECK_INTERVAL_SECONDS = float(os.getenv("FACE_CHECK_INTERVAL_SECONDS", "60"))
NO_PERSON_TIMEOUT_SECONDS = float(os.getenv("NO_PERSON_TIMEOUT_SECONDS", "300"))
TELEMETRY_INTERVAL_SECONDS = float(os.getenv("TELEMETRY_INTERVAL_SECONDS", "30"))

TOPIC_TELEMETRY = "home/ac/telemetry"
TOPIC_STATUS = "home/ac/status"
TOPIC_PRESENCE = "home/ac/presence"
TOPIC_COMMAND = "home/ac/command"
TOPIC_MODE = "home/ac/mode"
TOPIC_SETPOINT = "home/ac/setpoint"


@dataclass
class EdgeState:
    suhu: Optional[float] = None
    kelembaban: Optional[float] = None
    presence: bool = False
    presence_updated_at: float = 0.0
    camera_update_interval_seconds: float = FACE_CHECK_INTERVAL_SECONDS
    ac_status: str = "OFF"
    mode: str = "AUTO"
    setpoint: int = 24
    esp32_status: str = "OFFLINE"
    last_person_seen_at: float = field(default_factory=time.time)
    last_esp32_seen_at: float = 0.0


state = EdgeState()
state_lock = threading.Lock()
serial_lock = threading.Lock()
ser: Optional[serial.Serial] = None
mqtt_client: Optional[mqtt.Client] = None


def write_serial_command(command: dict) -> None:
    global ser
    payload = json.dumps(command, separators=(",", ":")) + "\n"
    with serial_lock:
        if ser and ser.is_open:
            ser.write(payload.encode("utf-8"))
            ser.flush()
            print(f"serial -> esp32: {payload.strip()}")
        else:
            print(f"serial unavailable, command skipped: {payload.strip()}")


def publish_json(topic: str, payload: dict, retain: bool = False) -> None:
    if mqtt_client is None:
        return
    mqtt_client.publish(topic, json.dumps(payload, separators=(",", ":")), retain=retain)


def telemetry_snapshot() -> dict:
    with state_lock:
        return {
            "suhu": state.suhu,
            "kelembaban": state.kelembaban,
            "presence": state.presence,
            "presence_updated_at": state.presence_updated_at or None,
            "camera_update_interval_seconds": state.camera_update_interval_seconds,
            "ac_status": state.ac_status,
            "mode": state.mode,
            "setpoint": state.setpoint,
            "esp32_status": state.esp32_status,
            "timestamp": int(time.time()),
        }


def publish_state() -> None:
    snapshot = telemetry_snapshot()
    publish_json(TOPIC_TELEMETRY, snapshot)
    publish_json(
        TOPIC_STATUS,
        {
            "ac_status": snapshot["ac_status"],
            "mode": snapshot["mode"],
            "setpoint": snapshot["setpoint"],
            "esp32_status": snapshot["esp32_status"],
        },
        retain=True,
    )
    publish_presence(snapshot)


def publish_presence(snapshot: Optional[dict] = None) -> None:
    if snapshot is None:
        snapshot = telemetry_snapshot()
    publish_json(
        TOPIC_PRESENCE,
        {
            "presence": snapshot["presence"],
            "presence_updated_at": snapshot["presence_updated_at"],
            "camera_update_interval_seconds": snapshot["camera_update_interval_seconds"],
        },
        retain=True,
    )


def handle_esp32_line(line: str) -> None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        print(f"invalid serial json: {line}")
        return

    with state_lock:
        if "suhu" in data:
            state.suhu = float(data["suhu"])
        if "kelembaban" in data:
            state.kelembaban = float(data["kelembaban"])
        if "ac_status" in data:
            state.ac_status = str(data["ac_status"]).upper()
        state.esp32_status = "ONLINE"
        state.last_esp32_seen_at = time.time()

    publish_state()


def serial_worker() -> None:
    global ser
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
            print(f"serial connected: {SERIAL_PORT} @ {SERIAL_BAUD}")

            while True:
                raw = ser.readline().decode("utf-8", errors="replace").strip()
                if raw:
                    print(f"esp32 -> serial: {raw}")
                    handle_esp32_line(raw)
        except Exception as exc:
            with state_lock:
                state.esp32_status = "OFFLINE"
            print(f"serial error: {exc}")
            time.sleep(3)


def apply_auto_control() -> None:
    with state_lock:
        if state.mode != "AUTO":
            return

        now = time.time()
        should_turn_off = not state.presence and (now - state.last_person_seen_at >= NO_PERSON_TIMEOUT_SECONDS)
        should_turn_on = state.presence and state.ac_status == "OFF"

        command = None
        if should_turn_on:
            state.ac_status = "ON"
            command = {"command": "ON"}
        elif should_turn_off and state.ac_status == "ON":
            state.ac_status = "OFF"
            command = {"command": "OFF"}

    if command:
        write_serial_command(command)
        publish_state()


def camera_worker() -> None:
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"camera failed to open: index {CAMERA_INDEX}")

    while True:
        start = time.time()
        ret, frame = cap.read()
        if not ret:
            print("camera read failed")
            time.sleep(FACE_CHECK_INTERVAL_SECONDS)
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        boxes = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        found_person = len(boxes) > 0

        changed = False
        checked_at = time.time()
        with state_lock:
            state.presence_updated_at = checked_at
            if found_person:
                state.last_person_seen_at = checked_at
            if state.presence != found_person:
                state.presence = found_person
                changed = True

        publish_presence()

        if changed:
            print(f"presence changed: {'YES' if found_person else 'NO'}")
            publish_state()

        apply_auto_control()

        elapsed = time.time() - start
        time.sleep(max(0.1, FACE_CHECK_INTERVAL_SECONDS - elapsed))


def telemetry_worker() -> None:
    while True:
        publish_state()
        time.sleep(TELEMETRY_INTERVAL_SECONDS)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("mqtt connected to HiveMQ")
        client.subscribe(TOPIC_COMMAND)
        client.subscribe(TOPIC_MODE)
        client.subscribe(TOPIC_SETPOINT)
        publish_state()
    else:
        print(f"mqtt connect failed rc={rc}")


def on_message(client, userdata, message):
    try:
        data = json.loads(message.payload.decode("utf-8"))
    except json.JSONDecodeError:
        print(f"invalid mqtt json on {message.topic}: {message.payload!r}")
        return

    if message.topic == TOPIC_COMMAND:
        command = str(data.get("command", "")).upper()
        if command not in {"ON", "OFF", "SET_TEMP"}:
            return

        with state_lock:
            if state.mode != "MANUAL":
                print(f"ignored manual command in AUTO mode: {command}")
                return
            if command in {"ON", "OFF"}:
                state.ac_status = command
            elif command == "SET_TEMP" and "temperature" in data:
                state.setpoint = int(data["temperature"])

        write_serial_command(data)
        publish_state()

    elif message.topic == TOPIC_MODE:
        mode = str(data.get("mode", "")).upper()
        if mode in {"AUTO", "MANUAL"}:
            with state_lock:
                state.mode = mode
            publish_state()

    elif message.topic == TOPIC_SETPOINT:
        try:
            setpoint = int(data.get("setpoint"))
        except (TypeError, ValueError):
            return
        setpoint = max(16, min(30, setpoint))
        with state_lock:
            state.setpoint = setpoint
        write_serial_command({"command": "SET_TEMP", "temperature": setpoint})
        publish_state()


def start_mqtt() -> mqtt.Client:
    client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.tls_set(ca_certs=certifi.where(), tls_version=ssl.PROTOCOL_TLSv1_2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def main() -> None:
    global mqtt_client
    mqtt_client = start_mqtt()

    threading.Thread(target=serial_worker, daemon=True).start()
    threading.Thread(target=camera_worker, daemon=True).start()
    threading.Thread(target=telemetry_worker, daemon=True).start()

    print("Raspberry edge gateway running")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
