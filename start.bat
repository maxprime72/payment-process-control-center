@echo off
setlocal

title NABINAGAR PAYMENT PROCESS CONTROL CENTER - PAYBLE

:: Determine project directory
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

:: Check for Payble_Portable distribution
if exist "%PROJECT_DIR%Payble_Portable\Payble.exe" (
    echo Launching Payble Portable Edition...
    start "" "%PROJECT_DIR%Payble_Portable\Payble.exe"
    exit /b 0
)

:: Check for direct Payble.exe
if exist "%PROJECT_DIR%Payble.exe" (
    echo Launching Payble...
    start "" "%PROJECT_DIR%Payble.exe"
    exit /b 0
)

:: Check for dist\Payble.exe
if exist "%PROJECT_DIR%dist\Payble.exe" (
    echo Launching Payble from dist...
    start "" "%PROJECT_DIR%dist\Payble.exe"
    exit /b 0
)

:: Check if portable zip exists and can be extracted
if exist "%PROJECT_DIR%Payble_Portable.zip" (
    echo [NOTE] Payble_Portable.zip detected. Extracting...
    powershell -NoProfile -Command "Expand-Archive -Path '%PROJECT_DIR%Payble_Portable.zip' -DestinationPath '%PROJECT_DIR%' -Force"
    if exist "%PROJECT_DIR%Payble_Portable\Payble.exe" (
        start "" "%PROJECT_DIR%Payble_Portable\Payble.exe"
        exit /b 0
    )
)

echo ==========================================================
echo [ERROR] Payble executable not found!
echo ==========================================================
echo Could not locate 'Payble_Portable\Payble.exe' or 'Payble.exe'.
echo.
echo To build the standalone portable executable, run:
echo   build_portable.bat
echo.
echo Or extract 'Payble_Portable.zip' into this directory.
echo ==========================================================
pause
exit /b 1
