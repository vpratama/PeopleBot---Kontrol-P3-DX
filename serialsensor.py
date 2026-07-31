# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import sys
import time

# === LOAD .env pakai python-dotenv ===
from dotenv import load_dotenv

# Load file .env yang ada di folder yang sama dengan script ini
# override=False biar tidak menimpa env yang sudah ada
base_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(base_dir, ".env")
load_dotenv(dotenv_path)

# Ambil SERIAL_PORT dari .env, default COM5
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM5")

# === FIX untuk Python 2.7 vs 3.8+ ===
ARIA_BIN = r"C:\Program Files\MobileRobots\Aria\bin"
ARIA_PYTHON = r"C:\Program Files\MobileRobots\Aria\python"

if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(ARIA_BIN)
else:
    if ARIA_BIN not in os.environ.get('PATH', ''):
        os.environ['PATH'] = ARIA_BIN + os.pathsep + os.environ.get('PATH', '')

if ARIA_PYTHON not in sys.path:
    sys.path.append(ARIA_PYTHON)

try:
    import AriaPy
except ImportError as e:
    print("GAGAL import AriaPy: %s" % e)
    print("Pastikan path ini benar: %s" % ARIA_PYTHON)
    sys.exit(1)

if hasattr(AriaPy, '__doc__') and AriaPy.__doc__:
    print(AriaPy.__doc__)

def read_aria_sensors(port=None):
    """
    Membaca data sensor dari PeopleBot P3-DX.
    Support Python 2.7 dan 3.x
    """
    if port is None:
        port = os.getenv("SERIAL_PORT", "COM5")

    AriaPy.Aria.init()
    robot = AriaPy.ArRobot()

    parser = AriaPy.ArArgumentParser(sys.argv)
    parser.addDefaultArgument("-rp %s" % port)

    if not AriaPy.Aria.parseArgs():
        AriaPy.Aria.logOptions()
        AriaPy.Aria.exit(1)

    sonar = AriaPy.ArSonarDevice()
    robot.addRangeDevice(sonar)

    conn = AriaPy.ArRobotConnector(parser, robot)
    if not conn.connectRobot():
        print("Error: Tidak dapat terhubung ke robot di port %s." % port)
        print("Cek .env SERIAL_PORT=%s" % port)
        AriaPy.Aria.logOptions()
        AriaPy.Aria.exit(1)

    robot.runAsync(True)

    print("Terhubung ke robot di port %s. Membaca sensor..." % port)
    print("Tekan Ctrl+C untuk berhenti.")
    try:
        while True:
            sensor_values_mm = []
            for i in range(8):
                sensor_values_mm.append(int(robot.getSonarRange(i)))

            formatted_output = ",".join([str(v) for v in sensor_values_mm])
            print("Pembacaan Sensor (mm): %s" % formatted_output)
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Program dihentikan oleh pengguna.")
    except Exception as e:
        print("Terjadi kesalahan: %s" % str(e))
    finally:
        print("Memutuskan koneksi...")
        robot.stopRunning()
        robot.waitForRunExit()
        AriaPy.Aria.exit(0)

if __name__ == "__main__":
    print("Menggunakan SERIAL_PORT dari .env: %s" % SERIAL_PORT)
    read_aria_sensors(port=SERIAL_PORT)