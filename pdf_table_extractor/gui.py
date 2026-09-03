"""Tkinter 图形界面。"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .database import TableDatabase
from .extractor import PdfTableExtractor


def _display_width(text: str) -> int:
    """估算显示宽度：中文等宽字符计 2。"""
    w = 0
    for ch in text:
        w += 2 if ord(ch) > 127 else 1
    return w


def _cell_text(value: str | None) -> str:
    return (value or "").replace("\r", "").replace("\n", " / ").strip()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("扫描件 PDF 表格提取工具")
        self.geometry("1100x720")
        self.minsize(900, 580)

        self.pdf_var = tk.StringVar()
        self.page_from_var = tk.StringVar(value="")
        self.page_to_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.content_search_var = tk.StringVar()
        self.preview_title_var = tk.StringVar(value="表格内容预览")
        self.cell_detail_var = tk.StringVar(value="")

        self._worker: threading.Thread | None = None
        self._cancel = False
        self._db_path: str | None = None
        self._last_db: TableDatabase | None = None
        self._current_matrix: list[list[str]] = []
        self._current_headers: list[str] = []
        self._displayed_rows: list[list[str]] = []
        self._header_row_used = False

        self._build_ui()

    @staticmethod
    def _default_db_path(pdf_path: str | Path) -> str:
        path = Path(pdf_path)
        return str(path.with_name(f"{path.stem}_tables.db"))

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        file_fr = ttk.LabelFrame(root, text="输入", padding=10)
        file_fr.pack(fill=tk.X, **pad)

        ttk.Label(file_fr, text="PDF 文件").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(file_fr, textvariable=self.pdf_var).grid(row=0, column=1, sticky=tk.EW, padx=6)
        ttk.Button(file_fr, text="浏览…", command=self._pick_pdf).grid(row=0, column=2)

        ttk.Label(file_fr, text="页码范围").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        range_fr = ttk.Frame(file_fr)
        range_fr.grid(row=1, column=1, sticky=tk.W, pady=(8, 0))
        ttk.Entry(range_fr, width=8, textvariable=self.page_from_var).pack(side=tk.LEFT)
        ttk.Label(range_fr, text=" — ").pack(side=tk.LEFT)
        ttk.Entry(range_fr, width=8, textvariable=self.page_to_var).pack(side=tk.LEFT)
        ttk.Label(range_fr, text="（留空=全部）").pack(side=tk.LEFT, padx=8)

        file_fr.columnconfigure(1, weight=1)

        btn_fr = ttk.Frame(root)
        btn_fr.pack(fill=tk.X, **pad)
        self.run_btn = ttk.Button(btn_fr, text="开始提取", command=self._start)
        self.run_btn.pack(side=tk.LEFT)
        self.cancel_btn = ttk.Button(btn_fr, text="取消", command=self._request_cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=8)

        prog_fr = ttk.Frame(root)
        prog_fr.pack(fill=tk.X, **pad)
        ttk.Progressbar(prog_fr, variable=self.progress_var, maximum=1.0).pack(fill=tk.X)
        ttk.Label(prog_fr, textvariable=self.status_var).pack(anchor=tk.W, pady=(4, 0))

        mid = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        mid.pack(fill=tk.BOTH, expand=True, **pad)

        left = ttk.Frame(mid)
        right = ttk.Frame(mid)
        mid.add(left, weight=1)
        mid.add(right, weight=3)

        search_fr = ttk.Frame(left)
        search_fr.pack(fill=tk.X)
        self.search_var = tk.StringVar()
        ttk.Entry(search_fr, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(search_fr, text="搜索", command=self._search).pack(side=tk.LEFT, padx=4)

        cols = ("id", "page", "name", "shape")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=18)
        self.tree.heading("id", text="ID")
        self.tree.heading("page", text="页")
        self.tree.heading("name", text="表名")
        self.tree.heading("shape", text="行列")
        self.tree.column("id", width=50, anchor=tk.CENTER)
        self.tree.column("page", width=40, anchor=tk.CENTER)
        self.tree.column("name", width=220)
        self.tree.column("shape", width=70, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.tree.bind("<<TreeviewSelect>>", self._on_select_table)

        ttk.Label(right, textvariable=self.preview_title_var).pack(anchor=tk.W)

        content_search_fr = ttk.Frame(right)
        content_search_fr.pack(fill=tk.X, pady=(4, 4))
        ttk.Label(content_search_fr, text="表内搜索").pack(side=tk.LEFT)
        content_entry = ttk.Entry(content_search_fr, textvariable=self.content_search_var)
        content_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        content_entry.bind("<Return>", lambda _e: self._filter_preview())
        ttk.Button(content_search_fr, text="筛选", command=self._filter_preview).pack(side=tk.LEFT)
        ttk.Button(content_search_fr, text="清除", command=self._clear_content_search).pack(side=tk.LEFT, padx=(4, 0))

        preview_wrap = ttk.Frame(right)
        preview_wrap.pack(fill=tk.BOTH, expand=True)
        self.preview = ttk.Treeview(preview_wrap, show="headings", selectmode="browse")
        self.preview.tag_configure("match", background="#FFF3BF")
        self.preview.tag_configure("odd", background="#FAFAFA")
        ysb = ttk.Scrollbar(preview_wrap, orient=tk.VERTICAL, command=self.preview.yview)
        xsb = ttk.Scrollbar(preview_wrap, orient=tk.HORIZONTAL, command=self.preview.xview)
        self.preview.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.preview.grid(row=0, column=0, sticky=tk.NSEW)
        ysb.grid(row=0, column=1, sticky=tk.NS)
        xsb.grid(row=1, column=0, sticky=tk.EW)
        preview_wrap.rowconfigure(0, weight=1)
        preview_wrap.columnconfigure(0, weight=1)
        self.preview.bind("<<TreeviewSelect>>", self._on_select_preview_row)
        self.preview.bind("<Motion>", self._on_preview_motion)

        ttk.Label(right, textvariable=self.cell_detail_var, wraplength=700, foreground="#333").pack(
            anchor=tk.W, fill=tk.X, pady=(6, 0)
        )

    def _pick_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 PDF",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if path:
            self.pdf_var.set(path)
            self._db_path = self._default_db_path(path)

    def _parse_pages(self) -> tuple[int | None, int | None]:
        pf = self.page_from_var.get().strip()
        pt = self.page_to_var.get().strip()
        page_from = int(pf) if pf else None
        page_to = int(pt) if pt else None
        return page_from, page_to

    def _start(self) -> None:
        pdf = self.pdf_var.get().strip()
        if not pdf or not Path(pdf).exists():
            messagebox.showerror("错误", "请选择有效的 PDF 文件")
            return
        try:
            page_from, page_to = self._parse_pages()
        except ValueError:
            messagebox.showerror("错误", "页码必须是整数")
            return

        db = self._db_path or self._default_db_path(pdf)
        self._db_path = db

        self._cancel = False
        self.run_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.progress_var.set(0)
        self.status_var.set("初始化 OCR 模型…")

        def worker():
            try:
                extractor = PdfTableExtractor()
                db_obj = TableDatabase(db)

                def progress(msg: str, ratio: float):
                    self.after(0, lambda: (self.status_var.set(msg), self.progress_var.set(ratio)))

                page_count, tables = extractor.extract_pdf(
                    pdf,
                    page_from=page_from,
                    page_to=page_to,
                    progress=progress,
                    cancel_flag=lambda: self._cancel,
                )
                doc_id = db_obj.upsert_document(pdf, page_count)
                for t in tables:
                    db_obj.save_table(
                        document_id=doc_id,
                        page_number=t.page_number,
                        table_index=t.table_index,
                        table_name=t.table_name,
                        matrix=t.matrix,
                        bbox=t.bbox,
                    )
                summary = db_obj.count_summary()
                db_obj.close()
                self.after(
                    0,
                    lambda: self._on_done(
                        True,
                        f"完成：提取 {len(tables)} 张表，库内共 {summary['tables']} 张",
                        db,
                    ),
                )
            except Exception as exc:
                self.after(0, lambda: self._on_done(False, str(exc), db))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _request_cancel(self) -> None:
        self._cancel = True
        self.status_var.set("正在取消…")

    def _on_done(self, ok: bool, msg: str, db_path: str) -> None:
        self.run_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)
        self.status_var.set(msg)
        if ok:
            messagebox.showinfo("完成", msg)
            self._load_db_preview(db_path)
        else:
            messagebox.showerror("失败", msg)

    def _load_db_preview(self, db_path: str) -> None:
        if self._last_db:
            try:
                self._last_db.close()
            except Exception:
                pass
        self._last_db = TableDatabase(db_path)
        self._db_path = db_path
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self._last_db.list_tables():
            self.tree.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                values=(row["id"], row["page_number"], row["table_name"], f"{row['row_count']}x{row['col_count']}"),
            )
        self.status_var.set(f"已加载 {self._last_db.count_summary()}")

    def _on_select_table(self, _event=None) -> None:
        if not self._last_db:
            return
        sel = self.tree.selection()
        if not sel:
            return
        table_id = int(sel[0])
        name, matrix = self._last_db.get_table_matrix(table_id)
        self.preview_title_var.set(f"表格内容预览 — {name}" if name else "表格内容预览")
        self.content_search_var.set("")
        self.cell_detail_var.set("")
        self._set_preview_matrix(matrix)

    def _looks_like_header(self, row: list[str]) -> bool:
        nonempty = [c for c in row if c]
        if len(nonempty) < max(2, len(row) // 3):
            return False
        digitish = sum(1 for c in nonempty if any(ch.isdigit() for ch in c) and len(c) <= 6)
        return digitish < len(nonempty) * 0.6

    def _set_preview_matrix(self, matrix: list[list[str]]) -> None:
        cleaned = [[_cell_text(c) for c in row] for row in matrix]
        col_count = max((len(r) for r in cleaned), default=0)
        cleaned = [r + [""] * (col_count - len(r)) for r in cleaned]

        self._header_row_used = False
        if cleaned and self._looks_like_header(cleaned[0]):
            headers = [h if h else f"列{i + 1}" for i, h in enumerate(cleaned[0])]
            body = cleaned[1:]
            self._header_row_used = True
        else:
            headers = [f"列{i + 1}" for i in range(col_count)]
            body = cleaned

        self._current_headers = headers
        self._current_matrix = body
        self._render_preview(body, highlight="")

    def _render_preview(self, rows: list[list[str]], highlight: str = "") -> None:
        children = self.preview.get_children()
        if children:
            self.preview.delete(*children)
        old_cols = self.preview["columns"]
        if old_cols:
            for col in old_cols:
                self.preview.heading(col, text="")
                self.preview.column(col, width=0)

        headers = self._current_headers
        col_ids = [f"c{i}" for i in range(len(headers))]
        self.preview["columns"] = col_ids
        self._displayed_rows = rows

        # 按内容估算列宽，限制在合理范围，尽量一屏看完
        for i, header in enumerate(headers):
            samples = [header] + [r[i] for r in rows if i < len(r)]
            max_w = max((_display_width(s) for s in samples), default=4)
            px = max(56, min(160, max_w * 7 + 16))
            short_header = header.replace("\n", " ")
            if _display_width(short_header) > 16:
                short_header = short_header[:10] + "…"
            self.preview.heading(col_ids[i], text=short_header)
            self.preview.column(col_ids[i], width=px, minwidth=48, stretch=True, anchor=tk.W)

        kw = highlight.strip().lower()
        for r_i, row in enumerate(rows):
            values = []
            matched = False
            for i in range(len(headers)):
                text = row[i] if i < len(row) else ""
                if kw and kw in text.lower():
                    matched = True
                if _display_width(text) > 24:
                    cut = text
                    while _display_width(cut) > 22 and len(cut) > 1:
                        cut = cut[:-1]
                    text = cut + "…"
                values.append(text)
            tags = []
            if matched:
                tags.append("match")
            elif r_i % 2:
                tags.append("odd")
            self.preview.insert("", tk.END, iid=str(r_i), values=values, tags=tuple(tags))

        if kw:
            self.status_var.set(f"表内匹配 {len(rows)} 行（关键字：{highlight.strip()}）")
        elif rows:
            self.status_var.set(f"当前表 {len(rows)} 行 × {len(headers)} 列")

    def _row_from_preview_iid(self, row_id: str) -> list[str] | None:
        try:
            idx = int(row_id)
        except ValueError:
            return None
        if 0 <= idx < len(self._displayed_rows):
            return self._displayed_rows[idx]
        return None

    def _filter_preview(self) -> None:
        if not self._current_matrix and not self._current_headers:
            return
        kw = self.content_search_var.get().strip().lower()
        if not kw:
            self._render_preview(self._current_matrix, highlight="")
            self.cell_detail_var.set("")
            return
        filtered = [row for row in self._current_matrix if any(kw in (c or "").lower() for c in row)]
        self._render_preview(filtered, highlight=kw)
        self.cell_detail_var.set(f"筛选结果：{len(filtered)} / {len(self._current_matrix)} 行")

    def _clear_content_search(self) -> None:
        self.content_search_var.set("")
        if self._current_matrix or self._current_headers:
            self._render_preview(self._current_matrix, highlight="")
            self.cell_detail_var.set("")

    def _on_select_preview_row(self, _event=None) -> None:
        sel = self.preview.selection()
        if not sel:
            return
        full = self._row_from_preview_iid(sel[0])
        if not full:
            return
        parts = [
            f"{h}: {full[i]}"
            for i, h in enumerate(self._current_headers)
            if i < len(full) and full[i]
        ]
        self.cell_detail_var.set("  |  ".join(parts) if parts else "")

    def _on_preview_motion(self, event) -> None:
        region = self.preview.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.preview.identify_row(event.y)
        col_id = self.preview.identify_column(event.x)
        if not row_id or not col_id:
            return
        try:
            col_index = int(col_id.replace("#", "")) - 1
        except ValueError:
            return
        full = self._row_from_preview_iid(row_id)
        if not full or not (0 <= col_index < len(self._current_headers)):
            return
        header = self._current_headers[col_index]
        value = full[col_index] if col_index < len(full) else ""
        if value:
            self.cell_detail_var.set(f"{header}: {value}")
    def _search(self) -> None:
        if not self._last_db:
            if self._db_path and Path(self._db_path).exists():
                self._load_db_preview(self._db_path)
            else:
                messagebox.showwarning("提示", "请先提取表格")
                return
        kw = self.search_var.get().strip()
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = self._last_db.search(kw) if kw else self._last_db.list_tables()
        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                values=(
                    row["id"],
                    row.get("page_number"),
                    row.get("table_name"),
                    f"{row.get('row_count')}x{row.get('col_count')}" if "row_count" in row else "",
                ),
            )
        self.status_var.set(f"搜索到 {len(rows)} 条" if kw else f"共 {len(rows)} 张表")


def run_app() -> None:
    app = App()
    app.mainloop()
