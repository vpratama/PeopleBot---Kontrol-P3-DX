# PeopleBot - Kontrol P3-DX

Deskripsi singkat
- Projek ini berisi dua script Python untuk mengendalikan robot P3-DX melalui RabbitMQ:
  - `p3dx_control.py` - menerima perintah kecepatan (left,right) dari antrian RabbitMQ dan mengirim paket ke robot melalui serial.
  - `remote_control.py` - antarmuka keyboard lokal yang mengirim pasangan kecepatan ke RabbitMQ.

Persyaratan
- Python 3.8+
- RabbitMQ berjalan dan dapat diakses dari host yang dikonfigurasi
- Paket Python diinstal (lihat `requirements.txt`)

Instalasi cepat
1. Salin contoh env dan sesuaikan jika perlu:

```
copy .env.example .env
```

2. (Opsional) Buat virtual environment dan aktifkan:

Windows PowerShell:

```
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

3. Install dependensi:

```
python -m pip install -r requirements.txt
```

Menjalankan
- Jalankan kontrol penerima (jalankan pada mesin yang terhubung ke robot atau serial):

```
python p3dx_control.py
```

- Jalankan antarmuka remote (keyboard) untuk mengirim perintah via RabbitMQ:

```
python remote_control.py
```

Format pesan
- `remote_control.py` mengirim pesan dalam format CSV `left,right` (contoh `100,0`).

Mapping tombol pada `remote_control.py`
- Default: tidak ada pergerakan, skrip terus mengirim `0,0`.
- Tekan angka `1/2/3/4` untuk mengubah magnitude kecepatan (100/200/300/400).
- Tombol gerak (skema saat ini):
  - `w` -> `-speed,-speed` (contoh: `-100,-100`)
  - `a` -> `speed,0` (contoh: `100,0`)
  - `s` -> `0,0` (stop)
  - `d` -> `0,speed` (contoh: `0,100`)
  - `z` -> keluar (quit)

Perilaku penerima di `p3dx_control.py`
- Menerima pasangan `left,right` dari queue RabbitMQ.
- Jika `left==right` maka dianggap gerak lurus (linear velocity = left), tanpa rotasi.
- Jika berbeda, linear diset 0 dan script mengonversi perbedaan menjadi kecepatan rotasi.
- Tekan `z` pada konsol `p3dx_control.py` untuk menghentikan program.

Konfigurasi
- Edit `.env` (atau gunakan `.env.example`) untuk mengatur `SERIAL_PORT`, `RABBITMQ_*` dan `RABBITMQ_VHOST`.

Catatan
- Pastikan nama queue di `.env` sama pada kedua skrip.
- Jika ingin perubahan mapping tombol, sesuaikan `calculate_motor_velocities()` di `remote_control.py`.

Lisensi
- Tidak ditentukan; gunakan sesuai kebutuhan internal.
