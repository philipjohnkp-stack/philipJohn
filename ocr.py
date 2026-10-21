from __future__ import annotations

from threading import Lock

from flask import abort

_engine = None
_lock = Lock()


def extract_text(data: bytes) -> str:
    global _engine
    try:
        import numpy as np
        from PIL import Image
        from io import BytesIO
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        abort(503, description="Snip reading is not available on this server.")
    try:
        image = Image.open(BytesIO(data))
        if image.width * image.height > 25_000_000:
            abort(400, description="The snip is too large.")
        array = np.array(image.convert("RGB"))
    except (OSError, ValueError):
        abort(400, description="The snip could not be read.")
    with _lock:
        _engine = _engine or RapidOCR()
        result, _ = _engine(array)
    return "\n".join(line[1] for line in result or [])
