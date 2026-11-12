#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import platform
import random
import re
import select
import sys
import threading
import time

import websocket
import certifi
import traceback
import paho.mqtt.client as mqtt
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
    response = response.replace('\r\n', '\n')
    if not response.startswith('CONNECTED\n'):
        raise ConnectionError(f'Web STOMP connection failed: {response[:200]}')


def _stomp_headers(frame):
    # STOMP heartbeats are bare line feeds and may appear between frames.
    frame = frame.replace('\r\n', '\n').lstrip('\r\n')
    lines = frame.split('\n')
    headers = {}
    for line in lines[1:]:
        if not line.strip():
            break
        key, sep, value = line.partition(':')
        if sep:
            headers[key] = value
    return lines[0].strip(), headers, frame.split('\n\n', 1)[1] if '\n\n' in frame else ''


def parse_sensor_readings(raw_data):
    """Parse one comma-separated line containing eight sensor values."""
    if isinstance(raw_data, (bytes, bytearray)):
        try:
            raw_data = raw_data.decode('ascii')
        except UnicodeDecodeError:
            return None

    fields = str(raw_data).strip().split(',')
    if len(fields) != 8:
        return None
    try:
        return [int(float(value.strip())) for value in fields]
    except ValueError:
        return None


class SensorMqttPublisher:
    """Publish sensor CSV payloads to the RabbitMQ Web MQTT endpoint."""

    def __init__(self):
        self.host = os.getenv('RABBITMQ_MQTT_HOST', 'mqtt.luminaire.software')
        self.port = int(os.getenv('RABBITMQ_MQTT_PORT', '443'))
        self.path = os.getenv('RABBITMQ_MQTT_PATH', '/ws')
        self.topic = os.getenv('RABBITMQ_MQTT_TOPIC', 'sensor')
        self.client = mqtt.Client(
            client_id=f'peoplebot-control-{os.getpid()}',
            transport='websockets',
        )
        self.connected = threading.Event()
        self.connect_result = {'rc': None}

        def _on_connect(_client, _userdata, _flags, rc):
            self.connect_result['rc'] = rc
            self.connected.set()

        self.client.on_connect = _on_connect
        self.client.username_pw_set(
            os.getenv('RABBITMQ_USER', 'guest'),
            os.getenv('RABBITMQ_PASSWORD', 'guest'),
        )
        self.client.ws_set_options(path=self.path)
        self.client.tls_set(ca_certs=certifi.where())
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()

        if not self.connected.wait(timeout=10):
            self.close()
            raise TimeoutError('Timed out waiting for the RabbitMQ MQTT connection.')
        if self.connect_result['rc'] != 0:
            result = self.connect_result['rc']
            self.close()
            raise ConnectionError(f'RabbitMQ MQTT connection was rejected (code {result}).')

        print(
            f'[MQTT] Connected to wss://{self.host}:{self.port}{self.path}; topic={self.topic}',
            flush=True,
        )

    def publish(self, readings, wait_for_delivery=True):
        payload = ','.join(map(str, readings))
        message = self.client.publish(self.topic, payload, qos=1)
        if message.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f'[MQTT] Publish failed: {mqtt.error_string(message.rc)}', flush=True)
            return
        if wait_for_delivery:
            try:
                message.wait_for_publish(timeout=5)
            except (RuntimeError, ValueError) as e:
                print(f'[MQTT] Publish failed: {e}', flush=True)
                return
            if not message.is_published():
                print('[MQTT] Timed out waiting for publish confirmation.', flush=True)
                return
            status = 'Published'
        else:
            status = 'Queued'
        print(f"[MQTT] {status} to '{self.topic}': {payload}", flush=True)

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass
        try:
            self.client.loop_stop()
        except Exception:
            pass


# Platform-specific non-blocking keyboard input imports
if platform.system() == "Windows":
    import msvcrt
else:
    import termios
    import tty


class P3DXRobot:
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600, sensor_callback=None):
        import serial

        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.sensor_callback = sensor_callback
        self.sensor_buffer = bytearray()
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
                            self._consume_sensor_data(data)
                    else:
                        time.sleep(0.05)
                except Exception as e:
                    print(f"Serial read error: {e}")
                    time.sleep(0.5)

        self.reader_thread = threading.Thread(target=_reader, daemon=True)
        self.reader_thread.start()

    def _consume_sensor_data(self, data: bytes | bytearray):
        """Extract complete eight-value CSV sensor lines from serial input."""
        if self.sensor_callback is None:
            return

        self.sensor_buffer.extend(data)
        readings = parse_sensor_readings(self.sensor_buffer)
        if readings is not None:
            self.sensor_buffer.clear()
            self.sensor_callback(readings)
            return

        while b'\n' in self.sensor_buffer:
            line, _, remainder = self.sensor_buffer.partition(b'\n')
            self.sensor_buffer = bytearray(remainder)
            readings = parse_sensor_readings(line.rstrip(b'\r'))
            if readings is not None:
                self.sensor_callback(readings)

        # Binary robot packets can contain arbitrary bytes; discard an
        # incomplete/non-CSV sequence before the buffer grows without bound.
        if len(self.sensor_buffer) > 4096:
            self.sensor_buffer.clear()

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


def _simulate_sensor_data(publisher, state):
    while not state['should_quit']:
        readings = [random.randint(150, 5000) for _ in range(8)]
        publisher.publish(readings)
        for _ in range(10):
            if state['should_quit']:
                return
            time.sleep(0.1)


def _read_sensor_serial(port, baudrate, publisher, state):
    try:
        import serial

        with serial.Serial(port, baudrate, timeout=1) as sensor_ser:
            print(f'[SENSOR] Reading CSV data from {port}', flush=True)
            while not state['should_quit']:
                raw_data = sensor_ser.readline()
                if not raw_data:
                    continue
                readings = parse_sensor_readings(raw_data)
                if readings is not None:
                    publisher.publish(readings)
    except Exception as e:
        if not state['should_quit']:
            print(f'[SENSOR] Serial reader error on {port}: {e}', flush=True)


def main():
    serial_port = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
    serial_baudrate = int(os.getenv('SERIAL_BAUDRATE', '9600'))
    rabbitmq_ws_url = os.getenv('RABBITMQ_WS_URL', 'ws://localhost:15674/ws')
    rabbitmq_user = os.getenv('RABBITMQ_USER', 'guest')
    rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'guest')
    rabbitmq_queue = os.getenv('RABBITMQ_QUEUE', 'robot_control')
    rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
    serial_simulation = os.getenv('SERIAL_SIMULATION', 'false').strip().lower() in (
        '1', 'true', 'yes', 'on'
    )
    sensor_simulation = os.getenv('SENSOR_SIMULATION', 'true').strip().lower() in (
        '1', 'true', 'yes', 'on'
    )
    robot = None
    sensor_publisher = None
    state = {'left': 0, 'right': 0, 'should_quit': False}

    try:
        try:
            sensor_publisher = SensorMqttPublisher()
        except Exception as e:
            print(f'[MQTT] Sensor publisher unavailable: {e}', flush=True)

        if serial_simulation:
            print(
                'SERIAL_SIMULATION=true: serial is disabled; '
                'RabbitMQ messages will be printed.',
                flush=True,
            )
        else:
            sensor_callback = None
            if sensor_publisher is not None and not sensor_simulation:
                sensor_callback = lambda readings: sensor_publisher.publish(
                    readings, wait_for_delivery=False
                )
            robot = P3DXRobot(
                port=serial_port,
                baudrate=serial_baudrate,
                sensor_callback=sensor_callback,
            )
            robot.connect()

        print("\nP3-DX RabbitMQ Control Started")
        if robot is not None:
            print(f"Serial Port: {serial_port} @ {serial_baudrate} baud")
        print(f"RabbitMQ Web STOMP: {rabbitmq_ws_url}")
        print("Press Z to quit\n")

        def rabbitmq_consumer():
            announced_subscription = False
            while not state['should_quit']:
                ws = None
                try:
                    ws = websocket.create_connection(
                        rabbitmq_ws_url,
                        timeout=5,
                        subprotocols=['v12.stomp'],
                        sslopt={'ca_certs': certifi.where()},
                    )
                    _stomp_connect(ws, rabbitmq_user, rabbitmq_password, rabbitmq_vhost)
                    ws.settimeout(1)
                    ws.send(
                        f'SUBSCRIBE\nid:peoplebot-control\ndestination:/amq/queue/{rabbitmq_queue}'
                        '\nack:auto\n\n\x00'
                    )
                    if not announced_subscription:
                        print(
                            f'Subscribed to RabbitMQ Web STOMP queue: {rabbitmq_queue}',
                            flush=True,
                        )
                        announced_subscription = True

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
                                message = body.rstrip('\r\n')
                                print(f'[RABBITMQ] Received: {message}', flush=True)
                                if serial_simulation:
                                    continue
                                try:
                                    values = message.split(',')
                                    if len(values) == 2:
                                        state['left'], state['right'] = map(int, values)
                                except ValueError as e:
                                    print(f"Error parsing message: {e}")
                            elif command == 'ERROR':
                                raise ConnectionError(
                                    f"Web STOMP broker error: {body.strip()}"
                                )

                    if state['should_quit']:
                        try:
                            ws.send('DISCONNECT\n\n\x00')
                        except Exception:
                            pass
                        break
                except Exception as e:
                    # Keep the main control loop running and report reconnect issues.
                    if not state['should_quit']:
                        print(
                            f'RabbitMQ Web STOMP error: {e}; retrying in 2 seconds.',
                            flush=True,
                        )
                        time.sleep(2)
                finally:
                    if ws is not None:
                        try:
                            ws.close()
                        except Exception:
                            pass

        def watchdog():
            while robot is not None and robot.running and not state['should_quit']:
                robot.pulse()
                time.sleep(1.0)

        threading.Thread(target=rabbitmq_consumer, daemon=True).start()
        if sensor_publisher is not None:
            if sensor_simulation:
                print('[SENSOR] Publishing simulated readings to MQTT topic.', flush=True)
                threading.Thread(
                    target=_simulate_sensor_data,
                    args=(sensor_publisher, state),
                    daemon=True,
                ).start()
            elif robot is None:
                threading.Thread(
                    target=_read_sensor_serial,
                    args=(serial_port, serial_baudrate, sensor_publisher, state),
                    daemon=True,
                ).start()
        if robot is not None:
            threading.Thread(target=watchdog, daemon=True).start()

        while not state['should_quit']:
            key = get_key_nonblocking()
            if key is not None and key.lower() == 'z':
                state['should_quit'] = True
                break

            if robot is not None:
                left_motor_vel = state['left']
                right_motor_vel = state['right']
                if left_motor_vel == right_motor_vel:
                    linear_vel, angular_vel = left_motor_vel, 0
                else:
                    linear_vel = 0
                    angular_vel = (right_motor_vel - left_motor_vel) // 2

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
        if robot is not None:
            robot.disconnect()
            print("Disconnected.")
        else:
            print("Simulation ended.")
        if sensor_publisher is not None:
            sensor_publisher.close()


if __name__ == "__main__":
    main()
