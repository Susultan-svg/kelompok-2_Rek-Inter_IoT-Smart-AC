#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <IRremoteESP8266.h>
#include <ir_Sharp.h>

// ESP32 GPIO. Jika wiring berbeda, ubah angka ini.
const uint16_t IR_LED_PIN = 4;
const uint8_t DHT_PIN = 14;
const uint8_t DHT_TYPE = DHT11;
const sharp_ac_remote_model_t SHARP_REMOTE_MODEL = sharp_ac_remote_model_t::A907;

const unsigned long TELEMETRY_INTERVAL_MS = 5000;

DHT dht(DHT_PIN, DHT_TYPE);
IRSharpAc ac(IR_LED_PIN);

bool acPower = false;
bool ecoMode = false;
int targetTemperature = 24;
String acMode = "COOL";
unsigned long lastTelemetryAt = 0;

void applySharpSettings() {
  ac.setModel(SHARP_REMOTE_MODEL);
  ac.setTemp(targetTemperature);
  ac.setEconoToggle(ecoMode);
  ac.setMode(kSharpAcCool);
  ac.setFan(kSharpAcFanAuto);
  ac.setSwingV(kSharpAcSwingVToggle, true);

  if (acPower) {
    ac.on();
  } else {
    ac.off();
  }
}

void sendSharpCommand(const char* reason) {
  applySharpSettings();
  ac.send();

  StaticJsonDocument<160> doc;
  doc["event"] = "ir_sent";
  doc["reason"] = reason;
  doc["ac_status"] = acPower ? "ON" : "OFF";
  doc["target_temp"] = targetTemperature;
  serializeJson(doc, Serial);
  Serial.println();
}

void publishSerialTelemetry() {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();

  StaticJsonDocument<192> doc;
  doc["type"] = "telemetry";

  if (isnan(temperature) || isnan(humidity)) {
    doc["dht_ok"] = false;
  } else {
    doc["dht_ok"] = true;
    doc["suhu"] = temperature;
    doc["kelembaban"] = humidity;
  }

  doc["ac_status"] = acPower ? "ON" : "OFF";
  doc["target_temp"] = targetTemperature;

  serializeJson(doc, Serial);
  Serial.println();
}

void handleSerialCommand(const String& line) {
  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, line);

  if (error) {
    StaticJsonDocument<96> err;
    err["error"] = "invalid_json";
    serializeJson(err, Serial);
    Serial.println();
    return;
  }

  String command = doc["command"] | "";
  command.toUpperCase();

  if (command == "ON") {
    acPower = true;
    sendSharpCommand("serial_on");
  } else if (command == "OFF") {
    acPower = false;
    sendSharpCommand("serial_off");
  } else if (command == "SET_TEMP") {
    int temp = doc["temperature"] | targetTemperature;
    targetTemperature = constrain(temp, 16, 30);
    sendSharpCommand("serial_set_temp");
  } else {
    StaticJsonDocument<96> err;
    err["error"] = "unknown_command";
    serializeJson(err, Serial);
    Serial.println();
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  dht.begin();
  ac.begin();
  applySharpSettings();

  StaticJsonDocument<128> doc;
  doc["event"] = "boot";
  doc["device"] = "esp32_serial_executor";
  serializeJson(doc, Serial);
  Serial.println();
}

void loop() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      handleSerialCommand(line);
    }
  }

  unsigned long now = millis();
  if (lastTelemetryAt == 0 || now - lastTelemetryAt >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryAt = now;
    publishSerialTelemetry();
  }
}
