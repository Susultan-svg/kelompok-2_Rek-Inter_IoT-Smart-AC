import json
import logging
import ssl
import threading
import uuid
from typing import Callable, Any

import paho.mqtt.client as mqtt


logger = logging.getLogger(__name__)


class MqttService:
    def __init__(
        self,
        host: str,
        port: int,
        base_topic: str,
        username: str = "",
        password: str = "",
        use_tls: bool = False,
        transport: str = "tcp",
        websocket_path: str = "/mqtt",
    ) -> None:
        self.host = host
        self.port = port
        self.base_topic = base_topic.rstrip("/")
        self.transport = transport
        self.websocket_path = websocket_path
        self.telemetry_handler: Callable[[dict[str, Any]], None] | None = None
        self.status_handler: Callable[[dict[str, Any]], None] | None = None
        self.connected = False
        self.last_error = "not connected yet"
        self.client_id = f"flask-ac-dashboard-{uuid.uuid4().hex[:8]}"
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            transport=self.transport,
        )
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        if self.transport == "websockets":
            self.client.ws_set_options(path=self.websocket_path)

        if username:
            self.client.username_pw_set(username, password or None)
        if use_tls:
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            self.client.tls_insecure_set(False)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def topic(self, suffix: str) -> str:
        return f"{self.base_topic}/{suffix.lstrip('/')}"

    def start(self) -> None:
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_forever()
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            logger.warning("MQTT broker is not reachable: %s", exc)

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if getattr(reason_code, "is_failure", False):
            self.connected = False
            self.last_error = f"connect failed: {reason_code}"
            logger.warning("MQTT connection failed: %s", reason_code)
            return

        self.connected = True
        self.last_error = ""
        client.subscribe(self.topic("telemetry"))
        client.subscribe(self.topic("status"))
        client.subscribe(self.topic("remote/state"))
        logger.info("Connected to MQTT broker at %s:%s as %s via %s", self.host, self.port, self.client_id, self.transport)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
        self.connected = False
        self.last_error = f"disconnected: {reason_code}"
        logger.warning("Disconnected from MQTT broker: %s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from topic %s: %r", message.topic, message.payload)
            return

        if message.topic == self.topic("telemetry") and self.telemetry_handler:
            self.telemetry_handler(payload)
        elif message.topic in {self.topic("status"), self.topic("remote/state")} and self.status_handler:
            self.status_handler(payload)

    def publish_json(self, suffix: str, payload: dict[str, Any], retain: bool = False) -> bool:
        info = self.client.publish(self.topic(suffix), json.dumps(payload), qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.last_error = f"publish failed: {mqtt.error_string(info.rc)}"
            return False
        return True

    def publish_command(self, command: str) -> None:
        self.publish_json("control", {"command": command.upper()})

    def publish_setpoint(self, setpoint: float) -> None:
        self.publish_json("setpoint", {"setpoint": setpoint}, retain=True)

    def publish_mode(self, mode: str) -> None:
        self.publish_json("mode", {"mode": mode}, retain=True)
