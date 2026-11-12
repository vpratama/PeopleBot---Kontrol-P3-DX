# PeopleBot - Kontrol P3-DX

Project ini berisi beberapa script Python untuk mengendalikan robot Pioneer P3-DX dan memantau sensor sonar 360° melalui RabbitMQ. Data sensor diterbitkan ke RabbitMQ menggunakan MQTT melalui WebSocket TLS (WSS).

## Ringkasan file
- `p3dx_control_python3.py` — konsumsi perintah kontrol, mengendalikan robot melalui serial, dan menerbitkan data sensor ke MQTT.
- `p3dx_control.py` — versi kontrol RabbitMQ/serial lama.
- `remote_control.py` — antarmuka keyboard lokal yang mengirimkan perintah ke RabbitMQ.
- `p3dx_sensor_reader.py` — pembaca sensor mandiri yang juga dapat menerbitkan simulasi atau data serial ke topik MQTT `sensor`.
- `sensor_gui.py` — aplikasi GUI Python untuk membaca data sensor dari RabbitMQ dan menampilkannya dalam visualisasi radar 360° secara real-time.

## Persyaratan
- Python 3.8+
- RabbitMQ yang berjalan dan dapat diakses dari host yang dikonfigurasi
- Paket Python berikut terdaftar di `requirements.txt`:
  - `pika`
  - `paho-mqtt`
  - `python-dotenv`
  - `pyserial`
  - `websocket-client`
  - `certifi`

## Konfigurasi lingkungan
Semua skrip sekarang menggunakan file `.env` untuk konfigurasi koneksi serial dan RabbitMQ.

Template konfigurasi tersedia di `.env.example`. Langkah awal yang disarankan:

```powershell
copy .env.example .env
```

Setelah file `.env` dibuat, sesuaikan nilai sesuai mesin atau server RabbitMQ Anda. Contoh variabel yang dipakai oleh project mengikuti isi dari `.env.example`:

```dotenv
SERIAL_PORT=COM3
SERIAL_BAUDRATE=9600

RABBITMQ_HOST=amqp.luminaire.software
RABBITMQ_QUEUE=control
RABBITMQ_WS_URL=wss://amqp.luminaire.software:443/ws
RABBITMQ_MQTT_HOST=mqtt.luminaire.software
RABBITMQ_MQTT_PORT=443
RABBITMQ_MQTT_PATH=/ws
RABBITMQ_MQTT_TOPIC=sensor
RABBITMQ_USER=your_rabbitmq_username
RABBITMQ_PASSWORD=your_rabbitmq_password
RABBITMQ_VHOST=/
```

`p3dx_control_python3.py` menerbitkan pembacaan sensor simulasi atau baris serial berformat CSV delapan angka. `p3dx_sensor_reader.py` tetap tersedia sebagai pembaca mandiri; jalankan salah satu publisher saja agar tidak mengirim data ganda. Keduanya menggunakan `RABBITMQ_MQTT_*`. RabbitMQ Web MQTT memakai endpoint WebSocket `/ws`; koneksi sensor menggunakan `wss://mqtt.luminaire.software:443/ws`. Kredensial MQTT menggunakan `RABBITMQ_USER` dan `RABBITMQ_PASSWORD` yang sama.

## Cara menjalankan

1. Pastikan RabbitMQ sudah aktif.
2. Salin `.env.example` menjadi `.env` jika belum ada.
3. Sesuaikan nilai di `.env`.
4. Install dependensi:

```powershell
python -m pip install -r requirements.txt
```

5. Jalankan konsumer kontrol:

```powershell
./run.sh
```

6. Jalankan remote controller untuk mengirim perintah:

```powershell
python remote_control.py
```

7. Untuk pembacaan sensor mandiri, jalankan pembaca sensor dan GUI. Jangan jalankan pembaca mandiri bersamaan dengan publisher sensor di `p3dx_control_python3.py`:

```powershell
python p3dx_sensor_reader.py
python sensor_gui.py
```

## Format pesan RabbitMQ

### Perintah kontrol
`remote_control.py` mengirim pesan ke queue kontrol dengan format CSV:

```text
left,right
```

Contoh:

```text
100,0
```

### Data sensor
`p3dx_control_python3.py` dan pembaca mandiri `p3dx_sensor_reader.py` menerbitkan data simulasi maupun serial ke topik MQTT `sensor` dengan format payload:

```text
S1,S2,S3,S4,S5,S6,S7,S8
```

Masing-masing nilai mewakili pembacaan sensor 360°:
- `S1` = Depan (0°)
- `S2` = Depan-Kanan (45°)
- `S3` = Kanan (90°)
- `S4` = Belakang-Kanan (135°)
- `S5` = Belakang (180°)
- `S6` = Belakang-Kiri (225°)
- `S7` = Kiri (270°)
- `S8` = Depan-Kiri (315°)

## Catatan
- Perintah kontrol tetap menggunakan queue `RABBITMQ_QUEUE` melalui Web STOMP.
- Data sensor diterbitkan melalui MQTT over WebSocket ke topik `RABBITMQ_MQTT_TOPIC`.
- GUI sensor dibuat sebagai visualisasi real-time berbasis Tkinter tanpa membutuhkan library tambahan selain dependensi yang sudah ada.
