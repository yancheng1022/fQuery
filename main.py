#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扫描件 PDF 表格提取工具入口。"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")

from pdf_table_extractor.database import TableDatabase
from pdf_table_extractor.extractor import PdfTableExtractor


def run_cli(args: argparse.Namespace) -> int:
    extractor = PdfTableExtractor(dpi=args.dpi, use_mobile_ocr=not args.server_ocr)

    def progress(msg: str, ratio: float) -> None:
        pct = int(ratio * 100)
        print(f"[{pct:3d}%] {msg}", flush=True)

    page_count, tables = extractor.extract_pdf(
        args.pdf,
        page_from=args.page_from,
        page_to=args.page_to,
        progress=progress,
    )
    db = TableDatabase(args.db)
    doc_id = db.upsert_document(args.pdf, page_count)
    for t in tables:
        db.save_table(
            document_id=doc_id,
            page_number=t.page_number,
            table_index=t.table_index,
            table_name=t.table_name,
            matrix=t.matrix,
            bbox=t.bbox,
        )
    summary = db.count_summary()
    db.close()
    print(f"完成：提取 {len(tables)} 张表 -> {args.db}")
    print(f"库统计：文档 {summary['documents']}，表格 {summary['tables']}，单元格 {summary['cells']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描件 PDF 表格提取并写入 SQLite")
    parser.add_argument("--gui", action="store_true", help="启动图形界面（默认）")
    parser.add_argument("--cli", action="store_true", help="命令行模式")
    parser.add_argument("--pdf", help="PDF 路径")
    parser.add_argument("--db", default="tables.db", help="SQLite 输出路径")
    parser.add_argument("--page-from", type=int, default=None)
    parser.add_argument("--page-to", type=int, default=None)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--server-ocr", action="store_true", help="使用更准但更慢的 server OCR 模型")
    args = parser.parse_args()

    if args.cli:
        if not args.pdf:
            parser.error("命令行模式需要 --pdf")
        return run_cli(args)

    from pdf_table_extractor.gui import run_app

    run_app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
