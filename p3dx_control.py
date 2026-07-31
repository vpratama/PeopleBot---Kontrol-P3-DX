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
from dotenv import load_dotenv

# Muat variabel lingkungan dari file.env
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
            else:
                # Python 2.7: pyserial <3 expects str
                self.ser.write(''.join(chr(b) for b in full_packet))

    def connect(self):
        print("Connecting to robot...")
        for sync_cmd in [0, 1, 2]:
            self._send_packet(sync_cmd)
            time.sleep(0.1)
        self._send_packet(1)
        time.sleep(0.1)
        self._send_packet(4, arg_type=0x3B, arg_val=1)
        self.connected = True
        print("Robot connected and motors enabled.")

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
        if self.connected:
            self._send_packet(2)
        self.ser.close()

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