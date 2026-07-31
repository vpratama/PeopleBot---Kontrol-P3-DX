@echo off
setlocal
:: === KONFIGURASI ===
set VENV_DIR=.venv
set WHEELS_DIR=.\wheels
set PYTHON27_PATH=C:\Python27\python.exe

echo [1/6] Menghapus existing venv dan wheels folder...
if exist %VENV_DIR% (
    echo  - Menghapus %VENV_DIR%...
    call %VENV_DIR%\Scripts\deactivate.bat 2>nul
    rmdir /s /q %VENV_DIR%
)
if exist %WHEELS_DIR% (
    echo  - Menghapus %WHEELS_DIR%...
    rmdir /s /q %WHEELS_DIR%
)

echo.
echo [2/6] Install virtualenv==16.7.12 via pip...
python -m pip install --upgrade pip
python -m pip install virtualenv==16.7.12

echo.
echo [3/6] Membuat venv dengan Python 2.7...
virtualenv -p "%PYTHON27_PATH%" %VENV_DIR%

echo.
echo [4/6] Download wheels ke %WHEELS_DIR%...
mkdir %WHEELS_DIR% 2>nul
pip download -d %WHEELS_DIR% -r requirements.txt

echo.
echo [5/6] Aktivasi venv...
call %VENV_DIR%\Scripts\activate.bat

echo.
echo [6/6] Install package offline dari wheels...
pip install --no-index --find-links=%WHEELS_DIR% -r requirements.txt

cmd /k