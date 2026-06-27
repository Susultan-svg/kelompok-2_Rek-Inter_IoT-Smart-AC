import os
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    flask_host: str
    flask_port: int
    flask_debug: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_tls: bool
    mqtt_transport: str
    mqtt_websocket_path: str
    mqtt_username: str
    mqtt_password: str
    mqtt_base_topic: str
    database_path: str
    default_setpoint: float
    control_mode: str


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        flask_host=os.getenv("FLASK_HOST", "127.0.0.1"),
        flask_port=int(os.getenv("FLASK_PORT", "5000")),
        flask_debug=os.getenv("FLASK_DEBUG", "1") == "1",
        mqtt_host=os.getenv("MQTT_HOST", "432bb18e49e24068802ceaaf02694995.s1.eu.hivemq.cloud"),
        mqtt_port=int(os.getenv("MQTT_PORT", "8883")),
        mqtt_tls=os.getenv("MQTT_TLS", "1") == "1",
        mqtt_transport=os.getenv("MQTT_TRANSPORT", "tcp"),
        mqtt_websocket_path=os.getenv("MQTT_WEBSOCKET_PATH", "/mqtt"),
        mqtt_username=os.getenv("MQTT_USERNAME", ""),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        mqtt_base_topic=os.getenv("MQTT_BASE_TOPIC", "campus/ac"),
        database_path=os.getenv("DATABASE_PATH", "data/ac_iot.db"),
        default_setpoint=float(os.getenv("DEFAULT_SETPOINT", "24")),
        control_mode=os.getenv("CONTROL_MODE", "auto"),
    )
