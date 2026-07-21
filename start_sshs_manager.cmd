@echo off
setlocal
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pythonw.exe "%~dp0sshfs_mount_manager.py"
    exit /b 0
)

where pyw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pyw.exe -3 "%~dp0sshfs_mount_manager.py"
    exit /b 0
)

where python.exe >nul 2>nul
if not errorlevel 1 (
    python.exe "%~dp0sshfs_mount_manager.py"
    if errorlevel 1 pause
    exit /b %errorlevel%
)

where py.exe >nul 2>nul
if not errorlevel 1 (
    py.exe -3 "%~dp0sshfs_mount_manager.py"
    if errorlevel 1 pause
    exit /b %errorlevel%
)

echo Python 3 was not found.
echo Install Python 3 and run this launcher again.
pause
