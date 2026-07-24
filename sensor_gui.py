import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from dotenv import load_dotenv
import pika

load_dotenv()

RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASSWORD = os.getenv('RABBITMQ_PASSWORD', 'guest')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST', '/')
RABBITMQ_QUEUE_SENSOR = os.getenv('RABBITMQ_QUEUE_SENSOR', 'sensor')

MAX_RANGE_MM = 5000
SENSOR_LABELS = [
    'S1 (Depan 0°)',
    'S2 (Depan-Kanan 45°)',
    'S3 (Kanan 90°)',
    'S4 (Belakang-Kanan 135°)',
    'S5 (Belakang 180°)',
    'S6 (Belakang-Kiri 225°)',
    'S7 (Kiri 270°)',
    'S8 (Depan-Kiri 315°)',
]


class SensorConsumerThread(threading.Thread):
    def __init__(self, data_queue):
        super().__init__(daemon=True)
        self.data_queue = data_queue
        self.connection = None
        self.channel = None
        self.stop_event = threading.Event()

    def connect(self):
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                virtual_host=RABBITMQ_VHOST,
                credentials=credentials,
            )
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=RABBITMQ_QUEUE_SENSOR, durable=True, auto_delete=True)
        print(f"[RABBITMQ] Terhubung ke {RABBITMQ_HOST}:{RABBITMQ_PORT} queue={RABBITMQ_QUEUE_SENSOR}")

    def run(self):
        try:
            self.connect()
            self.channel.basic_consume(
                queue=RABBITMQ_QUEUE_SENSOR,
                on_message_callback=self.on_message,
                auto_ack=True,
            )
            self.channel.start_consuming()
        except Exception as exc:
            print(f"[RABBITMQ] Error: {exc}")

    def on_message(self, ch, method, properties, body):
        try:
            payload = body.decode('utf-8', errors='ignore').strip()
            readings = [int(part.strip()) for part in payload.split(',') if part.strip()]
            if len(readings) == 8:
                self.data_queue.put(readings)
                print(f"[RABBITMQ] menerima: {payload}")
            else:
                print(f"[WARN] Format tidak valid: {payload}")
        except Exception as exc:
            print(f"[WARN] Gagal parsing pesan sensor: {exc}")

    def stop(self):
        self.stop_event.set()
        if self.connection and self.connection.is_open:
            self.connection.close()


class SensorRadarWindow:
    def __init__(self, root):
        self.root = root
        self.root.title('PeopleBot P3-DX Sensor 360° Viewer')
        self.root.geometry('780x760')
        self.root.configure(bg='#0f172a')

        self.data_queue = queue.Queue()
        self.consumer_thread = SensorConsumerThread(self.data_queue)
        self.consumer_thread.start()

        self.latest_readings = [0] * 8
        self.status_var = tk.StringVar(value='Menunggu data sensor...')

        title = ttk.Label(root, text='Pembacaan Sensor 360°', font=('Segoe UI', 16, 'bold'))
        title.pack(pady=(12, 6))

        self.status_label = ttk.Label(root, textvariable=self.status_var, foreground='#0f766e')
        self.status_label.pack(pady=(0, 8))

        self.canvas = tk.Canvas(root, width=650, height=650, bg='#111827', highlightthickness=0)
        self.canvas.pack()

        self.draw_static_layout()
        self.poll_queue()
        root.protocol('WM_DELETE_WINDOW', self.on_close)

    def draw_static_layout(self):
        self.canvas.delete('all')
        cx = 325
        cy = 325
        radius = 250
        self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline='#38bdf8', width=2)
        self.canvas.create_oval(cx - radius * 0.75, cy - radius * 0.75, cx + radius * 0.75, cy + radius * 0.75, outline='#1e40af', width=1)
        self.canvas.create_oval(cx - radius * 0.5, cy - radius * 0.5, cx + radius * 0.5, cy + radius * 0.5, outline='#1e40af', width=1)
        self.canvas.create_oval(cx - radius * 0.25, cy - radius * 0.25, cx + radius * 0.25, cy + radius * 0.25, outline='#1e40af', width=1)

        angles_deg = [0, 45, 90, 135, 180, 225, 270, 315]
        for angle_deg in angles_deg:
            angle_rad = angle_deg * 3.141592653589793 / 180.0
            x = cx + radius * 0.98 * __import__('math').cos(angle_rad)
            y = cy - radius * 0.98 * __import__('math').sin(angle_rad)
            self.canvas.create_line(cx, cy, x, y, fill='#334155', width=1)

        for idx, label in enumerate(SENSOR_LABELS):
            angle_deg = (idx * 45) % 360
            angle_rad = angle_deg * 3.141592653589793 / 180.0
            label_x = cx + (radius + 38) * __import__('math').cos(angle_rad)
            label_y = cy - (radius + 38) * __import__('math').sin(angle_rad)
            self.canvas.create_text(label_x, label_y, text=label, fill='#e2e8f0', font=('Segoe UI', 8), anchor='center')

        self.canvas.create_text(cx, cy, text='Center', fill='#fdba74', font=('Segoe UI', 10, 'bold'))

    def _normalize_radius(self, distance):
        if distance <= 0:
            return 0
        return max(0, min(distance, MAX_RANGE_MM)) / MAX_RANGE_MM * 240

    def update_plot(self, readings):
        self.latest_readings = readings
        self.status_var.set('Data sensor diterima dan dipetakan secara real-time')
        cx = 325
        cy = 325
        radius = 250

        self.canvas.delete('overlay')
        self.canvas.delete('radar')

        points = []
        for idx, distance in enumerate(readings):
            angle_deg = idx * 45
            angle_rad = angle_deg * 3.141592653589793 / 180.0
            r = self._normalize_radius(distance)
            x = cx + r * __import__('math').cos(angle_rad)
            y = cy - r * __import__('math').sin(angle_rad)
            points.append((x, y))
            color = ['#22c55e', '#14b8a6', '#38bdf8', '#60a5fa', '#818cf8', '#a78bfa', '#f59e0b', '#f87171'][idx]
            self.canvas.create_line(cx, cy, x, y, fill=color, width=2, tags='radar')
            self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=color, outline=color, tags='radar')

        polygon = []
        for x, y in points:
            polygon.extend([x, y])
        if polygon:
            self.canvas.create_polygon(polygon, fill='#22d3ee22', outline='#22d3ee', width=2, tags='overlay')

        self.canvas.create_text(cx, cy, text='Center', fill='#fdba74', font=('Segoe UI', 10, 'bold'), tags='overlay')

    def poll_queue(self):
        try:
            while True:
                readings = self.data_queue.get_nowait()
                self.update_plot(readings)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def on_close(self):
        self.consumer_thread.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = SensorRadarWindow(root)
    root.mainloop()


if __name__ == '__main__':
    main()
