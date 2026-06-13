import sys
import random
import re
import math
import time
import struct
import serial
import serial.tools.list_ports
import pandas as pd
import osmnx as ox
import statistics
import asyncio
import websockets
import json
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene, QGraphicsView,
    QGraphicsPolygonItem, QGraphicsPathItem, QGraphicsDropShadowEffect,
    QWidget, QVBoxLayout, QLabel, QPushButton, QDialog, QHBoxLayout,
    QProgressBar, QFrame, QSlider, QScrollArea, QSizePolicy, QGraphicsItem,
    QComboBox, QMessageBox
)
from PyQt5.QtCore import Qt, QPointF, QTimer, QTimeLine, QRectF, QThread, pyqtSignal, QSize
from PyQt5.QtGui import (
    QPen, QColor, QBrush, QPolygonF, QPainter, QCursor,
    QLinearGradient, QFont, QTransform, QRadialGradient, QPainterPath
)

# ── AYARLAR ──────────────────────────────────────────────────────────────────
SERIAL_PORT       = "/dev/tty.usbmodem354A386F30331"
SERIAL_PORT_DAIRE = "/dev/tty.usbmodemXXXXXXXXX"
BAUD_RATE         = 115200
WS_PORT           = 8765
PLACE             = "Moda, Kadikoy, Istanbul, Turkey"
DIST              = 1000
DAIRE_REHBERI     = {}

# ── RENK PALETİ ──────────────────────────────────────────────────────────────
BG_COLOR    = QColor("#030309")
ROAD_COLOR  = QColor(0, 160, 255, 190)
WATER_COLOR = QColor("#000d1a")
PARK_COLOR  = QColor(0, 255, 100, 18)

NEON_BLUE   = QColor("#00f2ff")
NEON_RED    = QColor("#ff0055")
NEON_GREEN  = QColor("#00ff9d")
NEON_PURPLE = QColor("#aa00ff")
NEON_YELLOW = QColor("#ffcc00")

RISK_EDGE   = QColor(255, 40, 60)
SAFE_EDGE   = QColor(0, 180, 255)
GLASS_LIT   = QColor(255, 235, 160, 80)
GLASS_DARK  = QColor(10, 15, 28, 255)

# backward-compat aliases
RISK_BORDER = RISK_EDGE
RISK_FILL   = QColor(255, 30, 50, 120)
SAFE_BORDER = SAFE_EDGE
SAFE_FILL   = QColor(0, 180, 255, 80)
GLASS_COLOR = GLASS_LIT

# ── YARDIMCI ÇİZİM ───────────────────────────────────────────────────────────
def _gc(c, a):
    return QColor(c.red(), c.green(), c.blue(), a)

def draw_glow_poly(painter, poly, color, core_w=1.5):
    painter.setBrush(QBrush(Qt.NoBrush))
    for w, a in [(core_w+6, 18), (core_w, 240)]:
        painter.setPen(QPen(_gc(color, a), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPolygon(poly)

def face_brightness(x1, y1, x2, y2, cx, cy):
    dx, dy = x2 - x1, y2 - y1
    L = math.sqrt(dx*dx + dy*dy) or 1
    nx, ny = dy/L, -dx/L
    if nx*((x1+x2)/2 - cx) + ny*((y1+y2)/2 - cy) < 0:
        nx, ny = -nx, -ny
    dot = nx * 0.6 + ny * (-0.6)
    return max(0.15, min(0.92, (dot + 1) * 0.46))

# ── MOBİL SUNUCU ─────────────────────────────────────────────────────────────
class MobileSyncServer:
    def __init__(self):
        self.clients = set()
        self.loop = None
        self.thread = threading.Thread(target=self.run_server_thread, daemon=True)
        self.thread.start()

    def run_server_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.main_logic())
        except Exception as e:
            print(f"[!] Sunucu Hatası: {e}")

    async def main_logic(self):
        async with websockets.serve(self.handler, "0.0.0.0", WS_PORT, reuse_address=True):
            print(f"[*] Mobil Sunucu Aktif. Port: {WS_PORT}")
            await asyncio.Future()

    def get_local_ip(self):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "0.0.0.0"

    async def handler(self, websocket):
        self.clients.add(websocket)
        print(f"\n[BAĞLANTI] {websocket.remote_address} bağlandı.")
        try:
            welcome = {"roll": 0.0, "pitch": 0.0, "alt": 0.0, "magnitude": 0.0,
                       "is_recording": False, "type": "WELCOME"}
            await websocket.send(json.dumps(welcome))
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("status") == "IYIYIM":
                        kat = int(data.get("kat", 1))
                        daire = int(data.get("daire", 1))
                        bildirim = {"ad": data.get("name", "Bilinmiyor"),
                                    "tc": data.get("tc", "11111111111"),
                                    "saat": data.get("saat", "00:00"),
                                    "konum": data.get("konum", "0,0")}
                        if (kat, daire) not in DAIRE_REHBERI:
                            DAIRE_REHBERI[(kat, daire)] = []
                        DAIRE_REHBERI[(kat, daire)].append(bildirim)
                        print(f"\n{'!'*50}\nHAYAT İZİ: Kat {kat}, Daire {daire} - {bildirim['ad']}\n{'!'*50}\n")
                except Exception as e:
                    print(f"[!] Mesaj hatası: {e}")
        except websockets.exceptions.ConnectionClosed:
            print(f"[-] {websocket.remote_address} ayrıldı.")
        finally:
            self.clients.discard(websocket)

    def broadcast_data(self, data):
        if self.loop and self.loop.is_running() and self.clients:
            asyncio.run_coroutine_threadsafe(self._send_to_all(data), self.loop)

    async def _send_to_all(self, data):
        if self.clients:
            msg = json.dumps(data)
            to_remove = set()
            for client in self.clients:
                try:
                    await client.send(msg)
                except:
                    to_remove.add(client)
            self.clients -= to_remove

MOBILE_SERVER = MobileSyncServer()

# ── MSP HANDLER ──────────────────────────────────────────────────────────────
class MspHandler:
    def __init__(self, port_name):
        self.port_name = port_name
        self.baud_rate = 115200
        self.ser = None
        self.connected = False

    def connect(self):
        try:
            self.ser = serial.Serial(self.port_name, self.baud_rate, timeout=0.1)
            if self.ser.is_open:
                self.connected = True
                print(f"[BAŞARILI] {self.port_name} portuna bağlanıldı.")
                return True
        except:
            return False

    def send_msp_request(self, command_code):
        if not self.connected or not self.ser:
            return None
        try:
            request = struct.pack('<3sBBB', b'$M<', 0, command_code, command_code)
            self.ser.write(request)
        except:
            self.connected = False

    def get_imu_data(self):
        if not self.connected:
            return None
        try:
            self.send_msp_request(102)
            response = self.ser.read(24)
            if len(response) < 24 or response[:3] != b'$M>':
                return None
            data = struct.unpack('<3sBB9hB', response)
            return {'ax': data[3], 'ay': data[4], 'az': data[5]}
        except:
            return None

    def get_altitude_data(self):
        if not self.connected:
            return None
        try:
            self.send_msp_request(109)
            response = self.ser.read(12)
            if len(response) < 12 or response[:3] != b'$M>':
                return None
            data = struct.unpack('<3sBBihB', response)
            return data[3]
        except:
            return None

    def close(self):
        if self.ser:
            self.ser.close()

# ── JEOSKOP WORKER ───────────────────────────────────────────────────────────
class JeoskopWorker(QThread):
    orientation_signal = pyqtSignal(float, float, float)
    raw_imu_signal     = pyqtSignal(int, int, int)   # ham ax, ay, az — PGA için
    status_signal      = pyqtSignal(bool, str)

    def run(self):
        msp = MspHandler(SERIAL_PORT)
        if not msp.connect():
            self.status_signal.emit(False, "Bağlantı Başarısız")
            return
        self.status_signal.emit(True, "Jeoskop + Altimetre Aktif")
        while self.isRunning():
            imu = msp.get_imu_data()
            alt = msp.get_altitude_data()
            current_alt = float(alt) if alt is not None else 0.0
            if imu:
                ax, ay, az = imu['ax'], imu['ay'], imu['az']
                self.raw_imu_signal.emit(ax, ay, az)
                roll = math.atan2(ay, az) * 57.295
                pitch = math.atan2(-ax, math.sqrt(ay*ay + az*az)) * 57.295
                self.orientation_signal.emit(roll, pitch, current_alt)
            else:
                self.orientation_signal.emit(0.0, 0.0, current_alt)
            time.sleep(0.04)
        msp.close()

# ── MATH YARDIMCILARI ─────────────────────────────────────────────────────────
def apply_rotation_3d(x, y, z, pitch, yaw, roll):
    rp = math.radians(pitch)
    ry = math.radians(yaw)
    rr = math.radians(roll)
    y1 = y * math.cos(rp) - z * math.sin(rp)
    z1 = y * math.sin(rp) + z * math.cos(rp)
    x1 = x
    x2 = x1 * math.cos(ry) - z1 * math.sin(ry)
    z2 = x1 * math.sin(ry) + z1 * math.cos(ry)
    y2 = y1
    x3 = x2 * math.cos(rr) - y2 * math.sin(rr)
    y3 = x2 * math.sin(rr) + y2 * math.cos(rr)
    z3 = z2
    return x3, y3, z3

def parse_height(row):
    h = 0
    if 'building:levels' in row and pd.notna(row['building:levels']):
        try:
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(row['building:levels']))
            if nums:
                h = float(nums[0]) * 3.5
        except:
            pass
    elif 'height' in row and pd.notna(row['height']):
        try:
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(row['height']))
            if nums:
                h = float(nums[0])
        except:
            pass
    if h == 0:
        r = random.random()
        if r < 0.7:
            h = random.randint(12, 24)
        elif r < 0.9:
            h = random.randint(27, 54)
        else:
            h = random.randint(60, 120)
    return h

# ── DOĞRU PGA / MMI FİZİĞİ ───────────────────────────────────────────────────
# Betaflight/Cleanflight MSP: ivmeölçer ham değeri tipik olarak 512 LSB/g (MPU-6050 ±2g modu)
ACC_LSB_PER_G = 512.0

def raw_to_pga_g(ax_raw, ay_raw):
    """Ham ivmeölçer değerlerinden yatay PGA (g cinsinden).
    Z ekseni yerçekimi taşır; deprem için X-Y yatay bileşeni anlamlıdır."""
    return math.sqrt((ax_raw / ACC_LSB_PER_G)**2 + (ay_raw / ACC_LSB_PER_G)**2)

def pga_to_mmi(pga_g):
    """Wald et al. 1999 — PGA(g) → MMI (Değiştirilmiş Mercalli Şiddeti).
    USGS ShakeMap metodolojisi ile uyumlu."""
    pga_cms2 = pga_g * 980.665
    if pga_cms2 < 0.17:
        return 1.0
    return max(1.0, min(12.0, 3.66 * math.log10(pga_cms2) - 1.66))

def mmi_info(mmi):
    for thr, label, col in [
        (2,"Hissedilmez","#888888"),(3,"Çok Hafif","#c8f0c8"),
        (4,"Hafif","#80e080"),(5,"Ilımlı","#ffff50"),
        (6,"Orta","#ffd700"),(7,"Güçlü","#ff8c00"),
        (8,"Çok Güçlü","#ff4500"),(9,"Yıkıcı","#cc0000"),
        (10,"Aşırı Yıkıcı","#880000"),(12,"Felaket","#440000"),
    ]:
        if mmi < thr:
            return label, col
    return "Felaket", "#440000"

def damage_ratios_from_mmi(mmi):
    """HAZUS (2003) basitleştirilmiş hasar oranları — (sağlam%, hafif%, orta%, ağır%, yıkık%)"""
    m = max(1.0, min(12.0, mmi))
    if m < 5:   return 98, 2,  0,  0,  0
    if m < 6:   return 80, 15, 4,  1,  0
    if m < 7:   return 50, 24, 16, 8,  2
    if m < 8:   return 30, 20, 20, 20, 10
    if m < 9:   return 15, 15, 20, 25, 25
    if m < 10:  return  5,  8, 15, 32, 40
    return               2,  4, 10, 24, 60

def sim_district(mmi):
    """MMI'ya göre ilçe hasarı simülasyonu (Kadıköy/Moda 1km yarıçap)."""
    total_b  = 847
    r        = damage_ratios_from_mmi(mmi)
    intact   = int(total_b * r[0] / 100)
    light    = int(total_b * r[1] / 100)
    moderate = int(total_b * r[2] / 100)
    heavy    = int(total_b * r[3] / 100)
    destroyed = max(0, total_b - intact - light - moderate - heavy)
    avg_occ  = 9
    trapped  = int((heavy * 0.28 + destroyed * 0.65) * avg_occ)
    alive0   = int(trapped * 0.38)
    dead0    = int(trapped * 0.09)
    missing  = max(0, trapped - alive0 - dead0)
    gas_leaks = int((moderate + heavy + destroyed) * 0.18)
    fires    = max(0, int(gas_leaks * 0.14))
    return dict(
        mmi=mmi, total_b=total_b, intact=intact, light=light,
        moderate=moderate, heavy=heavy, destroyed=destroyed,
        trapped=trapped, alive=alive0, missing=missing, dead=dead0,
        gas_leaks=gas_leaks, fires=fires,
        afad_teams=12, k9=4, crane=3,
        hospital_cap=520, hospital_used=int(dead0*1.8 + alive0*0.4),
    )

# Hayatta kalma eğrisi — INSARAG gerçek saha verileri (saat, %)
SURVIVAL_CURVE = [
    (0,100),(3,97),(6,91),(12,81),(18,72),(24,62),
    (36,48),(48,35),(60,25),(72,18),(84,13),(96,9),(120,5),
]

AFAD_TEAM_DEFS = [
    (1,"KRT-1","Arama Kurtarma A","Moda Cad. No:12","#ff0055"),
    (2,"KRT-2","Arama Kurtarma B","Bahariye Cad. No:34","#ff0055"),
    (3,"KRT-3","Arama Kurtarma C","Söğütlüçeşme Cad.","#ff0055"),
    (4,"KRT-4","Arama Kurtarma D","Rıhtım Cad. No:7","#ff0055"),
    (5,"ILK-1","İlk Yardım A","Kadıköy Meydanı","#00ff9d"),
    (6,"ILK-2","İlk Yardım B","Moda Parkı","#00ff9d"),
    (7,"MUH-1","Hasar Tespit A","Çarşı Bölgesi","#ffcc00"),
    (8,"MUH-2","Hasar Tespit B","Kızıltoprak","#ffcc00"),
    (9,"GZ-1", "Gaz Acil","Mühürdar Cad.","#ff8c00"),
    (10,"ITF-1","İtfaiye","Moda Yangın","#ff4500"),
    (11,"LOG-1","Lojistik A","Kadıköy İskele","#00aaff"),
    (12,"LOG-2","Lojistik B","Hasanpaşa Depo","#00aaff"),
]

LIVE_EVENTS_TEMPLATE = [
    (0,  "🔴","DEPREM ALARM","M{mag} depremi tespit edildi — 06:47:23"),
    (15, "🟠","KRİZ MERKEZİ","Kadıköy Afet Koordinasyon Merkezi devrede"),
    (30, "🔵","AFAD-KRT-1","Moda Cad No:12 kurtarma başladı — {trapped} kişi enkaz altında"),
    (45, "🟡","GAZ ALARM","Mühürdar Cad. No:45 doğalgaz kaçağı — tahliye"),
    (60, "🔴","YANGIN","Bahariye Cad. yangın — {fires} noktada — ITF-1 yönlendirildi"),
    (90, "🟢","KURTARMA","KRT-1 — 2 kişi enkaz altından çıkarıldı, bilinçli"),
    (120,"🔵","K9 BİRLİĞİ","Köpek birliği KRT-2 ile Söğütlüçeşme'de tarama"),
    (150,"🟢","KURTARMA","KRT-2 — 1 kişi hayatta, sağlık birimine teslim"),
    (180,"🟡","ALTYAPI","İSKİ: Rıhtım hattında su kesintisi — onarım ekibi yolda"),
    (210,"🟠","GAZ İZOL.","GZ-1: {gas_leaks} binada gaz vanası kapatıldı"),
    (240,"🟢","KURTARMA","KRT-4 — 3 kişi, bilinçli, soğuklama yok"),
    (270,"🔵","SAĞLIK","112: 47 yaralı Kadıköy Hastanesi'ne sevk"),
    (300,"🟢","KURTARMA","KRT-1 K9 ile 7. hayatta kişi tespit edildi"),
    (360,"🟡","MÜHENDİSLİK","MUH-1: {heavy} bina ağır hasarlı — GİRİŞ YASAK"),
    (420,"💡","AI SİSTEM","Öneri: KRT-2 → Söğütlüçeşme Apt B blok önceliklendirildi"),
    (480,"🟢","KURTARMA","KRT-3 — 4 kişi daha, toplam kurtarılan: 17"),
    (540,"🔴","YAPI","Bahariye Apt. zemin katta çökme riski — bölge güvenli kapalı"),
    (600,"🟢","KURTARMA","KRT-2 — 2 çocuk, sağlıklı, ailesine teslim edildi"),
    (660,"🔵","SAĞLIK","112: Toplam {alive} yaralı tedavi altında"),
    (720,"🟠","GAZ","GZ-1: Tüm gaz hattı izolasyonu tamamlandı — güvenli"),
    (780,"💡","AI SİSTEM","Hayatta kalma tahmini düşüyor — ek K9 talebi"),
    (840,"🟢","KURTARMA","KRT-3 — 5. saat, 23. kişi kurtarıldı"),
    (900,"🔵","ELEKTRİK","BEDAŞ: Kritik bölgede elektrik kesintisi güvenlik amaçlı"),
    (960,"🟡","DEĞERLENDİRME","MUH-2: {destroyed} bina yıkılmış, acil yıkım listesi hazırlanıyor"),
]

# ── SİSMİK DALGA GRAFİĞİ — SPEKTRAL EDİSYON ─────────────────────────────────
class SeismicWaveform(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.data_points = []
        self.max_points = 120
        self.setStyleSheet("background: transparent;")

    def add_point(self, magnitude, is_active=False):
        self.data_points.append((magnitude, is_active))
        if len(self.data_points) > self.max_points:
            self.data_points.pop(0)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(12, 12, 28, 255))
        bg.setColorAt(1, QColor(4, 4, 12, 255))
        painter.fillRect(0, 0, w, h, QBrush(bg))

        # grid
        painter.setPen(QPen(QColor(255, 255, 255, 12), 1))
        for frac in [0.25, 0.5, 0.75]:
            painter.drawLine(0, int(h*frac), w, int(h*frac))
            painter.drawLine(int(w*frac), 0, int(w*frac), h)

        # center glow line
        for lw, la in [(5, 8), (2, 30), (1, 120)]:
            painter.setPen(QPen(_gc(NEON_BLUE, la), lw))
            painter.drawLine(0, h//2, w, h//2)

        if not self.data_points:
            painter.setPen(QPen(_gc(NEON_BLUE, 40), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(0, 0, w-1, h-1)
            return

        bar_w = w / self.max_points
        for i, (mag, is_rec) in enumerate(self.data_points):
            x = i * bar_w
            bar_h = max(3, (mag / 100) * (h * 0.85))
            y_top = (h - bar_h) / 2

            if is_rec:
                if mag < 25:
                    ct, cb = NEON_GREEN, QColor(0, 100, 50)
                elif mag < 55:
                    ct, cb = NEON_YELLOW, QColor(110, 70, 0)
                else:
                    ct, cb = NEON_RED, QColor(140, 0, 25)
                alpha = 230
            else:
                ct, cb = QColor(70, 70, 110), QColor(25, 25, 45)
                alpha = 100

            grad = QLinearGradient(x, y_top, x, y_top + bar_h)
            grad.setColorAt(0, _gc(ct, alpha))
            grad.setColorAt(0.5, _gc(ct, int(alpha * 0.65)))
            grad.setColorAt(1, _gc(cb, int(alpha * 0.4)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawRect(QRectF(x, y_top, max(1, bar_w - 0.5), bar_h))

            if is_rec and mag > 15:
                glow = QRadialGradient(x + bar_w/2, y_top, bar_w * 3)
                glow.setColorAt(0, _gc(ct, 60))
                glow.setColorAt(1, _gc(ct, 0))
                painter.setBrush(QBrush(glow))
                painter.drawRect(QRectF(x - bar_w, y_top - bar_w*2, bar_w*3, bar_w*3))

        painter.setPen(QPen(_gc(NEON_BLUE, 50), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(0, 0, w-1, h-1)

    def clear_data(self):
        self.data_points = []
        self.update()


# ── 3D GÖRÜNÜM — GERÇEK AYDINLATMA + NEON GLOW ───────────────────────────────
class Interactive3DView(QGraphicsView):
    def __init__(self, polygon_points, height, status, show_grid=True, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setStyleSheet("background-color: #030309; border: none;")
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.raw_points = polygon_points
        self.height = height * 5.0
        self.status = status
        self.show_grid = show_grid

        avg_x = sum(p.x() for p in polygon_points) / len(polygon_points)
        avg_y = sum(p.y() for p in polygon_points) / len(polygon_points)
        scale = 4.0
        self.base_coords = [((p.x()-avg_x)*scale, (p.y()-avg_y)*scale) for p in polygon_points]

        self.cam_yaw   = 45.0
        self.cam_pitch = 20.0
        self.model_pitch = self.model_roll = self.model_alt = 0.0
        self.offset_pitch = self.offset_roll = self.offset_alt = 0.0
        self.last_raw_pitch = self.last_raw_roll = self.last_raw_alt = 0.0
        self._smooth_alt = 0.0   # EMA filtreli yükseklik
        self.last_mouse_pos = None

        # Pencere animasyonu — sensör yoksa 1fps yeterli, sensör varken her veri gelişinde tetiklenir
        self._win_timer = QTimer()
        self._win_timer.timeout.connect(self.draw_frame)
        self._win_timer.start(1000)

        self.draw_frame()

    def set_static_angles(self, roll, pitch, alt=0):
        self.model_roll  = roll
        self.model_pitch = pitch
        self.model_alt   = alt * 0.15
        self.draw_frame()

    def set_front_view(self):
        self.cam_yaw = 0
        self.cam_pitch = 0
        self.draw_frame()

    def calibrate_sensor(self):
        self.offset_roll  = self.last_raw_roll
        self.offset_pitch = self.last_raw_pitch
        self.offset_alt   = self.last_raw_alt
        self.update_rotation_from_sensor(self.last_raw_roll, self.last_raw_pitch, self.last_raw_alt)
        print(f"Kalibre Edildi. Ref Alt={self.offset_alt:.1f}cm")

    def update_rotation_from_sensor(self, roll, pitch, alt_cm):
        self.last_raw_roll  = roll
        self.last_raw_pitch = pitch
        self.last_raw_alt   = alt_cm

        cal_roll  = roll  - self.offset_roll
        cal_pitch = pitch - self.offset_pitch
        cal_alt   = alt_cm - self.offset_alt

        # 1:1 açı — amplifikasyon yok
        self.model_roll  = cal_roll
        self.model_pitch = cal_pitch

        # Altimetre: EMA low-pass filtresi (alpha=0.08) + deadband ±3cm
        self._smooth_alt += 0.08 * (cal_alt - self._smooth_alt)
        if abs(self._smooth_alt) < 3.0:
            self._smooth_alt = 0.0
        self.model_alt = self._smooth_alt * 0.15   # gürültüyü bastır

        self.draw_frame()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is not None:
            delta = event.pos() - self.last_mouse_pos
            self.cam_yaw   += delta.x() * 0.5
            self.cam_pitch += delta.y() * 0.5
            self.cam_pitch = max(-90, min(90, self.cam_pitch))
            self.last_mouse_pos = event.pos()
            self.draw_frame()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.last_mouse_pos = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def draw_frame(self):
        self.scene.clear()
        t = time.time()

        edge_color = RISK_EDGE if self.status == 'red' else SAFE_EDGE
        vshift = -self.model_alt
        n = len(self.base_coords)
        cx = sum(c[0] for c in self.base_coords) / n
        cy = sum(c[1] for c in self.base_coords) / n
        faces = []

        for i in range(n):
            x1, y1 = self.base_coords[i]
            x2, y2 = self.base_coords[(i+1) % n]
            z_base =  self.height / 2
            z_roof = -self.height / 2

            def tv(vx, vy, vz):
                mx, my, mz = apply_rotation_3d(vx, vz, vy, self.model_pitch, 0, self.model_roll)
                cx2, cy2, cz2 = apply_rotation_3d(mx, my, mz, self.cam_pitch, self.cam_yaw, 0)
                return cx2, cy2 + vshift, cz2

            t1x, t1y, d1 = tv(x1, y1, z_base)
            t2x, t2y, d2 = tv(x2, y2, z_base)
            r2x, r2y, d3 = tv(x2, y2, z_roof)
            r1x, r1y, d4 = tv(x1, y1, z_roof)

            poly = QPolygonF([QPointF(t1x,t1y), QPointF(t2x,t2y), QPointF(r2x,r2y), QPointF(r1x,r1y)])
            bright = face_brightness(x1, y1, x2, y2, cx, cy)
            faces.append({
                'poly': poly, 'depth': (d1+d2+d3+d4)/4,
                'type': 'wall', 'bright': bright,
                'pts': [(t1x,t1y),(t2x,t2y),(r2x,r2y),(r1x,r1y)],
                'wall_idx': i
            })

        def add_surf(z_level, typ):
            pts, ds = [], 0
            for x, y in self.base_coords:
                mx, my, mz = apply_rotation_3d(x, z_level, y, self.model_pitch, 0, self.model_roll)
                cx2, cy2, cz2 = apply_rotation_3d(mx, my, mz, self.cam_pitch, self.cam_yaw, 0)
                pts.append(QPointF(cx2, cy2 + vshift))
                ds += cz2
            faces.append({'poly': QPolygonF(pts), 'depth': ds/len(pts), 'type': typ})

        add_surf(-self.height/2, 'roof')
        add_surf( self.height/2, 'base')
        faces.sort(key=lambda f: f['depth'], reverse=True)

        # Animated grid
        if self.show_grid:
            pulse_a = int(18 + 10 * math.sin(t * 1.8))
            gpen = QPen(_gc(NEON_BLUE, pulse_a), 0.7)
            gsz, step = 500, 80
            for gi in range(-gsz, gsz+1, step):
                p1x, p1y, _ = apply_rotation_3d(-gsz, self.height/2+12, gi, self.cam_pitch, self.cam_yaw, 0)
                p2x, p2y, _ = apply_rotation_3d( gsz, self.height/2+12, gi, self.cam_pitch, self.cam_yaw, 0)
                self.scene.addLine(p1x, p1y, p2x, p2y, gpen).setZValue(-100)
                p3x, p3y, _ = apply_rotation_3d(gi, self.height/2+12, -gsz, self.cam_pitch, self.cam_yaw, 0)
                p4x, p4y, _ = apply_rotation_3d(gi, self.height/2+12,  gsz, self.cam_pitch, self.cam_yaw, 0)
                self.scene.addLine(p3x, p3y, p4x, p4y, gpen).setZValue(-100)

        for face in faces:
            if face['type'] == 'wall':
                br = face['bright']
                if self.status == 'red':
                    rc, gc_val, bc_val = int(65*br), int(8*br), int(18*br)
                else:
                    rc, gc_val, bc_val = int(4*br), int(32*br), int(78*br)
                wall_c = QColor(rc, gc_val, bc_val, 225)

                item = QGraphicsPolygonItem(face['poly'])
                item.setBrush(QBrush(wall_c))
                item.setPen(QPen(_gc(edge_color, 35), 0.5))
                self.scene.addItem(item)

                pts = face['pts']
                p1, p2, p3, p4 = pts
                cols = 4
                rows = max(1, int(self.height / 15))
                wi = face['wall_idx']

                # Batch all windows into two paths (lit vs dark) — much faster
                path_warm = QPainterPath()
                path_blue = QPainterPath()
                path_dark = QPainterPath()

                for row_i in range(rows):
                    rt = (row_i + 0.12) / rows
                    rb = (row_i + 0.88) / rows
                    lx  = p4[0] + (p1[0]-p4[0])*rt;  ly  = p4[1] + (p1[1]-p4[1])*rt
                    rx  = p3[0] + (p2[0]-p3[0])*rt;  ry  = p3[1] + (p2[1]-p3[1])*rt
                    lxb = p4[0] + (p1[0]-p4[0])*rb;  lyb = p4[1] + (p1[1]-p4[1])*rb
                    rxb = p3[0] + (p2[0]-p3[0])*rb;  ryb = p3[1] + (p2[1]-p3[1])*rb

                    for col_i in range(cols):
                        cl = (col_i + 0.12) / cols
                        cr = (col_i + 0.88) / cols
                        wx1 = lx  + (rx -lx )*cl;  wy1 = ly  + (ry -ly )*cl
                        wx2 = lx  + (rx -lx )*cr;  wy2 = ly  + (ry -ly )*cr
                        wx3 = lxb + (rxb-lxb)*cr;  wy3 = lyb + (ryb-lyb)*cr
                        wx4 = lxb + (rxb-lxb)*cl;  wy4 = lyb + (ryb-lyb)*cl

                        seed = wi*97 + row_i*13 + col_i*7
                        is_lit = (int(t / (2.0 + (seed%8)*0.5)) + seed) % 4 != 0
                        p = QPainterPath()
                        p.addPolygon(QPolygonF([QPointF(wx1,wy1),QPointF(wx2,wy2),QPointF(wx3,wy3),QPointF(wx4,wy4)]))
                        if is_lit:
                            if seed % 3 != 0:
                                path_warm.addPath(p)
                            else:
                                path_blue.addPath(p)
                        else:
                            path_dark.addPath(p)

                for path, fill_c in [
                    (path_warm, GLASS_LIT),
                    (path_blue, QColor(100, 180, 255, 85)),
                    (path_dark, GLASS_DARK),
                ]:
                    if not path.isEmpty():
                        pi = QGraphicsPathItem(path)
                        pi.setBrush(QBrush(fill_c))
                        pi.setPen(QPen(Qt.NoPen))
                        self.scene.addItem(pi)

                # glow edge passes
                for gw, ga in [(6,10),(1.5,200)]:
                    ge = QGraphicsPolygonItem(face['poly'])
                    ge.setBrush(QBrush(Qt.NoBrush))
                    ge.setPen(QPen(_gc(edge_color, ga), gw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    self.scene.addItem(ge)

            elif face['type'] == 'roof':
                rc_val = QColor(90, 8, 18, 225) if self.status=='red' else QColor(6, 28, 65, 225)
                item = QGraphicsPolygonItem(face['poly'])
                item.setBrush(QBrush(rc_val))
                item.setPen(QPen(_gc(edge_color, 220), 2))
                self.scene.addItem(item)
                for gw, ga in [(8,12),(2,90)]:
                    ge = QGraphicsPolygonItem(face['poly'])
                    ge.setBrush(QBrush(Qt.NoBrush))
                    ge.setPen(QPen(_gc(edge_color, ga), gw))
                    self.scene.addItem(ge)
                center = item.boundingRect().center()
                txt = self.scene.addText("H")
                txt.setDefaultTextColor(edge_color)
                txt.setFont(QFont("Arial", 10, QFont.Bold))
                txt.setPos(center.x()-8, center.y()-12)

            elif face['type'] == 'base':
                item = QGraphicsPolygonItem(face['poly'])
                item.setBrush(QBrush(QColor(3, 3, 10, 180)))
                item.setPen(QPen(_gc(edge_color, 60), 1))
                self.scene.addItem(item)


# ── RAPOR PENCERESİ ───────────────────────────────────────────────────────────
class EarthquakeReportDialog(QDialog):
    def __init__(self, start_data, end_data, stats, polygon_points, height, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DEPREM SİMÜLASYON RAPORU")
        self.resize(1200, 750)
        self.setStyleSheet("""
            QDialog { background-color: #06060f; color: white; }
            QLabel { color: #ccc; }
        """)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        header = QLabel("STATİK YAPI VE ZEMİN ANALİZİ")
        header.setStyleSheet("""
            font-size: 26px; font-weight: 900; color: #00f2ff;
            letter-spacing: 4px; padding: 14px;
            border-bottom: 2px solid #00f2ff;
        """)
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)

        model_layout = QHBoxLayout()
        for label_text, label_bg, data, s in [
            ("BAŞLANGIÇ  T=0", "#00ff9d", start_data, "green"),
            ("FİNAL  T=End",   "#ff0055", end_data,   "red")
        ]:
            container = QWidget()
            container.setStyleSheet("background:#0b0b1a; border:1px solid #222; border-radius:8px;")
            vl = QVBoxLayout(container)
            lbl = QLabel(label_text)
            lbl.setAlignment(Qt.AlignCenter)
            bg = label_bg
            lbl.setStyleSheet(f"background:{bg}; color:{'black' if s=='green' else 'white'}; font-weight:900; padding:6px; border-radius:4px; letter-spacing:2px;")
            view = Interactive3DView(polygon_points, height, s, show_grid=False)
            view.set_static_angles(data['roll'], data['pitch'], data['alt'])
            vl.addWidget(lbl)
            vl.addWidget(view)
            model_layout.addWidget(container)
        self.model_layout_ref = model_layout
        main_layout.addLayout(model_layout, stretch=2)

        delta_roll  = abs(end_data['roll']  - start_data['roll'])
        delta_pitch = abs(end_data['pitch'] - start_data['pitch'])
        max_angle   = max(delta_roll, delta_pitch)
        mac         = stats['max_alt_change']
        if mac > 50:
            st, sc = "ÇOK YÜKSEK RİSK — ZEMİN ÇÖKMESİ TESPİT EDİLDİ", "#ff0000"
        elif max_angle > 5:
            st, sc = "AĞIR HASARLI — Yıkım Riski Yüksek", "#ff0000"
        elif max_angle > 1 or mac > 20:
            st, sc = "DENETİM GEREKLİ — Yapısal/Zemin Deformasyon", "#ffcc00"
        else:
            st, sc = "GÜVENLİ — Elastik Sınırlar İçinde", "#00ff9d"

        report_frame = QFrame()
        report_frame.setStyleSheet("background:#0d0d22; border:1px solid #00f2ff44; border-radius:10px; padding:14px;")
        rl = QVBoxLayout(report_frame)
        html = f"""
        <h3 style='color:#00f2ff; letter-spacing:2px;'>SONUÇ DEĞERLENDİRMESİ</h3>
        <table width='100%' cellpadding='6'>
        <tr><td style='color:#778;'>Test Süresi</td><td style='color:white;'><b>{stats['duration']:.2f} sn</b></td></tr>
        <tr><td style='color:#778;'>Açısal Deformasyon</td><td style='color:#ffcc00;'><b>{max_angle:.2f}°</b></td></tr>
        <tr><td style='color:#778;'>Maks. Dikey Hareket (Heave)</td><td style='color:#00aaff;'><b>{mac:.1f} cm</b></td></tr>
        <tr><td style='color:#778;'>Maks. Anlık Eğim</td><td style='color:white;'><b>{stats['max_roll']:.1f}° / {stats['max_pitch']:.1f}°</b></td></tr>
        <tr><td style='color:#778;'>Kritik Kuvvet Yönü</td><td style='color:#00f2ff;'><b>{stats['force_direction']}</b></td></tr>
        <tr><td style='color:#778;'>Tahmini G-Kuvveti</td><td style='color:#ff0055;'><b>{stats['g_force']:.2f} G</b></td></tr>
        <tr><td style='color:#778;'>YAPI DURUMU</td><td style='color:{sc}; font-size:15px;'><b>{st}</b></td></tr>
        </table>"""
        lbl_report = QLabel(html)
        lbl_report.setTextFormat(Qt.RichText)
        rl.addWidget(lbl_report)
        main_layout.addWidget(report_frame, stretch=1)

        btn_layout = QHBoxLayout()
        self._views = []
        for btn_txt, btn_col, btn_fn in [
            ("HİZALA (2D)", "#00aaff", self._align_views),
            ("RAPORU KAPAT", "#1a1a3e", self.close),
        ]:
            b = QPushButton(btn_txt)
            b.setStyleSheet(f"QPushButton{{background:{btn_col};color:white;padding:12px 24px;font-weight:900;border-radius:6px;font-size:13px;}} QPushButton:hover{{opacity:0.85;}}")
            b.clicked.connect(btn_fn)
            btn_layout.addWidget(b)
        main_layout.addLayout(btn_layout)

    def _align_views(self):
        for v in self.findChildren(Interactive3DView):
            v.set_front_view()


# ── DAİRE LİSTESİ ─────────────────────────────────────────────────────────────
class ApartmentListDialog(QDialog):
    def __init__(self, floors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Daire Detay Listesi")
        self.resize(520, 620)
        self.setStyleSheet("""
            QDialog{background:#06060f; color:white;}
            QScrollArea{border:none;}
            QFrame{border-radius:6px;}
        """)
        layout = QVBoxLayout(self)

        hdr = QLabel("DAİRE KONTROL PANELİ")
        hdr.setStyleSheet("font-size:18px;font-weight:900;color:#00f2ff;letter-spacing:3px;padding:10px;border-bottom:1px solid #00f2ff44;")
        hdr.setAlignment(Qt.AlignCenter)
        layout.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#06060f;")
        content = QWidget()
        scroll_layout = QVBoxLayout(content)
        scroll_layout.setSpacing(4)

        for f in range(floors, 0, -1):
            floor_frame = QFrame()
            floor_frame.setStyleSheet("background:#0d0d20; border:1px solid #1a1a35; border-radius:6px; padding:4px;")
            fl = QHBoxLayout(floor_frame)
            lbl = QLabel(f"{f}. Kat")
            lbl.setStyleSheet("color:#00f2ff; font-weight:bold; min-width:60px; font-size:12px;")
            fl.addWidget(lbl)
            for d in range(1, 5):
                has_data = (f, d) in DAIRE_REHBERI and DAIRE_REHBERI[(f, d)]
                btn = QPushButton(f"Daire {d}")
                if has_data:
                    btn.setStyleSheet("QPushButton{background:#00ff9d;color:black;font-weight:900;border-radius:4px;padding:6px 10px;} QPushButton:hover{background:#33ffb5;}")
                else:
                    btn.setStyleSheet("QPushButton{background:#12122a;color:#556;border:1px solid #222;border-radius:4px;padding:6px 10px;} QPushButton:hover{border-color:#00f2ff;color:#00f2ff;}")
                btn.clicked.connect(lambda checked, k=f, da=d: self.show_apartment_details(k, da))
                fl.addWidget(btn)
            scroll_layout.addWidget(floor_frame)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def show_apartment_details(self, kat, daire):
        win = QDialog(self)
        win.setWindowTitle(f"{kat}. Kat — Daire {daire}")
        win.setMinimumSize(600, 460)
        win.setStyleSheet("background:#050510; color:white;")
        layout = QVBoxLayout(win)

        title = QLabel(f"KAT {kat}  ·  DAİRE {daire}  — SENSÖR VERİLERİ")
        title.setStyleSheet("font-size:16px;font-weight:900;color:#00f2ff;letter-spacing:2px;padding:10px;border-bottom:1px solid #00f2ff33;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sensor_row = QHBoxLayout()
        for icon, name, val in [
            ("🌡", "SICAKLIK", f"{random.randint(18,25)}°C"),
            ("🫁", "OKSİJEN",  f"%{random.randint(19,21)}"),
            ("🔊", "SES",       f"{random.randint(40,70)} dB"),
        ]:
            box = QFrame()
            box.setStyleSheet("background:#0d0d22; border:1px solid #00f2ff33; border-radius:8px; padding:12px;")
            bl = QVBoxLayout(box)
            il = QLabel(icon)
            il.setStyleSheet("font-size:28px;")
            il.setAlignment(Qt.AlignCenter)
            nl = QLabel(name)
            nl.setStyleSheet("color:#00f2ff; font-size:10px; font-weight:bold; letter-spacing:1px;")
            nl.setAlignment(Qt.AlignCenter)
            vl2 = QLabel(val)
            vl2.setStyleSheet("font-size:22px; font-weight:900; color:white;")
            vl2.setAlignment(Qt.AlignCenter)
            bl.addWidget(il); bl.addWidget(nl); bl.addWidget(vl2)
            sensor_row.addWidget(box)
        layout.addLayout(sensor_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#1a1a35; margin:8px 0;")
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        container = QWidget()
        container.setStyleSheet("background:transparent;")
        people_layout = QHBoxLayout(container)

        kisi_list = DAIRE_REHBERI.get((kat, daire), [])
        if not kisi_list:
            pl = QLabel("Bu daireden henüz bildirim gelmedi.")
            pl.setStyleSheet("color:#446; font-size:13px; padding:20px;")
            pl.setAlignment(Qt.AlignCenter)
            people_layout.addWidget(pl)
        else:
            for k in kisi_list:
                pb = QFrame()
                pb.setStyleSheet("background:#0d0d22; border:1px solid #00ff9d44; border-radius:10px; padding:12px;")
                pvl = QVBoxLayout(pb)
                icon_lbl = QLabel("👤")
                icon_lbl.setStyleSheet("font-size:44px;")
                icon_lbl.setAlignment(Qt.AlignCenter)
                info = QLabel(f"<b>{k['ad']}</b><br><span style='color:#556;font-size:10px;'>TC: {k['tc']}</span><br>🕒 {k['saat']}<br>📍 {k['konum']}")
                info.setStyleSheet("font-size:11px; color:#aaa;")
                info.setAlignment(Qt.AlignCenter)
                pvl.addWidget(icon_lbl)
                pvl.addWidget(info)
                people_layout.addWidget(pb)

        scroll.setWidget(container)
        layout.addWidget(scroll)

        close_btn = QPushButton("KAPAT")
        close_btn.setStyleSheet("QPushButton{background:#1a1a3e;color:#aaa;padding:10px;border:1px solid #333;border-radius:6px;font-weight:bold;} QPushButton:hover{color:white;border-color:#00f2ff;}")
        close_btn.clicked.connect(win.close)
        layout.addWidget(close_btn)
        win.exec_()


# ── BİNA İNSPEKTÖRÜ — HOLOGRAFIK HUD ────────────────────────────────────────
CYBER_BTN = """
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {c1}, stop:1 {c2});
    color: {txt};
    padding: {pad}px;
    font-size: {fs}px;
    font-weight: 900;
    border-radius: 6px;
    border: 1px solid {bdr};
    letter-spacing: 1px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {c2}, stop:1 {c1});
    border-color: {txt};
}}
"""

def cyber_btn(c1="#0a2040", c2="#061228", txt="#00f2ff", bdr="#00f2ff44", pad=10, fs=13):
    return CYBER_BTN.format(c1=c1, c2=c2, txt=txt, bdr=bdr, pad=pad, fs=fs)


class CyberPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent; border:none;")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(12, 12, 28, 255))
        bg.setColorAt(1, QColor(6, 6, 18, 255))
        painter.fillRect(0, 0, w, h, QBrush(bg))

        for bw, ba in [(6, 8), (3, 20), (1, 80)]:
            pen = QPen(_gc(NEON_BLUE, ba), bw)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(0, 0, w-1, h-1, 4, 4)

        cs = 16
        painter.setPen(QPen(NEON_BLUE, 2))
        for cx2, cy2 in [(0,0),(w-1,0),(0,h-1),(w-1,h-1)]:
            sx = 1 if cx2 == 0 else -1
            sy = 1 if cy2 == 0 else -1
            painter.drawLine(cx2, cy2, cx2+sx*cs, cy2)
            painter.drawLine(cx2, cy2, cx2, cy2+sy*cs)

        super().paintEvent(event)


class BuildingInspector3D(QDialog):
    def __init__(self, polygon_points, height, status, parent=None):
        super().__init__(parent)
        self.setWindowTitle("METAVERSE 3D — DEPREM SİMÜLATÖRÜ")
        self.setModal(True)
        self.resize(1140, 760)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setStyleSheet("background:#030309; border:2px solid #00f2ff44;")

        self.polygon_points = polygon_points
        self.height_val     = height
        self.status         = status
        self.is_recording   = False
        self.test_start_time = 0
        self.recorded_data  = []
        self.replay_timer   = QTimer()
        self.replay_timer.timeout.connect(self.replay_step)
        self.replay_index   = 0
        self.is_replaying   = False
        self.is_paused      = False
        self.mode           = "BINA"
        self._current_pga_g = 0.0   # anlık PGA
        self.max_pga_g      = 0.0   # test sırasındaki zirve PGA

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── LEFT PANEL ──
        panel = CyberPanel()
        panel.setFixedWidth(310)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 14, 14, 14)
        pl.setSpacing(8)

        title = QLabel("DEPREM\nSİMÜLASYONU")
        title.setStyleSheet("color:#00f2ff; font-size:20px; font-weight:900; letter-spacing:3px; line-height:1.3;")
        title.setAlignment(Qt.AlignCenter)
        pl.addWidget(title)

        # Brand
        brand = QLabel("GÖKÇE")
        brand.setStyleSheet("color:rgba(255,255,255,80); font-size:11px; font-weight:900; letter-spacing:5px;")
        brand.setAlignment(Qt.AlignCenter)
        pl.addWidget(brand)

        sep = self._sep()
        pl.addWidget(sep)

        # Mode buttons
        mode_row = QHBoxLayout()
        self.btn_bina  = QPushButton("BİNA MODU")
        self.btn_daire = QPushButton("DAİRE MODU")
        for b, m in [(self.btn_bina,"BINA"),(self.btn_daire,"DAIRE")]:
            b.setStyleSheet(cyber_btn(pad=7, fs=11))
            b.clicked.connect(lambda _, mm=m: setattr(self, 'mode', mm))
            mode_row.addWidget(b)
        pl.addLayout(mode_row)

        list_btn = QPushButton("🏢  DAİRELERİ GÖRÜNTÜLE")
        list_btn.setStyleSheet(cyber_btn("#2a006a","#180040","#aa00ff","#aa00ff66",pad=8,fs=12))
        list_btn.clicked.connect(self.show_apartments)
        pl.addWidget(list_btn)

        pl.addWidget(self._sep())

        self.connection_lbl = QLabel("⏳  Sensör Bağlanıyor...")
        self.connection_lbl.setStyleSheet("color:#ffcc00; font-size:11px; font-weight:bold;")
        self.connection_lbl.setAlignment(Qt.AlignCenter)
        pl.addWidget(self.connection_lbl)

        calib_btn = QPushButton("⚙  KALİBRASYON (SIFIRLA)")
        calib_btn.setStyleSheet(cyber_btn("#3a2800","#201800",NEON_YELLOW.name(),"#ffcc0044",pad=8,fs=11))
        calib_btn.clicked.connect(lambda: self.view_3d.calibrate_sensor())
        pl.addWidget(calib_btn)

        align_btn = QPushButton("↔  HİZALA (2D)")
        align_btn.setStyleSheet(cyber_btn(pad=7,fs=11))
        align_btn.clicked.connect(lambda: self.view_3d.set_front_view())
        pl.addWidget(align_btn)

        pl.addWidget(self._sep())

        self.timer_lbl = QLabel("00:00:000")
        self.timer_lbl.setStyleSheet("""
            color: #00f2ff; font-size: 32px; font-weight: 900;
            font-family: 'Courier New', monospace;
            letter-spacing: 2px;
            padding: 6px;
        """)
        self.timer_lbl.setAlignment(Qt.AlignCenter)
        pl.addWidget(self.timer_lbl)

        self.test_btn = QPushButton("▶  TESTİ BAŞLAT")
        self.test_btn.setStyleSheet(cyber_btn("#003a1e","#001a0d","#00ff9d","#00ff9d66",pad=14,fs=15))
        self.test_btn.clicked.connect(self.toggle_test)
        pl.addWidget(self.test_btn)

        self.waveform = SeismicWaveform()
        pl.addWidget(self.waveform)

        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setStyleSheet("""
            QSlider::groove:horizontal {border:1px solid #1a1a35;height:8px;background:#0a0a18;margin:2px 0;border-radius:4px;}
            QSlider::handle:horizontal {background:#00f2ff;border:1px solid #00f2ff;width:16px;height:16px;margin:-5px 0;border-radius:8px;}
            QSlider::sub-page:horizontal {background:#00f2ff44;border-radius:4px;}
        """)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self.scrub_timeline)
        pl.addWidget(self.timeline_slider)

        self.playback_container = QWidget()
        self.playback_container.setStyleSheet("background:transparent;")
        pb_l = QVBoxLayout(self.playback_container)
        pb_l.setContentsMargins(0,0,0,0)
        ctrl_l = QHBoxLayout()
        self.play_btn  = QPushButton("▶")
        self.pause_btn = QPushButton("⏸")
        self.stop_btn  = QPushButton("⏹")
        self.play_btn.setStyleSheet(cyber_btn("#001a40","#00081e","#00aaff","#00aaff55",pad=8,fs=14))
        self.pause_btn.setStyleSheet(cyber_btn("#302000","#181000",NEON_YELLOW.name(),"#ffcc0044",pad=8,fs=14))
        self.stop_btn.setStyleSheet(cyber_btn("#3a0010","#200008","#ff0055","#ff005544",pad=8,fs=14))
        self.play_btn.clicked.connect(self.start_resume_replay)
        self.pause_btn.clicked.connect(self.pause_replay)
        self.stop_btn.clicked.connect(self.stop_replay)
        ctrl_l.addWidget(self.play_btn)
        ctrl_l.addWidget(self.pause_btn)
        ctrl_l.addWidget(self.stop_btn)
        pb_l.addLayout(ctrl_l)

        self.report_btn = QPushButton("📄  RAPORLARI GÖR")
        self.report_btn.setStyleSheet(cyber_btn("#2a006a","#180040","#aa00ff","#aa00ff55",pad=12,fs=13))
        self.report_btn.clicked.connect(self.open_report)
        pb_l.addWidget(self.report_btn)

        self.district_btn = QPushButton("🗺  İLÇE RAPORUNU GÖR")
        self.district_btn.setStyleSheet(cyber_btn("#003a30","#001e18","#00ff9d","#00ff9d44",pad=10,fs=12))
        self.district_btn.clicked.connect(self.open_district_report)
        pb_l.addWidget(self.district_btn)

        self.playback_container.setEnabled(False)
        pl.addWidget(self.playback_container)
        pl.addStretch()

        close_btn = QPushButton("✕  BİNAYI KAPAT")
        close_btn.setStyleSheet(cyber_btn("#0d0d20","#080810","#556","#222",pad=9,fs=11))
        close_btn.clicked.connect(self.close)
        pl.addWidget(close_btn)

        self.view_3d = Interactive3DView(polygon_points, height, status)
        root.addWidget(panel)
        root.addWidget(self.view_3d, 1)

        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_ui_timer)

        self.jeoskop_thread = JeoskopWorker()
        self.jeoskop_thread.orientation_signal.connect(self.handle_sensor_data)
        self.jeoskop_thread.raw_imu_signal.connect(self.handle_raw_imu)
        self.jeoskop_thread.status_signal.connect(self.update_connection_status)
        self.jeoskop_thread.start()

    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color:#1a1a35; margin:2px 0;")
        return f

    def show_apartments(self):
        floors = max(1, int(self.height_val / 3.5))
        ApartmentListDialog(floors, self).exec_()

    def update_connection_status(self, connected, message):
        if connected:
            self.connection_lbl.setText("✅  JEOSKOP + ALTİMETRE BAĞLI")
            self.connection_lbl.setStyleSheet("color:#00ff9d; font-size:11px; font-weight:900;")
        else:
            self.connection_lbl.setText(f"❌  {message}")
            self.connection_lbl.setStyleSheet("color:#ff0055; font-size:11px; font-weight:bold;")

    def handle_sensor_data(self, roll, pitch, alt):
        cal_roll  = roll  - self.view_3d.offset_roll
        cal_pitch = pitch - self.view_3d.offset_pitch
        cal_alt   = alt   - self.view_3d.offset_alt
        magnitude = math.sqrt(cal_roll**2 + cal_pitch**2)

        packet = {"roll": round(cal_roll,2), "pitch": round(cal_pitch,2),
                  "alt": round(cal_alt,2), "magnitude": round(magnitude,2),
                  "is_recording": self.is_recording, "timestamp": time.time()}

        if magnitude >= 6.0 and self.mode == "DAIRE":
            MOBILE_SERVER.broadcast_data({"type":"ALERT","message":f"Şiddet: {magnitude:.1f} - İYİ MİSİN?","kat":1,"daire":1})
        MOBILE_SERVER.broadcast_data(packet)

        if self.is_recording:
            self.view_3d.update_rotation_from_sensor(roll, pitch, alt)
            elapsed = time.time() - self.test_start_time
            self.recorded_data.append({'time':elapsed,'roll':cal_roll,'pitch':cal_pitch,'alt':cal_alt,'pga':self._current_pga_g})
            self.max_pga_g = max(self.max_pga_g, self._current_pga_g)
            mag_disp = math.sqrt(cal_roll**2 + cal_pitch**2)*2 + abs(cal_alt/2)
            self.waveform.add_point(min(100, mag_disp), True)
        elif not self.recorded_data:
            self.view_3d.update_rotation_from_sensor(roll, pitch, alt)

    def handle_raw_imu(self, ax, ay, _az):
        """Ham ivmeölçer verisiyle anlık PGA hesapla (Wald 1999)."""
        self._current_pga_g = raw_to_pga_g(ax, ay)

    def open_district_report(self):
        DistrictReportDialog(self.max_pga_g, self).exec_()

    def toggle_test(self):
        if not self.is_recording:
            self.is_recording   = True
            self.test_start_time = time.time()
            self.recorded_data  = []
            self.max_pga_g      = 0.0
            self.waveform.clear_data()
            self.test_btn.setText("⏹  TESTİ BİTİR")
            self.test_btn.setStyleSheet(cyber_btn("#3a0010","#200008","#ff0055","#ff005544",pad=14,fs=15))
            self.ui_timer.start(10)
            self.playback_container.setEnabled(False)
            self.timeline_slider.setEnabled(False)
        else:
            self.is_recording = False
            self.ui_timer.stop()
            self.test_btn.setText("▶  YENİ TEST BAŞLAT")
            self.test_btn.setStyleSheet(cyber_btn("#003a1e","#001a0d","#00ff9d","#00ff9d66",pad=14,fs=15))
            self.playback_container.setEnabled(True)
            if self.recorded_data:
                self.timeline_slider.setEnabled(True)
                self.timeline_slider.setRange(0, len(self.recorded_data)-1)
                self.timeline_slider.setValue(0)

    def update_ui_timer(self):
        if self.is_recording:
            el = time.time() - self.test_start_time
            self.timer_lbl.setText(f"{int(el//60):02}:{int(el%60):02}:{int((el*1000)%1000):03}")

    def start_resume_replay(self):
        if not self.recorded_data: return
        self.is_replaying = True
        self.is_paused    = False
        if self.replay_index >= len(self.recorded_data)-1:
            self.replay_index = 0
        self.replay_timer.start(20)

    def pause_replay(self):
        if self.is_replaying:
            self.is_replaying = False
            self.is_paused    = True
            self.replay_timer.stop()

    def stop_replay(self):
        self.is_replaying = False
        self.is_paused    = False
        self.replay_timer.stop()
        self.replay_index = 0
        self.timeline_slider.setValue(0)
        self.view_3d.model_roll = self.view_3d.model_pitch = self.view_3d.model_alt = 0
        self.view_3d.draw_frame()
        self.timer_lbl.setText("00:00:000")

    def scrub_timeline(self, value):
        if value < len(self.recorded_data):
            self.replay_index = value
            d = self.recorded_data[value]
            self.view_3d.model_roll  = d['roll']
            self.view_3d.model_pitch = d['pitch']
            self.view_3d.model_alt   = d['alt'] * 0.15
            self.view_3d.draw_frame()
            t = d['time']
            self.timer_lbl.setText(f"{int(t//60):02}:{int(t%60):02}:{int((t*1000)%1000):03}")

    def replay_step(self):
        if self.replay_index < len(self.recorded_data):
            self.timeline_slider.blockSignals(True)
            self.timeline_slider.setValue(self.replay_index)
            self.timeline_slider.blockSignals(False)
            d = self.recorded_data[self.replay_index]
            self.view_3d.model_roll  = d['roll']
            self.view_3d.model_pitch = d['pitch']
            self.view_3d.model_alt   = d['alt'] * 0.15
            self.view_3d.draw_frame()
            t = d['time']
            self.timer_lbl.setText(f"{int(t//60):02}:{int(t%60):02}:{int((t*1000)%1000):03}")
            self.replay_index += 1
        else:
            self.pause_replay()

    def open_report(self):
        if not self.recorded_data: return
        rolls   = [abs(d['roll'])  for d in self.recorded_data]
        pitches = [abs(d['pitch']) for d in self.recorded_data]
        alts    = [abs(d['alt'])   for d in self.recorded_data]
        avg_roll  = statistics.mean([d['roll']  for d in self.recorded_data])
        avg_pitch = statistics.mean([d['pitch'] for d in self.recorded_data])
        deg = math.degrees(math.atan2(avg_pitch, avg_roll))
        if -45 < deg <= 45:   direction = "DOĞU (Yanal)"
        elif 45 < deg <= 135: direction = "KUZEY (Ön)"
        elif deg > 135:       direction = "BATI (Yanal)"
        else:                 direction = "GÜNEY (Arka)"
        max_roll  = max(rolls)
        max_pitch = max(pitches)
        stats = {
            'duration': self.recorded_data[-1]['time'],
            'max_roll': max_roll, 'max_pitch': max_pitch,
            'max_alt_change': max(alts) if alts else 0.0,
            'force_direction': direction,
            'g_force': round(self.max_pga_g, 4) if self.max_pga_g > 0 else round(1.0 + (max_roll + max_pitch) / 90.0, 4)
        }
        EarthquakeReportDialog(self.recorded_data[0], self.recorded_data[-1],
                               stats, self.polygon_points, self.height_val, self).exec_()

    def closeEvent(self, event):
        if self.jeoskop_thread.isRunning():
            self.jeoskop_thread.terminate()
        super().closeEvent(event)


# ── YARDIMCI WİDGETLER ────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, title, value, unit="", color="#00f2ff", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:#0a0a1e;border:1px solid {color}44;border-radius:8px;padding:4px;")
        l = QVBoxLayout(self)
        l.setSpacing(1)
        l.setContentsMargins(6,6,6,6)
        t = QLabel(title.upper())
        t.setStyleSheet(f"color:{color};font-size:8px;font-weight:900;letter-spacing:2px;")
        t.setAlignment(Qt.AlignCenter)
        self.val_lbl = QLabel(str(value))
        self.val_lbl.setStyleSheet("color:white;font-size:20px;font-weight:900;font-family:'Courier New',monospace;")
        self.val_lbl.setAlignment(Qt.AlignCenter)
        u = QLabel(unit)
        u.setStyleSheet(f"color:{color}88;font-size:9px;")
        u.setAlignment(Qt.AlignCenter)
        l.addWidget(t); l.addWidget(self.val_lbl); l.addWidget(u)
    def set_value(self, v):
        self.val_lbl.setText(str(v))


class SurvivalCurveWidget(QWidget):
    def __init__(self, current_hours=0, parent=None):
        super().__init__(parent)
        self.current_hours = current_hours
        self.setMinimumHeight(140)
        self.setStyleSheet("background:#06060f;border-radius:6px;border:1px solid #1a1a35;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QBrush(QColor("#04040c")))
        mx = 120
        lm, rm, tm, bm = int(w*0.1), int(w*0.95), int(h*0.1), int(h*0.88)
        pw, ph = rm-lm, bm-tm

        p.setPen(QPen(QColor(255,255,255,10), 1))
        for i in range(1,5):
            y = tm + ph*i//4; p.drawLine(lm, y, rm, y)
        for i in range(1,5):
            x = lm + pw*i//4; p.drawLine(x, tm, x, bm)

        path = QPainterPath()
        first = True
        for hrs, pct in SURVIVAL_CURVE:
            px2 = lm + int(pw * hrs / mx)
            py2 = bm - int(ph * pct / 100)
            if first: path.moveTo(px2, py2); first = False
            else: path.lineTo(px2, py2)

        fill = QPainterPath(path)
        fill.lineTo(rm, bm); fill.lineTo(lm, bm); fill.closeSubpath()
        grad = QLinearGradient(0, tm, 0, bm)
        grad.setColorAt(0, QColor(0,255,100,55)); grad.setColorAt(1, QColor(0,255,100,5))
        p.fillPath(fill, QBrush(grad))
        for lw, la in [(5,15),(2,70),(1,255)]:
            p.setPen(QPen(QColor(0,255,100,la), lw)); p.drawPath(path)

        if 0 < self.current_hours <= mx:
            cx2 = lm + int(pw * self.current_hours / mx)
            surv = 5
            for i,(hrs,pct) in enumerate(SURVIVAL_CURVE):
                if hrs >= self.current_hours:
                    if i > 0:
                        t0,p0 = SURVIVAL_CURVE[i-1]
                        frac = (self.current_hours-t0)/max(1,hrs-t0)
                        surv = p0+(pct-p0)*frac
                    else: surv = pct
                    break
            cy2 = bm - int(ph * surv / 100)
            for lw, la in [(6,15),(2,200)]:
                p.setPen(QPen(QColor(255,200,0,la), lw)); p.drawLine(cx2, tm, cx2, bm)
            p.setBrush(QBrush(NEON_YELLOW)); p.setPen(QPen(QColor(0,0,0),1))
            p.drawEllipse(QPointF(cx2, cy2), 5, 5)
            p.setPen(QPen(NEON_YELLOW)); p.setFont(QFont("Arial",8,QFont.Bold))
            p.drawText(cx2+6, cy2-4, f"%{surv:.0f}")

        p.setPen(QPen(QColor(150,150,150), 1)); p.setFont(QFont("Arial",7))
        for hrs in [0,24,48,72,96,120]:
            px2 = lm + int(pw*hrs/mx); p.drawText(px2-8, bm+12, f"{hrs}s")
        p.setPen(QPen(QColor(0,255,100))); p.setFont(QFont("Arial",8,QFont.Bold))
        p.drawText(2, tm+10, "HAYATTa KALMA ORANI (Saat Bazlı — INSARAG)")


class HeatmapWidget(QWidget):
    def __init__(self, grid_data, parent=None):
        super().__init__(parent)
        self.grid_data = grid_data
        self.setMinimumSize(320, 200)
        self.setStyleSheet("background:#04040c;border-radius:6px;border:1px solid #1a1a35;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QBrush(QColor("#04040c")))
        if not self.grid_data: return
        cols = max(x for x,y,d,*_ in self.grid_data)+1
        rows = max(y for x,y,d,*_ in self.grid_data)+1
        cw = (w-20)/cols; ch = (h-30)/rows
        fills  = [QColor(15,60,20,220),QColor(80,80,0,220),QColor(130,55,0,220),QColor(140,15,15,220),QColor(15,5,5,240)]
        edges  = [QColor(0,220,70),QColor(220,200,0),QColor(255,130,0),QColor(255,40,40),QColor(80,0,0)]
        for item in self.grid_data:
            bx, by, dmg = item[0], item[1], item[2]
            x0 = 10 + bx*cw; y0 = 10 + by*ch
            has_gas  = len(item)>3 and item[3]
            has_fire = len(item)>4 and item[4]
            has_team = len(item)>5 and item[5]
            p.setBrush(QBrush(fills[dmg])); p.setPen(QPen(edges[dmg], 0.5))
            p.drawRect(QRectF(x0+1,y0+1,cw-2,ch-2))
            if has_fire:
                p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(255,80,0,180)))
                p.drawEllipse(QPointF(x0+cw*0.7,y0+ch*0.3),min(cw,ch)*0.2,min(cw,ch)*0.2)
            if has_gas:
                p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(160,100,255,160)))
                p.drawEllipse(QPointF(x0+cw*0.3,y0+ch*0.7),min(cw,ch)*0.15,min(cw,ch)*0.15)
            if has_team:
                p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor(0,200,255,200)))
                p.drawEllipse(QPointF(x0+cw*0.5,y0+ch*0.5),min(cw,ch)*0.25,min(cw,ch)*0.25)
                p.setPen(QPen(QColor(0,0,0))); p.setFont(QFont("Arial",max(5,int(min(cw,ch)*0.3)),QFont.Bold))
                p.drawText(QRectF(x0,y0,cw,ch), Qt.AlignCenter, str(item[5]))
        items = [("Sağlam",0),("Hafif",1),("Orta",2),("Ağır",3),("Yıkık",4),("🔥",None),("⬤ gaz",None)]
        lw2 = (w-10)/len(items)
        for i,(name,lvl) in enumerate(items):
            lx = 5+i*lw2; ly = h-16
            if lvl is not None:
                p.setBrush(QBrush(edges[lvl])); p.setPen(Qt.NoPen)
                p.drawRect(QRectF(lx, ly, 8, 8))
            p.setPen(QPen(QColor(160,160,160))); p.setFont(QFont("Arial",6))
            p.drawText(int(lx+10 if lvl is not None else lx), int(ly+7), name)


class LiveFeedWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#020208;border-radius:4px;border:1px solid #00f2ff22;")
        l = QVBoxLayout(self); l.setContentsMargins(4,4,4,4); l.setSpacing(2)
        hdr = QLabel("◉  CANLI VERİ AKIŞI")
        hdr.setStyleSheet("color:#ff0055;font-size:10px;font-weight:900;letter-spacing:2px;padding:3px;")
        l.addWidget(hdr)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border:none;background:transparent;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inner = QWidget(); self.inner.setStyleSheet("background:transparent;")
        self.feed_l = QVBoxLayout(self.inner); self.feed_l.setSpacing(2); self.feed_l.setContentsMargins(2,2,2,2)
        self.feed_l.addStretch()
        self.scroll.setWidget(self.inner); l.addWidget(self.scroll)

    def add_event(self, icon, category, message, ts=""):
        item = QFrame()
        item.setStyleSheet("background:#0a0a1e;border-left:2px solid #00f2ff44;border-radius:3px;padding:2px;margin:1px;")
        il = QVBoxLayout(item); il.setSpacing(0); il.setContentsMargins(5,3,5,3)
        if ts:
            tl = QLabel(ts); tl.setStyleSheet("color:#333;font-size:7px;"); il.addWidget(tl)
        cl = QLabel(f"{icon}  {category}"); cl.setStyleSheet("color:#00f2ff;font-size:9px;font-weight:900;"); il.addWidget(cl)
        ml = QLabel(message); ml.setStyleSheet("color:#bbb;font-size:10px;"); ml.setWordWrap(True); il.addWidget(ml)
        self.feed_l.insertWidget(self.feed_l.count()-1, item)
        QTimer.singleShot(60, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))


# ── İLÇE RAPOR DİALOGU ────────────────────────────────────────────────────────
class DistrictReportDialog(QDialog):
    def __init__(self, max_pga_g, parent=None):
        super().__init__(parent)
        self.setWindowTitle("İLÇE DEPREM ANALİZ RAPORU")
        self.resize(1300, 820)
        self.setStyleSheet("QDialog{background:#030309;color:white;} QLabel{color:#ccc;}")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)

        mmi = pga_to_mmi(max_pga_g) if max_pga_g > 0 else 6.2
        mmi_label, mmi_color = mmi_info(mmi)
        data = sim_district(mmi)
        mag_est = round(0.58 * mmi + 1.0, 1)  # Trifunac & Brady basit ilişkisi

        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Header
        hdr = QWidget(); hdr.setFixedHeight(60)
        hdr.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #080015,stop:0.5 #0f0025,stop:1 #080015);border-bottom:2px solid #aa00ff44;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20,0,20,0)
        sim_badge = QLabel("⚠  SİMÜLASYON — GERÇEK VERİ DEĞİLDİR")
        sim_badge.setStyleSheet("color:#ffcc00;font-size:11px;font-weight:900;background:#3a2000;padding:4px 10px;border-radius:4px;border:1px solid #ffcc0055;")
        title_l = QLabel(f"KADİKÖY İLÇESİ — DEPREM ANALİZ RAPORU   |   MMI {mmi:.1f} ({mmi_label})")
        title_l.setStyleSheet(f"color:{mmi_color};font-size:15px;font-weight:900;letter-spacing:2px;")
        hl.addWidget(sim_badge); hl.addSpacing(20); hl.addWidget(title_l); hl.addStretch()
        close_hdr = QPushButton("✕")
        close_hdr.setStyleSheet("QPushButton{background:transparent;color:#666;font-size:18px;border:none;padding:0 10px;} QPushButton:hover{color:white;}")
        close_hdr.clicked.connect(self.close); hl.addWidget(close_hdr)
        root.addWidget(hdr)

        body = QWidget(); body_l = QVBoxLayout(body); body_l.setContentsMargins(16,12,16,12); body_l.setSpacing(10)

        # ROW 1: KPI kartları
        kpi_row = QHBoxLayout(); kpi_row.setSpacing(8)
        kpi_data = [
            ("TAHMİNİ BÜYÜKLÜK", f"M{mag_est}", "", "#aa00ff"),
            ("MMI ŞİDDETİ",      f"{mmi:.1f}", mmi_label, mmi_color),
            ("TOPLAM BİNA",      str(data['total_b']), "adet", "#00f2ff"),
            ("YIKILAN BİNA",     str(data['destroyed']), "adet", "#ff0055"),
            ("ENKAZ ALTINDA",    str(data['trapped']), "kişi", "#ff4500"),
            ("KURTARILAN",       str(data['alive']), "kişi", "#00ff9d"),
            ("GAZ KAÇAĞI",       str(data['gas_leaks']), "bina", "#ff8c00"),
            ("YANGIN",           str(data['fires']), "nokta", "#ff4500"),
        ]
        for title, val, unit, col in kpi_data:
            kpi_row.addWidget(StatCard(title, val, unit, col))
        body_l.addLayout(kpi_row)

        # ROW 2: Hasar grafik + heatmap + enkaz/hayatta kalma
        mid_row = QHBoxLayout(); mid_row.setSpacing(10)

        # Sol: bina hasar grafiği
        dmg_frame = QFrame(); dmg_frame.setStyleSheet("background:#0a0a1e;border:1px solid #1a1a35;border-radius:8px;padding:8px;")
        dmg_l = QVBoxLayout(dmg_frame)
        dmg_title = QLabel("BİNA HASAR DAĞILIMI"); dmg_title.setStyleSheet("color:#00f2ff;font-size:11px;font-weight:900;letter-spacing:2px;")
        dmg_l.addWidget(dmg_title)
        categories = [
            ("SAĞLAM",   data['intact'],    "#00ff9d"),
            ("HAFİF",    data['light'],     "#ffff40"),
            ("ORTA",     data['moderate'],  "#ff8c00"),
            ("AĞIR",     data['heavy'],     "#ff3030"),
            ("YIKIK",    data['destroyed'], "#880000"),
        ]
        for name, count, col in categories:
            row_w = QWidget(); row_l = QHBoxLayout(row_w); row_l.setContentsMargins(0,2,0,2); row_l.setSpacing(6)
            lbl = QLabel(name); lbl.setStyleSheet(f"color:{col};font-size:10px;font-weight:bold;min-width:55px;")
            bar = QProgressBar(); bar.setRange(0, data['total_b']); bar.setValue(count)
            bar.setTextVisible(False); bar.setFixedHeight(14)
            bar.setStyleSheet(f"QProgressBar{{background:#0d0d1e;border-radius:4px;}} QProgressBar::chunk{{background:{col};border-radius:4px;}}")
            cnt = QLabel(str(count)); cnt.setStyleSheet("color:#aaa;font-size:10px;min-width:35px;"); cnt.setAlignment(Qt.AlignRight)
            pct_l = QLabel(f"%{count*100//data['total_b']}"); pct_l.setStyleSheet(f"color:{col};font-size:10px;min-width:32px;")
            row_l.addWidget(lbl); row_l.addWidget(bar,1); row_l.addWidget(cnt); row_l.addWidget(pct_l)
            dmg_l.addWidget(row_w)
        dmg_l.addStretch()

        # Hayatta kalma eğrisi
        sc_frame = QFrame(); sc_frame.setStyleSheet("background:#0a0a1e;border:1px solid #1a1a35;border-radius:8px;padding:8px;")
        sc_l = QVBoxLayout(sc_frame)
        sc_title = QLabel("HAYATTa KALMA EĞRİSİ — ZAMANA GÖRE"); sc_title.setStyleSheet("color:#00ff9d;font-size:11px;font-weight:900;letter-spacing:2px;")
        sc_l.addWidget(sc_title)
        surv_widget = SurvivalCurveWidget(current_hours=0.5)
        sc_l.addWidget(surv_widget)
        sc_l.addWidget(QLabel('<span style="color:#aaa;font-size:10px;">▲ İlk 6 saat kritik. Her saatin değeri var.</span>'))

        # Heatmap
        hm_frame = QFrame(); hm_frame.setStyleSheet("background:#0a0a1e;border:1px solid #1a1a35;border-radius:8px;padding:8px;")
        hm_l = QVBoxLayout(hm_frame)
        hm_title = QLabel("HASAR YOĞUNLUK HARİTASI — MODA/KADİKÖY"); hm_title.setStyleSheet("color:#ffcc00;font-size:11px;font-weight:900;letter-spacing:2px;")
        hm_l.addWidget(hm_title)
        random.seed(42)
        grid = []
        cols2, rows2 = 22, 14
        d_probs = [r/100 for r in damage_ratios_from_mmi(mmi)]
        cum = [sum(d_probs[:i+1]) for i in range(5)]
        gas_set  = set(random.sample(range(cols2*rows2), min(data['gas_leaks'], cols2*rows2)))
        fire_set = set(random.sample(list(gas_set), min(data['fires'], len(gas_set))))
        team_positions = {(random.randint(0,cols2-1), random.randint(0,rows2-1)): i+1 for i in range(min(8,len(AFAD_TEAM_DEFS)))}
        for gy in range(rows2):
            for gx in range(cols2):
                idx = gy*cols2+gx
                rv = random.random()
                dmg = next((i for i,c in enumerate(cum) if rv < c), 4)
                has_gas  = idx in gas_set
                has_fire = idx in fire_set
                team_no  = team_positions.get((gx,gy), None)
                grid.append((gx, gy, dmg, has_gas, has_fire, team_no))
        hm_widget = HeatmapWidget(grid)
        hm_l.addWidget(hm_widget)

        mid_row.addWidget(dmg_frame, 2)
        mid_row.addWidget(sc_frame, 2)
        mid_row.addWidget(hm_frame, 3)
        body_l.addLayout(mid_row)

        # ROW 3: Ek bilgi çubukları
        bot_row = QHBoxLayout(); bot_row.setSpacing(8)
        def mini_info(title, items_list, border_col):
            f = QFrame(); f.setStyleSheet(f"background:#0a0a1e;border:1px solid {border_col}44;border-radius:8px;padding:8px;")
            fl = QVBoxLayout(f)
            tl = QLabel(title); tl.setStyleSheet(f"color:{border_col};font-size:10px;font-weight:900;letter-spacing:2px;margin-bottom:4px;")
            fl.addWidget(tl)
            for (icon, text, val) in items_list:
                rl = QHBoxLayout(); rl.setSpacing(4)
                il2 = QLabel(f"{icon}  {text}"); il2.setStyleSheet("color:#aaa;font-size:10px;")
                vl2 = QLabel(str(val)); vl2.setStyleSheet(f"color:{border_col};font-size:11px;font-weight:bold;"); vl2.setAlignment(Qt.AlignRight)
                rl.addWidget(il2,1); rl.addWidget(vl2); fl.addLayout(rl)
            fl.addStretch(); return f

        bot_row.addWidget(mini_info("KURTARMA KAYNAKLARI",[
            ("🚁","AFAD Ekibi",data['afad_teams']),("🐕","K9 Birliği",data['k9']),
            ("🚒","İTFAİYE",6),("🏗","Vinç/İş Makinesi",data['crane']),
            ("🚑","Ambulans",14),("🏥","Yatak Kapasitesi",data['hospital_cap']),
        ],"#00aaff"))
        bot_row.addWidget(mini_info("KASÜALTİ DURUMU",[
            ("❓","Enkaz Altında (tahmin)",data['trapped']),
            ("🟢","Hayatta — Kurtarılan",data['alive']),
            ("❓","Kayıp (bilinmiyor)",data['missing']),
            ("⚫","Hayatını Kaybeden",data['dead']),
            ("🏥","Hastanede Tedavi",data['hospital_used']),
        ],"#ff4500"))
        bot_row.addWidget(mini_info("ALTYAPI & RİSK",[
            ("💧","Su Kesintisi (bina)",int(data['heavy']*0.4+data['destroyed']*0.9)),
            ("⚡","Elektrik Kesintisi",int(data['moderate']*0.2+data['heavy']*0.7)),
            ("🌿","Doğalgaz Kaçağı",data['gas_leaks']),
            ("🔥","Aktif Yangın",data['fires']),
            ("🛣","Erişimi Kesik Yol",7),
            ("🌉","Hasar Tespit Köprü",2),
        ],"#ff8c00"))
        bot_row.addWidget(mini_info("AI TAVSİYELERİ",[
            ("💡","En yüksek öncelik","3 nokta"),
            ("🐕","K9 gönder","Söğütlüçeşme"),
            ("🚁","Helikopter gereği","2 konum"),
            ("⚡","Elektrik kes","Hasar bölgesi"),
            ("🚧","Yıkım listesi",data['destroyed']),
        ],"#aa00ff"))
        body_l.addLayout(bot_row)

        root.addWidget(body)

        # Footer
        ftr = QWidget(); ftr.setFixedHeight(52)
        ftr.setStyleSheet("background:#08080f;border-top:1px solid #1a1a35;")
        fl2 = QHBoxLayout(ftr); fl2.setContentsMargins(16,8,16,8); fl2.setSpacing(10)
        crisis_btn = QPushButton("🚨  KRİZ YÖNETİM MERKEZİ'Nİ BAŞLAT")
        crisis_btn.setStyleSheet(cyber_btn("#3a0010","#200008","#ff0055","#ff005566",pad=12,fs=13))
        crisis_btn.clicked.connect(lambda: CrisisCommandCenter(data, self).exec_())
        close_btn2 = QPushButton("✕  KAPAT")
        close_btn2.setStyleSheet(cyber_btn("#0d0d20","#080810","#556","#222",pad=12,fs=12))
        close_btn2.clicked.connect(self.close)
        note = QLabel("⚠  Bu rapor simülasyon amaçlıdır. Gerçek deprem verisi içermez. MMI ve hasar hesaplamaları Wald et al. 1999 ve HAZUS 2003 metodolojisine dayanmaktadır.")
        note.setStyleSheet("color:#445;font-size:9px;")
        note.setWordWrap(True)
        fl2.addWidget(crisis_btn); fl2.addWidget(close_btn2); fl2.addWidget(note,1)
        root.addWidget(ftr)


# ── KRİZ YÖNETİM MERKEZİ ─────────────────────────────────────────────────────
class CrisisCommandCenter(QDialog):
    def __init__(self, district_data, parent=None):
        super().__init__(parent)
        self.data    = district_data
        self.elapsed = 0          # saniye cinsinden geçen süre
        self.rescued = 0
        self.dead_count = district_data['dead']
        self.alive_count = district_data['alive']
        self.event_idx = 0
        self.team_progress = {i+1: random.randint(0,15) for i in range(12)}

        self.setWindowTitle("KRİZ YÖNETİM MERKEZİ")
        self.resize(1400, 860)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setStyleSheet("QDialog{background:#020208;color:white;}")

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Top bar
        topbar = QWidget(); topbar.setFixedHeight(52)
        topbar.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0d0000,stop:0.5 #1a0005,stop:1 #0d0000);border-bottom:2px solid #ff005544;")
        tl = QHBoxLayout(topbar); tl.setContentsMargins(16,0,16,0)
        badge = QLabel("⚠  SİMÜLASYON"); badge.setStyleSheet("color:#ffcc00;font-size:10px;font-weight:900;background:#2a1800;padding:3px 8px;border-radius:4px;")
        title_main = QLabel("🔴  KRİZ YÖNETİM MERKEZİ — KADİKÖY/MODA   |   CANLI OPERASYON")
        title_main.setStyleSheet("color:#ff0055;font-size:15px;font-weight:900;letter-spacing:2px;")
        self.clock_lbl = QLabel("⏱  00:00:00"); self.clock_lbl.setStyleSheet("color:#00f2ff;font-size:14px;font-weight:900;font-family:monospace;")
        close_b = QPushButton("✕"); close_b.setStyleSheet("QPushButton{background:transparent;color:#666;font-size:18px;border:none;} QPushButton:hover{color:white;}"); close_b.clicked.connect(self.close)
        tl.addWidget(badge); tl.addSpacing(12); tl.addWidget(title_main); tl.addStretch(); tl.addWidget(self.clock_lbl); tl.addSpacing(20); tl.addWidget(close_b)
        root.addWidget(topbar)

        # Main content
        body = QWidget(); bl = QHBoxLayout(body); bl.setContentsMargins(8,8,8,8); bl.setSpacing(8)

        # LEFT: Canlı veri akışı
        self.feed = LiveFeedWidget(); self.feed.setFixedWidth(280)
        bl.addWidget(self.feed)

        # CENTER: Operasyonel harita + metrikler
        center_col = QVBoxLayout(); center_col.setSpacing(8)

        # KPI bar
        kpi_bar = QHBoxLayout(); kpi_bar.setSpacing(6)
        self.sc_enkaz  = StatCard("ENKAZ ALTINDA", self.data['trapped'], "kişi", "#ff4500")
        self.sc_alive  = StatCard("KURTARILAN",    self.alive_count,    "kişi", "#00ff9d")
        self.sc_dead   = StatCard("HAYATINı KAYBETTİ", self.dead_count, "kişi", "#ff0055")
        self.sc_rescue = StatCard("AKTİF KURTARMA", "12", "ekip", "#00aaff")
        self.sc_golden = StatCard("ALTIN SAAT", "05:12:37", "kalan", "#ffcc00")
        self.sc_surv   = StatCard("HAYATTa KALMA",  "91%",  "(0-6s)", "#00ff9d")
        for c in [self.sc_enkaz, self.sc_alive, self.sc_dead, self.sc_rescue, self.sc_golden, self.sc_surv]:
            kpi_bar.addWidget(c)
        center_col.addLayout(kpi_bar)

        # Harita
        self.op_map = OperationalMapWidget(self.data, self.team_progress)
        center_col.addWidget(self.op_map, 1)
        bl.addLayout(center_col, 1)

        # RIGHT: Ekip kartları
        right_col = QVBoxLayout(); right_col.setSpacing(4)
        teams_title = QLabel("AFAD EKİP DURUMU"); teams_title.setStyleSheet("color:#00f2ff;font-size:11px;font-weight:900;letter-spacing:2px;padding:4px;")
        right_col.addWidget(teams_title)

        teams_scroll = QScrollArea(); teams_scroll.setWidgetResizable(True)
        teams_scroll.setStyleSheet("background:transparent;border:none;"); teams_scroll.setFixedWidth(260)
        teams_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        teams_content = QWidget(); teams_content.setStyleSheet("background:transparent;")
        self.teams_l = QVBoxLayout(teams_content); self.teams_l.setSpacing(3); self.teams_l.setContentsMargins(2,2,2,2)

        self.team_cards = {}
        for tid, short, name, loc, col in AFAD_TEAM_DEFS:
            card = self._make_team_card(tid, short, name, loc, col, self.team_progress.get(tid,0))
            self.teams_l.addWidget(card); self.team_cards[tid] = card
        self.teams_l.addStretch()
        teams_scroll.setWidget(teams_content)
        right_col.addWidget(teams_scroll)

        # Alert panel
        alert_title = QLabel("⚠  AKTİF ALARMLAR"); alert_title.setStyleSheet("color:#ff8c00;font-size:10px;font-weight:900;letter-spacing:2px;padding:4px;")
        right_col.addWidget(alert_title)
        self.alert_frame = QFrame(); self.alert_frame.setStyleSheet("background:#0a0500;border:1px solid #ff8c0044;border-radius:6px;padding:4px;")
        af_l = QVBoxLayout(self.alert_frame); af_l.setSpacing(2)
        for (icon, txt) in [("🔥", f"{self.data['fires']} aktif yangın noktası"),
                              ("💨", f"{self.data['gas_leaks']} bölgede gaz kaçağı"),
                              ("🏗",  f"{self.data['destroyed']} yıkık bina — enkaz tehlikesi"),
                              ("⚡", "Kritik bölgede elektrik kesildi"),
                              ("💧", "Su şebeke kesintisi — 3 mahalle")]:
            al = QLabel(f"{icon}  {txt}"); al.setStyleSheet("color:#ff8c00;font-size:10px;padding:2px;"); af_l.addWidget(al)
        right_col.addWidget(self.alert_frame)

        bl.addLayout(right_col)
        root.addWidget(body, 1)

        # Bottom bar
        botbar = QWidget(); botbar.setFixedHeight(40)
        botbar.setStyleSheet("background:#060606;border-top:1px solid #1a1a35;")
        bbl = QHBoxLayout(botbar); bbl.setContentsMargins(16,4,16,4)
        ai_lbl = QLabel("💡  AI KOORDİNASYON: Aktif   |   Sinyaller işleniyor...   |   Son öneri: KRT-2 → Söğütlüçeşme Apt B")
        ai_lbl.setStyleSheet("color:#aa00ff;font-size:10px;")
        bbl.addWidget(ai_lbl)
        root.addWidget(botbar)

        # Timers
        self._tick_timer = QTimer(); self._tick_timer.timeout.connect(self._tick); self._tick_timer.start(1000)
        self._event_timer = QTimer(); self._event_timer.timeout.connect(self._add_next_event); self._event_timer.start(3500)
        self._update_timer = QTimer(); self._update_timer.timeout.connect(self._update_stats); self._update_timer.start(5000)

        # Initial events
        self.feed.add_event("🔴","DEPREM ALARM", f"M{round(0.58*self.data['mmi']+1.0,1)} depremi — 06:47:23 — Tüm ekipler alarm!", "06:47:23")
        self.feed.add_event("🟠","KRİZ MERKEZİ", "Kadıköy Afet Koordinasyonu devrede", "06:47:45")
        self.feed.add_event("💡","AI SİSTEM", f"{self.data['trapped']} kişi enkaz altında tahmini — öncelik haritası oluşturuldu", "06:48:02")

    def _make_team_card(self, tid, short, name, loc, col, progress):
        card = QFrame()
        card.setStyleSheet(f"background:#080818;border:1px solid {col}33;border-radius:5px;padding:4px;")
        cl = QVBoxLayout(card); cl.setSpacing(1); cl.setContentsMargins(6,4,6,4)
        top_row = QHBoxLayout()
        id_lbl = QLabel(short); id_lbl.setStyleSheet(f"color:{col};font-size:10px;font-weight:900;min-width:45px;")
        nm_lbl = QLabel(name); nm_lbl.setStyleSheet("color:#aaa;font-size:9px;")
        st_lbl = QLabel("● SAHADA"); st_lbl.setStyleSheet(f"color:{col};font-size:8px;font-weight:bold;"); st_lbl.setAlignment(Qt.AlignRight)
        top_row.addWidget(id_lbl); top_row.addWidget(nm_lbl,1); top_row.addWidget(st_lbl)
        cl.addLayout(top_row)
        loc_lbl = QLabel(f"📍 {loc}"); loc_lbl.setStyleSheet("color:#555;font-size:8px;"); cl.addWidget(loc_lbl)
        pb = QProgressBar(); pb.setRange(0,100); pb.setValue(progress); pb.setFixedHeight(5); pb.setTextVisible(False)
        pb.setStyleSheet(f"QProgressBar{{background:#111;border-radius:2px;}} QProgressBar::chunk{{background:{col};border-radius:2px;}}")
        cl.addWidget(pb)
        card._pb = pb
        return card

    def _tick(self):
        self.elapsed += 1
        h = self.elapsed // 3600; m = (self.elapsed % 3600) // 60; s = self.elapsed % 60
        self.clock_lbl.setText(f"⏱  {h:02}:{m:02}:{s:02}")
        # Altın saat geri sayım (24 saat = 86400 saniye)
        remaining = max(0, 86400 - self.elapsed)
        rh = remaining//3600; rm = (remaining%3600)//60; rs = remaining%60
        self.sc_golden.set_value(f"{rh:02}:{rm:02}:{rs:02}")
        # Hayatta kalma oranı güncelle
        hrs_elapsed = self.elapsed / 3600
        surv = 100
        for i,(hrs,pct) in enumerate(SURVIVAL_CURVE):
            if hrs >= hrs_elapsed:
                if i>0:
                    t0,p0 = SURVIVAL_CURVE[i-1]
                    frac = (hrs_elapsed-t0)/max(0.01,hrs-t0)
                    surv = p0+(pct-p0)*frac
                else: surv = pct
                break
        self.sc_surv.set_value(f"%{surv:.0f}")
        # Ekip progress güncelle
        for tid in self.team_progress:
            if self.team_progress[tid] < 100:
                self.team_progress[tid] = min(100, self.team_progress[tid] + random.randint(0,2))
                if tid in self.team_cards:
                    self.team_cards[tid]._pb.setValue(self.team_progress[tid])
        self.op_map.update()

    def _add_next_event(self):
        if self.event_idx >= len(LIVE_EVENTS_TEMPLATE):
            return
        _, icon, cat, msg_tmpl = LIVE_EVENTS_TEMPLATE[self.event_idx]
        msg = msg_tmpl.format(
            mag=round(0.58*self.data['mmi']+1.0,1),
            trapped=self.data['trapped'], alive=self.alive_count,
            fires=self.data['fires'], gas_leaks=self.data['gas_leaks'],
            heavy=self.data['heavy'], destroyed=self.data['destroyed'],
        )
        h = self.elapsed//3600; m = (self.elapsed%3600)//60; s = self.elapsed%60
        self.feed.add_event(icon, cat, msg, f"{h:02}:{m:02}:{s:02}")
        self.event_idx += 1

    def _update_stats(self):
        # Kurtarılanlar artıyor
        rescue_rate = random.randint(0, 3)
        self.rescued += rescue_rate
        self.alive_count = min(self.data['trapped'], self.data['alive'] + self.rescued)
        self.sc_alive.set_value(self.alive_count)
        remaining_trapped = max(0, self.data['trapped'] - self.rescued)
        self.sc_enkaz.set_value(remaining_trapped)

    def closeEvent(self, event):
        self._tick_timer.stop(); self._event_timer.stop(); self._update_timer.stop()
        super().closeEvent(event)


class OperationalMapWidget(QWidget):
    def __init__(self, data, team_progress, parent=None):
        super().__init__(parent)
        self.data = data
        self.team_progress = team_progress
        self.setStyleSheet("background:#03030a;border:1px solid #1a1a35;border-radius:6px;")
        self.setMinimumHeight(350)
        random.seed(99)
        self._cols, self._rows = 30, 18
        self._mmi = data['mmi']
        d_probs = [r/100 for r in damage_ratios_from_mmi(self._mmi)]
        cum = [sum(d_probs[:i+1]) for i in range(5)]
        total = self._cols * self._rows
        self._grid = []
        gas_set  = set(random.sample(range(total), min(data['gas_leaks'], total)))
        fire_set = set(random.sample(list(gas_set), min(data['fires'], len(gas_set))))
        for gy in range(self._rows):
            row = []
            for gx in range(self._cols):
                idx = gy*self._cols+gx
                rv = random.random()
                dmg = next((i for i,c in enumerate(cum) if rv < c), 4)
                row.append({'dmg': dmg, 'gas': idx in gas_set, 'fire': idx in fire_set})
            self._grid.append(row)
        self._team_pos = {}
        positions = [(random.randint(0,self._cols-1), random.randint(0,self._rows-1)) for _ in range(12)]
        for i, (x,y) in enumerate(positions):
            self._team_pos[i+1] = [x, y, AFAD_TEAM_DEFS[i][4]]

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QBrush(QColor("#03030a")))
        lm, tm = 8, 8
        cw = (w-lm*2)/self._cols; ch = (h-tm*2)/self._rows
        fills  = [QColor(12,50,18,200),QColor(65,65,0,200),QColor(110,45,0,200),QColor(120,12,12,200),QColor(12,4,4,230)]
        edges  = [QColor(0,180,60,180),QColor(200,180,0,180),QColor(255,110,0,180),QColor(255,30,30,180),QColor(60,0,0,180)]
        t = time.time()
        for gy in range(self._rows):
            for gx in range(self._cols):
                cell = self._grid[gy][gx]
                dmg  = cell['dmg']
                x0 = lm + gx*cw; y0 = tm + gy*ch
                p.setBrush(QBrush(fills[dmg])); p.setPen(QPen(edges[dmg], 0.3))
                p.drawRect(QRectF(x0+0.5,y0+0.5,cw-1,ch-1))
                if cell['fire']:
                    a = int(120 + 80*math.sin(t*4+gx+gy))
                    p.setBrush(QBrush(QColor(255,80,0,a))); p.setPen(Qt.NoPen)
                    p.drawEllipse(QPointF(x0+cw*0.5,y0+ch*0.5), cw*0.3, ch*0.3)
                elif cell['gas']:
                    p.setBrush(QBrush(QColor(160,80,255,80))); p.setPen(Qt.NoPen)
                    p.drawEllipse(QPointF(x0+cw*0.5,y0+ch*0.5), cw*0.2, ch*0.2)
        # Ekipler
        for tid, (tx,ty,col) in self._team_pos.items():
            if tid in self.team_progress and self.team_progress[tid] < 100:
                if random.random() < 0.05:
                    dx = random.choice([-1,0,0,1]); dy = random.choice([-1,0,0,1])
                    self._team_pos[tid][0] = max(0, min(self._cols-1, tx+dx))
                    self._team_pos[tid][1] = max(0, min(self._rows-1, ty+dy))
            cx2 = lm + tx*cw + cw/2; cy2 = tm + ty*ch + ch/2
            r = max(cw,ch)*0.45
            pulse_a = int(100 + 80*math.sin(t*2+tid))
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(col).lighter(130),1))
            p.drawEllipse(QPointF(cx2,cy2), r*1.4, r*1.4)
            p.setBrush(QBrush(QColor(col))); p.setPen(QPen(QColor(0,0,0),1))
            p.drawEllipse(QPointF(cx2,cy2), r, r)
            p.setPen(QPen(QColor(255,255,255))); p.setFont(QFont("Arial",max(5,int(r*0.9)),QFont.Bold))
            p.drawText(QRectF(cx2-r,cy2-r,r*2,r*2), Qt.AlignCenter, str(tid))
        # Harita başlığı
        p.setPen(QPen(QColor(100,100,100))); p.setFont(QFont("Arial",8))
        p.drawText(lm, int(tm+self._rows*ch+12), "OPERASYONEL HARİTA — KADİKÖY/MODA — CANLI")


# ── İZOMETRİK NEONBİNA (2D HARİTA ÜZERİ) ────────────────────────────────────
class NeonBuilding3D(QGraphicsItem):
    def __init__(self, polygon_pts, height, status, view_ref):
        super().__init__()
        self.base_pts  = polygon_pts
        self.height    = height
        self.status    = status
        self.view_ref  = view_ref
        self.h_scale   = min(height / 11.0, 90.0)
        self.hovered   = False
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        n = len(self.base_pts)
        self._cx = sum(p.x() for p in self.base_pts) / n
        self._cy = sum(p.y() for p in self.base_pts) / n

    def boundingRect(self):
        xs = [p.x() for p in self.base_pts]
        ys = [p.y() for p in self.base_pts]
        m = 6 if not self.hovered else self.h_scale + 10
        return QRectF(min(xs)-m, min(ys)-m-m, max(xs)-min(xs)+2*m, max(ys)-min(ys)+2*m+m)

    def paint(self, painter, _option, _widget):
        painter.setRenderHint(QPainter.Antialiasing)
        n   = len(self.base_pts)
        h   = self.h_scale
        base_poly = QPolygonF(self.base_pts)

        if self.status == 'red':
            pulse  = (math.sin(time.time() * 3.0) + 1.0) / 2.0
            fill_c = QColor(int(130 + pulse*60), 10, 20, 190)
            edge_c = QColor(255, int(25+pulse*60), 50, 255)
        else:
            pulse  = 0.0
            fill_c = QColor(8, 35, 80, 185)
            edge_c = QColor(0, 155, 255, 210)

        if self.hovered:
            # Full 3D isometric view on hover
            top_pts  = [QPointF(p.x(), p.y() - h) for p in self.base_pts]
            top_poly = QPolygonF(top_pts)
            bright_fill = fill_c.lighter(160)
            painter.setPen(Qt.NoPen)
            for i in range(n):
                b1, b2 = self.base_pts[i], self.base_pts[(i+1)%n]
                t1, t2 = top_pts[i], top_pts[(i+1)%n]
                mid_y = (b1.y()+b2.y())/2.0
                wc = (QColor(110,8,18,230) if self.status=='red' else QColor(5,22,52,230)) if mid_y > self._cy \
                     else (QColor(65,4,10,210) if self.status=='red' else QColor(3,12,30,210))
                painter.setBrush(QBrush(wc))
                painter.drawPolygon(QPolygonF([b1,b2,t2,t1]))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(bright_fill))
            painter.drawPolygon(top_poly)
            draw_glow_poly(painter, top_poly, edge_c, core_w=0.8)
        else:
            # Flat fast draw — just the base polygon with neon border
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill_c))
            painter.drawPolygon(base_poly)
            painter.setPen(QPen(_gc(edge_c, 200), 0.8))
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.drawPolygon(base_poly)
            if self.status == 'red' and pulse > 0.4:
                # Outer glow ring for risky buildings
                painter.setPen(QPen(_gc(edge_c, int(pulse*80)), 4))
                painter.drawPolygon(base_poly)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.view_ref.animate_zoom_to(self)
        event.accept()

    def open_detail_window(self):
        dialog = BuildingInspector3D(self.base_pts, self.height, self.status, self.view_ref.window())
        dialog.exec_()


# ── ANA HARİTA ────────────────────────────────────────────────────────────────
class MainCityMap(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setBackgroundBrush(QBrush(BG_COLOR))
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.anim_timeline   = None
        self.target_building = None

        # Pulse timer — sadece risk binaları için, 8 fps yeterli
        self._pulse_timer = QTimer()
        self._pulse_timer.timeout.connect(self.viewport().update)
        self._pulse_timer.start(120)

        QTimer.singleShot(100, self.load_data)

    def load_data(self):
        try:
            print("[*] Harita verileri indiriliyor...")
            G = ox.graph_from_address(PLACE, dist=DIST, network_type='all')
            G_proj = ox.project_graph(G)
            tags = {'building': True, 'building:levels': True, 'height': True,
                    'natural': 'water', 'leisure': 'park'}
            features = ox.features_from_address(PLACE, tags=tags, dist=DIST)
            features_proj = features.to_crs(G_proj.graph['crs'])
            nodes = ox.graph_to_gdfs(G_proj, edges=False)
            minx, miny, maxx, maxy = nodes.total_bounds
            self.scene.setSceneRect(minx, -maxy, maxx-minx, maxy-miny)

            if 'natural' in features_proj.columns:
                self.draw_static(features_proj[features_proj['natural'] == 'water'],
                                 WATER_COLOR, alpha=255, z=-5)
            if 'leisure' in features_proj.columns:
                self.draw_static(features_proj[features_proj['leisure'] == 'park'],
                                 PARK_COLOR, alpha=30, z=-4)
            self.draw_roads(G_proj, z=-3)

            buildings = features_proj[features_proj['building'].notna()]
            for idx, row in buildings.iterrows():
                if row.geometry.geom_type == 'Polygon':
                    geoms = [row.geometry]
                elif row.geometry.geom_type == 'MultiPolygon':
                    geoms = list(row.geometry.geoms)
                else:
                    continue
                height = parse_height(row)
                status = 'red' if random.random() < 0.2 else 'green'
                for poly in geoms:
                    pts = [QPointF(x, -y) for x, y in poly.exterior.coords]
                    if len(pts) < 3: continue
                    b_item = NeonBuilding3D(pts, height, status, self)
                    self.scene.addItem(b_item)

            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            print("[OK] Harita yüklendi.")
            QTimer.singleShot(2000, self.send_neighborhood_report)
        except Exception as e:
            print(f"[HATA] Veriler yüklenemedi: {e}")

    def draw_static(self, gdf, fill, alpha=255, z=0):
        bc = QColor(fill)
        bc.setAlpha(alpha)
        for _, row in gdf.iterrows():
            if row.geometry.geom_type == 'Polygon':
                geoms = [row.geometry]
            elif row.geometry.geom_type == 'MultiPolygon':
                geoms = list(row.geometry.geoms)
            else:
                continue
            for poly in geoms:
                pts = [QPointF(x, -y) for x, y in poly.exterior.coords]
                item = self.scene.addPolygon(QPolygonF(pts), QPen(Qt.NoPen), QBrush(bc))
                item.setZValue(z)

    def draw_roads(self, G, z):
        pen = QPen(ROAD_COLOR, 0.5)
        pen.setCosmetic(True)
        for u, v, d in G.edges(data=True):
            x1, y1 = G.nodes[u]['x'], G.nodes[u]['y']
            x2, y2 = G.nodes[v]['x'], G.nodes[v]['y']
            self.scene.addLine(x1, -y1, x2, -y2, pen).setZValue(z)

    def send_neighborhood_report(self):
        print("[*] Mahalle raporu Flutter'a gönderiliyor...")
        reports = []
        for item in self.scene.items():
            if isinstance(item, NeonBuilding3D):
                reports.append({
                    "id": str(abs(hash(item)))[:5],
                    "height": f"{item.height:.1f}m",
                    "status": "RİSKLİ" if item.status == 'red' else "GÜVENLİ",
                    "deformasyon": f"{random.uniform(0.1, 12.0):.2f}°",
                    "zemin_skoru": f"{random.randint(30, 98)}/100"
                })
        MOBILE_SERVER.broadcast_data({"type": "NEIGHBORHOOD_REPORTS", "data": reports[:50]})

    def animate_zoom_to(self, building_item):
        self.target_building = building_item
        start_pos  = self.mapToScene(self.viewport().rect().center())
        start_scale = self.transform().m11()
        rect = building_item.boundingRect()
        end_pos   = building_item.mapToScene(rect.center())
        end_scale = 12.0
        self.anim_start_pos   = start_pos
        self.anim_end_pos     = end_pos
        self.anim_start_scale = start_scale
        self.anim_end_scale   = end_scale
        self.anim_timeline = QTimeLine(1200, self)
        self.anim_timeline.setFrameRange(0, 100)
        self.anim_timeline.setCurveShape(QTimeLine.EaseInOutCurve)
        self.anim_timeline.frameChanged.connect(self.step_animation)
        self.anim_timeline.finished.connect(self.finish_animation)
        self.anim_timeline.start()

    def step_animation(self, frame):
        t = frame / 100.0
        cx = self.anim_start_pos.x() + (self.anim_end_pos.x() - self.anim_start_pos.x()) * t
        cy = self.anim_start_pos.y() + (self.anim_end_pos.y() - self.anim_start_pos.y()) * t
        cs = self.anim_start_scale + (self.anim_end_scale - self.anim_start_scale) * t
        self.centerOn(cx, cy)
        self.setTransform(QTransform().scale(cs, cs))

    def finish_animation(self):
        if self.target_building:
            self.target_building.open_detail_window()

    def wheelEvent(self, event):
        zoom_in = event.angleDelta().y() > 0
        factor = 1.05 if zoom_in else (1 / 1.05)
        if not zoom_in:
            vr = self.viewport().rect()
            sr = self.sceneRect()
            min_s = min(vr.width()/sr.width(), vr.height()/sr.height())
            if self.transform().m11() * factor < min_s:
                self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
                return
        self.scale(factor, factor)


# ── ANA PENCERE ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KADİKÖY, İSTANBUL — BİNA KARA KUTU — GÖKÇE")
        self.setGeometry(100, 100, 1300, 920)
        self.setStyleSheet("QMainWindow { background: #030309; }")

        central = QWidget()
        self.setCentralWidget(central)
        vl = QVBoxLayout(central)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #020210, stop:0.5 #06061a, stop:1 #020210);
            border-bottom: 1px solid #00f2ff44;
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)

        title_lbl = QLabel("🏙  BİNA KARA KUTU — KADİKÖY, İSTANBUL")
        title_lbl.setStyleSheet("color:#00f2ff; font-size:15px; font-weight:900; letter-spacing:3px;")
        hl.addWidget(title_lbl)
        hl.addStretch()

        brand = QLabel("GÖKÇE")
        brand.setStyleSheet("""
            color: rgba(0, 242, 255, 180);
            font-size: 18px; font-weight: 900;
            letter-spacing: 6px;
        """)
        hl.addWidget(brand)

        vl.addWidget(header)
        vl.addWidget(MainCityMap(), 1)


# ── PORT SEÇİM DİALOGU ───────────────────────────────────────────────────────
class PortSelectionDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GÖKÇE — Bina Kara Kutu")
        self.setFixedSize(540, 440)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setStyleSheet("QDialog{background:#030309;color:white;border:2px solid #00f2ff44;}")
        self.selected_port  = None
        self.selected_port2 = None
        self.demo_mode      = False

        l = QVBoxLayout(self)
        l.setContentsMargins(28, 24, 28, 24)
        l.setSpacing(14)

        # Logo / başlık
        logo = QLabel("GÖKÇE")
        logo.setStyleSheet("color:#00f2ff;font-size:36px;font-weight:900;letter-spacing:10px;")
        logo.setAlignment(Qt.AlignCenter)
        sub  = QLabel("BİNA KARA KUTU SİSTEMİ")
        sub.setStyleSheet("color:rgba(0,242,255,120);font-size:12px;letter-spacing:4px;font-weight:bold;")
        sub.setAlignment(Qt.AlignCenter)
        l.addWidget(logo); l.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#00f2ff22; margin:4px 0;"); l.addWidget(sep)

        # Port 1
        p1_lbl = QLabel("🔌  JEOSKOP / İMU SENSÖR PORTU")
        p1_lbl.setStyleSheet("color:#00f2ff;font-size:10px;font-weight:900;letter-spacing:2px;")
        l.addWidget(p1_lbl)
        p1_row = QHBoxLayout(); p1_row.setSpacing(8)
        self.port1_combo = self._make_combo()
        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.setStyleSheet("QPushButton{background:#0a2040;color:#00f2ff;border:1px solid #00f2ff44;border-radius:4px;font-size:16px;font-weight:bold;} QPushButton:hover{background:#0d3060;}")
        refresh_btn.clicked.connect(self._refresh_ports)
        p1_row.addWidget(self.port1_combo, 1); p1_row.addWidget(refresh_btn)
        l.addLayout(p1_row)

        # Port 2 (opsiyonel)
        p2_lbl = QLabel("🔌  DAİRE SENSÖR PORTU  (opsiyonel)")
        p2_lbl.setStyleSheet("color:#aa00ff;font-size:10px;font-weight:900;letter-spacing:2px;")
        l.addWidget(p2_lbl)
        self.port2_combo = self._make_combo(add_none=True)
        l.addWidget(self.port2_combo)

        # Butonlar
        l.addStretch()
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)

        demo_btn = QPushButton("🎮  DEMO MODU  (sensör gerekmez)")
        demo_btn.setStyleSheet(cyber_btn("#003a1e","#001a0d","#00ff9d","#00ff9d44",pad=12,fs=12))
        demo_btn.clicked.connect(self._demo)

        start_btn = QPushButton("▶  BAŞLAT")
        start_btn.setStyleSheet(cyber_btn("#001a40","#000d20","#00f2ff","#00f2ff55",pad=12,fs=13))
        start_btn.clicked.connect(self._start)

        btn_row.addWidget(demo_btn); btn_row.addWidget(start_btn)
        l.addLayout(btn_row)

        note = QLabel("Demo modunda sensör verisi simüle edilir. Harita ve tüm raporlar çalışır.")
        note.setStyleSheet("color:#445;font-size:9px;")
        note.setAlignment(Qt.AlignCenter); l.addWidget(note)

        self._refresh_ports()

    def _make_combo(self, add_none=False):
        cb = self._make_combo_widget()
        if add_none:
            cb.addItem("— Kullanılmayacak —", "")
        return cb

    def _make_combo_widget(self):
        cb = QComboBox()
        cb.setStyleSheet("""
            QComboBox{background:#0a0a1e;color:white;border:1px solid #00f2ff44;border-radius:5px;padding:6px 10px;font-size:11px;}
            QComboBox::drop-down{border:none;}
            QComboBox QAbstractItemView{background:#0a0a1e;color:white;selection-background-color:#001a40;}
        """)
        return cb

    def _refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        for cb in [self.port1_combo, self.port2_combo]:
            current = cb.currentData()
            cb.blockSignals(True); cb.clear()
            if cb is self.port2_combo:
                cb.addItem("— Kullanılmayacak —", "")
            for p in ports:
                desc = p.description or p.device
                cb.addItem(f"{p.device}  —  {desc}", p.device)
            if not ports:
                cb.addItem("Port bulunamadı", "")
            # restore
            idx = cb.findData(current)
            if idx >= 0: cb.setCurrentIndex(idx)
            cb.blockSignals(False)

    def _start(self):
        port = self.port1_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Port Seçilmedi", "Lütfen bir sensör portu seçin veya Demo Modu kullanın.")
            return
        self.selected_port  = port
        self.selected_port2 = self.port2_combo.currentData() or ""
        self.accept()

    def _demo(self):
        self.demo_mode = True
        self.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    dlg = PortSelectionDialog()
    if dlg.exec_() != QDialog.Accepted:
        sys.exit(0)

    # Port ayarlarını global değişkenlere aktar
    if not dlg.demo_mode:
        SERIAL_PORT = dlg.selected_port
        if dlg.selected_port2:
            SERIAL_PORT_DAIRE = dlg.selected_port2

    # Demo modunda JeoskopWorker simüle veri göndersin
    if dlg.demo_mode:
        def _demo_run(self):
            self.status_signal.emit(True, "DEMO MODU — Simüle Sensör")
            t0 = time.time()
            while self.isRunning():
                t = time.time() - t0
                roll  = 8  * math.sin(t * 0.4)
                pitch = 5  * math.sin(t * 0.6 + 1)
                alt   = 15 * math.sin(t * 0.25) * 100
                # Simüle ham IMU (yaklaşık 0.05g titreşim)
                ax_sim = int(0.05 * 512 * math.sin(t*3))
                ay_sim = int(0.05 * 512 * math.cos(t*3.7))
                self.raw_imu_signal.emit(ax_sim, ay_sim, 512)
                self.orientation_signal.emit(roll, pitch, alt)
                time.sleep(0.04)
        JeoskopWorker.run = _demo_run

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
