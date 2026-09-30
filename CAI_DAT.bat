@echo off
REM ====================================================================
REM  CAI_DAT.bat - Cai bot timesheet len may cua ban (chay 1 lan).
REM  - Tao thu muc: src, config, template, data, output, backup
REM  - Chep 28 file .py + file mau Excel + cau hinh MAU
REM  - Cai thu vien Python (requirements.txt)
REM  - (Tuy chon) Tao lich chay tu dong trong Task Scheduler
REM  AN TOAN: neu thu muc dich DA CO bot (co config\secrets.env) -> DUNG LAI,
REM  KHONG ghi de du lieu / cau hinh cua ban.
REM ====================================================================
setlocal EnableDelayedExpansion
set "REPO=%~dp0"
set "DEST=C:\timesheet"
echo.
echo ===== CAI DAT BOT TIMESHEET =====
echo Thu muc cai dat mac dinh: %DEST%
set /p "NHAP=Nhan ENTER de dung mac dinh, hoac go thu muc khac (vd D:\timesheet): "
if not "!NHAP!"=="" set "DEST=!NHAP!"
REM bo dau nhay kep (vd dan tu "Copy as path" cua Windows)
set "DEST=!DEST:"=!"
if "!DEST:~-1!"=="\" set "DEST=!DEST:~0,-1!"
echo.
if /I "!DEST!\"=="%REPO%" (
  echo [DUNG] Thu muc cai dat trung voi thu muc tai ve. Hay chon thu muc KHAC, vd C:\timesheet
  pause
  exit /b 1
)
if exist "!DEST!\config\secrets.env" (
  echo [DUNG] "!DEST!" DA CO bot dang cai ^(co config\secrets.env^).
  echo        De KHONG ghi de du lieu / cau hinh cua ban, bo cai dat DUNG LAI.
  echo        Muon cai moi thi chon thu muc khac.
  pause
  exit /b 1
)
python --version >nul 2>&1
if errorlevel 1 (
  echo [DUNG] Chua co Python. Cai Python 3.10 tro len tu https://www.python.org/downloads/
  echo        NHO tick o "Add python.exe to PATH" luc cai, roi chay lai file nay.
  pause
  exit /b 1
)
echo [1/5] Tao thu muc trong "!DEST!" ...
for %%D in (src config template data output backup) do if not exist "!DEST!\%%D" mkdir "!DEST!\%%D"
echo [2/5] Chep file ...
copy /Y "%REPO%src\*.py" "!DEST!\src\" >nul
copy /Y "%REPO%template\master_template.xlsx" "!DEST!\template\" >nul
for %%F in (requirements.txt start_bot.vbs run_weekly.vbs restart_bot.bat README.md) do copy /Y "%REPO%%%F" "!DEST!\" >nul
if not exist "!DEST!\config\settings.json" copy "%REPO%config\settings.example.json" "!DEST!\config\settings.json" >nul
if not exist "!DEST!\config\secrets.env" copy "%REPO%config\secrets.env.example" "!DEST!\config\secrets.env" >nul
set N=0
for %%F in ("!DEST!\src\*.py") do set /a N+=1
if not "!N!"=="28" (
  echo [CANH BAO] Chi chep duoc !N!/28 file .py - kiem tra lai thu muc src trong ban tai ve.
) else (
  echo       Du 28/28 file .py
)
echo [3/5] Cai thu vien Python (can Internet, mat 1-3 phut) ...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r "!DEST!\requirements.txt"
if errorlevel 1 echo [CANH BAO] Cai thu vien bi loi - chup man hinh loi, xem README muc Su co.
echo [4/5] Lich chay tu dong (bot bat 16:00 hang ngay + chot timesheet thu 6 17:00)
choice /C YN /M "Tao lich tu dong ngay bay gio"
if errorlevel 2 goto BOQUA
schtasks /Create /TN "Timesheet Bot" /TR "wscript.exe \"!DEST!\start_bot.vbs\"" /SC DAILY /ST 16:00 /RL LIMITED /F
schtasks /Create /TN "Timesheet Weekly" /TR "wscript.exe \"!DEST!\run_weekly.vbs\"" /SC WEEKLY /D FRI /ST 17:00 /RL LIMITED /F
REM Laptop: chay ca khi dung PIN + may tat luc 16:00/17:00 thi CHAY BU khi bat may
powershell -NoProfile -Command "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; Set-ScheduledTask -TaskName 'Timesheet Bot' -Settings $s | Out-Null; Set-ScheduledTask -TaskName 'Timesheet Weekly' -Settings $s | Out-Null"
if errorlevel 1 echo [CANH BAO] Chua bat duoc tuy chon pin/chay bu - lam tay theo README muc 3b.
:BOQUA
echo [5/5] Mo 2 file cau hinh de ban dien (lam theo README.md muc 3) ...
start "" notepad "!DEST!\config\secrets.env"
start "" notepad "!DEST!\config\settings.json"
echo.
echo ===== CAI DAT XONG =====
echo Dien xong 2 file cau hinh roi kiem tra:
echo    cd /d "!DEST!\src"
echo    python config_loader.py
echo    python selfcheck.py
echo Sau do khoi dong bot: nhap dup "!DEST!\start_bot.vbs"
pause
