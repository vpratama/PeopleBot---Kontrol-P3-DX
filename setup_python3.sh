#!/bin/bash
set -e

# === LOAD CONFIGURATION FROM .ENV ===
if [ ! -f .env ]; then
    echo "[ERROR] File .env tidak ditemukan!"
    echo "Harap buat file .env terlebih dahulu."
    exit 1
fi

# Load variables directly with trim
set -o allexport
source <(grep -v '^#' .env | grep -v '^[[:space:]]*$' | sed 's/\r$//')
set +o allexport

VENV_DIR="${VENV_DIR:-.venv}"
WHEELS_DIR="${WHEELS_DIR:-./wheels}"
PYTHON3_PATH="${PYTHON3_PATH:-python3}"

echo "[INFO] Konfigurasi berhasil dimuat dari .env:"
echo "  - VENV_DIR     : ${VENV_DIR}"
echo "  - WHEELS_DIR   : ${WHEELS_DIR}"
echo "  - PYTHON3_PATH : ${PYTHON3_PATH}"
echo

echo "[1/5] Menghapus existing venv dan wheels folder..."
if [ -d "${VENV_DIR}" ]; then
    echo "  - Menghapus ${VENV_DIR}..."
    rm -rf "${VENV_DIR}"
fi

if [ -d "${WHEELS_DIR}" ]; then
    echo "  - Menghapus ${WHEELS_DIR}..."
    rm -rf "${WHEELS_DIR}"
fi

echo
echo "[2/5] Membuat virtual environment dengan Python 3..."
"${PYTHON3_PATH}" -m venv "${VENV_DIR}"

echo
echo "[3/5] Download wheels ke ${WHEELS_DIR}..."
mkdir -p "${WHEELS_DIR}"
"${PYTHON3_PATH}" -m pip download -d "${WHEELS_DIR}" -r requirements.txt

echo
echo "[4/5] Aktivasi venv..."
ACTIVATE_SCRIPT="${VENV_DIR}/bin/activate"

if [ ! -f "${ACTIVATE_SCRIPT}" ]; then
    echo "[ERROR] File activation script '${ACTIVATE_SCRIPT}' tidak ditemukan!"
    exit 1
fi

source "${ACTIVATE_SCRIPT}"

echo
echo "[5/5] Install package offline dari wheels..."
pip install --upgrade pip --no-index --find-links="${WHEELS_DIR}" 2>/dev/null || true
pip install --no-index --find-links="${WHEELS_DIR}" -r requirements.txt

echo
echo "[SUCCESS] Environment Python 3 berhasil disiapkan."

exec $SHELL