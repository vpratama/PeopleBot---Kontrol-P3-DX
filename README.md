# PeopleBot - Kontrol P3-DX

Project ini berisi beberapa script Python untuk mengendalikan robot Pioneer P3-DX dan memantau sensor sonar 360° melalui RabbitMQ.

## Ringkasan file
- `p3dx_control.py` — konsumsi perintah kontrol dari RabbitMQ dan mengirimkan paket ke robot melalui serial.
- `remote_control.py` — antarmuka keyboard lokal yang mengirimkan perintah ke RabbitMQ.
- `p3dx_sensor_reader.py` — membaca data sensor simulasi atau data serial, lalu mengirim hasilnya ke queue `sensor` di RabbitMQ.
- `sensor_gui.py` — aplikasi GUI Python untuk membaca data sensor dari RabbitMQ dan menampilkannya dalam visualisasi radar 360° secara real-time.

## Persyaratan
- Python 3.8+
- RabbitMQ yang berjalan dan dapat diakses dari host yang dikonfigurasi
- Paket Python berikut terdaftar di `requirements.txt`:
  - `pika`
  - `python-dotenv`
  - `pyserial`

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

RABBITMQ_HOST=localhost
RABBITMQ_QUEUE=control
RABBITMQ_QUEUE_SENSOR=sensor
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_VHOST=/
```

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
python p3dx_control.py
```

6. Jalankan remote controller untuk mengirim perintah:

```powershell
python remote_control.py
```

7. Jalankan pembaca sensor dan GUI visualisasi:

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
`p3dx_sensor_reader.py` mengirim data sensor ke queue `sensor` dengan format:

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
- Queue kontrol dan queue sensor dibuat melalui konfigurasi RabbitMQ di `.env`.
- Queue sensor pada script saat ini menggunakan `durable=True` dan `auto_delete=True`.
- GUI sensor dibuat sebagai visualisasi real-time berbasis Tkinter tanpa membutuhkan library tambahan selain dependensi yang sudah ada.
