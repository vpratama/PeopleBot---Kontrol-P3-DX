#!/bin/bash

# === LOAD CONFIGURATION FROM .ENV ===
if [ ! -f .env ]; then
    echo "ERROR: File .env tidak ditemukan!"
    echo "Harap buat file .env terlebih dahulu."
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

# Export semua variabel dari .env (mengabaikan komentar '#' dan baris kosong)
set -o allexport
source <(grep -v '^#' .env | grep -v '^[[:space:]]*$' | sed 's/\r$//')
set +o allexport

# Pastikan VENV_DIR terisi dari .env
if [ -z "${VENV_DIR}" ]; then
    echo "ERROR: VENV_DIR tidak ditemukan di dalam file .env!"
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

echo "[1/2] Activating venv (${VENV_DIR})..."
if [ ! -f "${VENV_DIR}/bin/activate" ]; then
    echo "ERROR: ${VENV_DIR}/bin/activate not found!"
    echo "Run setup.sh first to create the venv."
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

source "${VENV_DIR}/bin/activate"

echo "[2/2] Running p3dx_control.py..."
if [ ! -f p3dx_control.py ]; then
    echo "ERROR: p3dx_control.py not found in current folder!"
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

python p3dx_control.py

echo
echo "Program exited."
read -p "Tekan Enter untuk keluar..."