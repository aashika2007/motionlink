@echo off
REM Person 2 circuit module: install, download real data, verify, test.
cd /d "%~dp0"
if not exist scripts\fetch_tumftm.py (
  echo Run this from the folder that contains scripts, motionink and tests.
  pause
  exit /b 1
)
python -m pip install -r requirements-circuits.txt || goto :fail
if "%~1"=="" (set TRACKS=Spielberg Monza Silverstone) else (set TRACKS=%*)
python scripts\fetch_tumftm.py --tracks %TRACKS% || goto :fail
python -m motionink.circuits.report %TRACKS%
python -m unittest discover -s tests -t . -v || goto :fail
echo.
echo All done. Start the API with: python dev_server.py
pause
exit /b 0
:fail
echo.
echo A step failed. Copy the messages above and share them.
pause
exit /b 1
