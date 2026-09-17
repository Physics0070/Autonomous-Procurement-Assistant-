"""OCR engine abstraction.

Tesseract is the primary engine as specified. Because Tesseract needs a system
binary that is not always present, a pip-only ONNX engine (RapidOCR) is used as
an automatic fallback so the OCR path stays exercisable on a clean machine.

If no engine is available, OCR fails *gracefully*: the caller gets an explicit
"no engine" result rather than silent empty text pretending to be a success.
"""
from __future__ import annotations

import abc
import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    text: str = ""
    confidence: Optional[float] = None
    engine: str = "none"
    available: bool = False
    error: Optional[str] = None
    word_count: int = 0
    meta: dict = field(default_factory=dict)


class OCREngine(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def is_available(self) -> bool:
        ...

    @abc.abstractmethod
    def run(self, image_bytes: bytes, lang: Optional[str] = None) -> OCRResult:
        ...


class TesseractEngine(OCREngine):
    name = "tesseract"

    def __init__(self) -> None:
        self._checked = False
        self._ok = False

    def _binary_path(self) -> Optional[str]:
        if settings.TESSERACT_CMD and os.path.exists(settings.TESSERACT_CMD):
            return settings.TESSERACT_CMD
        found = shutil.which("tesseract")
        if found:
            return found
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
        ):
            if os.path.exists(candidate):
                return candidate
        return None

    def is_available(self) -> bool:
        if self._checked:
            return self._ok
        self._checked = True
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            self._ok = False
            return False
        path = self._binary_path()
        if not path:
            self._ok = False
            return False
        try:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = path
            pytesseract.get_tesseract_version()
            self._ok = True
        except Exception as exc:  # binary present but unusable
            logger.warning("Tesseract found at %s but not usable: %s", path, exc)
            self._ok = False
        return self._ok

    def run(self, image_bytes: bytes, lang: Optional[str] = None) -> OCRResult:
        if not self.is_available():
            return OCRResult(engine=self.name, available=False, error="tesseract binary not found")
        import io

        import pytesseract
        from PIL import Image

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            tess_lang = _tesseract_lang(lang)
            data = pytesseract.image_to_data(
                img, lang=tess_lang, output_type=pytesseract.Output.DICT
            )
            words, confs = [], []
            for text, conf in zip(data.get("text", []), data.get("conf", [])):
                if text and text.strip():
                    words.append(text)
                    try:
                        c = float(conf)
                        if c >= 0:
                            confs.append(c / 100.0)
                    except (TypeError, ValueError):
                        pass
            text_out = pytesseract.image_to_string(img, lang=tess_lang)
            return OCRResult(
                text=text_out.strip(),
                confidence=(sum(confs) / len(confs)) if confs else None,
                engine=self.name,
                available=True,
                word_count=len(words),
                meta={"lang": tess_lang},
            )
        except Exception as exc:
            return OCRResult(engine=self.name, available=True, error=str(exc))


def _tesseract_lang(lang: Optional[str]) -> str:
    if not lang or lang in ("unknown", "en"):
        return "eng"
    mapping = {"hi": "hin", "gu": "guj", "ta": "tam", "te": "tel", "bn": "ben"}
    parts = [mapping.get(p, "eng") for p in lang.split("+")]
    seen, out = set(), []
    for p in parts + ["eng"]:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return "+".join(out)


class RapidOCREngine(OCREngine):
    """Pip-installable ONNX OCR. No system binary required."""

    name = "rapidocr"
    _engine = None

    def __init__(self) -> None:
        self._checked = False
        self._ok = False

    def is_available(self) -> bool:
        if self._checked:
            return self._ok
        self._checked = True
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: F401

            self._ok = True
        except Exception as exc:
            logger.info("RapidOCR unavailable: %s", exc)
            self._ok = False
        return self._ok

    def _get_engine(self):
        if RapidOCREngine._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            RapidOCREngine._engine = RapidOCR()
        return RapidOCREngine._engine

    def run(self, image_bytes: bytes, lang: Optional[str] = None) -> OCRResult:
        if not self.is_available():
            return OCRResult(engine=self.name, available=False, error="rapidocr not installed")
        import io

        import numpy as np
        from PIL import Image

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            arr = np.array(img)
            engine = self._get_engine()
            result, _elapsed = engine(arr)
            if not result:
                return OCRResult(text="", confidence=None, engine=self.name, available=True, word_count=0)
            detections, confs = [], []
            for entry in result:
                # entry: [box, text, confidence]
                if len(entry) < 3:
                    continue
                box = entry[0]
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                detections.append(
                    {
                        "text": str(entry[1]),
                        "x": min(xs),
                        "y": (min(ys) + max(ys)) / 2.0,
                        "height": max(ys) - min(ys),
                    }
                )
                try:
                    confs.append(float(entry[2]))
                except (TypeError, ValueError):
                    pass
            text = _group_detections_into_lines(detections)
            return OCRResult(
                text=text,
                confidence=(sum(confs) / len(confs)) if confs else None,
                engine=self.name,
                available=True,
                word_count=len(detections),
            )
        except Exception as exc:
            return OCRResult(engine=self.name, available=True, error=str(exc))


def _group_detections_into_lines(detections: list[dict]) -> str:
    """Rebuild visual rows from OCR boxes.

    Detectors emit one box per text run, so a table row arrives as several
    detections. Grouping by vertical centre and ordering by x preserves the
    column layout, which is what makes the downstream extraction usable.
    """
    if not detections:
        return ""
    heights = [d["height"] for d in detections if d["height"] > 0]
    tolerance = (sum(heights) / len(heights) * 0.6) if heights else 10.0

    rows: list[list[dict]] = []
    for det in sorted(detections, key=lambda d: d["y"]):
        placed = False
        for row in rows:
            if abs(row[0]["y"] - det["y"]) <= tolerance:
                row.append(det)
                placed = True
                break
        if not placed:
            rows.append([det])

    lines = []
    for row in rows:
        row.sort(key=lambda d: d["x"])
        lines.append("  ".join(d["text"] for d in row).strip())
    return "\n".join(line for line in lines if line)


class OCRService:
    """Picks an engine according to OCR_ENGINE, honouring availability."""

    def __init__(self) -> None:
        self.tesseract = TesseractEngine()
        self.rapidocr = RapidOCREngine()

    def available_engines(self) -> list[str]:
        out = []
        if self.tesseract.is_available():
            out.append(self.tesseract.name)
        if self.rapidocr.is_available():
            out.append(self.rapidocr.name)
        return out

    def select(self) -> Optional[OCREngine]:
        pref = (settings.OCR_ENGINE or "auto").lower()
        if pref == "none":
            return None
        if pref == "tesseract":
            return self.tesseract if self.tesseract.is_available() else None
        if pref == "rapidocr":
            return self.rapidocr if self.rapidocr.is_available() else None
        # auto: Tesseract first (as specified), RapidOCR as the fallback.
        if self.tesseract.is_available():
            return self.tesseract
        if self.rapidocr.is_available():
            return self.rapidocr
        return None

    def run(self, image_bytes: bytes, lang: Optional[str] = None) -> OCRResult:
        engine = self.select()
        if engine is None:
            return OCRResult(
                engine="none",
                available=False,
                error="No OCR engine available. Install Tesseract (and set TESSERACT_CMD) "
                "or install rapidocr-onnxruntime.",
            )
        return engine.run(image_bytes, lang=lang)


_ocr_service: Optional[OCRService] = None


def get_ocr_service() -> OCRService:
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service
