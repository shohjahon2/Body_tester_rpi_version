"""
Lokal yuz keshi — Kiosk API qo'llanmasi (Bodytester_Kiosk_API.docx), 5-bo'lim.

Kiosk klinikadagi faol bemorlarning yuz vektorlarini diskda (SQLite)
saqlaydi va yangi kadrni serverga so'rovsiz, o'zida taniydi. Server
(`/clinic/patients/identify/`) faqat kesh topa olmagan yoki natija
noaniq bo'lgan holatlarda so'raladi — hujjat, 3-bo'lim.

Ishlatilishi:

    cache = FaceCache(path)
    sync(client, cache, bt.MODEL_VERSION)          # bitta sinxronlash
    start_sync_worker(client, cache, bt.MODEL_VERSION)  # fonda, soatiga

    match = cache.find_match(embedding)            # (patient_id, o'xshashlik, ism) yoki None
"""
import base64
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone

import numpy as np

log = logging.getLogger("bodytester.face_cache")

DIM = 512


def decode_embedding(b64):
    """Hujjat namuna kodi: float32, little-endian, base64 -> L2-normallangan vektor."""
    v = np.frombuffer(base64.b64decode(b64), dtype="<f4")
    n = np.linalg.norm(v)
    return (v / n) if n else v


def _upsert_name(upsert):
    """Sinxronlash yozuvidagi first_name+last_name -> to'liq ism (hujjat, 5.1-bo'lim)."""
    full = " ".join(x for x in [upsert.get("first_name"), upsert.get("last_name")] if x).strip()
    return full or None


class FaceCache:
    """
    Xotirada (tez qidirish uchun) va diskda (qayta yoqilganda yo'qolmasin
    deb) bir xil holatda saqlanadi. Har bir yozish avval diskka, keyin
    xotiradagi nusxaga aks etadi.
    """

    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        # Ikkita sinxronlash bir vaqtda yugurmasligi uchun (masalan, birinchi
        # token olishda ham fon-worker, ham on_new_token callback deyarli bir
        # paytda sync() ni chaqiradi). Qayta kiruvchan — _reconcile o'zi ham
        # sync() ni bir marta (o'sha oqimda) qayta chaqiradi.
        self.sync_lock = threading.RLock()
        self._ids = np.empty((0,), dtype=np.int64)
        self._vecs = np.empty((0, DIM), dtype=np.float32)
        self._names = {}
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS faces "
            "(patient_id INTEGER PRIMARY KEY, embedding BLOB NOT NULL, name TEXT)"
        )
        try:
            # Eski (name ustunisiz) bazalar uchun ko'chirish.
            self._db.execute("ALTER TABLE faces ADD COLUMN name TEXT")
        except sqlite3.OperationalError:
            pass  # ustun allaqachon bor
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        self._db.commit()
        self._load()

    # --- disk -> xotira ---

    def _load(self):
        with self._lock:
            rows = self._db.execute("SELECT patient_id, embedding, name FROM faces").fetchall()
            if rows:
                self._ids = np.array([r[0] for r in rows], dtype=np.int64)
                self._vecs = np.stack(
                    [np.frombuffer(r[1], dtype=np.float32) for r in rows]
                )
                self._names = {r[0]: r[2] for r in rows if r[2]}
            else:
                self._ids = np.empty((0,), dtype=np.int64)
                self._vecs = np.empty((0, DIM), dtype=np.float32)
                self._names = {}

    # --- meta ---

    def get_meta(self, key, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row and row[0] not in (None, "") else default

    def set_meta(self, **kv):
        with self._lock:
            for k, v in kv.items():
                if v is None:
                    continue
                self._db.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, str(v)),
                )
            self._db.commit()

    def model_version(self):
        return self.get_meta("model_version")

    def cursor(self):
        return self.get_meta("cursor")

    def threshold(self):
        # Hujjat: "Kodda qattiq yozmang" — server har sinxronlashda yuboradi.
        # Birinchi to'liq nusxagacha ehtiyotkor standart (hujjatdagi joriy qiymat).
        return float(self.get_meta("threshold", 0.66))

    def margin(self):
        return float(self.get_meta("margin", 0.05))

    def last_synced_at(self):
        return self.get_meta("last_synced_at")

    def last_sync_error(self):
        return self.get_meta("last_sync_error")

    # --- yozish ---

    def upsert(self, patient_id, embedding, name=None):
        """
        name berilmasa, mavjud ism o'zgarmay qoladi — COALESCE shu uchun.
        Ism ro'yxatdan o'tkazishda, server orqali tanishda va sinxronlashda
        (hujjat, 5.1-bo'lim: upserts first_name/last_name beradi) kelishi
        mumkin.
        """
        vec = np.asarray(embedding, dtype=np.float32)
        with self._lock:
            self._db.execute(
                "INSERT INTO faces(patient_id, embedding, name) VALUES (?, ?, ?) "
                "ON CONFLICT(patient_id) DO UPDATE SET "
                "embedding=excluded.embedding, "
                "name=COALESCE(excluded.name, faces.name)",
                (int(patient_id), vec.tobytes(), name),
            )
            self._db.commit()
            self._load()

    def remove(self, patient_id):
        with self._lock:
            self._db.execute("DELETE FROM faces WHERE patient_id=?", (int(patient_id),))
            self._db.commit()
            self._load()

    def replace_all(self, rows):
        """
        rows: [(patient_id, vektor, ism yoki None), ...]. Bitta tranzaksiyada
        almashtiriladi — hujjat: "to'liq nusxa yarim yo'lda uzilsa, eski
        kesh o'z joyida qolishi kerak" — shu sabab chaqiruvchi (sync) hamma
        sahifani avval yig'ib, faqat oxirida shu metodni chaqiradi.

        Server sinxronlashda first_name/last_name'ni ham yuboradi (hujjat,
        5.1-bo'lim). Agar biror yozuvda ism bo'lmasa (masalan eski server),
        mavjud (lokal bilingan) ism saqlab qolinadi — aks holda har to'liq
        sinxronlashda ismlar o'chib ketardi.
        """
        with self._lock:
            existing_names = dict(
                self._db.execute(
                    "SELECT patient_id, name FROM faces WHERE name IS NOT NULL"
                ).fetchall()
            )
            self._db.execute("DELETE FROM faces")
            self._db.executemany(
                "INSERT INTO faces(patient_id, embedding, name) VALUES (?, ?, ?)",
                [(int(pid), np.asarray(v, dtype=np.float32).tobytes(),
                  name or existing_names.get(int(pid)))
                 for pid, v, name in rows],
            )
            self._db.commit()
            self._load()

    def clear(self):
        with self._lock:
            self._db.execute("DELETE FROM faces")
            self._db.execute("DELETE FROM meta")
            self._db.commit()
            self._load()
        log.warning("Yuz keshi butunlay o'chirildi")

    def count(self):
        with self._lock:
            return len(self._ids)

    def ids(self):
        with self._lock:
            return set(int(i) for i in self._ids)

    # --- qidirish ---

    def find_match(self, embedding):
        """
        Hujjat, "Lokal tanish qoidasi":
          - hamma vektor L2-normallangan, o'xshashlik = skalyar ko'paytma
          - keshdan eng yaqin ikkitasi olinadi
          - eng yaxshisi threshold dan kichik bo'lsa — topilmadi
          - birinchi va ikkinchining farqi margin dan kichik bo'lsa — noaniq
          - aks holda — topildi

        Qaytaradi: (patient_id, o'xshashlik, ism yoki None) yoki None
        (server orqali tanish kerak: kesh topolmadi yoki natija noaniq).
        Ism odatda yo'q bo'ladi — faqat shu qurilmada ro'yxatdan o'tgan
        yoki server orqali tanilgan bemorlarda bo'ladi (pastga qarang).
        """
        with self._lock:
            ids, vecs, names = self._ids, self._vecs, self._names

        if len(ids) == 0:
            return None

        vec = np.asarray(embedding, dtype=np.float32)
        sims = vecs @ vec

        if len(sims) == 1:
            best_i, best, second = 0, float(sims[0]), -1.0
        else:
            top2 = np.argpartition(sims, -2)[-2:]
            top2 = top2[np.argsort(sims[top2])[::-1]]
            best_i, second_i = int(top2[0]), int(top2[1])
            best, second = float(sims[best_i]), float(sims[second_i])

        if best < self.threshold():
            return None
        if best - second < self.margin():
            return None
        patient_id = int(ids[best_i])
        return patient_id, best, names.get(patient_id)


# ------------------------------------------------------------ sinxronlash

def sync(client, cache, model_version):
    """
    Hujjat, 5-bo'lim: GET /clinic/faces/sync/ — sahifalab yuklanadi,
    to'liq nusxa (full=true) faqat oxirida bitta amalda qo'llaniladi.

    Bir vaqtning o'zida ikkita sinxronlash yugurmasin deb qulflangan —
    masalan birinchi token olinganda fon-worker ham, on_new_token
    callback ham deyarli bir paytda shu funksiyani chaqiradi.
    """
    if not cache.sync_lock.acquire(blocking=False):
        log.info("Yuz keshi sinxronlashi allaqachon ketyapti — o'tkazib yuborildi")
        return
    try:
        _sync_locked(client, cache, model_version)
    finally:
        cache.sync_lock.release()


def _sync_locked(client, cache, model_version, allow_reconcile=True):
    if cache.model_version() and cache.model_version() != model_version:
        log.warning(
            "model_version o'zgargan (%s -> %s) — kesh o'chirilmoqda",
            cache.model_version(), model_version,
        )
        cache.clear()

    since = cache.cursor()
    page = client.faces_sync(model_version, since=since)

    staged_upserts = list(page.get("upserts") or [])
    staged_removed = list(page.get("removed") or [])
    is_full = bool(page.get("full"))
    threshold = page.get("threshold")
    margin = page.get("margin")
    next_link = page.get("next")

    while next_link:
        page = client.faces_sync_page(next_link)
        staged_upserts += page.get("upserts") or []
        staged_removed += page.get("removed") or []
        is_full = is_full or bool(page.get("full"))
        threshold = page.get("threshold", threshold)
        margin = page.get("margin", margin)
        next_link = page.get("next")

    cursor = page.get("cursor")
    total = page.get("total")

    rows = [(u["patient_id"], decode_embedding(u["embedding"]), _upsert_name(u))
            for u in staged_upserts]

    if is_full:
        cache.replace_all(rows)
    else:
        for pid, vec, name in rows:
            cache.upsert(pid, vec, name=name)
        for pid in staged_removed:
            cache.remove(pid)

    cache.set_meta(model_version=model_version, cursor=cursor,
                    threshold=threshold, margin=margin,
                    last_synced_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    log.info("Yuz keshi sinxronlandi: %d ta bemor (full=%s)", cache.count(), is_full)

    if total is not None and cache.count() != total:
        if allow_reconcile:
            _reconcile(client, cache, model_version)
        else:
            log.warning("Kesh sinxronlashdan keyin ham mos kelmadi: %d != %d",
                        cache.count(), total)


def _reconcile(client, cache, model_version):
    """
    Hujjat, "Solishtirish: total va ids": o'zgarishlar ro'yxati bazadan
    butunlay o'chirilgan yozuvni hech qachon ko'rsatmasligi mumkin —
    shuning uchun son mos kelmasa /clinic/faces/ids/ bilan tekshiramiz.
    Qulf allaqachon (sync() orqali) ushlangan — to'g'ridan-to'g'ri
    _sync_locked chaqiriladi, qayta qulflash shart emas.
    """
    ids_resp = client.faces_ids(model_version)
    server_ids = set(ids_resp.get("patient_ids") or [])
    local_ids = cache.ids()

    for pid in local_ids - server_ids:
        cache.remove(pid)

    if server_ids - local_ids:
        # Ro'yxatda bor, lekin keshda yo'q — kursorni tashlab to'liq nusxa
        # olamiz. allow_reconcile=False — cheksiz aylanishning oldi olinadi.
        cache.set_meta(cursor="")
        _sync_locked(client, cache, model_version, allow_reconcile=False)


_SYNC_BACKOFF_START = 30
_SYNC_BACKOFF_MAX = 30 * 60


def start_sync_worker(client, cache, model_version, interval=3600):
    """
    Hujjat, 3-bo'lim: token olingandan keyin darhol, so'ng har soatda.
    Token o'zi ham shu birinchi chaqiruvda (lazy) olinadi.

    Xato bo'lsa hujjat, 10-bo'lim: 429'da server aytgan Retry-After
    sarlavhasi hurmat qilinadi; boshqa xatolarda (5xx, tarmoq uzilishi)
    orqaga chekinish (30s -> 60s -> ... -> 30 daqiqagacha).
    """
    def loop():
        delay = 5
        backoff = _SYNC_BACKOFF_START
        while True:
            time.sleep(delay)
            try:
                sync(client, cache, model_version)
                cache.set_meta(last_sync_error="")
                delay, backoff = interval, _SYNC_BACKOFF_START
            except Exception as e:
                log.exception("Yuz keshini sinxronlashda xato")
                cache.set_meta(last_sync_error=str(e))
                retry_after = getattr(e, "retry_after", None)
                if retry_after:
                    delay, backoff = retry_after, _SYNC_BACKOFF_START
                else:
                    delay, backoff = backoff, min(backoff * 2, _SYNC_BACKOFF_MAX)

    threading.Thread(target=loop, daemon=True, name="bodytester-face-sync").start()
