# -*- coding: utf-8 -*-
import serial
import time
import struct

# Tentukan port serial sesuai konfigurasi Anda
SERIAL_PORT = 'COM5' 
BAUD_RATE = 9600  # Baud rate default untuk P3DX/ARCOS

def calculate_checksum(data):
    """Menghitung checksum 2-byte standar ARCOS (Kompatibel Python 2.7)."""
    c = 0
    i = 0
    length = len(data)
    while i < length - 1:
        c += (ord(data[i]) << 8) | ord(data[i+1])
        c = c & 0xFFFF
        i += 2
    if i < length:
        c += ord(data[i]) << 8
        c = c & 0xFFFF
    return struct.pack('>H', c)

def build_packet(cmd, arg):
    """Membangun paket biner ARCOS menggunakan string biner Python 2.7."""
    packet_body = chr(cmd) + chr(0x3B) + chr(arg & 0xFF) + chr((arg >> 8) & 0xFF)
    byte_count = len(packet_body) + 2 
    header = chr(0xFA) + chr(0xFB) + chr(byte_count)
    full_payload = packet_body
    checksum = calculate_checksum(full_payload)
    return header + full_payload + checksum

def parse_sonar_data(packet_body):
    """
    Memparsing paket data untuk mengambil nilai sensor sonar.
    Format SIP Standar ARCOS/P2OS:
    - Byte 0: ID Paket (Biasanya 0x32 atau 0x5C untuk baris sonar tambahan)
    - Pada SIP standar (0x32), jumlah membaca sonar ada di byte urutan ke-23.
    """
    if len(packet_body) < 3:
        return

    packet_type = ord(packet_body[0])
    
    # 1. SIP Standar (0x32) umumnya membawa data sonar utama (sampai 16 sonar)
    if packet_type == 0x32:
        # Offset standar ARCOS: Jumlah sonar berada di byte indeks ke-23
        if len(packet_body) > 23:
            num_sonars = ord(packet_body[23])
            
            if num_sonars > 0:
                print("\n--- DATA SENSOR SONAR ---")
                # Data sonar dimulai dari byte indeks ke-24
                # Tiap sonar berukuran 3 byte: 1 byte nomor sensor, 2 byte nilai jarak (Little Endian)
                current_idx = 24
                
                for s in range(num_sonars):
                    if current_idx + 3 <= len(packet_body):
                        sonar_id = ord(packet_body[current_idx])
                        # Membaca nilai jarak 2 byte integer (Little Endian)
                        distance = ord(packet_body[current_idx+1]) | (ord(packet_body[current_idx+2]) << 8)
                        
                        print("Sonar #%d: %d mm" % (sonar_id, distance))
                        current_idx += 3
                print("-------------------------")

try:
    # 1. Membuka koneksi serial
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print("Terhubung ke robot pada port", SERIAL_PORT)
    time.sleep(1) 

    # 2. Kirim perintah OPEN (Command #1) untuk memulai sesi komunikasi
    open_packet = build_packet(1, 0)
    ser.write(open_packet)
    print("Sesi komunikasi dibuka (Command OPEN dikirim).")
    time.sleep(0.5)

    # 3. Kirim perintah SONAR Enable (Command #28, Argumen = 1)
    sonar_enable_packet = build_packet(28, 1)
    ser.write(sonar_enable_packet)
    print("Perintah aktivasi SONAR berhasil dikirim!")

    # 4. Membaca data SIP (Server Information Packet) secara berkala
    print("Membaca aliran data sensor (Tekan Ctrl+C untuk berhenti)...")
    while True:
        if ser.in_waiting > 0:
            header = ser.read(2)
            if header == '\xfa\xfb':
                length = ord(ser.read(1))
                packet_data = ser.read(length)
                
                # Panggil fungsi parsing untuk mengekstrak data sonar
                parse_sonar_data(packet_data)
                
        time.sleep(0.05) # Mengurangi delay ke 50ms agar pembacaan lebih responsif

except serial.SerialException as e:
    print("Gagal membuka atau berkomunikasi dengan port serial:", e)
except KeyboardInterrupt:
    print("\nKomunikasi dihentikan oleh pengguna.")
finally:
    if 'ser' in locals() and ser.is_open:
        # Kirim perintah CLOSE sebelum memutus port serial
        close_packet = build_packet(2, 0)
        ser.write(close_packet)
        ser.close()
        print("Port serial ditutup dengan aman.")
