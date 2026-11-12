#!/bin/bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# --- restart an existing controller if its lock is already held ---
LOCK_FILE="/tmp/peoplebot-control.lock"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "ERROR: peoplebot control is already running; stopping it and restarting."

    RUNNING_APP_PIDS=()
    while IFS= read -r candidate_pid; do
        if [ -n "${candidate_pid}" ] && [ "${candidate_pid}" != "$$" ]; then
            RUNNING_APP_PIDS+=("${candidate_pid}")
        fi
    done < <(pgrep -f -- "${SCRIPT_DIR}/p3dx_control_python3.py" || true)

    RUNNING_LAUNCHER_PIDS=()
    while IFS= read -r candidate_pid; do
        if [ -z "${candidate_pid}" ] || [ "${candidate_pid}" = "$$" ]; then
            continue
        fi
        candidate_cwd="$(readlink -f "/proc/${candidate_pid}/cwd" 2>/dev/null || true)"
        if [ "${candidate_cwd}" = "${SCRIPT_DIR}" ]; then
            RUNNING_LAUNCHER_PIDS+=("${candidate_pid}")
        fi
    done < <(pgrep -f -- 'run_control_python3.sh' || true)

    for existing_pid in "${RUNNING_APP_PIDS[@]}"; do
        kill -INT "${existing_pid}" 2>/dev/null || true
    done

    # Give Python time to run its cleanup before stopping an old paused launcher.
    restart_wait=0
    while [ "${restart_wait}" -lt 30 ]; do
        running_app=0
        for existing_pid in "${RUNNING_APP_PIDS[@]}"; do
            if kill -0 "${existing_pid}" 2>/dev/null; then
                running_app=1
                break
            fi
        done
        [ "${running_app}" -eq 0 ] && break
        sleep 0.1
        restart_wait=$((restart_wait + 1))
    done

    for launcher_pid in "${RUNNING_LAUNCHER_PIDS[@]}"; do
        kill -TERM "${launcher_pid}" 2>/dev/null || true
    done

    LOCK_ACQUIRED=0
    restart_wait=0
    while [ "${restart_wait}" -lt 50 ]; do
        if flock -n 9; then
            LOCK_ACQUIRED=1
            break
        fi
        sleep 0.1
        restart_wait=$((restart_wait + 1))
    done

    if [ "${LOCK_ACQUIRED}" -eq 0 ]; then
        for existing_pid in "${RUNNING_APP_PIDS[@]}"; do
            kill -KILL "${existing_pid}" 2>/dev/null || true
        done
        for launcher_pid in "${RUNNING_LAUNCHER_PIDS[@]}"; do
            kill -KILL "${launcher_pid}" 2>/dev/null || true
        done
        restart_wait=0
        while [ "${restart_wait}" -lt 20 ]; do
            if flock -n 9; then
                LOCK_ACQUIRED=1
                break
            fi
            sleep 0.1
            restart_wait=$((restart_wait + 1))
        done
    fi

    if [ "${LOCK_ACQUIRED}" -eq 0 ]; then
        echo "ERROR: could not release the existing peoplebot control lock."
        exit 1
    fi
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

SERIAL_SIMULATION_NORMALIZED="$(printf '%s' "${SERIAL_SIMULATION:-false}" | tr '[:upper:]' '[:lower:]')"
case "${SERIAL_SIMULATION_NORMALIZED}" in
    1|true|yes|on) SERIAL_SIMULATION_ENABLED=1 ;;
    *) SERIAL_SIMULATION_ENABLED=0 ;;
esac

if [ "${SERIAL_SIMULATION_ENABLED}" -eq 0 ] && ! "${PYTHON_BIN}" -c 'import serial' 2>/dev/null; then
    echo "ERROR: pyserial is not installed in ${VENV_DIR}."
    echo "Run setup_python3.sh first to install the Python 3 dependencies."
    read -p "Tekan Enter untuk keluar..."
    exit 1
fi

"${PYTHON_BIN}" "$SCRIPT_DIR/p3dx_control_python3.py"
program_status=$?

echo
echo "Program exited."
exit "${program_status}"
