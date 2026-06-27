  #include <Arduino.h>
  #include <ESP8266WiFi.h>
  #include <WiFiClientSecure.h>
  #include <PubSubClient.h>
  #include <ArduinoJson.h>
  #include <DHT.h>
  #include <IRremoteESP8266.h>
  #include <ir_Sharp.h>

  // WiFi
  const char* WIFI_SSID = "ABAH_UNI 1 BAWAH";
  const char* WIFI_PASSWORD = "793793Rr";

  // HiveMQ Cloud MQTT TLS
  const char* MQTT_HOST = "432bb18e49e24068802ceaaf02694995.s1.eu.hivemq.cloud";
  const uint16_t MQTT_PORT = 8883;
  const char* MQTT_USER = "ISI_USERNAME_HIVEMQ";
  const char* MQTT_PASSWORD = "ISI_PASSWORD_HIVEMQ";
  const char* BASE_TOPIC = "campus/ac";

  // Hardware NodeMCU / ESP8266
  const uint16_t IR_LED_PIN = D2; // D2 = GPIO4, IR transmitter to Sharp AC
  const uint8_t DHT_PIN = D5;     // D5 = GPIO14, DHT11 data pin
  const uint8_t DHT_TYPE = DHT11;
  const sharp_ac_remote_model_t SHARP_REMOTE_MODEL = sharp_ac_remote_model_t::A907;

  const unsigned long TELEMETRY_INTERVAL_MS = 10000;

  WiFiClientSecure wifiClient;
  PubSubClient mqtt(wifiClient);
  DHT dht(DHT_PIN, DHT_TYPE);
  IRSharpAc ac(IR_LED_PIN);

  bool acPower = false;
  bool ecoMode = false;
  int targetTemperature = 24;
  String acMode = "COOL";
  String fanMode = "AUTO";
  String swingMode = "AUTO";
  unsigned long lastCommandId = 0;
  unsigned long lastTelemetryAt = 0;

  String topic(const char* suffix) {
    return String(BASE_TOPIC) + "/" + suffix;
  }

  void connectWiFi();
  void connectMqtt();
  void handleMqttMessage(char* rawTopic, byte* payload, unsigned int length);
  void applySharpSettings();
  void sendSharpCommand(const char* reason);
  void publishTelemetry();
  void publishState(const char* reason);

  void setup() {
    Serial.begin(115200);
    delay(200);

    dht.begin();
    ac.begin();
    ac.setModel(SHARP_REMOTE_MODEL);
    applySharpSettings();

    connectWiFi();

    // For class/demo simplicity. For production, install HiveMQ root CA instead.
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

  void connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }
    Serial.println();
    Serial.print("WiFi connected. IP: ");
    Serial.println(WiFi.localIP());
  }

  void connectMqtt() {
    while (!mqtt.connected()) {
      String clientId = "esp8266-sharp-ac-" + String(ESP.getChipId(), HEX);

      Serial.print("Connecting to HiveMQ as ");
      Serial.println(clientId);

      bool ok = mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD);
      if (ok) {
        Serial.println("MQTT connected");
        mqtt.subscribe(topic("remote/command").c_str());
        publishState("mqtt connected");
      } else {
        Serial.print("MQTT failed, rc=");
        Serial.println(mqtt.state());
        delay(3000);
      }
    }
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
      if (!doc["command_id"].is<unsigned long>()) {
        Serial.println("Ignored command without command_id");
        return;
      }

      unsigned long commandId = doc["command_id"].as<unsigned long>();
      if (commandId <= lastCommandId) {
        Serial.println("Ignored duplicate or old command_id");
        return;
      }
      lastCommandId = commandId;

      if (doc["power"].is<bool>()) {
        acPower = doc["power"].as<bool>();
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
      publishState("remote command");
      return;
    }
  }

  void applySharpSettings() {
    ac.setTemp(targetTemperature);
    ac.setEconoToggle(ecoMode);

    if (acMode == "AUTO") {
      ac.setMode(kSharpAcAuto);
    } else if (acMode == "DRY") {
      ac.setMode(kSharpAcDry);
    } else {
      ac.setMode(kSharpAcCool);
    }

    if (fanMode == "LOW") {
      ac.setFan(kSharpAcFanMin);
    } else if (fanMode == "MED") {
      ac.setFan(kSharpAcFanMed);
    } else if (fanMode == "MAX") {
      ac.setFan(kSharpAcFanMax);
    } else {
      ac.setFan(kSharpAcFanAuto);
    }

    if (swingMode == "HIGH") {
      ac.setSwingV(kSharpAcSwingVHigh, true);
    } else if (swingMode == "MID") {
      ac.setSwingV(kSharpAcSwingVMid, true);
    } else if (swingMode == "LOW") {
      ac.setSwingV(kSharpAcSwingVLow, true);
    } else if (swingMode == "LOWEST") {
      ac.setSwingV(kSharpAcSwingVLowest, true);
    } else {
      ac.setSwingV(kSharpAcSwingVToggle, true);
    }

    if (acPower) {
      ac.on();
    } else {
      ac.off();
    }
  }

  void sendSharpCommand(const char* reason) {
    applySharpSettings();
    ac.send();
    Serial.print("Sharp AC IR sent: ");
    Serial.println(reason);
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
    doc["ac_on"] = acPower;
    doc["set_temperature"] = targetTemperature;
    doc["mode"] = acMode;
    doc["fan"] = fanMode;
    doc["swing"] = swingMode;
    doc["eco"] = ecoMode;
    doc["actuator"] = "sharp_ir";
    doc["source"] = "esp8266-dht11-sharp-ir";

    char json[384];
    serializeJson(doc, json);
    mqtt.publish(topic("telemetry").c_str(), json, false);

    Serial.print("Telemetry: ");
    Serial.println(json);
  }

  void publishState(const char* reason) {
    StaticJsonDocument<384> doc;
    doc["power"] = acPower;
    doc["temperature"] = targetTemperature;
    doc["mode"] = acMode;
    doc["fan"] = fanMode;
    doc["swing"] = swingMode;
    doc["eco"] = ecoMode;
    doc["actuator"] = "sharp_ir";
    doc["reason"] = reason;

    char json[384];
    serializeJson(doc, json);
    mqtt.publish(topic("remote/state").c_str(), json, true);
    mqtt.publish(topic("status").c_str(), json, true);
  }
