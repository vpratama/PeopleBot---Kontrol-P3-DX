
import os
import pika
import serial
import time
import random
from dotenv import load_dotenv

# Muat variabel lingkungan dari file .env
load_dotenv()

# --- Konfigurasi Serial Port ---
# Ambil nilai dari file .env dengan fallback default jika tidak ada
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
SERIAL_BAUDRATE = int(os.getenv('SERIAL_BAUDRATE', '9600'))

# --- Konfigurasi RabbitMQ ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASSWORD = os.getenv('RABBITMQ_PASSWORD', 'guest')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST', '/')
RABBITMQ_QUEUE_SENSOR = os.getenv('RABBITMQ_QUEUE_SENSOR', 'sensor')

# --- Simulasi Data Sonar ---
# Pioneer P3-DX biasanya memiliki 8 atau 16 sensor sonar. Kita akan simulasikan 8 sensor.
# Data sonar biasanya dalam milimeter atau sentimeter. Kita akan gunakan milimeter.
# Jangkauan sonar tipikal: 0mm - 5000mm (5 meter)
NUM_SONAR_SENSORS = 8
MIN_RANGE_MM = 150  # Jarak minimum yang bisa dideteksi sonar (sekitar 15cm)
MAX_RANGE_MM = 5000 # Jarak maksimum yang bisa dideteksi sonar (sekitar 5 meter)

def simulate_sonar_data():
    """Menghasilkan data sonar simulasi untuk 8 sensor."""
    data = []
    for _ in range(NUM_SONAR_SENSORS):
        # Simulasikan variasi jarak antar sensor
        range_mm = random.randint(MIN_RANGE_MM, MAX_RANGE_MM)
        data.append(range_mm)
    return data

def parse_sip_packet(raw_data):
    """Fungsi placeholder untuk parsing paket SIP (Serial Interface Protocol).
    Dalam implementasi nyata, ini akan jauh lebih kompleks dan spesifik terhadap format SIP.
    Untuk simulasi, kita asumsikan raw_data sudah berupa list integer jarak sonar.
    """
    # Asumsi: raw_data adalah string yang berisi nilai-nilai sonar yang dipisahkan koma
    # Contoh: "1234,2345,3456,4567,1234,2345,3456,4567\n"
    try:
        sonar_values_str = raw_data.strip().split(',')
        sonar_values_int = [int(s) for s in sonar_values_str]
        if len(sonar_values_int) == NUM_SONAR_SENSORS:
            return sonar_values_int
        else:
            print(f"[ERROR] Jumlah sensor tidak sesuai: {len(sonar_values_int)} ditemukan, {NUM_SONAR_SENSORS} diharapkan.")
            return None
    except ValueError:
        print(f"[ERROR] Gagal parsing data: {raw_data}")
        return None
    except Exception as e:
        print(f"[ERROR] Terjadi kesalahan saat parsing: {e}")
        return None

def display_sonar_data(sonar_readings):
    """Menampilkan pembacaan sonar dalam format 360 derajat sederhana."""
    if sonar_readings:
        print("\n--- Pembacaan Sensor Sonar 360° ---")
        # Asumsi sensor 0 adalah depan, dan berurutan searah jarum jam
        # Ini adalah representasi visual yang sangat sederhana
        sensor_angles = [
            "Depan (0°)", "Depan-Kanan (45°)", "Kanan (90°)", "Belakang-Kanan (135°)",
            "Belakang (180°)", "Belakang-Kiri (225°)", "Kiri (270°)", "Depan-Kiri (315°)"
        ]
        for i, distance in enumerate(sonar_readings):
            print(f"Sensor {i+1} ({sensor_angles[i]}): {distance} mm")
    else:
        print("Tidak ada data sonar untuk ditampilkan.")


def connect_rabbitmq():
    """Membuka koneksi RabbitMQ berdasarkan konfigurasi dari .env."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            virtual_host=RABBITMQ_VHOST,
            credentials=credentials
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue=RABBITMQ_QUEUE_SENSOR, durable=True, auto_delete=False)
    print(f"[RABBITMQ] Terhubung ke {RABBITMQ_HOST}:{RABBITMQ_PORT} vhost={RABBITMQ_VHOST} queue={RABBITMQ_QUEUE_SENSOR}")
    return connection, channel


def publish_sensor_data(channel, sonar_readings):
    """Mengirim data sensor ke queue RabbitMQ dalam format S1,S2,...,S8."""
    if not sonar_readings:
        return

    payload = ','.join(map(str, sonar_readings))
    channel.basic_publish(
        exchange='',
        routing_key=RABBITMQ_QUEUE_SENSOR,
        body=payload,
        properties=pika.BasicProperties(delivery_mode=2)
    )
    print(f"[RABBITMQ] Data sensor terkirim ke queue '{RABBITMQ_QUEUE_SENSOR}': {payload}")


def main():
    print(f"Mencoba membuka port serial: {SERIAL_PORT} dengan baud rate: {SERIAL_BAUDRATE}")
    connection = None
    channel = None

    try:
        connection, channel = connect_rabbitmq()

        # Untuk simulasi, kita tidak benar-benar membuka port serial fisik.
        # Jika Anda memiliki robot, uncomment baris di bawah ini dan comment bagian simulasi.
        # ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
        # print("Port serial berhasil dibuka.")

        while True:
            # --- Bagian Simulasi (Ganti dengan pembacaan serial nyata jika terhubung ke robot) ---
            simulated_raw_data = ','.join(map(str, simulate_sonar_data())) + '\n'
            print(f"[SIMULASI] Menerima data mentah: {simulated_raw_data.strip()}")

            # Dalam skenario nyata, Anda akan membaca dari serial port seperti ini:
            # raw_data = ser.readline().decode('utf-8') # Sesuaikan decoding jika perlu
            # if raw_data:
            #     sonar_readings = parse_sip_packet(raw_data)
            #     display_sonar_data(sonar_readings)
            # else:
            #     print("Menunggu data dari robot...")

            sonar_readings = parse_sip_packet(simulated_raw_data)
            display_sonar_data(sonar_readings)
            publish_sensor_data(channel, sonar_readings)

            time.sleep(1) # Tunggu 1 detik sebelum pembacaan berikutnya

    except serial.SerialException as e:
        print(f"[ERROR] Gagal membuka atau berkomunikasi dengan port serial: {e}")
        print("Pastikan robot terhubung, driver terinstal, dan port serial sudah benar.")
        print("Di Linux, Anda mungkin perlu menambahkan user ke grup 'dialout': sudo usermod -a -G dialout $USER")
    except KeyboardInterrupt:
        print("Program dihentikan oleh pengguna.")
    except Exception as e:
        print(f"[ERROR] Terjadi kesalahan tak terduga: {e}")
    finally:
        if connection and connection.is_open:
            connection.close()
            print("[RABBITMQ] Koneksi ditutup.")

        # Jika menggunakan serial port nyata, pastikan untuk menutupnya
        # if 'ser' in locals() and ser.is_open:
        #     ser.close()
        #     print("Port serial ditutup.")

if __name__ == "__main__":
    main()
