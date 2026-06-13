import serial
import struct

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
        except Exception as e:
            print(f"[HATA] Bağlantı sorunu: {e}")
            return False

    def get_imu_data(self):
        """
        Karttan İvmeölçer ve Jiroskop verisini ister.
        Dönüş: {'ax': .., 'ay': .., 'az': ..} veya None
        """
        if not self.connected or not self.ser:
            return None

        try:
            # MSP_RAW_IMU (Komut Kodu: 102) isteği gönderiliyor
            request = struct.pack('<3sBBB', b'$M<', 0, 102, 102)
            self.ser.write(request)

            # Cevap bekleniyor (24 byte)
            response = self.ser.read(24)
            
            if len(response) < 24 or response[:3] != b'$M>':
                return None

            # DÜZELTİLEN KISIM BURASI:
            # Format: Header(3s) + Size(B) + Code(B) + 9xShort(9h) + Checksum(B)
            data = struct.unpack('<3sBB9hB', response)
            
            # data[0]=Header, data[1]=Size, data[2]=Code
            # Veriler 3. indeksten başlıyor:
            # data[3]=AccX, data[4]=AccY, data[5]=AccZ
            return {
                'ax': data[3],
                'ay': data[4],
                'az': data[5]
            }
            
        except Exception as e:
            # Hata olursa ekrana basmasın, sessizce geçsin (akışı bozmamak için)
            return None

    def close(self):
        if self.ser:
            self.ser.close()
            print("Bağlantı kapatıldı.")