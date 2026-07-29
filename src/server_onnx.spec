# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['server_onnx.py'],
    pathex=['E:\\bc\\Easy2Sound\\src'],
    binaries=[],
    datas=[
        ('pc_nsf_hifigan_44.1k_hop512_128bin_2025.02', 'pc_nsf_hifigan_44.1k_hop512_128bin_2025.02'),
        ('hnsep', 'hnsep'),
        ('config.yaml', '.'),
        ('config.default.yaml', '.'),
        ('ds_cmudict-07b.txt', '.'),
        ('ds-zh-pinyin-lite.txt', '.'),
    ],
    hiddenimports=[
        'util', 'util.wav2mel_numpy', 'util.hnsep_onnx_infer',
        'yaml', 'onnxruntime', 'filelock', 'resampy', 'soundfile',
        'numpy', 'numpy.core._dtype_ctypes',
        'scipy', 'scipy.interpolate',
        'charset_normalizer', 'certifi', 'markupsafe',
        'librosa', 'audioread', 'lazy_loader', 'msgpack',
        'decorator', 'numba', 'llvmlite',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'unittest', 'pytest', 'setuptools',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'IPython', 'jupyter', 'notebook', 'sphinx',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='server_onnx',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
