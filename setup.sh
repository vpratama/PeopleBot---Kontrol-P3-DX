#!/bin/bash

# === LOAD CONFIGURATION FROM .ENV ===
if [ ! -f .env ]; then
    echo "[ERROR] File .env tidak ditemukan!"
    echo "Harap buat file .env terlebih dahulu."
    exit 1
fi

# Export semua variabel dari .env (mengabaikan baris kosong dan komentar '#')
export $(grep -v '^#' .env | xargs)

echo "[INFO] Konfigurasi berhasil dimuat dari .env:"
echo "  - VENV_DIR     : ${VENV_DIR}"
echo "  - WHEELS_DIR   : ${WHEELS_DIR}"
echo "  - PYTHON27_PATH: ${PYTHON27_PATH}"
echo

echo "[1/6] Menghapus existing venv dan wheels folder..."
if [ -d "${VENV_DIR}" ]; then
    echo "  - Menghapus ${VENV_DIR}..."
    if [ -f "${VENV_DIR}/bin/deactivate" ]; then
        deactivate 2>/dev/null || true
    fi
    rm -rf "${VENV_DIR}"
fi

if [ -d "${WHEELS_DIR}" ]; then
    echo "  - Menghapus ${WHEELS_DIR}..."
    rm -rf "${WHEELS_DIR}"
fi

echo
echo "[2/6] Install virtualenv==16.7.12 via pip..."
python -m pip install --upgrade pip
python -m pip install virtualenv==16.7.12

echo
echo "[3/6] Membuat venv dengan Python 2.7..."
virtualenv -p "${PYTHON27_PATH}" "${VENV_DIR}"

echo
echo "[4/6] Download wheels ke ${WHEELS_DIR}..."
mkdir -p "${WHEELS_DIR}"
pip download -d "${WHEELS_DIR}" -r requirements.txt

echo
echo "[5/6] Aktivasi venv..."
source "${VENV_DIR}/bin/activate"

echo
echo "[6/6] Install package offline dari wheels..."
pip install --no-index --find-links="${WHEELS_DIR}" -r requirements.txt

# Menjaga shell tetap terbuka interaktif dalam lingkungan venv yang sudah aktif
exec $SHELL