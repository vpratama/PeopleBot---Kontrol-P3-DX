# Panduan Sensor 360° Pioneer P3-DX

Dokumen ini menjelaskan arsitektur pembacaan sensor 360° pada project PeopleBot - Kontrol P3-DX yang saat ini ada di workspace.

## 1. Gambaran umum

Project saat ini menggunakan kombinasi:
- serial port untuk menghubungkan ke robot atau mensimulasikan data sensor
- RabbitMQ untuk saluran data antar proses
- GUI Python untuk menampilkan pembacaan sensor secara real-time

File yang relevan:
- `p3dx_sensor_reader.py` — membangkitkan atau menerima data sensor dan mengirimnya ke RabbitMQ
- `sensor_gui.py` — membaca data sensor dari RabbitMQ dan menampilkannya dalam visualisasi 360°

## 2. Format data sensor

Data yang dikirim ke queue sensor memiliki format:

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

Konfigurasi koneksi RabbitMQ diambil dari file `.env` yang dibuat dari template `.env.example`.

Contoh template yang dipakai project:

```dotenv
RABBITMQ_HOST=localhost
RABBITMQ_QUEUE_SENSOR=sensor
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_VHOST=/
```

Queue sensor dibuat dengan pengaturan:
- `durable=True`
- `auto_delete=True`

## 4. Alur kerja saat ini

1. `p3dx_sensor_reader.py` menghasilkan data sensor atau menerima dari serial.
2. Data sensor diubah menjadi string berformat CSV `S1,S2,...,S8`.
3. String dikirim ke queue RabbitMQ bernama `RABBITMQ_QUEUE_SENSOR`.
4. `sensor_gui.py` menerima pesan dan menunjukkan plot radar 360° secara real-time.

## 5. Cara menjalankan

1. Salin `.env.example` ke `.env` jika belum dibuat.
2. Sesuaikan nilai koneksi yang diperlukan.
3. Jalankan program:

```powershell
python p3dx_sensor_reader.py
python sensor_gui.py
```

## 6. Catatan implementasi

- Untuk saat ini, pembacaan sensor bersifat simulasi secara default.
- Jika robot fisik digunakan, bagian serial di `p3dx_sensor_reader.py` dapat diaktifkan kembali.
- Nilai sensor dikonversi ke rentang visual koordinat untuk menampilkan jarak pada radar 360° di GUI.
