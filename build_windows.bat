@echo off
echo ============================================
echo  GOKCE - Bina Kara Kutu - Windows EXE Build
echo ============================================
echo.

:: Python yuklu mu kontrol et
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadi!
    echo Python 3.10+ indirin: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Gerekli paketleri yukle
echo [1/3] Bagimliliklar yukleniyor...
pip install -r requirements.txt
pip install pyinstaller

:: PyInstaller ile exe olustur
echo.
echo [2/3] EXE olusturuluyor (bu 3-5 dakika surebilir)...
pyinstaller ^
    --onedir ^
    --windowed ^
    --name "BinaKaraKutu_GOKCE" ^
    --icon=icon.ico ^
    --add-data "cache;cache" ^
    --hidden-import "osmnx" ^
    --hidden-import "geopandas" ^
    --hidden-import "shapely" ^
    --hidden-import "fiona" ^
    --hidden-import "pyproj" ^
    --hidden-import "networkx" ^
    --hidden-import "pandas" ^
    --hidden-import "PyQt5" ^
    --hidden-import "PyQt5.QtCore" ^
    --hidden-import "PyQt5.QtGui" ^
    --hidden-import "PyQt5.QtWidgets" ^
    --hidden-import "serial" ^
    --hidden-import "serial.tools.list_ports" ^
    --hidden-import "websockets" ^
    --collect-all osmnx ^
    --collect-all geopandas ^
    --collect-all shapely ^
    --collect-all fiona ^
    --collect-all pyproj ^
    bina_karakutu.py

echo.
echo [3/3] Tamamlandi!
echo.
echo EXE konumu: dist\BinaKaraKutu_GOKCE\BinaKaraKutu_GOKCE.exe
echo Bu klasoru oldugu gibi kopyalayin - iceride calistirma dosyasi var.
echo.
echo NOT: ilk acilista harita icin internet baglantisi gereklidir.
echo Sonraki acilislarda cache klasoründen yuklenir (offline calisir).
echo.
pause
