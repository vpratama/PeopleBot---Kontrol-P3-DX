# -*- coding: utf-8 -*-
from __future__ import print_function

import serial
import time
import sys
import threading
import platform
import pika
import json
import os
import select
import traceback
from dotenv import load_dotenv

# Muat variabel lingkungan dari file.env
load_dotenv()

# Read VERBOSE from VERBOSE_SONAR in .env (supports true/false)
VERBOSE = os.getenv('VERBOSE_SONAR', 'true').lower() in ('1', 'true', 'yes', 'on')


def hexdump(b):
    """Return a hex string for bytes/bytearray (Py2/3 safe)."""
    try:
        return ' '.join('{:02X}'.format(x) for x in b)
    except TypeError:
        return ' '.join('{:02X}'.format(ord(x)) for x in b)

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
        self.reader_thread = None
        self.reader_running = False
        # RabbitMQ publisher placeholders
        self.rabbit_conn = None
        self.rabbit_channel = None
        self.rabbit_queue = os.getenv('RABBITMQ_QUEUE_TERMINAL', 'terminal')

    def _calc_checksum(self, data):
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
            packet.append(arg_val & 0xFF)
            packet.append((arg_val >> 8) & 0xFF)

        byte_count = len(packet) + 2
        full_packet = [0xFA, 0xFB, byte_count] + packet

        checksum = self._calc_checksum(packet)
        full_packet.append((checksum >> 8) & 0xFF)
        full_packet.append(checksum & 0xFF)

        with self.lock:
            if sys.version_info[0] >= 3:
                self.ser.write(bytearray(full_packet))
                sent_bytes = bytearray(full_packet)
            else:
                # Python 2.7: pyserial <3 expects str
                s = ''.join(chr(b) for b in full_packet)
                self.ser.write(s)
                # represent sent bytes for publishing
                try:
                    sent_bytes = bytearray(full_packet)
                except Exception:
                    sent_bytes = s

        # publish send event to rabbitmq (best-effort)
        try:
            self._publish_terminal_event('send', sent_bytes)
        except Exception:
            pass

    def connect(self):
        print("Connecting to robot...")
        # initialize rabbitmq publisher (best-effort)
        try:
            self._init_rabbit_publisher()
        except Exception:
            pass
        for sync_cmd in [0, 1, 2]:
            self._send_packet(sync_cmd)
            time.sleep(0.1)
        self._send_packet(1)
        time.sleep(0.1)
        self._send_packet(4, arg_type=0x3B, arg_val=1)
        self.connected = True
        print("Robot connected and motors enabled.")
        # Start background reader thread to print incoming serial data
        try:
            self.start_reader()
        except Exception:
            pass

    def set_velocity(self, linear):
        self._send_packet(11, arg_type=0x1B, arg_val=linear)

    def set_rot_velocity(self, angular):
        self._send_packet(21, arg_type=0x1B, arg_val=angular)

    def stop(self):
        self._send_packet(29)

    def pulse(self):
        self._send_packet(0)

    def disconnect(self):
        self.running = False
        # stop reader thread
        try:
            self.reader_running = False
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=0.5)
        except Exception:
            pass
        if self.connected:
            self._send_packet(2)
        self.ser.close()
        # close rabbit connection
        try:
            if self.rabbit_channel:
                try:
                    self.rabbit_channel.close()
                except Exception:
                    pass
            if self.rabbit_conn:
                try:
                    self.rabbit_conn.close()
                except Exception:
                    pass
        except Exception:
            pass

    def start_reader(self):
        """Start a background thread that reads and prints serial input."""
        if getattr(self, 'reader_thread', None):
            return
        self.reader_running = True

        def _reader():
            while self.running and self.reader_running:
                try:
                    # in_waiting may not be present on all pyserial versions; fallback accordingly
                    avail = 0
                    try:
                        avail = self.ser.in_waiting
                    except Exception:
                        # older pyserial: use select on fileno
                        try:
                            if select.select([self.ser], [], [], 0)[0]:
                                avail = 1
                        except Exception:
                            avail = 0

                    if avail and avail > 0:
                        data = self.ser.read(avail or 1)
                        if data:
                            # publish receive event to rabbitmq (best-effort)
                            try:
                                self._publish_terminal_event('recv', data)
                            except Exception:
                                pass
                    else:
                        time.sleep(0.05)
                except Exception as e:
                    print("Serial read error: {}".format(e))
                    time.sleep(0.5)

        self.reader_thread = threading.Thread(target=_reader)
        self.reader_thread.daemon = True
        self.reader_thread.start()

    def _init_rabbit_publisher(self):
        """Initialize a RabbitMQ blocking connection and channel for publishing terminal events."""
        host = os.getenv('RABBITMQ_HOST', 'localhost')
        port = int(os.getenv('RABBITMQ_PORT', '5672'))
        user = os.getenv('RABBITMQ_USER', 'guest')
        password = os.getenv('RABBITMQ_PASSWORD', 'guest')
        vhost = os.getenv('RABBITMQ_VHOST', '/')
        queue = os.getenv('RABBITMQ_QUEUE_TERMINAL', self.rabbit_queue)
        try:
            credentials = pika.PlainCredentials(user, password)
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(host=host, port=port, virtual_host=vhost, credentials=credentials)
            )
            ch = conn.channel()
            ch.queue_declare(queue=queue, durable=True, auto_delete=False)
            self.rabbit_conn = conn
            self.rabbit_channel = ch
            self.rabbit_queue = queue
        except Exception as e:
            # failed to init publisher; leave None and continue
            try:
                print("RabbitMQ publisher init failed: {}\n{}".format(e, traceback.format_exc()))
            except Exception:
                pass

    def _publish_terminal_event(self, direction, data):
        """Publish a JSON message to the terminal queue describing send/recv serial data."""
        if not getattr(self, 'rabbit_channel', None):
            # try lazy init
            try:
                self._init_rabbit_publisher()
            except Exception:
                return
        if not self.rabbit_channel:
            return
        try:
            hexstr = hexdump(data) if data is not None else ''
        except Exception:
            try:
                hexstr = hexdump(bytearray(data))
            except Exception:
                hexstr = repr(data)
        text = ''
        try:
            if isinstance(data, (bytes, bytearray)):
                text = data.decode('utf-8', errors='ignore')
            else:
                text = str(data)
        except Exception:
            text = ''
        payload = {
            'time': time.time(),
            'dir': direction,
            'hex': hexstr,
            'text': text,
        }
        try:
            body = json.dumps(payload)
            # pika expects bytes in py3; in py2 str is fine
            if sys.version_info[0] >= 3:
                body = body.encode('utf-8')
            self.rabbit_channel.basic_publish(exchange='', routing_key=self.rabbit_queue, body=body)
        except Exception as e:
            # If the channel/connection was closed by the server, try re-init once and retry publish
            try:
                from pika.exceptions import ChannelClosed, AMQPConnectionError
            except Exception:
                ChannelClosed = None
                AMQPConnectionError = None
            handled = False
            if (ChannelClosed is not None and isinstance(e, ChannelClosed)) or (AMQPConnectionError is not None and isinstance(e, AMQPConnectionError)):
                handled = True
            # Fallback: check exception class name when pika exceptions not importable
            if not handled and e.__class__.__name__ in ('ChannelClosed', 'ConnectionClosed'):
                handled = True

            if handled:
                try:
                    # attempt to re-init connection and retry once
                    try:
                        self._init_rabbit_publisher()
                    except Exception:
                        pass
                    if self.rabbit_channel:
                        body = json.dumps(payload)
                        if sys.version_info[0] >= 3:
                            body = body.encode('utf-8')
                        self.rabbit_channel.basic_publish(exchange='', routing_key=self.rabbit_queue, body=body)
                        return
                except Exception as e2:
                    try:
                        print('Terminal publish retry failed: {}\n{}'.format(e2, traceback.format_exc()))
                    except Exception:
                        pass

            # best-effort; show full trace for debugging
            try:
                print('Terminal publish error: {}\n{}'.format(e, traceback.format_exc()))
            except Exception:
                pass

def get_key_nonblocking():
    if platform.system() == "Windows":
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            # py2: str, py3: bytes
            if isinstance(ch, bytes):
                try:
                    return ch.decode('utf-8', 'ignore')
                except Exception:
                    return ch.decode('utf-8', errors='ignore') if hasattr(ch, 'decode') else str(ch)
            return ch
        return None
    else:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            if select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                return ch
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

    # Use dict instead of nonlocal (Python 2.7 compatible)
    state = {
        'left': 0,
        'right': 0,
        'should_quit': False
    }

    try:
        robot.connect()

        print("\nP3-DX RabbitMQ Control Started")
        print("Serial Port: {} @ {} baud".format(serial_port, serial_baudrate))
        print("RabbitMQ Host: {}:{}".format(rabbitmq_host, rabbitmq_port))
        print("RabbitMQ Virtual Host: {}".format(rabbitmq_vhost))
        print("RabbitMQ Queue: {}".format(rabbitmq_queue))
        print("Data format: x,y (left_motor_velocity, right_motor_velocity)")
        print("Press Z to quit\n")

        def rabbitmq_consumer():
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
                channel.queue_declare(queue=rabbitmq_queue, durable=True, auto_delete=False)

                def callback(ch, method, properties, body):
                    try:
                        if isinstance(body, bytes):
                            message = body.decode('utf-8').strip()
                        else:
                            # Python 2.7: body is str
                            message = body.strip()
                            # if str is bytes, decode to unicode for split
                            if isinstance(message, str):
                                try:
                                    # in py2 this is str -> try decode, in py3 it's already str
                                    if isinstance(body, str) and sys.version_info[0] == 2:
                                        message = message.decode('utf-8')
                                except Exception:
                                    pass
                        values = message.split(',')
                        if len(values) == 2:
                            state['left'] = int(values[0])
                            state['right'] = int(values[1])
                            sys.stdout.write("\rReceived: Left={} mm/s, Right={} mm/s ".format(
                                state['left'], state['right']))
                            sys.stdout.flush()
                    except Exception as e:
                        print("Error parsing message: {}".format(e))

                    ch.basic_ack(delivery_tag=method.delivery_tag)

                # Compatible with both pika 0.12 (py2.7) and pika 1.x
                try:
                    # pika >= 1.0
                    channel.basic_consume(
                        queue=rabbitmq_queue,
                        on_message_callback=callback,
                        auto_ack=False
                    )
                except TypeError:
                    # pika 0.12.x for Python 2.7
                    channel.basic_consume(
                        callback,
                        queue=rabbitmq_queue,
                        no_ack=False
                    )

                print("Waiting for messages...")
                channel.start_consuming()
            except Exception as e:
                print("RabbitMQ Error: {}".format(e))
                state['should_quit'] = True

                def terminal_consumer():
                    """Subscribe to RABBITMQ_QUEUE_TERMINAL and write messages to terminal.log and console."""
                    term_queue = os.getenv('RABBITMQ_QUEUE_TERMINAL', 'terminal')
                    try:
                        credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_password)
                        conn = pika.BlockingConnection(
                            pika.ConnectionParameters(
                                host=rabbitmq_host,
                                port=rabbitmq_port,
                                virtual_host=rabbitmq_vhost,
                                credentials=credentials
                            )
                        )
                        ch = conn.channel()
                        ch.queue_declare(queue=term_queue, durable=True, auto_delete=False)

                        def _cb(ch, method, properties, body):
                            try:
                                if isinstance(body, bytes):
                                    msg = body.decode('utf-8', errors='ignore').strip()
                                else:
                                    msg = body.strip()
                                # Append to log file
                                try:
                                    with open('terminal.log', 'a', encoding='utf-8') as f:
                                        f.write('{}\n'.format(msg))
                                except TypeError:
                                    # Python2 fallback
                                    with open('terminal.log', 'a') as f:
                                        f.write('{}\n'.format(msg))
                                # Print short console line
                                try:
                                    print('TERMINAL MSG: {}'.format(msg))
                                except Exception:
                                    pass
                            except Exception as e:
                                print('Error handling terminal message: {}'.format(e))
                            try:
                                ch.basic_ack(delivery_tag=method.delivery_tag)
                            except Exception:
                                try:
                                    ch.basic_ack()
                                except Exception:
                                    pass

                        try:
                            ch.basic_consume(queue=term_queue, on_message_callback=_cb, auto_ack=False)
                        except TypeError:
                            # pika 0.12.x
                            ch.basic_consume(_cb, queue=term_queue, no_ack=False)

                        ch.start_consuming()
                    except Exception as e:
                        print('Terminal consumer error: {}'.format(e))

        def watchdog():
            while robot.running and not state['should_quit']:
                robot.pulse()
                time.sleep(1.0)

        consumer_thread = threading.Thread(target=rabbitmq_consumer)
        consumer_thread.daemon = True
        consumer_thread.start()

        watchdog_thread = threading.Thread(target=watchdog)
        watchdog_thread.daemon = True
        watchdog_thread.start()

        while not state['should_quit']:
            left_motor_vel = state['left']
            right_motor_vel = state['right']

            if left_motor_vel == right_motor_vel:
                linear_vel = left_motor_vel
                angular_vel = 0
            else:
                linear_vel = 0
                angular_vel = (right_motor_vel - left_motor_vel) // 2

            key = get_key_nonblocking()
            if key is not None and key.lower() == 'z':
                print("\nShutdown requested by user...")
                state['should_quit'] = True
                break

            if linear_vel!= 0 or angular_vel!= 0:
                robot.set_velocity(linear_vel)
                robot.set_rot_velocity(angular_vel)
            else:
                robot.stop()

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nShutdown requested...")
    except Exception as e:
        print("\nError: {}".format(e))
    finally:
        state['should_quit'] = True
        robot.disconnect()
        print("Disconnected.")

if __name__ == "__main__":
    main()