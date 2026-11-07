@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing dependencies...
python -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist .env copy .env.example .env >nul
start "" cmd /c "timeout /t 10 >nul & start http://127.0.0.1:8000/demo"
python scripts\run_all.py --seed
pause
