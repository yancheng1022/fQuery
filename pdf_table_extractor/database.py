"""SQLite 存储：表名、表格内容，并建立 FTS 便于后续搜索。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL UNIQUE,
    page_count INTEGER,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    table_index INTEGER NOT NULL,
    table_name TEXT,
    row_count INTEGER NOT NULL,
    col_count INTEGER NOT NULL,
    bbox_json TEXT,
    content_json TEXT NOT NULL,
    content_text TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER NOT NULL,
    row_idx INTEGER NOT NULL,
    col_idx INTEGER NOT NULL,
    cell_text TEXT NOT NULL,
    FOREIGN KEY(table_id) REFERENCES tables(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS tables_fts USING fts5(
    table_name,
    content_text,
    tokenize='unicode61'
);

CREATE INDEX IF NOT EXISTS idx_tables_doc ON tables(document_id);
CREATE INDEX IF NOT EXISTS idx_tables_page ON tables(page_number);
CREATE INDEX IF NOT EXISTS idx_cells_table ON cells(table_id);
CREATE INDEX IF NOT EXISTS idx_cells_text ON cells(cell_text);
"""


class TableDatabase:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_document(self, filepath: str | Path, page_count: int) -> int:
        path = Path(filepath).resolve()
        now = datetime.now().isoformat(timespec="seconds")
        existing = self.conn.execute(
            "SELECT id FROM documents WHERE filepath = ?", (str(path),)
        ).fetchone()
        if existing:
            doc_id = int(existing["id"])
            self.conn.execute("DELETE FROM cells WHERE table_id IN (SELECT id FROM tables WHERE document_id = ?)", (doc_id,))
            self.conn.execute(
                "DELETE FROM tables_fts WHERE rowid IN (SELECT id FROM tables WHERE document_id = ?)",
                (doc_id,),
            )
            self.conn.execute("DELETE FROM tables WHERE document_id = ?", (doc_id,))
            self.conn.execute(
                "UPDATE documents SET filename=?, page_count=?, processed_at=? WHERE id=?",
                (path.name, page_count, now, doc_id),
            )
        else:
            cur = self.conn.execute(
                "INSERT INTO documents(filename, filepath, page_count, processed_at) VALUES (?,?,?,?)",
                (path.name, str(path), page_count, now),
            )
            doc_id = int(cur.lastrowid)
        self.conn.commit()
        return doc_id

    def find_document_id(self, filepath: str | Path) -> int | None:
        path = str(Path(filepath).resolve())
        row = self.conn.execute(
            "SELECT id FROM documents WHERE filepath = ?", (path,)
        ).fetchone()
        if not row:
            # 兼容历史相对路径/不同盘符写法：按文件名回退
            name = Path(filepath).name
            row = self.conn.execute(
                "SELECT id FROM documents WHERE filename = ? ORDER BY id DESC LIMIT 1",
                (name,),
            ).fetchone()
        return int(row["id"]) if row else None

    def delete_document(self, filepath: str | Path) -> int:
        """删除指定 PDF 的全部表格数据，返回删除的表格数。"""
        doc_id = self.find_document_id(filepath)
        if doc_id is None:
            return 0
        table_ids = [
            int(r["id"])
            for r in self.conn.execute(
                "SELECT id FROM tables WHERE document_id = ?", (doc_id,)
            ).fetchall()
        ]
        deleted = len(table_ids)
        if table_ids:
            placeholders = ",".join("?" * len(table_ids))
            self.conn.execute(
                f"DELETE FROM cells WHERE table_id IN ({placeholders})",
                table_ids,
            )
            self.conn.execute(
                f"DELETE FROM tables_fts WHERE rowid IN ({placeholders})",
                table_ids,
            )
            self.conn.execute(
                "DELETE FROM tables WHERE document_id = ?", (doc_id,)
            )
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self.conn.commit()
        return deleted

    def document_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"])

    def save_table(
        self,
        document_id: int,
        page_number: int,
        table_index: int,
        table_name: str,
        matrix: list[list[str]],
        bbox: dict[str, Any] | None = None,
    ) -> int:
        row_count = len(matrix)
        col_count = max((len(r) for r in matrix), default=0)
        content_text = "\n".join("\t".join(cell or "" for cell in row) for row in matrix)
        cur = self.conn.execute(
            """
            INSERT INTO tables(
                document_id, page_number, table_index, table_name,
                row_count, col_count, bbox_json, content_json, content_text
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                document_id,
                page_number,
                table_index,
                table_name,
                row_count,
                col_count,
                json.dumps(bbox or {}, ensure_ascii=False),
                json.dumps(matrix, ensure_ascii=False),
                content_text,
            ),
        )
        table_id = int(cur.lastrowid)
        self.conn.execute(
            "INSERT INTO tables_fts(rowid, table_name, content_text) VALUES (?,?,?)",
            (table_id, table_name or "", content_text),
        )
        cell_rows = [
            (table_id, r_i, c_i, (cell or "").strip())
            for r_i, row in enumerate(matrix)
            for c_i, cell in enumerate(row)
            if (cell or "").strip()
        ]
        if cell_rows:
            self.conn.executemany(
                "INSERT INTO cells(table_id, row_idx, col_idx, cell_text) VALUES (?,?,?,?)",
                cell_rows,
            )
        self.conn.commit()
        return table_id

    def search(self, keyword: str, limit: int = 50) -> list[dict[str, Any]]:
        kw = keyword.strip()
        if not kw:
            return []
        like = f"%{kw}%"
        # 优先 LIKE，兼容中文与特殊符号；FTS 作为补充
        rows = self.conn.execute(
            """
            SELECT t.id, d.filename, t.page_number, t.table_name, t.row_count, t.col_count,
                   substr(t.content_text, 1, 160) AS snippet
            FROM tables t
            JOIN documents d ON d.id = t.document_id
            WHERE t.table_name LIKE ? OR t.content_text LIKE ?
            ORDER BY t.page_number, t.table_index
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]
        try:
            rows = self.conn.execute(
                """
                SELECT t.id, d.filename, t.page_number, t.table_name, t.row_count, t.col_count,
                       snippet(tables_fts, 1, '[', ']', '…', 24) AS snippet
                FROM tables_fts
                JOIN tables t ON t.id = tables_fts.rowid
                JOIN documents d ON d.id = t.document_id
                WHERE tables_fts MATCH ?
                ORDER BY t.page_number, t.table_index
                LIMIT ?
                """,
                (kw, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        return [dict(r) for r in rows]

    def list_tables(self, document_id: int | None = None) -> list[dict[str, Any]]:
        if document_id is None:
            rows = self.conn.execute(
                """
                SELECT t.id, d.filename, t.page_number, t.table_index, t.table_name,
                       t.row_count, t.col_count
                FROM tables t
                JOIN documents d ON d.id = t.document_id
                ORDER BY d.filename, t.page_number, t.table_index
                """
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT t.id, d.filename, t.page_number, t.table_index, t.table_name,
                       t.row_count, t.col_count
                FROM tables t
                JOIN documents d ON d.id = t.document_id
                WHERE t.document_id = ?
                ORDER BY t.page_number, t.table_index
                """,
                (document_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_table_matrix(self, table_id: int) -> tuple[str, list[list[str]]]:
        row = self.conn.execute(
            "SELECT table_name, content_json FROM tables WHERE id = ?", (table_id,)
        ).fetchone()
        if not row:
            return "", []
        return row["table_name"] or "", json.loads(row["content_json"])

    def count_summary(self) -> dict[str, int]:
        docs = self.conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
        tables = self.conn.execute("SELECT COUNT(*) AS c FROM tables").fetchone()["c"]
        cells = self.conn.execute("SELECT COUNT(*) AS c FROM cells").fetchone()["c"]
        return {"documents": docs, "tables": tables, "cells": cells}
