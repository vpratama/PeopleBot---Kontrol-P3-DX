#!/bin/bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# --- single-instance lock (prevents duplicate motor-control processes) ---
exec 9>"/tmp/peoplebot-control.lock"
if ! flock -n 9; then
    echo "ERROR: peoplebot control is already running."
    exit 1
fi

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

echo "[2/2] Running p3dx_control_python3.py..."
if [ ! -f p3dx_control_python3.py ]; then
    echo "ERROR: p3dx_control_python3.py not found in current folder!"
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

# Use the Python binary from the configured venv explicitly.
PYTHON_BIN="${VENV_DIR}/bin/python3"
if [ ! -x "${PYTHON_BIN}" ]; then
    echo "ERROR: ${PYTHON_BIN} not found or not executable!"
    echo "Run setup_python3.sh first to create the Python 3 environment."
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

if ! "${PYTHON_BIN}" -c 'import serial' 2>/dev/null; then
    echo "ERROR: pyserial is not installed in ${VENV_DIR}."
    echo "Run setup_python3.sh first to install the Python 3 dependencies."
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

"${PYTHON_BIN}" "$SCRIPT_DIR/p3dx_control_python3.py"

echo
echo "Program exited."
read -p "Tekan Enter untuk keluar..."
