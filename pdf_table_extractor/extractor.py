"""从扫描件 PDF 中提取表格（RapidOCR + ONNXRuntime）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import pymupdf

from .ocr_patch import apply_img2table_patch
from .paths import rapidocr_params

ProgressCallback = Callable[[str, float], None]


@dataclass
class ExtractedTable:
    page_number: int
    table_index: int
    table_name: str
    matrix: list[list[str]]
    bbox: dict[str, int] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.matrix)

    @property
    def col_count(self) -> int:
        return max((len(r) for r in self.matrix), default=0)


class PdfTableExtractor:
    def __init__(
        self,
        dpi: int = 150,
        min_rows: int = 4,
        min_cols: int = 4,
        max_page_area_ratio: float = 0.72,
    ):
        self.dpi = dpi
        self.min_rows = min_rows
        self.min_cols = min_cols
        self.max_page_area_ratio = max_page_area_ratio
        self._ocr = None
        self._title_ocr = None
        apply_img2table_patch()

    def _ensure_ocr(self):
        if self._ocr is not None:
            return self._ocr
        from img2table.ocr import RapidOCR as Img2TableRapid

        self._ocr = Img2TableRapid(params=rapidocr_params())
        return self._ocr

    def _ensure_title_ocr(self):
        if self._title_ocr is not None:
            return self._title_ocr
        from rapidocr import RapidOCR

        self._title_ocr = RapidOCR(params=rapidocr_params())
        return self._title_ocr

    def render_page(self, page: pymupdf.Page) -> np.ndarray:
        zoom = self.dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _to_png_bytes(bgr: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".png", bgr)
        if not ok:
            raise RuntimeError("无法编码页面图像")
        return buf.tobytes()

    def _structure_tables(self, bgr: np.ndarray):
        from img2table.document import Image as Img2TableImage

        doc = Img2TableImage(src=self._to_png_bytes(bgr))
        return doc.extract_tables(ocr=None, borderless_tables=False)

    def _is_data_table(self, table, page_h: int, page_w: int) -> bool:
        df = table.df
        if df is None:
            return False
        rows, cols = df.shape
        if rows < self.min_rows or cols < self.min_cols:
            return False
        bbox = table.bbox
        area = (bbox.x2 - bbox.x1) * (bbox.y2 - bbox.y1)
        if area / float(page_h * page_w) > self.max_page_area_ratio:
            return False
        if bbox.y1 > page_h * 0.82 and (bbox.y2 - bbox.y1) < page_h * 0.15:
            return False
        return True

    def _crop_with_title(self, bgr: np.ndarray, bbox, margin_top_ratio: float = 0.08) -> tuple[np.ndarray, int, int]:
        h, w = bgr.shape[:2]
        pad_x = max(8, int((bbox.x2 - bbox.x1) * 0.02))
        pad_top = max(40, int(h * margin_top_ratio))
        pad_bottom = 8
        x1 = max(0, int(bbox.x1) - pad_x)
        y1 = max(0, int(bbox.y1) - pad_top)
        x2 = min(w, int(bbox.x2) + pad_x)
        y2 = min(h, int(bbox.y2) + pad_bottom)
        return bgr[y1:y2, x1:x2].copy(), x1, y1

    def _df_to_matrix(self, df) -> list[list[str]]:
        matrix: list[list[str]] = []
        for _, row in df.iterrows():
            cells = []
            for val in row.tolist():
                if val is None:
                    text = ""
                else:
                    try:
                        if val != val:  # NaN
                            text = ""
                        else:
                            text = str(val).replace("\r", "").strip()
                    except Exception:
                        text = str(val).replace("\r", "").strip()
                    if text.lower() in {"nan", "none", "null"}:
                        text = ""
                    else:
                        text = re.sub(r"[ \t]+", " ", text)
                cells.append(text)
            matrix.append(cells)
        return self._dedupe_merged_noise(matrix)

    def _dedupe_merged_noise(self, matrix: list[list[str]]) -> list[list[str]]:
        cleaned = []
        for row in matrix:
            nonempty = [c for c in row if c]
            if len(nonempty) >= 3 and len(set(nonempty)) == 1:
                sample = nonempty[0]
                if "页" in sample or len(sample) < 4:
                    continue
            cleaned.append(row)
        return cleaned or matrix

    def _infer_table_name(self, matrix: list[list[str]], ocr_title_candidates: list[str]) -> str:
        for cand in ocr_title_candidates:
            if "表" in cand and len(cand) >= 4:
                return cand.strip()
        for row in matrix[:4]:
            joined = "".join(row)
            if "表" in joined:
                cells = sorted((c for c in row if c), key=len, reverse=True)
                if cells:
                    return cells[0].replace("\n", "")
        for row in matrix[:2]:
            cells = [c.replace("\n", "") for c in row if c]
            if cells:
                return cells[0][:80]
        return "未命名表格"

    def _title_candidates_above(self, bgr: np.ndarray, bbox) -> list[str]:
        h, w = bgr.shape[:2]
        y1 = max(0, int(bbox.y1) - max(60, int(h * 0.08)))
        y2 = max(y1 + 10, int(bbox.y1) + 5)
        x1 = max(0, int(bbox.x1) - 10)
        x2 = min(w, int(bbox.x2) + 10)
        band = bgr[y1:y2, x1:x2]
        if band.size == 0:
            return []
        try:
            engine = self._ensure_title_ocr()
            result = engine(band)
            texts = getattr(result, "txts", None) or ()
            return [t for t in texts if t and str(t).strip()]
        except Exception:
            return []

    def extract_page(self, bgr: np.ndarray, page_number: int) -> list[ExtractedTable]:
        from img2table.document import Image as Img2TableImage

        h, w = bgr.shape[:2]
        candidates = self._structure_tables(bgr)
        data_tables = [t for t in candidates if self._is_data_table(t, h, w)]
        if not data_tables:
            return []

        ocr = self._ensure_ocr()
        extracted: list[ExtractedTable] = []
        for idx, stub in enumerate(data_tables):
            crop, _ox, _oy = self._crop_with_title(bgr, stub.bbox)
            doc = Img2TableImage(src=self._to_png_bytes(crop))
            tables = doc.extract_tables(
                ocr=ocr,
                implicit_rows=True,
                borderless_tables=False,
                min_confidence=40,
            )
            page_h, page_w = crop.shape[:2]
            valid = [t for t in tables if self._is_data_table(t, page_h, page_w)]
            if not valid and tables:
                valid = [max(tables, key=lambda t: (t.df.shape[0] * t.df.shape[1]) if t.df is not None else 0)]
            if not valid:
                continue
            best = max(valid, key=lambda t: t.df.shape[0] * t.df.shape[1])
            matrix = self._df_to_matrix(best.df)
            titles = self._title_candidates_above(bgr, stub.bbox)
            name = self._infer_table_name(matrix, titles)
            bbox = {
                "x1": int(stub.bbox.x1),
                "y1": int(stub.bbox.y1),
                "x2": int(stub.bbox.x2),
                "y2": int(stub.bbox.y2),
            }
            extracted.append(
                ExtractedTable(
                    page_number=page_number,
                    table_index=idx,
                    table_name=name,
                    matrix=matrix,
                    bbox=bbox,
                )
            )
        return extracted

    def extract_pdf(
        self,
        pdf_path: str | Path,
        page_from: int | None = None,
        page_to: int | None = None,
        progress: ProgressCallback | None = None,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> tuple[int, list[ExtractedTable]]:
        path = Path(pdf_path)
        doc = pymupdf.open(str(path))
        total = doc.page_count
        start = max(1, page_from or 1)
        end = min(total, page_to or total)
        all_tables: list[ExtractedTable] = []

        try:
            for page_no in range(start, end + 1):
                if cancel_flag and cancel_flag():
                    break
                if progress:
                    progress(f"扫描第 {page_no}/{end} 页…", (page_no - start) / max(1, end - start + 1))
                page = doc[page_no - 1]
                bgr = self.render_page(page)
                h, w = bgr.shape[:2]
                stubs = [t for t in self._structure_tables(bgr) if self._is_data_table(t, h, w)]
                if not stubs:
                    continue
                if progress:
                    progress(f"OCR 识别第 {page_no} 页表格…", (page_no - start + 0.4) / max(1, end - start + 1))
                tables = self.extract_page(bgr, page_no)
                all_tables.extend(tables)
        finally:
            doc.close()

        if progress:
            progress(f"完成，共提取 {len(all_tables)} 张表", 1.0)
        return total, all_tables
