"""Face detection with OpenCV YuNet (small ONNX model, auto-downloaded once to models/).
Falls back to OpenCV's Haar cascade if YuNet can't be loaded."""
from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

import cv2

from utils import net

YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
YUNET_FILE = "face_detection_yunet_2023mar.onnx"
log = logging.getLogger("clipper.faces")
try:  # silence harmless OpenCV DNN backend warnings
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:  # noqa: BLE001
    pass


def _ensure_model(models_dir: Path) -> Path | None:
    path = models_dir / YUNET_FILE
    if path.exists() and path.stat().st_size > 100_000:
        return path
    models_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"downloading face model (~230 KB) -> {path}")
    try:
        with urllib.request.urlopen(YUNET_URL, context=net.ssl_context(), timeout=60) as r:
            path.write_bytes(r.read())
        return path
    except Exception as e:  # noqa: BLE001
        log.warning(f"could not download face model: {e}. Download it manually from {YUNET_URL} into {models_dir}/")
        return None


class FaceDetector:
    """detect(frame_bgr) -> list of (x, y, w, h, score) in original frame pixels."""

    def __init__(self, models_dir: Path, work_width: int = 640):
        self.work_width = work_width
        self.yunet = None
        self.haar = None
        model = _ensure_model(models_dir)
        if model and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.yunet = cv2.FaceDetectorYN.create(str(model), "", (320, 320), 0.6, 0.3, 50)
            except cv2.error as e:
                log.warning(f"YuNet failed to load ({e}); trying Haar cascade")
        if self.yunet is None:
            try:
                c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                self.haar = None if c.empty() else c
            except Exception:  # noqa: BLE001
                self.haar = None
        if self.yunet is None and self.haar is None:
            log.warning("no face detector available - 'auto' layout will use the wide (blur) layout")

    @property
    def available(self) -> bool:
        return self.yunet is not None or self.haar is not None

    def detect(self, frame):
        h, w = frame.shape[:2]
        scale = min(1.0, self.work_width / w)
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1 else frame
        sh, sw = small.shape[:2]
        out = []
        if self.yunet is not None:
            self.yunet.setInputSize((sw, sh))
            _, faces = self.yunet.detect(small)
            for f in (faces if faces is not None else []):
                x, y, fw, fh, score = f[0], f[1], f[2], f[3], f[14]
                out.append((x / scale, y / scale, fw / scale, fh / scale, float(score)))
        elif self.haar is not None:
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            for x, y, fw, fh in self.haar.detectMultiScale(gray, 1.1, 5, minSize=(30, 30)):
                out.append((x / scale, y / scale, fw / scale, fh / scale, 0.9))
        return out
