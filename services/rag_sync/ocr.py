# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Lazy, process-wide offline OCR for attachment page images."""

import threading
from pathlib import Path
from typing import Any

from common import utils

logger = utils.get_logger("rag_ocr")

# Multilingual PP-OCRv6 models (English, German and other Latin-script languages)
# shipped inside the rapidocr wheel. Explicit paths skip RapidOCR's model registry,
# so it never downloads a model at runtime.
_DETECTION_MODEL = "PP-OCRv6_det_small.onnx"
_CLASSIFICATION_MODEL = "ch_ppocr_mobile_v2.0_cls_mobile.onnx"
_RECOGNITION_MODEL = "PP-OCRv6_rec_small.onnx"

_engine: Any | None = None
_engine_initialization_attempted = False
_engine_lock = threading.Lock()


def get_engine() -> Any | None:
    """Returns the lazily initialized RapidOCR engine, or ``None`` if unavailable."""
    global _engine, _engine_initialization_attempted
    if _engine is not None or _engine_initialization_attempted:
        return _engine
    with _engine_lock:
        if _engine is not None or _engine_initialization_attempted:
            return _engine
        _engine_initialization_attempted = True
        try:
            import rapidocr

            models_dir = Path(rapidocr.__file__).parent / "models"
            _engine = rapidocr.RapidOCR(
                params={
                    "Global.log_level": "warning",
                    "Det.model_path": str(models_dir / _DETECTION_MODEL),
                    "Cls.model_path": str(models_dir / _CLASSIFICATION_MODEL),
                    "Rec.model_path": str(models_dir / _RECOGNITION_MODEL),
                }
            )
            logger.info("OCR engine initialized (RapidOCR PP-OCRv6, packaged offline models).")
        except Exception as error:
            logger.warning("OCR is unavailable; image-only pages get no OCR text: %s", error)
        return _engine


def extract_text(image_bytes: bytes) -> str:
    """Runs OCR and returns line-ordered text, degrading to an empty string on failure."""
    engine = get_engine()
    if engine is None:
        return ""
    try:
        lines = engine(image_bytes).txts
        return "\n".join(lines).strip() if lines else ""
    except Exception:
        logger.warning("OCR failed on one page image; the page stays image-only.", exc_info=True)
        return ""
