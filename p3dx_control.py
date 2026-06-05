import serial
import time
import sys
import threading
import platform
import pika
import json
import os
from dotenv import load_dotenv

# Muat variabel lingkungan dari file .env
load_dotenv()

# Impor khusus platform untuk membaca input keyboard
if platform.system() == "Windows":
    import msvcrt
else:
    import tty
    import termios

class P3DXRobot:
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600):
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        
    def _calc_checksum(self, data):
        """
        Hitung checksum ARCOS.
        Menjumlahkan pasangan byte data secara berurutan (byte tinggi terlebih dahulu)
        ke checksum berjalan. Jika jumlah byte ganjil, byte terakhir di-XOR ke byte rendah.
        """
        c = 0
        n = len(data)
        i = 0
        while n > 1:
            c += (data[i] << 8) | data[i+1]
            c = c & 0xffff
            n -= 2
            i += 2
        if n > 0:
            c = c ^ data[i]
        return c

    def _send_packet(self, command_num, arg_type=None, arg_val=None):
        packet = [command_num]
        if arg_type is not None:
            packet.append(arg_type)
            # Argumen berupa integer 2-byte, byte kurang signifikan terlebih dahulu
            packet.append(arg_val & 0xFF)
            packet.append((arg_val >> 8) & 0xFF)
        
        byte_count = len(packet) + 2
        full_packet = [0xFA, 0xFB, byte_count] + packet
        
        # Checksum dihitung pada isi paket (tidak termasuk header dan byte jumlah)
        # Catatan: manual menunjukkan cara perhitungan berdasarkan byte count pada indeks 2.
        checksum = self._calc_checksum(packet)
        
        # Byte checksum dikirimkan byte tinggi dahulu
        full_packet.append((checksum >> 8) & 0xFF)
        full_packet.append(checksum & 0xFF)
        
        with self.lock:
            self.ser.write(bytearray(full_packet))

    def connect(self):
        print("Connecting to robot...")
        # Urutan sinkronisasi
        for sync_cmd in [0, 1, 2]:
            self._send_packet(sync_cmd)
            time.sleep(0.1)
            # Dalam skenario nyata, sebaiknya menunggu echo dari robot di sini
            
        # Perintah OPEN
        self._send_packet(1)
        time.sleep(0.1)
        
        # Aktifkan motor
        self._send_packet(4, arg_type=0x3B, arg_val=1)
        self.connected = True
        print("Robot connected and motors enabled.")

    def set_velocity(self, linear):
        # Perintah VEL (#11), tipe argumen 0x1B (int)
        self._send_packet(11, arg_type=0x1B, arg_val=linear)

    def set_rot_velocity(self, angular):
        # Perintah RVEL (#21), tipe argumen 0x1B (int)
        self._send_packet(21, arg_type=0x1B, arg_val=angular)

    def stop(self):
        # Perintah STOP (#29)
        self._send_packet(29)

    def pulse(self):
        # Perintah PULSE (#0)
        self._send_packet(0)

    def disconnect(self):
        self.running = False
        if self.connected:
            self._send_packet(2) # CLOSE
        self.ser.close()

def get_key_nonblocking():
    """Ambil tekanan tombol tanpa blocking, kembalikan None jika tidak ada tombol."""
    if platform.system() == "Windows":
        if msvcrt.kbhit():
            return msvcrt.getch().decode('utf-8', errors='ignore')
        return None
    else:
        import select
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            # Use select with 0 timeout for non-blocking read
            if select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                return ch
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def main():
    # Muat konfigurasi dari file .env
    serial_port = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
    serial_baudrate = int(os.getenv('SERIAL_BAUDRATE', '9600'))
    rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
    rabbitmq_port = int(os.getenv('RABBITMQ_PORT', '5672'))
    rabbitmq_user = os.getenv('RABBITMQ_USER', 'guest')
    rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'guest')
    rabbitmq_queue = os.getenv('RABBITMQ_QUEUE', 'robot_control')
    rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
    
    robot = P3DXRobot(port=serial_port, baudrate=serial_baudrate)
    
    try:
        robot.connect()
        
        print("\nP3-DX RabbitMQ Control Started")
        print(f"Serial Port: {serial_port} @ {serial_baudrate} baud")
        print(f"RabbitMQ Host: {rabbitmq_host}:{rabbitmq_port}")
        print(f"RabbitMQ Virtual Host: {rabbitmq_vhost}")
        print(f"RabbitMQ Queue: {rabbitmq_queue}")
        print("Data format: x,y (left_motor_velocity, right_motor_velocity)")
        print("Press Z to quit\n")
        
        left_motor_vel = 0
        right_motor_vel = 0
        should_quit = False
        
        # Koneksi RabbitMQ dan penangan pesan
        def rabbitmq_consumer():
            nonlocal left_motor_vel, right_motor_vel, should_quit
            try:
                credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_password)
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(
                        host=rabbitmq_host,
                        port=rabbitmq_port,
                        virtual_host=rabbitmq_vhost,
                        credentials=credentials
                    )
                )
                channel = connection.channel()
                channel.queue_declare(queue=rabbitmq_queue, durable=True)
                
                def callback(ch, method, properties, body):
                    nonlocal left_motor_vel, right_motor_vel
                    try:
                        # Parse pesan: format "x,y"
                        message = body.decode('utf-8').strip()
                        values = message.split(',')
                        if len(values) == 2:
                            left_motor_vel = int(values[0])
                            right_motor_vel = int(values[1])
                            print(f"\rReceived: Left={left_motor_vel} mm/s, Right={right_motor_vel} mm/s  ", end="", flush=True)
                    except Exception as e:
                        print(f"Error parsing message: {e}")
                    
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                
                channel.basic_consume(
                    queue=rabbitmq_queue,
                    on_message_callback=callback,
                    auto_ack=False
                )
                
                print("Waiting for messages...")
                channel.start_consuming()
            except Exception as e:
                print(f"RabbitMQ Error: {e}")
                should_quit = True
        
        # Thread latar untuk PULSE agar koneksi tetap hidup
        def watchdog():
            while robot.running and not should_quit:
                robot.pulse()
                time.sleep(1.0)
        
        # Mulai thread consumer RabbitMQ
        consumer_thread = threading.Thread(target=rabbitmq_consumer, daemon=True)
        consumer_thread.start()
        
        # Mulai thread watchdog
        threading.Thread(target=watchdog, daemon=True).start()
        
        # Loop utama: terapkan kecepatan motor
        while not should_quit:
            # Pemetaan pasangan kecepatan left/right ke gerakan robot:
            # - 100,100 => maju
            # - 0,0     => berhenti
            # - 0,100   => belok kiri
            # - 100,0   => belok kanan
            if left_motor_vel == right_motor_vel:
                linear_vel = left_motor_vel
                angular_vel = 0
            else:
                linear_vel = 0
                angular_vel = (right_motor_vel - left_motor_vel) // 2

            # Periksa tombol keluar dari pengguna
            key = get_key_nonblocking()
            if key is not None and key.lower() == 'z':
                print("\nShutdown requested by user...")
                should_quit = True
                break

            # Terapkan kecepatan ke robot
            if linear_vel != 0 or angular_vel != 0:
                robot.set_velocity(linear_vel)
                robot.set_rot_velocity(angular_vel)
            else:
                robot.stop()

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nShutdown requested...")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        should_quit = True
        robot.disconnect()
        print("Disconnected.")

if __name__ == "__main__":
    main()
