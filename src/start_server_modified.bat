@echo off
echo Starting Easy2Sound server (modified version)...
echo.
echo Changes applied:
echo   1. Soft clipping instead of hard normalization (less distortion)
echo   2. Reduced tension filter range (less darkening)
echo   3. Loudness normalization enabled
echo.
cd /d "%~dp0"
python server_onnx.py
pause
