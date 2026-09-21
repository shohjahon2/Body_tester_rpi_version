"""
Yuz embeddingini hisoblash — Bodytester_Kiosk_API.docx 2-bo'limidagi
namuna kodga mos (InsightFace buffalo_l, ArcFace).

Model FaceAnalysis birinchi chaqiriqda yuklanadi (lazy) — server tezroq
ishga tushsin va kamera/sensor sozlamalariga xalaqit bermasin.
"""
import base64
import logging

import cv2
import numpy as np

log = logging.getLogger("bodytester.face")

DET_SCORE_MIN = 0.5   # hujjat: past sifatli kadrni yubormang

_app = None


def _get_app():
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        log.info("InsightFace (buffalo_l) modeli yuklanmoqda...")
        _app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _app.prepare(ctx_id=0, det_size=(640, 640))
        log.info("InsightFace tayyor")
    return _app


def embed_photo(photo_data_url):
    """
    `data:image/png;base64,...` ko'rinishidagi rasmdan yuz vektorini
    hisoblaydi.

    Qaytaradi: (embedding: 512 ta float, quality_score: float) yoki
    yuz topilmasa / sifati past bo'lsa None.
    """
    header, _, b64data = photo_data_url.partition(",")
    raw = base64.b64decode(b64data or header)

    arr = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return None

    faces = _get_app().get(frame)
    if not faces:
        return None

    # Kameraga eng yaqin odam — hujjat: "Bir nechta yuz: eng kattasini oling"
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))

    if face.det_score < DET_SCORE_MIN:
        return None

    return face.normed_embedding.tolist(), float(face.det_score)
