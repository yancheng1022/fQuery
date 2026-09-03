"""修补 img2table：OpenCV 5 缺少 niBlackThreshold 时改用自适应阈值。"""

from __future__ import annotations

import cv2
import numpy as np


def threshold_dark_areas(img: np.ndarray, char_length: float) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    if float(np.mean(gray)) <= 127:
        gray = 255 - gray
    k = max(int(char_length) // 2 * 2 + 1, 15)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, k, 10
    )


def apply_img2table_patch() -> None:
    import img2table.tables.common as common
    import img2table.tables.common.threshold as thmod
    import img2table.tables.extractor as extractor

    thmod.threshold_dark_areas = threshold_dark_areas
    common.threshold_dark_areas = threshold_dark_areas
    extractor.threshold_dark_areas = threshold_dark_areas
