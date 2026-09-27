@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation complete. Run start.bat.
pause
exit /b 0
:failed
echo Installation failed. Install Python 3.12 x64 from python.org and retry.
pause
exit /b 1
