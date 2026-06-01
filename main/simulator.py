import json
import math
import random
import time

import paho.mqtt.client as mqtt

from ac_iot.config import get_settings


settings = get_settings()
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ac-simulator")
if settings.mqtt_username:
    client.username_pw_set(settings.mqtt_username, settings.mqtt_password or None)

base_topic = settings.mqtt_base_topic.rstrip("/")
state = {
    "ac_on": False,
    "setpoint": settings.default_setpoint,
    "energy_kwh": 0.0,
}


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode("utf-8"))
    except json.JSONDecodeError:
        return

    if message.topic == f"{base_topic}/control":
        state["ac_on"] = str(payload.get("command", "")).upper() == "ON"
    elif message.topic == f"{base_topic}/setpoint":
        state["setpoint"] = float(payload.get("setpoint", state["setpoint"]))


client.on_message = on_message
client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
client.subscribe(f"{base_topic}/control")
client.subscribe(f"{base_topic}/setpoint")
client.loop_start()

print(f"Simulator publishing to {base_topic}/telemetry")
tick = 0
last_time = time.time()
temperature = 29.0

while True:
    now = time.time()
    elapsed_hours = (now - last_time) / 3600
    last_time = now

    motion = (tick % 18) < 13
    outdoor_load = 1.2 * math.sin(tick / 8)
    if state["ac_on"]:
        temperature -= random.uniform(0.05, 0.25)
    else:
        temperature += random.uniform(0.02, 0.18)
    temperature = max(20.0, min(33.0, temperature + outdoor_load * 0.02))

    power = random.uniform(520, 820) if state["ac_on"] else random.uniform(1, 8)
    voltage = random.uniform(215, 225)
    current = power / voltage
    state["energy_kwh"] += (power / 1000) * elapsed_hours

    payload = {
        "temperature": round(temperature, 2),
        "humidity": round(random.uniform(48, 75), 2),
        "motion": motion,
        "voltage": round(voltage, 2),
        "current": round(current, 3),
        "power": round(power, 2),
        "energy_kwh": round(state["energy_kwh"], 5),
        "ac_on": state["ac_on"],
    }
    client.publish(f"{base_topic}/telemetry", json.dumps(payload), qos=1)
    print(payload)

    tick += 1
    time.sleep(5)
