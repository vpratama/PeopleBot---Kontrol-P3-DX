import time
import sys
import threading
import platform
import pika
import os
from dotenv import load_dotenv

# Muat variabel lingkungan dari file .env
load_dotenv()

# Impor khusus platform untuk input keyboard
if platform.system() == "Windows":
    import msvcrt
else:
    import tty
    import termios
    import select


def get_key_input():
    """Ambil input keyboard tanpa blocking (non-blocking)."""
    if platform.system() == "Windows":
        if msvcrt.kbhit():
            return msvcrt.getch().decode('utf-8', errors='ignore').lower()
        return None
    else:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            if select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1).lower()
                return ch
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class RobotRemoteControl:
    def __init__(self):
        # Muat konfigurasi dari file .env
        self.rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
        self.rabbitmq_port = int(os.getenv('RABBITMQ_PORT', '5672'))
        self.rabbitmq_user = os.getenv('RABBITMQ_USER', 'guest')
        self.rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'guest')
        self.rabbitmq_queue = os.getenv('RABBITMQ_QUEUE', 'robot_control')
        self.rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
        
        self.velocity_speed = 100  # Default velocity speed (mm/s)
        self.velocity_multipliers = {
            '1': 100,
            '2': 200,
            '3': 300,
            '4': 400
        }
        
        self.pressed_keys = set()
        self.should_quit = False
        self.connection = None
        self.channel = None
        
    def connect_rabbitmq(self):
        """Sambung ke RabbitMQ."""
        try:
            credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.rabbitmq_host,
                    port=self.rabbitmq_port,
                    virtual_host=self.rabbitmq_vhost,
                    credentials=credentials
                )
            )
            self.channel = self.connection.channel()
            self.channel.queue_declare(queue=self.rabbitmq_queue, durable=True, auto_delete=False)
            print(f"Connected to RabbitMQ at {self.rabbitmq_host}:{self.rabbitmq_port} vhost={self.rabbitmq_vhost}")
        except Exception as e:
            print(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    def send_velocity(self, left_vel, right_vel):
        """Kirim perintah kecepatan ke RabbitMQ."""
        try:
            message = f"{left_vel},{right_vel}"
            self.channel.basic_publish(
                exchange='',
                routing_key=self.rabbitmq_queue,
                body=message,
                properties=pika.BasicProperties(delivery_mode=2)
            )
        except Exception as e:
            print(f"Error sending message: {e}")
    
    def calculate_motor_velocities(self):
        """Hitung kecepatan motor kiri/kanan berdasarkan tombol yang ditekan."""
        if 'w' in self.pressed_keys:
            return -self.velocity_speed, -self.velocity_speed

        if 'a' in self.pressed_keys:
            return self.velocity_speed, 0

        if 's' in self.pressed_keys:
            return 0, 0

        if 'd' in self.pressed_keys:
            return 0, self.velocity_speed

        return 0, 0
    
    def key_reader_thread(self):
        """Thread latar untuk membaca input keyboard."""
        if platform.system() == "Windows":
            while not self.should_quit:
                if msvcrt.kbhit():
                    key = msvcrt.getch().decode('utf-8', errors='ignore').lower()
                    if key == 'z':
                        self.should_quit = True
                    elif key in ['w', 'a', 's', 'd']:
                        self.pressed_keys.difference_update({'w', 'a', 's', 'd'})
                        self.pressed_keys.add(key)
                    elif key in ['1', '2', '3', '4']:
                        self.pressed_keys.add(key)
                time.sleep(0.01)
        else:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(sys.stdin.fileno())
                while not self.should_quit:
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        key = sys.stdin.read(1).lower()
                        if key == 'z':
                            self.should_quit = True
                        elif key in ['w', 'a', 's', 'd']:
                            self.pressed_keys.difference_update({'w', 'a', 's', 'd'})
                            self.pressed_keys.add(key)
                        elif key in ['1', '2', '3', '4']:
                            self.pressed_keys.add(key)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    
    def run(self):
        """Loop utama pengendalian."""
        try:
            self.connect_rabbitmq()
            
            print("\n=== Robot Remote Control ===")
            print(f"RabbitMQ Queue: {self.rabbitmq_queue}")
            print("\nControls:")
            print("  W       - Send -speed,-speed")
            print("  A       - Send speed,0")
            print("  S       - Send 0,0")
            print("  D       - Send 0,speed")
            print("  1/2/3/4 - Set velocity (100/200/300/400 mm/s)")
            print("  Z       - Exit")
            print("\nStarting remote control...\n")
            
            # Mulai thread pembaca tombol (latar)
            key_thread = threading.Thread(target=self.key_reader_thread, daemon=True)
            key_thread.start()
            
            last_left_vel = 0
            last_right_vel = 0
            
            # Loop utama
            while not self.should_quit:
                # Tangani perubahan magnitude kecepatan (tombol 1-4)
                for key in ['1', '2', '3', '4']:
                    if key in self.pressed_keys:
                        self.velocity_speed = self.velocity_multipliers[key]
                        self.pressed_keys.discard(key)

                # Hitung kecepatan motor berdasarkan tombol gerak saat ini
                left_vel, right_vel = self.calculate_motor_velocities()

                # Selalu kirim kecepatan; default adalah 0,0 saat tidak bergerak
                self.send_velocity(left_vel, right_vel)

                if left_vel != last_left_vel or right_vel != last_right_vel:
                    last_left_vel = left_vel
                    last_right_vel = right_vel

                    status = "Stopped"
                    if left_vel != 0 or right_vel != 0:
                        status = f"Left: {left_vel:4d} mm/s, Right: {right_vel:4d} mm/s"
                    print(f"\rVelocity: {self.velocity_speed} mm/s | {status}                 ", end="", flush=True)

                time.sleep(0.05)

        except KeyboardInterrupt:
            print("\n\nShutdown requested...")
        except Exception as e:
            print(f"\nError: {e}")
        finally:
            self.should_quit = True
            # Send final stop command
            if self.channel:
                self.send_velocity(0, 0)
                self.connection.close()
            print("Disconnected.")


def main():
    remote = RobotRemoteControl()
    remote.run()


if __name__ == "__main__":
    main()
