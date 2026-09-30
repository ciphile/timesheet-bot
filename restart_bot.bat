@echo off
REM ====================================================================
REM  restart_bot.bat - TAT dung tien trinh bot timesheet roi BAT LAI.
REM  Dung khi: doi settings.json / secrets.env, cap nhat code, bot bi treo.
REM  Chi tat chuong trinh dang chay src\bot.py (KHONG dung cac chuong trinh
REM  Python khac tren may). Phai nam cung thu muc voi start_bot.vbs.
REM ====================================================================
echo Dang tat bot timesheet (neu dang chay)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*\src\bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  Da tat bot, PID ' + $_.ProcessId) }"
timeout /t 3 /nobreak >nul
echo Dang bat lai bot...
wscript.exe "%~dp0start_bot.vbs"
echo Xong. Cho khoang 10 giay roi nhan /status cho bot tren Telegram.
pause
