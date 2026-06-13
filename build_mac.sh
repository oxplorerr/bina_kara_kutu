#!/bin/bash
echo "============================================"
echo " GOKCE - Bina Kara Kutu - macOS APP Build"
echo "============================================"
echo

source venv/bin/activate

echo "[1/3] PyInstaller kuruluyor..."
pip install pyinstaller

echo "[2/3] .app olusturuluyor..."
pyinstaller \
    --onedir \
    --windowed \
    --name "BinaKaraKutu_GOKCE" \
    --add-data "cache:cache" \
    --hidden-import "osmnx" \
    --hidden-import "geopandas" \
    --hidden-import "shapely" \
    --hidden-import "fiona" \
    --hidden-import "pyproj" \
    --hidden-import "networkx" \
    --hidden-import "pandas" \
    --hidden-import "PyQt5" \
    --hidden-import "serial" \
    --hidden-import "serial.tools.list_ports" \
    --hidden-import "websockets" \
    --collect-all osmnx \
    --collect-all geopandas \
    --collect-all shapely \
    bina_karakutu.py

echo
echo "[3/3] Tamamlandi!"
echo "Uygulama: dist/BinaKaraKutu_GOKCE.app"
