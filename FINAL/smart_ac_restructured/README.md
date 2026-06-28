# Smart AC Restructured

Versi ini memisahkan tugas sesuai arsitektur proyek:

- `esp32/smart_ac_serial_executor.ino`
  - membaca DHT11
  - mengontrol AC Sharp lewat LED infrared
  - mengirim telemetry JSON ke Raspberry Pi lewat USB serial
  - menerima command JSON dari Raspberry Pi lewat USB serial
  - tidak memakai WiFi dan tidak publish MQTT

- `raspberry/edge_gateway.py`
  - membaca serial dari ESP32
  - melakukan face detection dari kamera USB setiap 10 detik
  - menjalankan mode otomatis/manual
  - publish telemetry/status ke HiveMQ
  - subscribe command dari web via HiveMQ
  - mengirim command AC ke ESP32 lewat serial

- `web/app.py`
  - dashboard/API cloud
  - autentikasi JWT
  - subscribe data dari MQTT over WebSocket
  - simpan data sensor ke PostgreSQL
  - publish command/mode/setpoint ke Raspberry Pi via MQTT
  - tidak membuka kamera dan tidak membaca serial

## MQTT Transport

- Web Flask/Railway memakai MQTT over WebSocket TLS:
  - `MQTT_TRANSPORT=websockets`
  - `MQTT_PORT=8884`
  - `MQTT_WEBSOCKET_PATH=/mqtt`
- Raspberry Pi tetap memakai MQTT TLS biasa:
  - `MQTT_PORT=8883`

## Topic MQTT

```text
home/ac/telemetry       Raspberry -> Web
home/ac/status          Raspberry -> Web
home/ac/presence        Raspberry -> Web
home/ac/command         Web -> Raspberry
home/ac/mode            Web -> Raspberry
home/ac/setpoint        Web -> Raspberry
```

## Payload Utama

Telemetry:

```json
{
  "suhu": 25.5,
  "kelembaban": 60.0,
  "presence": true,
  "ac_status": "ON",
  "mode": "AUTO",
  "setpoint": 24,
  "esp32_status": "ONLINE"
}
```

Command:

```json
{"command": "ON"}
{"command": "OFF"}
{"command": "SET_TEMP", "temperature": 24}
```

Mode:

```json
{"mode": "AUTO"}
{"mode": "MANUAL"}
```

Setpoint:

```json
{"setpoint": 24}
```

## Catatan Penting

- Pada mode `AUTO`, Raspberry membaca kamera setiap 10 detik. Jika tidak ada orang selama 5 menit, AC dimatikan. Jika ada orang dan AC masih mati, AC dinyalakan. Jika AC sudah menyala, Raspberry tidak mengubah status ON/OFF.
- Status `presence` dibuat stabil: jika kamera sesekali gagal membaca wajah, status tidak langsung berubah ke `Tidak`; harus tidak terdeteksi sekitar 30 detik dulu.
- Pada mode `MANUAL`, Raspberry tidak boleh mematikan/menyalakan AC berdasarkan kamera; Raspberry hanya meneruskan command dari web ke ESP32.
- Frame kamera tidak disimpan ke database. Hasil kamera hanya dipakai untuk status `presence`.
