#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import platform
import select
import serial
import sys
import threading
import time

import websocket
import certifi
import traceback
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Read VERBOSE from VERBOSE_SONAR in .env
VERBOSE = os.getenv('VERBOSE_SONAR', 'true').lower() in ('1', 'true', 'yes', 'on')


def hexdump(b: bytes | bytearray) -> str:
    """Return a hex string for bytes/bytearray."""
    return ' '.join(f'{x:02X}' for x in b)


def _stomp_escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n').replace(':', '\\c')


def _stomp_connect(ws, user, password, vhost):
    ws.send('CONNECT\naccept-version:1.2\nheart-beat:0,0\n'
            f'host:{_stomp_escape(vhost)}\nlogin:{_stomp_escape(user)}\n'
            f'passcode:{_stomp_escape(password)}\n\n\x00')
    response = ws.recv()
    if isinstance(response, bytes):
        response = response.decode('utf-8', errors='replace')
    if not response.startswith('CONNECTED\n'):
        raise ConnectionError(f'Web STOMP connection failed: {response[:200]}')


def _stomp_headers(frame):
    lines = frame.split('\n')
    headers = {}
    for line in lines[1:]:
        if not line:
            break
        key, sep, value = line.partition(':')
        if sep:
            headers[key] = value
    return lines[0], headers, frame.split('\n\n', 1)[1] if '\n\n' in frame else ''


# Platform-specific non-blocking keyboard input imports
if platform.system() == "Windows":
    import msvcrt
else:
    import termios
    import tty


class P3DXRobot:
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600):
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self.reader_thread = None
        self.reader_running = False
        
        # RabbitMQ Web STOMP publisher and thread safety lock
        self.rabbit_conn = None
        self.rabbit_queue = os.getenv('RABBITMQ_QUEUE_TERMINAL', 'terminal')
        self.rabbit_lock = threading.Lock()

    def _calc_checksum(self, data: list[int]) -> int:
        c = 0
        n = len(data)
        i = 0
        while n > 1:
            c += (data[i] << 8) | data[i + 1]
            c &= 0xFFFF
            n -= 2
            i += 2
        if n > 0:
            c ^= data[i]
        return c

    def _send_packet(self, command_num: int, arg_type: int | None = None, arg_val: int | None = None):
        packet = [command_num]
        if arg_type is not None and arg_val is not None:
            packet.append(arg_type)
            packet.append(arg_val & 0xFF)
            packet.append((arg_val >> 8) & 0xFF)

        byte_count = len(packet) + 2
        full_packet = [0xFA, 0xFB, byte_count] + packet

        checksum = self._calc_checksum(packet)
        full_packet.append((checksum >> 8) & 0xFF)
        full_packet.append(checksum & 0xFF)

        sent_bytes = bytearray(full_packet)
        with self.lock:
            self.ser.write(sent_bytes)

        # Publish send event to RabbitMQ (best-effort)
        try:
            self._publish_terminal_event('send', sent_bytes)
        except Exception:
            pass

    def connect(self):
        print("Connecting to robot...")
        try:
            self._init_rabbit_publisher()
        except Exception:
            pass
            
        for sync_cmd in (0, 1, 2):
            self._send_packet(sync_cmd)
            time.sleep(0.1)
            
        self._send_packet(1)
        time.sleep(0.1)
        self._send_packet(4, arg_type=0x3B, arg_val=1)
        self.connected = True
        print("Robot connected and motors enabled.")
        
        # Start background reader thread
        try:
            self.start_reader()
        except Exception:
            pass

    def set_velocity(self, linear: int):
        self._send_packet(11, arg_type=0x1B, arg_val=linear)

    def set_rot_velocity(self, angular: int):
        self._send_packet(21, arg_type=0x1B, arg_val=angular)

    def stop(self):
        self._send_packet(29)

    def pulse(self):
        self._send_packet(0)

    def disconnect(self):
        self.running = False
        self.reader_running = False
        
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=0.5)
            
        if self.connected:
            self._send_packet(2)
            
        self.ser.close()
        
        # Thread-safe Web STOMP connection cleanup
        with self.rabbit_lock:
            try:
                if self.rabbit_conn:
                    self.rabbit_conn.send('DISCONNECT\n\n\x00')
                    self.rabbit_conn.close()
            except Exception:
                pass
            finally:
                self.rabbit_conn = None

    def start_reader(self):
        """Start a background thread that reads serial input."""
        if self.reader_thread:
            return
        self.reader_running = True

        def _reader():
            while self.running and self.reader_running:
                try:
                    avail = self.ser.in_waiting
                    if avail > 0:
                        data = self.ser.read(avail)
                        if data:
                            self._publish_terminal_event('recv', data)
                    else:
                        time.sleep(0.05)
                except Exception as e:
                    print(f"Serial read error: {e}")
                    time.sleep(0.5)

        self.reader_thread = threading.Thread(target=_reader, daemon=True)
        self.reader_thread.start()

    def _init_rabbit_publisher(self):
        """Initialize a RabbitMQ Web STOMP connection."""
        url = os.getenv('RABBITMQ_WS_URL', 'ws://localhost:15674/ws')
        user = os.getenv('RABBITMQ_USER', 'guest')
        password = os.getenv('RABBITMQ_PASSWORD', 'guest')
        vhost = os.getenv('RABBITMQ_VHOST', '/')
        queue = os.getenv('RABBITMQ_QUEUE_TERMINAL', self.rabbit_queue)
        if self.rabbit_conn:
            try: self.rabbit_conn.close()
            except Exception: pass
            self.rabbit_conn = None
        try:
            conn = websocket.create_connection(url, timeout=5, subprotocols=['v12.stomp'], sslopt={'ca_certs': certifi.where()})
            _stomp_connect(conn, user, password, vhost)
            self.rabbit_conn = conn
            self.rabbit_queue = queue
        except Exception as e:
            print(f"RabbitMQ Web STOMP publisher init failed: {e}")

    def _publish_terminal_event(self, direction: str, data: bytes | bytearray):
        if not self.rabbit_conn:
            self._init_rabbit_publisher()
        if not self.rabbit_conn:
            return
        payload = {'time': time.time(), 'dir': direction, 'hex': hexdump(data),
                   'text': data.decode('utf-8', errors='ignore')}
        try:
            with self.rabbit_lock:
                self.rabbit_conn.send(
                    f'SEND\ndestination:/amq/queue/{self.rabbit_queue}'
                    f'\ncontent-type:application/json\n\n{json.dumps(payload)}\x00'
                )
        except Exception as e:
            print(f"Terminal publish error: {e}")
            with self.rabbit_lock:
                try: self.rabbit_conn.close()
                except Exception: pass
                self.rabbit_conn = None


def get_key_nonblocking():
    if platform.system() == "Windows":
        if msvcrt.kbhit():
            return msvcrt.getch().decode('utf-8', errors='ignore')
        return None

    # No controlling terminal (e.g. running as a boot service): no key input.
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return None
    except (ValueError, OSError):
        return None

    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
    except (termios.error, ValueError, OSError):
        return None
    try:
        tty.setraw(fd)
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def main():
    serial_port = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
    serial_baudrate = int(os.getenv('SERIAL_BAUDRATE', '9600'))
    rabbitmq_ws_url = os.getenv('RABBITMQ_WS_URL', 'ws://localhost:15674/ws')
    rabbitmq_user = os.getenv('RABBITMQ_USER', 'guest')
    rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'guest')
    rabbitmq_queue = os.getenv('RABBITMQ_QUEUE', 'robot_control')
    rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
    robot = P3DXRobot(port=serial_port, baudrate=serial_baudrate)
    state = {'left': 0, 'right': 0, 'should_quit': False}

    try:
        robot.connect()
        print("\nP3-DX RabbitMQ Control Started")
        print(f"Serial Port: {serial_port} @ {serial_baudrate} baud")
        print(f"RabbitMQ Web STOMP: {rabbitmq_ws_url}")
        print("Press Z to quit\n")

        def rabbitmq_consumer():
            try:
                ws = websocket.create_connection(
                    rabbitmq_ws_url, timeout=5, subprotocols=['v12.stomp'], sslopt={'ca_certs': certifi.where()}
                )
                _stomp_connect(ws, rabbitmq_user, rabbitmq_password, rabbitmq_vhost)
                ws.settimeout(1)
                ws.send(
                    f'SUBSCRIBE\nid:peoplebot-control\ndestination:/amq/queue/{rabbitmq_queue}'
                    '\nack:auto\n\n\x00'
                )
                print(f'Subscribed to RabbitMQ Web STOMP queue: {rabbitmq_queue}', flush=True)
                buffer = ''
                while not state['should_quit']:
                    try:
                        chunk = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not chunk:
                        raise ConnectionError('Web STOMP connection closed')
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode('utf-8', errors='replace')
                    buffer += chunk
                    while '\x00' in buffer:
                        frame, buffer = buffer.split('\x00', 1)
                        if not frame.strip():
                            continue
                        command, headers, body = _stomp_headers(frame)
                        if command == 'MESSAGE':
                            try:
                                values = body.strip().split(',')
                                if len(values) == 2:
                                    state['left'], state['right'] = map(int, values)
                            except ValueError as e:
                                print(f"Error parsing message: {e}")
                        elif command == 'ERROR':
                            raise ConnectionError(f"Web STOMP broker error: {body.strip()}")
                ws.send('DISCONNECT\n\n\x00')
                ws.close()

            except Exception as e:
                print(f"RabbitMQ Web STOMP Error: {e}")
                state['should_quit'] = True

        def watchdog():
            while robot.running and not state['should_quit']:
                robot.pulse()
                time.sleep(1.0)

        threading.Thread(target=rabbitmq_consumer, daemon=True).start()
        threading.Thread(target=watchdog, daemon=True).start()

        while not state['should_quit']:
            left_motor_vel = state['left']
            right_motor_vel = state['right']
            if left_motor_vel == right_motor_vel:
                linear_vel, angular_vel = left_motor_vel, 0
            else:
                linear_vel = 0
                angular_vel = (right_motor_vel - left_motor_vel) // 2

            key = get_key_nonblocking()
            if key is not None and key.lower() == 'z':
                state['should_quit'] = True
                break
            if linear_vel or angular_vel:
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
        state['should_quit'] = True
        robot.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()