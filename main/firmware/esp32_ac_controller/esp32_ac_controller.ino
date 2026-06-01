#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <IRremoteESP8266.h>
#include <ir_Sharp.h>

// Konfigurasi Wi-Fi dan MQTT. Sesuaikan sebelum upload ke ESP32.
const char* WIFI_SSID = "ABAH_UNI 1 BAWAH";
const char* WIFI_PASSWORD = "793793Rr";
const char* MQTT_HOST = "432bb18e49e24068802ceaaf02694995.s1.eu.hivemq.cloud";
const uint16_t MQTT_PORT = 8883;
const char* MQTT_USER = "ISI_USERNAME_HIVEMQ";
const char* MQTT_PASSWORD = "ISI_PASSWORD_HIVEMQ";
const char* BASE_TOPIC = "campus/ac";

// DHT11 membaca suhu/kelembapan, IR LED mengontrol AC Sharp.
const uint8_t DHT_PIN = 5; // D5 pada ESP32 DevKit umumnya GPIO5
const uint8_t DHT_TYPE = DHT11;
const uint8_t AC_IR_PIN = 2; // D2 pada ESP32 DevKit umumnya GPIO2
const sharp_ac_remote_model_t SHARP_REMOTE_MODEL = sharp_ac_remote_model_t::A907;

const unsigned long TELEMETRY_INTERVAL_MS = 10000;

WiFiClientSecure wifiClient;
PubSubClient mqtt(wifiClient);
DHT dht(DHT_PIN, DHT_TYPE);
IRSharpAc sharpAc(AC_IR_PIN);

bool acOn = false;
int targetTemperature = 24;
String acMode = "COOL";
String fanMode = "AUTO";
String swingMode = "AUTO";
bool ecoMode = false;
unsigned long lastTelemetryAt = 0;

String topic(const char* suffix) {
  return String(BASE_TOPIC) + "/" + suffix;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi connected: ");
  Serial.println(WiFi.localIP());
}

void applySharpSettings() {
  sharpAc.setTemp(targetTemperature);
  sharpAc.setEconoToggle(ecoMode);

  if (acMode == "AUTO") {
    sharpAc.setMode(kSharpAcAuto);
  } else if (acMode == "DRY") {
    sharpAc.setMode(kSharpAcDry);
  } else {
    sharpAc.setMode(kSharpAcCool);
  }

  if (fanMode == "LOW") {
    sharpAc.setFan(kSharpAcFanMin);
  } else if (fanMode == "MED") {
    sharpAc.setFan(kSharpAcFanMed);
  } else if (fanMode == "MAX") {
    sharpAc.setFan(kSharpAcFanMax);
  } else {
    sharpAc.setFan(kSharpAcFanAuto);
  }

  if (swingMode == "HIGH") {
    sharpAc.setSwingV(kSharpAcSwingVHigh, true);
  } else if (swingMode == "MID") {
    sharpAc.setSwingV(kSharpAcSwingVMid, true);
  } else if (swingMode == "LOW") {
    sharpAc.setSwingV(kSharpAcSwingVLow, true);
  } else if (swingMode == "LOWEST") {
    sharpAc.setSwingV(kSharpAcSwingVLowest, true);
  } else {
    sharpAc.setSwingV(kSharpAcSwingVToggle, true);
  }

  if (acOn) {
    sharpAc.on();
  } else {
    sharpAc.off();
  }
}

void sendSharpCommand(const char* reason) {
  applySharpSettings();
  sharpAc.send();

  Serial.print("Sharp AC command sent: ");
  Serial.println(reason);
}

void setAcPower(bool turnOn, const char* reason) {
  acOn = turnOn;
  sendSharpCommand(reason);

  StaticJsonDocument<192> doc;
  doc["ac_on"] = acOn;
  doc["reason"] = reason;
  doc["actuator"] = "sharp_ir";

  char payload[192];
  serializeJson(doc, payload);
  mqtt.publish(topic("status").c_str(), payload, true);
}

void publishRemoteState() {
  StaticJsonDocument<256> doc;
  doc["power"] = acOn;
  doc["temperature"] = targetTemperature;
  doc["mode"] = acMode;
  doc["fan"] = fanMode;
  doc["swing"] = swingMode;
  doc["eco"] = ecoMode;
  doc["actuator"] = "sharp_ir";

  char payload[256];
  serializeJson(doc, payload);
  mqtt.publish(topic("remote/state").c_str(), payload, true);
}

void handleRemoteCommand(JsonDocument& doc) {
  if (doc["power"].is<bool>()) {
    acOn = doc["power"].as<bool>();
  }

  if (doc["temperature"].is<int>()) {
    targetTemperature = constrain(doc["temperature"].as<int>(), 16, 30);
  }
  if (doc["mode"].is<const char*>()) {
    acMode = doc["mode"].as<const char*>();
  }
  if (doc["fan"].is<const char*>()) {
    fanMode = doc["fan"].as<const char*>();
  }
  if (doc["swing"].is<const char*>()) {
    swingMode = doc["swing"].as<const char*>();
  }
  if (doc["eco"].is<bool>()) {
    ecoMode = doc["eco"].as<bool>();
  }

  sendSharpCommand("remote command");
  publishRemoteState();
}

void handleLegacyControl(JsonDocument& doc) {
  const char* command = doc["command"] | "";
  if (strcmp(command, "ON") == 0) {
    setAcPower(true, "legacy control topic");
  } else if (strcmp(command, "OFF") == 0) {
    setAcPower(false, "legacy control topic");
  }
  publishRemoteState();
}

void handleMqttMessage(char* rawTopic, byte* payload, unsigned int length) {
  StaticJsonDocument<384> doc;
  DeserializationError error = deserializeJson(doc, payload, length);
  if (error) {
    Serial.print("Invalid MQTT JSON: ");
    Serial.println(error.c_str());
    return;
  }

  String incomingTopic = String(rawTopic);
  if (incomingTopic == topic("remote/command")) {
    handleRemoteCommand(doc);
  } else if (incomingTopic == topic("control")) {
    handleLegacyControl(doc);
  } else if (incomingTopic == topic("setpoint")) {
    targetTemperature = constrain(doc["setpoint"] | targetTemperature, 16, 30);
    publishRemoteState();
  }
}

void connectMqtt() {
  while (!mqtt.connected()) {
    uint64_t chipId = ESP.getEfuseMac();
    String clientId = "esp32-ac-simple-" + String((uint32_t)chipId, HEX);

    Serial.print("Connecting MQTT as ");
    Serial.println(clientId);

    bool connected;
    if (strlen(MQTT_USER) > 0) {
      connected = mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD);
    } else {
      connected = mqtt.connect(clientId.c_str());
    }

    if (connected) {
      Serial.println("MQTT connected");
      mqtt.subscribe(topic("remote/command").c_str());
      mqtt.subscribe(topic("control").c_str());
      mqtt.subscribe(topic("setpoint").c_str());
      publishRemoteState();
    } else {
      Serial.print("MQTT failed, rc=");
      Serial.println(mqtt.state());
      delay(2000);
    }
  }
}

void publishTelemetry() {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();

  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("DHT11 read failed");
    return;
  }

  StaticJsonDocument<384> doc;
  doc["temperature"] = round(temperature * 100) / 100.0;
  doc["humidity"] = round(humidity * 100) / 100.0;
  doc["motion"] = false;
  doc["ac_on"] = acOn;
  doc["set_temperature"] = targetTemperature;
  doc["mode"] = acMode;
  doc["fan"] = fanMode;
  doc["swing"] = swingMode;
  doc["eco"] = ecoMode;
  doc["actuator"] = "sharp_ir";
  doc["source"] = "esp32-dht11-sharp-ir";

  char payload[384];
  serializeJson(doc, payload);
  mqtt.publish(topic("telemetry").c_str(), payload, false);

  Serial.print("Telemetry: ");
  Serial.println(payload);
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  sharpAc.begin();
  sharpAc.setModel(SHARP_REMOTE_MODEL);
  applySharpSettings();

  connectWiFi();
  wifiClient.setInsecure();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(handleMqttMessage);
  connectMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (!mqtt.connected()) {
    connectMqtt();
  }

  mqtt.loop();

  unsigned long now = millis();
  if (now - lastTelemetryAt >= TELEMETRY_INTERVAL_MS || lastTelemetryAt == 0) {
    lastTelemetryAt = now;
    publishTelemetry();
  }
}
