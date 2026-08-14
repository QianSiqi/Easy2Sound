@echo off
REM Nuitka 编译 server_onnx.py（standalone onedir 模式）
REM 产物：dist_nuitka\server_onnx.dist\server_onnx.exe（含模型/配置，整个目录可分发）
REM 依赖：Nuitka + MinGW64（PATH 中无 gcc 时 --assume-yes-for-downloads 会自动下载）
cd /d "%~dp0"

.\venv\Scripts\python.exe -m nuitka ^
  --standalone ^
  --mingw64 ^
  --assume-yes-for-downloads ^
  --output-dir=dist_nuitka ^
  --include-package=onnxruntime ^
  --include-package=scipy ^
  --nofollow-import-to=librosa,numba,llvmlite,audioread ^
  --include-data-dir=pc_nsf_hifigan_44.1k_hop512_128bin_2025.02=pc_nsf_hifigan_44.1k_hop512_128bin_2025.02 ^
  --include-data-dir=hnsep=hnsep ^
  --include-data-file=config.yaml=config.yaml ^
  --include-data-file=config.default.yaml=config.default.yaml ^
  --windows-console-mode=force ^
  --jobs=8 ^
  server_onnx.py

if %errorlevel% neq 0 (
  echo.
  echo Build FAILED.
) else (
  echo.
  echo Build OK. Run: dist_nuitka\server_onnx.dist\server_onnx.exe
  echo (keep the whole server_onnx.dist folder together when distributing)
)
pause
