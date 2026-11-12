# Panduan Sensor 360° Pioneer P3-DX

Dokumen ini menjelaskan arsitektur pembacaan sensor 360° pada project PeopleBot - Kontrol P3-DX yang saat ini ada di workspace.

## 1. Gambaran umum

Project saat ini menggunakan kombinasi:
- serial port untuk menghubungkan ke robot atau menerima baris data sensor
- MQTT melalui WebSocket TLS untuk mengirimkan data sensor ke broker RabbitMQ
- GUI Python untuk menampilkan pembacaan sensor secara real-time

File yang relevan:
- `p3dx_control_python3.py` — menerbitkan data sensor simulasi atau data CSV dari serial ke MQTT saat kontrol robot berjalan
- `p3dx_sensor_reader.py` — pembaca sensor mandiri dengan fungsi publikasi MQTT yang sama
- `sensor_gui.py` — membaca data sensor dari RabbitMQ dan menampilkannya dalam visualisasi 360°

## 2. Format data sensor

Payload yang diterbitkan ke topik MQTT `sensor` memiliki format:

```text
S1,S2,S3,S4,S5,S6,S7,S8
```

Keterangan:
- `S1` = Depan (0°)
- `S2` = Depan-Kanan (45°)
- `S3` = Kanan (90°)
- `S4` = Belakang-Kanan (135°)
- `S5` = Belakang (180°)
- `S6` = Belakang-Kiri (225°)
- `S7` = Kiri (270°)
- `S8` = Depan-Kiri (315°)

## 3. Konfigurasi RabbitMQ

Konfigurasi koneksi RabbitMQ Web MQTT diambil dari file `.env` yang dibuat dari template `.env.example`.

Contoh template yang dipakai project:

```dotenv
RABBITMQ_MQTT_HOST=mqtt.luminaire.software
RABBITMQ_MQTT_PORT=443
RABBITMQ_MQTT_PATH=/ws
RABBITMQ_MQTT_TOPIC=sensor
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
```

Koneksi menggunakan WSS ke `wss://mqtt.luminaire.software:443/ws`. Kredensial memakai `RABBITMQ_USER` dan `RABBITMQ_PASSWORD`.

## 4. Alur kerja saat ini

1. `p3dx_control_python3.py` menghasilkan data simulasi atau membaca delapan nilai CSV dari serial. `p3dx_sensor_reader.py` dapat digunakan sendiri untuk alur sensor terpisah.
2. Data sensor diubah menjadi string berformat CSV `S1,S2,...,S8`.
3. String diterbitkan ke topik MQTT `RABBITMQ_MQTT_TOPIC`.
4. `sensor_gui.py` menerima pesan dan menunjukkan plot radar 360° secara real-time.

## 5. Cara menjalankan

1. Salin `.env.example` ke `.env` jika belum dibuat.
2. Sesuaikan nilai koneksi yang diperlukan.
3. Jalankan kontrol robot. Script ini juga menerbitkan data sensor berdasarkan `SENSOR_SIMULATION`:

```powershell
python p3dx_control_python3.py
```

Untuk menjalankan pembaca sensor mandiri, hentikan publisher sensor pada kontrol robot terlebih dahulu, lalu jalankan:

```powershell
python p3dx_sensor_reader.py
python sensor_gui.py
```

## 6. Catatan implementasi

- `SENSOR_SIMULATION=true` menerbitkan data sensor acak setiap detik.
- Dengan `SENSOR_SIMULATION=false`, kontrol robot menerbitkan baris serial yang berisi delapan nilai CSV.
- Jangan jalankan dua publisher sensor bersamaan karena keduanya mengirim ke topik `sensor`.
- Nilai sensor dikonversi ke rentang visual koordinat untuk menampilkan jarak pada radar 360° di GUI.
