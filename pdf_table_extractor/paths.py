"""运行路径与离线模型目录解析。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    """程序根目录：开发时为项目根；打包后为 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def setup_offline_env() -> Path:
    """配置离线运行环境，返回本地模型根目录。"""
    root = app_root()
    models_dir = root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # 关闭无关网络探测（兼容旧环境变量）
    os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("RAPIDOCR_MODEL_DIR", str(models_dir))
    return models_dir


def rapidocr_model_dir() -> Path | None:
    """若本地 models 目录含 onnx，则返回该目录，否则 None（使用包内默认模型）。"""
    candidates = [
        Path(os.environ["RAPIDOCR_MODEL_DIR"]) if os.environ.get("RAPIDOCR_MODEL_DIR") else None,
        app_root() / "models",
    ]
    for base in candidates:
        if base is None:
            continue
        if any(base.glob("*.onnx")):
            return base
    return None


def rapidocr_params() -> dict:
    """构造 img2table/RapidOCR 所需的中文识别参数。"""
    from rapidocr import LangRec

    params: dict = {
        "Rec.lang_type": LangRec.CH,
        "Global.log_level": "error",
    }
    model_dir = rapidocr_model_dir()
    if model_dir is not None:
        params["Global.model_root_dir"] = str(model_dir)
    return params
