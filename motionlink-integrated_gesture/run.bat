@echo off
REM MotionLink: install, get circuit data on first run, start the app.
cd /d "%~dp0"
if not exist app.py (
  echo Run this from the folder that contains app.py, backend and frontend.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt || goto :fail
if not exist backend\circuits\data\tumftm\manifest.json (
  echo Downloading real circuit data from TUMFTM...
  python scripts\fetch_tumftm.py --tracks Spielberg Monza Silverstone || goto :fail
)
start "" http://127.0.0.1:5000
python app.py
exit /b 0
:fail
echo.
echo A step failed. Copy the messages above and share them.
pause
exit /b 1
