"""本地历史：记录已提取过的 PDF，便于重启后回看。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import app_root


def history_path() -> Path:
    return app_root() / "data" / "history.json"


def load_history() -> list[dict[str, Any]]:
    path = history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pdf = str(item.get("pdf_path") or "").strip()
        db = str(item.get("db_path") or "").strip()
        if not pdf or not db:
            continue
        if not Path(db).exists():
            continue
        cleaned.append(
            {
                "pdf_path": pdf,
                "db_path": db,
                "filename": item.get("filename") or Path(pdf).name,
                "table_count": int(item.get("table_count") or 0),
                "processed_at": item.get("processed_at") or "",
            }
        )
    return cleaned


def save_history(items: list[dict[str, Any]]) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_history(
    pdf_path: str | Path,
    db_path: str | Path,
    table_count: int = 0,
) -> list[dict[str, Any]]:
    pdf = str(Path(pdf_path).resolve())
    db = str(Path(db_path).resolve())
    items = [i for i in load_history() if Path(i["pdf_path"]).resolve() != Path(pdf)]
    entry = {
        "pdf_path": pdf,
        "db_path": db,
        "filename": Path(pdf).name,
        "table_count": int(table_count),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.insert(0, entry)
    # 保留最近 50 条
    items = items[:50]
    save_history(items)
    return items


def remove_history(pdf_path: str | Path) -> list[dict[str, Any]]:
    want = Path(pdf_path).resolve()
    items = [i for i in load_history() if Path(i["pdf_path"]).resolve() != want]
    save_history(items)
    return items


def history_label(item: dict[str, Any]) -> str:
    name = item.get("filename") or Path(str(item.get("pdf_path", ""))).name
    count = item.get("table_count")
    when = (item.get("processed_at") or "")[:16].replace("T", " ")
    parts = [name]
    if count is not None:
        parts.append(f"{count}表")
    if when:
        parts.append(when)
    return "  |  ".join(parts)
