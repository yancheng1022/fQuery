# runtime hook：在任何业务 import 之前设置离线环境变量
import os
import sys
from pathlib import Path

os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ.setdefault("FLAGS_use_mkldnn", "0")

if getattr(sys, "frozen", False):
    root = Path(sys.executable).resolve().parent
else:
    root = Path(__file__).resolve().parents[1]

cache = root / ".paddlex"
cache.mkdir(parents=True, exist_ok=True)
os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache)
