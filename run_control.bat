@echo off
setlocal enableextensions enabledelayedexpansion

:: === LOAD CONFIGURATION FROM .ENV ===
if not exist .env (
    echo ERROR: File .env tidak ditemukan!
    echo Harap buat file .env terlebih dahulu.
    pause
    exit /b 1
)

for /f "usebackq tokens=1* delims==" %%A in (".env") do (
    set "line=%%A"
    if defined line (
        if not "!line:~0,1!"=="#" (
            if /i not "!line:~0,3!"=="rem" (
                set "%%A=%%B"
            )
        )
    )
)

:: Pastikan VENV_DIR terisi dari .env
if not defined VENV_DIR (
    echo ERROR: VENV_DIR tidak ditemukan di dalam file .env!
    pause
    exit /b 1
)

echo [1/2] Activating venv (%VENV_DIR%)...
if not exist %VENV_DIR%\Scripts\activate.bat (
    echo ERROR: %VENV_DIR%\Scripts\activate.bat not found!
    echo Run setup.bat first to create the venv.
    pause
    exit /b 1
)

call %VENV_DIR%\Scripts\activate.bat

echo [2/2] Running p3dx_control.py...
if not exist p3dx_control.py (
    echo ERROR: p3dx_control.py not found in current folder!
    pause
    exit /b 1
)

python p3dx_control.py

echo.
echo Program exited.
pause