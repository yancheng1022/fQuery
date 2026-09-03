"""Tkinter 图形界面。"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .database import TableDatabase
from .extractor import PdfTableExtractor
from .history import history_label, load_history, remove_history, upsert_history


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
        self._history_items: list[dict] = []
        self._current_matrix: list[list[str]] = []
        self._current_headers: list[str] = []
        self._displayed_rows: list[list[str]] = []
        self._header_row_used = False

        self._build_ui()
        self._refresh_history(select_first=True)

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

        hist_fr = ttk.Frame(left)
        hist_fr.pack(fill=tk.X)
        ttk.Label(hist_fr, text="历史 PDF").pack(side=tk.LEFT)
        self.history_var = tk.StringVar()
        self.history_combo = ttk.Combobox(
            hist_fr,
            textvariable=self.history_var,
            state="readonly",
            width=36,
        )
        self.history_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.history_combo.bind("<<ComboboxSelected>>", self._on_select_history)
        ttk.Button(hist_fr, text="刷新", width=4, command=lambda: self._refresh_history(select_current=True)).pack(
            side=tk.LEFT
        )
        ttk.Button(hist_fr, text="删除", width=4, command=self._delete_history).pack(side=tk.LEFT, padx=(4, 0))

        search_fr = ttk.Frame(left)
        search_fr.pack(fill=tk.X, pady=(6, 0))
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
        content_entry.bind("<Return>", lambda _e: self._highlight_preview())
        ttk.Button(content_search_fr, text="高亮", command=self._highlight_preview).pack(side=tk.LEFT)
        ttk.Button(content_search_fr, text="清除", command=self._clear_content_search).pack(side=tk.LEFT, padx=(4, 0))

        preview_wrap = ttk.Frame(right)
        preview_wrap.pack(fill=tk.BOTH, expand=True)
        self.preview = ttk.Treeview(preview_wrap, show="headings", selectmode="browse")
        self.preview.tag_configure("hit", background="#FFE08A")
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

    def _refresh_history(self, select_first: bool = False, select_current: bool = False, select_pdf: str | None = None) -> None:
        self._history_items = load_history()
        labels = [history_label(item) for item in self._history_items]
        self.history_combo["values"] = labels

        if not self._history_items:
            self.history_var.set("")
            self.status_var.set("暂无历史记录，请先提取 PDF")
            return

        target_idx = None
        if select_pdf:
            want = str(Path(select_pdf).resolve())
            for i, item in enumerate(self._history_items):
                if str(Path(item["pdf_path"]).resolve()) == want:
                    target_idx = i
                    break
        elif select_current and self.pdf_var.get().strip():
            want = str(Path(self.pdf_var.get().strip()).resolve())
            for i, item in enumerate(self._history_items):
                if str(Path(item["pdf_path"]).resolve()) == want:
                    target_idx = i
                    break
        elif select_first:
            target_idx = 0

        if target_idx is None:
            # 保持当前下拉文本；若无效则选第一条
            if self.history_var.get() not in labels:
                target_idx = 0
            else:
                return

        self.history_combo.current(target_idx)
        self._on_select_history()

    def _delete_history(self) -> None:
        idx = self.history_combo.current()
        if idx < 0 or idx >= len(self._history_items):
            messagebox.showinfo("提示", "请先选择要删除的历史 PDF")
            return
        item = self._history_items[idx]
        name = item.get("filename") or item.get("pdf_path")
        pdf = item["pdf_path"]
        db_path = item["db_path"]
        if not messagebox.askyesno(
            "确认删除",
            f"删除该 PDF 的历史记录，并清除其已提取的全部表格？\n\n{name}\n\n此操作不可恢复。",
        ):
            return

        deleted_tables = 0
        # 关闭当前库连接，避免 Windows 下文件占用
        if self._last_db and self._db_path and Path(self._db_path).resolve() == Path(db_path).resolve():
            try:
                self._last_db.close()
            except Exception:
                pass
            self._last_db = None

        if Path(db_path).exists():
            try:
                db_obj = TableDatabase(db_path)
                deleted_tables = db_obj.delete_document(pdf)
                empty = db_obj.document_count() == 0
                db_obj.close()
                if empty:
                    try:
                        Path(db_path).unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception as exc:
                messagebox.showerror("删除失败", f"清除表格数据时出错：\n{exc}")
                return

        remove_history(pdf)

        for child in self.tree.get_children():
            self.tree.delete(child)
        children = self.preview.get_children()
        if children:
            self.preview.delete(*children)
        self.preview_title_var.set("表格内容预览")
        self.cell_detail_var.set("")
        self._current_matrix = []
        self._current_headers = []
        self._displayed_rows = []
        if self.pdf_var.get().strip() and Path(self.pdf_var.get().strip()).resolve() == Path(pdf).resolve():
            self.pdf_var.set("")
            self._db_path = None
        self._refresh_history(select_first=True)
        self.status_var.set(f"已删除：{name}（清除 {deleted_tables} 张表）")

    def _on_select_history(self, _event=None) -> None:
        idx = self.history_combo.current()
        if idx < 0 or idx >= len(self._history_items):
            return
        item = self._history_items[idx]
        pdf = item["pdf_path"]
        db = item["db_path"]
        if not Path(db).exists():
            messagebox.showwarning("提示", f"数据库不存在，已从历史中跳过：\n{db}")
            self._refresh_history(select_first=True)
            return
        self.pdf_var.set(pdf)
        self._db_path = db
        self._load_db_preview(db, document_pdf=pdf)
        self.status_var.set(f"已加载历史：{item.get('filename')}（{item.get('table_count', 0)} 张表）")

    def _pick_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 PDF",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.pdf_var.set(path)
        db = self._default_db_path(path)
        self._db_path = db
        if Path(db).exists():
            try:
                tmp = TableDatabase(db)
                table_count = tmp.count_summary().get("tables", 0)
                tmp.close()
            except Exception:
                table_count = 0
            upsert_history(path, db, table_count=table_count)
            self._refresh_history(select_pdf=path)
        else:
            self.status_var.set("已选择 PDF，点击「开始提取」")

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
                table_count = len(tables)
                self.after(
                    0,
                    lambda: self._on_done(
                        True,
                        f"完成：提取 {table_count} 张表，库内共 {summary['tables']} 张",
                        db,
                        pdf,
                        table_count,
                    ),
                )
            except Exception as exc:
                self.after(0, lambda: self._on_done(False, str(exc), db, pdf, 0))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _request_cancel(self) -> None:
        self._cancel = True
        self.status_var.set("正在取消…")

    def _on_done(self, ok: bool, msg: str, db_path: str, pdf_path: str = "", table_count: int = 0) -> None:
        self.run_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)
        self.status_var.set(msg)
        if ok:
            if pdf_path:
                upsert_history(pdf_path, db_path, table_count=table_count)
                self._refresh_history(select_pdf=pdf_path)
            else:
                self._load_db_preview(db_path)
            messagebox.showinfo("完成", msg)
        else:
            messagebox.showerror("失败", msg)

    def _load_db_preview(self, db_path: str, document_pdf: str | None = None) -> None:
        if self._last_db:
            try:
                self._last_db.close()
            except Exception:
                pass
        self._last_db = TableDatabase(db_path)
        self._db_path = db_path
        for item in self.tree.get_children():
            self.tree.delete(item)

        document_id = None
        if document_pdf:
            document_id = self._last_db.find_document_id(document_pdf)

        for row in self._last_db.list_tables(document_id=document_id):
            self.tree.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                values=(row["id"], row["page_number"], row["table_name"], f"{row['row_count']}x{row['col_count']}"),
            )
        summary = self._last_db.count_summary()
        shown = len(self.tree.get_children())
        self.status_var.set(f"当前 PDF 表格 {shown} 张（库内共 {summary['tables']} 张）")

        # 清空右侧预览
        self.preview_title_var.set("表格内容预览")
        self.content_search_var.set("")
        self.cell_detail_var.set("")
        self._current_matrix = []
        self._current_headers = []
        self._displayed_rows = []
        children = self.preview.get_children()
        if children:
            self.preview.delete(*children)

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
        # 始终保留原始行，详情栏/悬停用未加标记的文本
        self._displayed_rows = rows

        kw = highlight.strip()
        kw_lower = kw.lower()

        for i, header in enumerate(headers):
            samples = [header] + [r[i] for r in rows if i < len(r)]
            max_w = max((_display_width(s) for s in samples), default=4)
            # 高亮标记可能略增宽度
            px = max(56, min(168, max_w * 7 + (28 if kw else 16)))
            short_header = header.replace("\n", " ")
            if _display_width(short_header) > 16:
                short_header = short_header[:10] + "…"
            self.preview.heading(col_ids[i], text=short_header)
            self.preview.column(col_ids[i], width=px, minwidth=48, stretch=True, anchor=tk.W)

        hit_cells = 0
        hit_rows = 0
        for r_i, row in enumerate(rows):
            values = []
            row_hit = False
            for i in range(len(headers)):
                text = row[i] if i < len(row) else ""
                display = text
                if kw_lower and kw_lower in text.lower():
                    row_hit = True
                    hit_cells += 1
                    display = self._mark_highlight(text, kw)
                if _display_width(display) > 28:
                    cut = display
                    while _display_width(cut) > 26 and len(cut) > 1:
                        cut = cut[:-1]
                    display = cut + "…"
                values.append(display)
            tags = []
            if row_hit:
                tags.append("hit")
                hit_rows += 1
            elif r_i % 2:
                tags.append("odd")
            self.preview.insert("", tk.END, iid=str(r_i), values=values, tags=tuple(tags))

        if kw:
            self.status_var.set(f"已高亮 {hit_cells} 处（{hit_rows} 行），关键字：{kw}")
            self.cell_detail_var.set(f"高亮关键字「{kw}」：{hit_cells} 处 / 共 {len(rows)} 行")
        elif rows:
            self.status_var.set(f"当前表 {len(rows)} 行 × {len(headers)} 列")

    @staticmethod
    def _mark_highlight(text: str, keyword: str) -> str:
        """在匹配处加可见标记（Treeview 无法给单格上色）。"""
        if not text or not keyword:
            return text
        lower = text.lower()
        key = keyword.lower()
        parts: list[str] = []
        start = 0
        while True:
            idx = lower.find(key, start)
            if idx < 0:
                parts.append(text[start:])
                break
            parts.append(text[start:idx])
            parts.append("【")
            parts.append(text[idx : idx + len(keyword)])
            parts.append("】")
            start = idx + len(keyword)
        return "".join(parts)

    def _row_from_preview_iid(self, row_id: str) -> list[str] | None:
        try:
            idx = int(row_id)
        except ValueError:
            return None
        if 0 <= idx < len(self._displayed_rows):
            return self._displayed_rows[idx]
        return None

    def _highlight_preview(self) -> None:
        if not self._current_matrix and not self._current_headers:
            return
        kw = self.content_search_var.get().strip()
        self._render_preview(self._current_matrix, highlight=kw)
        if not kw:
            self.cell_detail_var.set("")

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
                self._load_db_preview(self._db_path, document_pdf=self.pdf_var.get().strip() or None)
            else:
                messagebox.showwarning("提示", "请先提取或选择历史 PDF")
                return
        kw = self.search_var.get().strip()
        for item in self.tree.get_children():
            self.tree.delete(item)

        document_id = None
        pdf = self.pdf_var.get().strip()
        if pdf:
            document_id = self._last_db.find_document_id(pdf)

        if kw:
            rows = self._last_db.search(kw)
            if document_id is not None:
                rows = [r for r in rows if self._table_belongs_to_doc(r["id"], document_id)]
        else:
            rows = self._last_db.list_tables(document_id=document_id)

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

    def _table_belongs_to_doc(self, table_id: int, document_id: int) -> bool:
        if not self._last_db:
            return True
        row = self._last_db.conn.execute(
            "SELECT document_id FROM tables WHERE id = ?", (table_id,)
        ).fetchone()
        return bool(row) and int(row["document_id"]) == document_id


def run_app() -> None:
    app = App()
    app.mainloop()
