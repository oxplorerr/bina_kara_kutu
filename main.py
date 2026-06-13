import time
import math
from msp_layer import MspHandler

# --- AYARLAR ---
PORT = "/dev/tty.usbmodem354A386F30331"  # <--- BURAYA KENDİ PORTUNUZU YAPIŞTIRIN!
# Örnek: PORT = "/dev/tty.usbmodem1101"

def calculate_tilt(ax, ay, az):
    """X, Y, Z ivme verisinden EĞİM açısını hesaplar (Derece cinsinden)"""
    # Basit trigonometri ile Roll (X ekseni) ve Pitch (Y ekseni) eğimi
    # 57.295 radyanı dereceye çevirir
    roll = math.atan2(ay, az) * 57.295
    pitch = math.atan2(-ax, math.sqrt(ay*ay + az*az)) * 57.295
    return roll, pitch

def main():
    sensor = MspHandler(PORT)
    
    if not sensor.connect():
        return # Bağlanamazsa çık

    print("\nSensör kalibrasyonu için 3 saniye bekleyin (Lütfen kımıldatmayın)...")
    time.sleep(3)
    print("Veri akışı başlıyor...\n")
    print(f"{'ACC X':^10} | {'ACC Y':^10} | {'ACC Z':^10} | {'EĞİM (Roll)':^15} | {'EĞİM (Pitch)':^15}")
    print("-" * 75)

    try:
        while True:
            data = sensor.get_imu_data()
            
            if data:
                # Ham Veriler
                ax, ay, az = data['ax'], data['ay'], data['az']
                
                # Açı Hesaplama
                roll, pitch = calculate_tilt(ax, ay, az)

                # Ekrana Yazdır (Formatlı düzgün çıktı)
                print(f"{ax:^10} | {ay:^10} | {az:^10} | {roll:^15.1f} | {pitch:^15.1f}", end="\r")
            
            # CPU'yu yormamak için minik bekleme
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n\nProgram durduruldu.")
        sensor.close()

if __name__ == "__main__":
    main()