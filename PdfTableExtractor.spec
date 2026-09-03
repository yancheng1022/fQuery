# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller：RapidOCR 轻量绿色包。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

ROOT = Path(SPECPATH).resolve()

datas = []
binaries = []
hiddenimports = [
    "PIL",
    "PIL._tkinter_finder",
    "tkinter",
    "pymupdf",
    "cv2",
    "numpy",
    "pandas",
    "img2table",
    "rapidocr",
    "onnxruntime",
    "pdf_table_extractor",
    "pdf_table_extractor.paths",
    "pdf_table_extractor.extractor",
    "pdf_table_extractor.database",
    "pdf_table_extractor.gui",
    "pdf_table_extractor.ocr_patch",
]

for pkg in ("rapidocr", "onnxruntime", "img2table", "cv2", "pymupdf", "omegaconf"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:
        print(f"[warn] collect_all({pkg}) failed: {exc}")

try:
    binaries += collect_dynamic_libs("onnxruntime")
    binaries += collect_dynamic_libs("cv2")
except Exception:
    pass

# Bundle onnx models next to runtime via datas -> extracted under _internal;
# also copy to dist root models/ in build script.
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "rthook_offline.py")],
    excludes=[
        "matplotlib",
        "IPython",
        "notebook",
        "pytest",
        "paddle",
        "paddleocr",
        "paddlex",
        "torch",
        "torchvision",
        "tensorboard",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PdfTableExtractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="PdfTableExtractor",
)
