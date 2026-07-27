import time
import sys
import threading
import platform
import pika
import os
from dotenv import load_dotenv

try:
    import pygame
except ImportError:  # pragma: no cover
    pygame = None

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
            '4': 400,
        }

        self.pressed_keys = set()
        self.should_quit = False
        self.connection = None
        self.channel = None
        self.controller_active = False
        self.controller_buttons = set()
        self.controller_axes = {
            'left_x': 0.0,
            'left_y': 0.0,
        }
        
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
        """Hitung kecepatan motor dari keyboard dan controller secara gabungan."""
        keyboard_forward = 's' in self.pressed_keys
        keyboard_backward = 'w' in self.pressed_keys
        keyboard_left = 'a' in self.pressed_keys
        keyboard_right = 'd' in self.pressed_keys

        controller_forward = False
        controller_backward = False
        controller_left = False
        controller_right = False

        if self.controller_active:
            if 'up' in self.controller_buttons:
                controller_forward = True
            if 'down' in self.controller_buttons:
                controller_backward = True
            if 'left' in self.controller_buttons:
                controller_left = True
            if 'right' in self.controller_buttons:
                controller_right = True

            left_x = self.controller_axes['left_x']
            left_y = self.controller_axes['left_y']
            if abs(left_y) > 0.2 or abs(left_x) > 0.2:
                if abs(left_y) > abs(left_x):
                    if left_y < 0:
                        controller_forward = True
                    elif left_y > 0:
                        controller_backward = True
                else:
                    if left_x < 0:
                        controller_left = True
                    elif left_x > 0:
                        controller_right = True

        # Gabungkan state keyboard + controller.
        forward = keyboard_forward or controller_forward
        backward = keyboard_backward or controller_backward
        turn_left = keyboard_left or controller_left
        turn_right = keyboard_right or controller_right

        if forward and not backward:
            if turn_left and not turn_right:
                return self.velocity_speed, 0
            if turn_right and not turn_left:
                return 0, self.velocity_speed
            return self.velocity_speed, self.velocity_speed

        if backward and not forward:
            if turn_left and not turn_right:
                return -self.velocity_speed, 0
            if turn_right and not turn_left:
                return 0, -self.velocity_speed
            return -self.velocity_speed, -self.velocity_speed

        if turn_left and not turn_right:
            return self.velocity_speed, 0
        if turn_right and not turn_left:
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
                    elif key == ' ':
                        self.pressed_keys.difference_update({'w', 'a', 's', 'd'})
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
                        elif key == ' ':
                            self.pressed_keys.difference_update({'w', 'a', 's', 'd'})
                        elif key in ['w', 'a', 's', 'd']:
                            self.pressed_keys.difference_update({'w', 'a', 's', 'd'})
                            self.pressed_keys.add(key)
                        elif key in ['1', '2', '3', '4']:
                            self.pressed_keys.add(key)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def init_pygame_controller(self):
        """Inisialisasi pygame untuk input controller."""
        if pygame is None:
            print("[CONTROLLER] pygame tidak terinstall. Install dengan pip install pygame")
            return False

        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            print("[CONTROLLER] Tidak ada controller terdeteksi")
            return False

        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        self.controller_active = True
        print(f"[CONTROLLER] Controller terdeteksi: {joystick.get_name()}")
        return True

    def update_from_controller(self):
        """Baca event controller menggunakan pygame."""
        if pygame is None:
            return

        pygame.event.pump()
        if pygame.joystick.get_count() == 0:
            self.controller_active = False
            self.controller_buttons.clear()
            return

        self.controller_active = True
        joystick = pygame.joystick.Joystick(0)
        if not joystick.get_init():
            joystick.init()

        self.controller_buttons.clear()
        for button_idx in range(joystick.get_numbuttons()):
            if joystick.get_button(button_idx):
                button_name = self._normalize_button_name(button_idx)
                if button_name:
                    self.controller_buttons.add(button_name)

        self._read_controller_dpad(joystick)

        if joystick.get_numaxes() >= 2:
            self.controller_axes['left_x'] = joystick.get_axis(0)
            self.controller_axes['left_y'] = -joystick.get_axis(1)

        # Mapping tombol aksi untuk kecepatan, kompatibel dengan Xbox/PlayStation/Switch
        if 'button_0' in self.controller_buttons:
            self.velocity_speed = 100
        elif 'button_1' in self.controller_buttons:
            self.velocity_speed = 200
        elif 'button_2' in self.controller_buttons:
            self.velocity_speed = 300
        elif 'button_3' in self.controller_buttons:
            self.velocity_speed = 400

    def _normalize_button_name(self, button_idx):
        """Normalisasi tombol controller lintas layout."""
        # Xbox: A=0, B=1, X=2, Y=3
        # PlayStation: X=0, Circle=1, Triangle=2, Square=3
        # Switch: B=0, A=1, Y=2, X=3
        mapping = {
            0: 'button_0',
            1: 'button_1',
            2: 'button_2',
            3: 'button_3',
        }
        if button_idx in mapping:
            return mapping[button_idx]
        return None

    def _read_controller_dpad(self, joystick):
        hat = joystick.get_hat(0)
        if hat[1] < 0:
            self.controller_buttons.add('up')
        elif hat[1] > 0:
            self.controller_buttons.add('down')
        if hat[0] < 0:
            self.controller_buttons.add('left')
        elif hat[0] > 0:
            self.controller_buttons.add('right')
    
    def run(self):
        """Loop utama pengendalian."""
        try:
            self.connect_rabbitmq()
            
            print("\n=== Robot Remote Control ===")
            print(f"RabbitMQ Queue: {self.rabbitmq_queue}")
            print("\nControls:")
            print("  Keyboard: W/A/S/D - Move / Stop")
            print("  Controller: D-pad / left stick - Move robot")
            print("  Controller: A/X/Square/1 / etc - Set velocity (100/200/300/400 mm/s)")
            print("  No input - Stop robot")
            print("  Z       - Exit")
            print("\nStarting remote control...\n")
            
            # Mulai thread pembaca tombol (latar)
            key_thread = threading.Thread(target=self.key_reader_thread, daemon=True)
            key_thread.start()

            if not self.init_pygame_controller():
                print("[CONTROLLER] Pygame controller mode unavailable; keyboard mode still works.")
            
            last_left_vel = 0
            last_right_vel = 0
            
            # Loop utama
            while not self.should_quit:
                # Tangani perubahan magnitude kecepatan (tombol 1-4)
                for key in ['1', '2', '3', '4']:
                    if key in self.pressed_keys:
                        self.velocity_speed = self.velocity_multipliers[key]
                        self.pressed_keys.discard(key)

                self.update_from_controller()

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
