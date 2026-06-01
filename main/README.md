# Sistem IoT AC Control dan Monitoring

Proyek ini adalah prototipe sistem kontrol AC cerdas berbasis IoT sesuai PPT kelompok: ESP8266 membaca sensor, MQTT mengirim data real-time, Flask menampilkan dashboard, dan SQLite menyimpan histori data untuk analisis energi.

## Fitur

- Monitoring suhu, kelembapan, dan status AC Sharp.
- Kontrol AC manual dari dashboard melalui MQTT.
- Kontrol AC manual dari web untuk tahap prototipe awal.
- Database SQLite untuk histori sensor, event kontrol, dan ringkasan energi harian.
- Grafik real-time berbasis HTML/CSS/JS tanpa CDN.
- Simulator data MQTT untuk pengujian tanpa hardware.
- Firmware ESP8266 untuk DHT11 dan IR transmitter AC Sharp tanpa Blynk.

## Arsitektur

```text
ESP8266 + DHT11 + IR LED Sharp AC
        |
        | MQTT publish/subscribe
        v
MQTT Broker Mosquitto
        |
        v
Flask App + SQLite
        |
        v
Dashboard Browser
```

## Topik MQTT

Base topic default: `campus/ac`

Konfigurasi broker saat ini disiapkan untuk HiveMQ Cloud:

```text
Host: 432bb18e49e24068802ceaaf02694995.s1.eu.hivemq.cloud
Port MQTT TLS: 8883
Port WebSocket TLS: 8884
```

ESP8266 memakai MQTT TLS port `8883`. Backend Flask/web app dapat memakai WebSocket TLS port `8884` dengan path `/mqtt`, sesuai `.env.example`. Isi `MQTT_USERNAME` dan `MQTT_PASSWORD` di `.env`, lalu isi juga `MQTT_USER` dan `MQTT_PASSWORD` di firmware ESP8266 sesuai credential dari HiveMQ Cloud.

- `campus/ac/telemetry` untuk data gabungan JSON dari ESP8266.
- `campus/ac/status` untuk status AC.
- `campus/ac/control` untuk perintah ON/OFF.
- `campus/ac/setpoint` untuk target suhu.
- `campus/ac/mode` untuk mode `auto` atau `manual`.
- `campus/ac/remote/command` untuk remote AC Sharp sesuai program ESP/Blynk.
- `campus/ac/remote/state` untuk state remote terakhir, memakai retained message.

Contoh payload telemetry:

```json
{
  "temperature": 27.5,
  "humidity": 61.2,
  "motion": false,
  "ac_on": true,
  "set_temperature": 24,
  "actuator": "sharp_ir",
  "source": "esp32-dht11-sharp-ir"
}
```

Payload remote AC Sharp dari web:

```json
{
  "command_id": 1717240000000,
  "source": "flask_dashboard",
  "power": true,
  "temperature": 24,
  "mode": "COOL",
  "fan": "AUTO",
  "swing": "AUTO",
  "eco": false
}
```

Mapping ke program ESP yang kamu lampirkan:

- `power` sama seperti Blynk `V0`.
- `eco` sama seperti Blynk `V1`.
- `mode` sama seperti tombol `V2`: `COOL`, `AUTO`, `DRY`.
- `fan` sama seperti tombol `V3`: `AUTO`, `LOW`, `MED`, `MAX`.
- `swing` sama seperti tombol `V4`: `AUTO`, `HIGH`, `MID`, `LOW`, `LOWEST`.
- `temperature` sama seperti `V5`, `V6`, dan tampilan `V8`, rentang 16-30 derajat.
- `command_id` wajib ada agar ESP8266 mengabaikan retained/command lama yang tidak sengaja tersimpan di broker.

Catatan penting: program ESP lampiran masih memakai Blynk, belum subscribe MQTT. Web ini sudah mengirim MQTT dan menyimpan SQL, tetapi ESP perlu ditambah library MQTT seperti `PubSubClient` agar menerima `campus/ac/remote/command`.

## Cara Menjalankan

1. Buat virtual environment dan install dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Jalankan broker MQTT, misalnya Mosquitto:

```powershell
mosquitto -v
```

3. Salin konfigurasi:

```powershell
Copy-Item .env.example .env
```

Default database berada di `data/ac_iot.db`. Koneksi SQLite memakai journal mode `OFF` agar prototipe tetap bisa berjalan di folder OneDrive. Untuk deployment server/cloud, pakai disk normal dan ubah journal mode ke WAL/DELETE di [ac_iot/db.py](C:/Users/ASUS/OneDrive/Documents/Kode_Proyek Rek.%20Inter/ac_iot/db.py).

4. Jalankan Flask:

```powershell
python app.py
```

5. Buka dashboard:

```text
http://127.0.0.1:5000
```

6. Untuk uji tanpa ESP32, jalankan simulator di terminal lain:

```powershell
python simulator.py
```

## Firmware ESP8266

Kode Arduino ada di:

```text
firmware/esp8266_sharp_blynk_mqtt_dht11/esp8266_sharp_blynk_mqtt_dht11.ino
```

Library Arduino yang dibutuhkan:

- WiFi
- WiFiClientSecure
- PubSubClient
- ArduinoJson
- DHT sensor library
- IRremoteESP8266

Sesuaikan Wi-Fi, alamat broker MQTT, pin DHT11, dan pin IR transmitter pada file firmware.

## Catatan Hardware

Versi ESP8266 / NodeMCU:

- DHT11 dipasang ke pin `D5` atau GPIO14 untuk suhu dan kelembapan.
- IR LED/transmitter dipasang ke pin `D2` atau GPIO4 untuk mengirim command remote AC Sharp.
- Pendeteksian manusia/PIR belum dipakai pada tahap simplifikasi ini.
- PZEM dan relay belum dipakai pada tahap simplifikasi ini.

Migrasi Raspberry Pi:

- Backend Flask, SQLite, dashboard, dan MQTT topic tetap sama.
- Ganti firmware ESP32 dengan script Python GPIO untuk PIR/relay, ADC eksternal untuk LM35, UART PZEM, dan IR transmitter.
