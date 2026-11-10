#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import collections
import collections.abc

# Monkey-patch collections.Callable for older pika versions on Python 3.10+
if not hasattr(collections, 'Callable'):
    collections.Callable = collections.abc.Callable

import json
import os
import platform
import select
import serial
import sys
import threading
import time
import traceback
from dotenv import load_dotenv
import pika

# Load environment variables from .env file
load_dotenv()

# Read VERBOSE from VERBOSE_SONAR in .env
VERBOSE = os.getenv('VERBOSE_SONAR', 'true').lower() in ('1', 'true', 'yes', 'on')


def hexdump(b: bytes | bytearray) -> str:
    """Return a hex string for bytes/bytearray."""
    return ' '.join(f'{x:02X}' for x in b)


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
        
        # RabbitMQ publisher setup & thread safety lock
        self.rabbit_conn = None
        self.rabbit_channel = None
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
        
        # Thread-safe RabbitMQ connection cleanup
        with self.rabbit_lock:
            try:
                if self.rabbit_channel and self.rabbit_channel.is_open:
                    self.rabbit_channel.close()
                if self.rabbit_conn and self.rabbit_conn.is_open:
                    self.rabbit_conn.close()
            except Exception:
                pass
            finally:
                self.rabbit_channel = None
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
        """Initialize RabbitMQ connection and channel."""
        host = os.getenv('RABBITMQ_HOST', 'localhost')
        port = int(os.getenv('RABBITMQ_PORT', '5672'))
        user = os.getenv('RABBITMQ_USER', 'guest')
        password = os.getenv('RABBITMQ_PASSWORD', 'guest')
        vhost = os.getenv('RABBITMQ_VHOST', '/')
        queue = os.getenv('RABBITMQ_QUEUE_TERMINAL', self.rabbit_queue)
        
        if self.rabbit_conn:
            try:
                self.rabbit_conn.close()
            except Exception:
                pass
            self.rabbit_conn = None
            self.rabbit_channel = None

        try:
            credentials = pika.PlainCredentials(user, password)
            params = pika.ConnectionParameters(
                host=host, port=port, virtual_host=vhost, credentials=credentials
            )
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue=queue, durable=True, auto_delete=False)
            self.rabbit_conn = conn
            self.rabbit_channel = ch
            self.rabbit_queue = queue
        except Exception as e:
            print(f"RabbitMQ publisher init failed: {e}")

    def _publish_terminal_event(self, direction: str, data: bytes | bytearray):
        if not self.rabbit_channel:
            self._init_rabbit_publisher()
        if not self.rabbit_channel:
            return

        payload = {
            'time': time.time(),
            'dir': direction,
            'hex': hexdump(data),
            'text': data.decode('utf-8', errors='ignore'),
        }
        body = json.dumps(payload).encode('utf-8')
        try:
            with self.rabbit_lock:
                self.rabbit_channel.basic_publish(
                    exchange='', routing_key=self.rabbit_queue, body=body
                )
        except Exception as e:
            print(f"Terminal publish error: {e}")


def get_key_nonblocking():
    if platform.system() == "Windows":
        if msvcrt.kbhit():
            return msvcrt.getch().decode('utf-8', errors='ignore')
        return None

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
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
    rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
    rabbitmq_port = int(os.getenv('RABBITMQ_PORT', '5672'))
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
        print(f"RabbitMQ Host: {rabbitmq_host}:{rabbitmq_port}")
        print("Press Z to quit\n")

        def rabbitmq_consumer():
            try:
                credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_password)
                connection = pika.BlockingConnection(pika.ConnectionParameters(
                    host=rabbitmq_host, port=rabbitmq_port,
                    virtual_host=rabbitmq_vhost, credentials=credentials
                ))
                channel = connection.channel()
                channel.queue_declare(queue=rabbitmq_queue, durable=True, auto_delete=False)

                def callback(ch, method, properties, body):
                    try:
                        message = body.decode('utf-8').strip()
                        values = message.split(',')
                        if len(values) == 2:
                            state['left'] = int(values[0])
                            state['right'] = int(values[1])
                    except (ValueError, UnicodeDecodeError) as e:
                        print(f"Error parsing message: {e}")
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                try:
                    channel.basic_consume(
                        queue=rabbitmq_queue,
                        on_message_callback=callback,
                        auto_ack=False
                    )
                except TypeError:
                    channel.basic_consume(
                        callback,
                        queue=rabbitmq_queue,
                        no_ack=False
                    )
                channel.start_consuming()
            except Exception as e:
                print(f"RabbitMQ Error: {e}")
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