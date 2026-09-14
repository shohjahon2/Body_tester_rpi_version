"""
Bodytester backend bilan aloqa.

Kiosk API qo'llanmasidagi kontrakt asosida:
  POST /clinic/devices/token/         token olish
  POST /clinic/patients/identify/     yuzni tanish
  POST /clinic/patients/              bemorni ro'yxatdan o'tkazish
  POST /clinic/patients/measurement/  o'lchovlarni yuborish

Bu faylda uskuna (serial, I2C) YO'Q — shuning uchun uni qurilmasiz
ham sinab ko'rish mumkin.
"""
import json
import logging
import os
import statistics
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import requests

log = logging.getLogger("bodytester")

# Aynan shu satr, harfma-harf. Boshqacha yozilsa server xato bermaydi,
# lekin bemorni TANIMAYDI va kiosk uni qayta ro'yxatdan o'tkazib yuboradi.
MODEL_VERSION = "arcface-buffalo_l"
EMBEDDING_DIM = 512

DEFAULT_API_URL = "https://bodytester-microservice.bodytester.uz/api"

# Server tokeni 30 daqiqa yashaydi — chegarada uzilib qolmaslik uchun
# oldinroq yangilaymiz.
TOKEN_TTL_SEC = 25 * 60

# Yuborish natijalari
SENT = "sent"          # saqlandi
QUEUED = "queued"      # vaqtinchalik muammo — keyin avtomatik qayta yuboriladi
REJECTED = "rejected"  # server qat'iy rad etdi — qayta yuborish foydasiz

# Server qabul qiladigan chegaralar (qo'llanma, 7-bo'lim).
BOUNDS = {
    "heart_rate":    (0, 300, int),
    "systolic_bp":   (0, 300, int),
    "diastolic_bp":  (0, 250, int),
    "spO2":          (0, 100, float),
    "temperature_c": (20, 45, float),
    "weight_kg":     (0, 200, float),
    "height_cm":     (0, 250, float),
    "bmi":           (0, 100, float),
}
VITAL_FIELDS = ("heart_rate", "systolic_bp", "diastolic_bp", "spO2",
                "temperature_c", "weight_kg", "height_cm")

# Sensorlar "o'lchanmadi" deganda qaytaradigan qiymatlar
_NOT_MEASURED = (None, 0, "0", "--", "")


# ------------------------------------------------------------ qiymatlar

def sanitize(field, raw):
    """
    Sensor qiymatini server kutgan ko'rinishga keltiradi yoki None qaytaradi.

    Ikki holatda None:

    1) "O'lchanmadi" belgilari. Sensorlar o'lchanmagan qiymatni 0, "0"
       yoki "--" deb qaytaradi. Server 0 ni QABUL QILADI, ya'ni ularni
       o'tkazib yuborsak bazaga "yurak urishi 0" degan soxta yozuv
       tushardi. Tirik odamda bu maydonlarning hech biri 0 bo'lmaydi.

    2) Chegaradan tashqari. Server bitta noto'g'ri qiymat uchun BUTUN
       so'rovni rad etadi — masalan sovuq xonada harorat sensori 18°C
       ko'rsatsa, vazn va bosim ham yo'qolardi. Shu yerda faqat o'sha
       bittasi tashlab yuboriladi.
    """
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None                        # "--", "", "error"
    if val != val or val <= 0:             # NaN yoki o'lchanmagan
        return None
    lo, hi, kind = BOUNDS[field]
    if not lo <= val <= hi:
        log.warning("%s=%s chegaradan tashqarida (%s..%s) — yuborilmaydi",
                    field, val, lo, hi)
        return None
    return int(round(val)) if kind is int else round(val, 2)


def compute_bmi(weight_kg, height_cm):
    if not weight_kg or not height_cm or height_cm < 50:
        return None
    return sanitize("bmi", round(weight_kg / (height_cm / 100.0) ** 2, 1))


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_measurement(values, recommendation=None):
    """
    Sessiya qiymatlaridan serverga ketadigan bitta o'lchov yasaydi.

    client_measurement_id SHU YERDA, o'lchov yig'ilgan paytda yaratiladi
    va navbatda saqlanadi. Qayta yuborishda aynan u ketadi — server
    takrorni tanib, ikkinchi marta yozmaydi.

    Qaytaradi: (o'lchov, tashlab yuborilganlar)
    `tashlab yuborilganlar` — qiymati BOR, lekin yaroqsiz bo'lgan
    maydonlar (masalan harorat 18°C). "O'lchanmadi" bu ro'yxatga
    kirmaydi — bu normal holat.
    """
    m = {"client_measurement_id": str(uuid.uuid4()),
         "recorded_at": utc_now_iso()}
    dropped = []

    for field in VITAL_FIELDS:
        raw = values.get(field)
        clean = sanitize(field, raw)
        if clean is not None:
            m[field] = clean
        elif raw not in _NOT_MEASURED:
            dropped.append({"field": field, "value": raw})

    bmi = compute_bmi(m.get("weight_kg"), m.get("height_cm"))
    if bmi is not None:
        m["bmi"] = bmi
    if recommendation:
        m["recommendation"] = recommendation

    return m, dropped


def has_vitals(measurement):
    return any(f in measurement for f in VITAL_FIELDS)


# --------------------------------------------------------- bemor sessiyasi

class SessionCache:
    """
    Joriy bemor sessiyasida o'lchangan qiymatlar.

    Nega kerak: sensor holati global va bir bemordan keyingisiga o'tib
    ketadi. Masalan bp_cache yangi bosim o'lchovi boshlanmaguncha OLDINGI
    bemorning qiymatini saqlab turadi — ikkinchi bemor bosim o'lchatmasa,
    unga birinchi bemorning bosimi yozilib ketardi.

    Qiymat UI sensorga murojaat qilgan paytda yoziladi — ya'ni serverga
    bemor ekranda ko'rgan son ketadi.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.start()

    def start(self):
        with self._lock:
            self._last = {}
            self._stable = {}
            self._recent = {}
            self.started_at = time.time()

    def put(self, name, value):
        with self._lock:
            self._last[name] = value
            self._stable.pop(name, None)

    def put_stable(self, name, value, tolerance, window=3):
        """
        Tarozi va bo'y o'lchagich uchun. Bemor chiqayotgan-tushayotgan
        paytdagi oraliq qiymat (bir oyog'i yerda — 40 kg) yozilib
        qolmasligi kerak. Ketma-ket `window` ta o'qish bir-biridan
        `tolerance` dan uzoq bo'lmasa, qiymat barqaror deb qabul qilinadi.
        """
        with self._lock:
            self._last[name] = value
            buf = self._recent.setdefault(name, deque(maxlen=window))
            buf.append(value)
            if len(buf) == window and max(buf) - min(buf) <= tolerance:
                self._stable[name] = round(statistics.median(buf), 2)

    def snapshot(self):
        with self._lock:
            out = dict(self._last)
            out.update(self._stable)       # barqaror qiymat ustun
            return out


# ------------------------------------------------------------ server

class ApiError(Exception):
    pass


def error_text(resp):
    """
    Server javobini o'qiladigan matnga aylantiradi.

    429 ni nginx qaytaradi va u JSON EMAS, HTML. Ko'r-ko'rona .json()
    qilinsa parser yiqiladi va asl sabab yo'qoladi.
    """
    if resp.status_code == 429:
        return "429: so'rovlar juda ko'p, keyinroq qayta urinish kerak"
    try:
        data = resp.json()
    except ValueError:
        return "%s: %s" % (resp.status_code, resp.text[:200].strip())
    if isinstance(data, dict) and "detail" in data:
        return "%s: %s" % (resp.status_code, data["detail"])
    return "%s: %s" % (resp.status_code, json.dumps(data, ensure_ascii=False)[:300])


def _check_embedding(embedding):
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError("embedding %d ta son bo'lishi kerak, %d keldi"
                         % (EMBEDDING_DIM, len(embedding)))
    # numpy float32 JSON'ga o'tmaydi — oddiy float qilamiz
    return [float(x) for x in embedding]


class BodytesterClient:

    def __init__(self, base_url, serial_number, secret, timeout=15):
        self.base_url = base_url.rstrip("/")
        self.serial_number = serial_number
        self._secret = secret
        self.timeout = timeout
        self.session = requests.Session()
        self._token = None
        self._token_until = 0.0
        self._lock = threading.Lock()

    def _get_token(self, force=False):
        with self._lock:
            if not force and self._token and time.time() < self._token_until:
                return self._token
            r = self.session.post(
                self.base_url + "/clinic/devices/token/",
                json={"serial_number": self.serial_number, "secret": self._secret},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                self._token = None
                raise ApiError("Token olinmadi — " + error_text(r))
            self._token = r.json()["access"]
            self._token_until = time.time() + TOKEN_TTL_SEC
            return self._token

    def _post(self, path, payload):
        """
        Token bilan POST. 401/403 kelsa tokenni BIR MARTA yangilab qayta
        uradi. Ikkinchisida ham xato bo'lsa javobni qaytaradi — cheksiz
        takrorlamaydi.
        """
        resp = None
        for attempt in (1, 2):
            token = self._get_token(force=(attempt == 2))
            resp = self.session.post(
                self.base_url + path, json=payload, timeout=self.timeout,
                headers={"Authorization": "Bearer " + token},
            )
            if resp.status_code not in (401, 403):
                break
        return resp

    # --- yuz ---

    def identify(self, embedding):
        """Qaytaradi: {"status": "found" | "not_found" | "ambiguous", ...}"""
        r = self._post("/clinic/patients/identify/",
                       {"embedding": _check_embedding(embedding),
                        "model_version": MODEL_VERSION})
        if r.status_code != 200:
            raise ApiError(error_text(r))
        return r.json()

    def enroll(self, embedding, quality_score=None, **patient):
        """
        Faqat identify "not_found" qaytarganda chaqiring.
        patient: first_name, last_name, gender ("M"/"F"), age, phone_number
        """
        payload = {k: v for k, v in patient.items() if v not in (None, "")}
        payload["embedding"] = _check_embedding(embedding)
        payload["model_version"] = MODEL_VERSION
        if quality_score is not None:
            payload["quality_score"] = float(quality_score)
        r = self._post("/clinic/patients/", payload)
        if r.status_code != 201:
            raise ApiError(error_text(r))
        return r.json()

    # --- o'lchov ---

    def send_measurement(self, patient_id, measurement):
        """Qaytaradi: (SENT | QUEUED | REJECTED, izoh)"""
        try:
            r = self._post("/clinic/patients/measurement/",
                           {"patient_id": int(patient_id),
                            "measurements": [measurement]})
        except (requests.RequestException, ApiError) as e:
            return QUEUED, str(e)

        if r.status_code == 201:
            # skipped_count=1 — bu o'lchov avval ham yetib borgan (javob
            # yo'lda yo'qolgan). Xato emas: idempotentlik aynan shu.
            return SENT, r.json().get("message", "")
        if r.status_code in (400, 404):
            return REJECTED, error_text(r)
        return QUEUED, error_text(r)


def client_from_env():
    """
    Sozlama muhit o'zgaruvchilaridan — secret kodga YOZILMAYDI.

      BODYTESTER_SERIAL    qurilma seriya raqami        (majburiy)
      BODYTESTER_SECRET    qurilma maxfiy kaliti dsk_… (majburiy)
      BODYTESTER_API_URL   server manzili               (ixtiyoriy)

    Qaytaradi: (client yoki None, xato matni yoki None)
    """
    serial = os.getenv("BODYTESTER_SERIAL", "").strip()
    secret = os.getenv("BODYTESTER_SECRET", "").strip()
    if not serial or not secret:
        return None, "BODYTESTER_SERIAL va BODYTESTER_SECRET o'rnatilmagan"
    url = os.getenv("BODYTESTER_API_URL", DEFAULT_API_URL).strip()
    return BodytesterClient(url, serial, secret), None


# ------------------------------------------------------------ navbat

class MeasurementQueue:
    """
    Yuborilmagan o'lchovlar — diskda saqlanadi, internet qaytganda
    avtomatik yuboriladi.

    Tartib muhim: o'lchov AVVAL diskka yoziladi, KEYIN yuboriladi. Aks
    holda yuborish paytida elektr o'chsa o'lchov yo'qolardi.

    Takroriy yuborish xavfsiz: har o'lchovning client_measurement_id si
    yaratilgan paytda qotiriladi va server takrorni o'zi tanib o'tkazadi.
    """

    def __init__(self, client, path, rejected_path=None):
        self.client = client
        self.path = path
        self.rejected_path = rejected_path or os.path.splitext(path)[0] + ".rejected.json"
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._items = self._load()

    # --- disk ---

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                items = json.load(f)
            return items if isinstance(items, list) else []
        except FileNotFoundError:
            return []
        except (ValueError, OSError) as e:
            # Buzilgan faylni o'chirmaymiz — ichida yuborilmagan tibbiy
            # ma'lumot bo'lishi mumkin. Chetga olib qo'yamiz.
            broken = "%s.broken-%d" % (self.path, int(time.time()))
            log.error("Navbat fayli o'qilmadi (%s) — %s ga ko'chirildi", e, broken)
            try:
                os.replace(self.path, broken)
            except OSError:
                pass
            return []

    @staticmethod
    def _write(path, items):
        """Atomik yozish: elektr o'chsa yarim yozilgan fayl qolmasin."""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _save(self):
        self._write(self.path, self._items)

    # --- holat ---

    def pending(self):
        with self._lock:
            return len(self._items)

    def _add(self, patient_id, measurement):
        item = {"patient_id": int(patient_id), "measurement": measurement,
                "created_at": utc_now_iso(), "attempts": 0, "last_error": None}
        with self._lock:
            self._items.append(item)
            self._save()
        return item

    def _remove(self, cmid):
        with self._lock:
            self._items = [i for i in self._items
                           if i["measurement"]["client_measurement_id"] != cmid]
            self._save()

    def _mark_failed(self, cmid, detail):
        with self._lock:
            for i in self._items:
                if i["measurement"]["client_measurement_id"] == cmid:
                    i["attempts"] += 1
                    i["last_error"] = detail
            self._save()

    def _move_to_rejected(self, item, reason):
        record = dict(item, rejected_reason=reason, rejected_at=utc_now_iso())
        with self._lock:
            try:
                with open(self.rejected_path, encoding="utf-8") as f:
                    rejected = json.load(f)
            except (FileNotFoundError, ValueError):
                rejected = []
            rejected.append(record)
            self._write(self.rejected_path, rejected)
        self._remove(item["measurement"]["client_measurement_id"])

    def _send(self, item):
        # Bir vaqtda ikkita yuborish ketmasin (worker + UI). Ketsa ham
        # zarari yo'q — server takroriy UUID ni o'tkazib yuboradi.
        with self._send_lock:
            return self.client.send_measurement(item["patient_id"], item["measurement"])

    # --- ish ---

    def submit(self, patient_id, measurement):
        """UI dan kelgan o'lchov: diskka yoziladi va darhol yuboriladi."""
        item = self._add(patient_id, measurement)
        cmid = measurement["client_measurement_id"]
        status, detail = self._send(item)

        if status == SENT:
            self._remove(cmid)
        elif status == REJECTED:
            # UI ga qaytadi — xato tuzatilsa (masalan to'g'ri patient_id)
            # qayta yuboriladi. Shuning uchun rejected faylga emas.
            self._remove(cmid)
        else:
            self._mark_failed(cmid, detail)
        return status, detail

    def flush(self):
        with self._lock:
            batch = [dict(i) for i in self._items]

        for item in batch:
            cmid = item["measurement"]["client_measurement_id"]
            status, detail = self._send(item)
            if status == SENT:
                self._remove(cmid)
                log.info("Navbatdagi o'lchov yuborildi: %s", cmid)
            elif status == REJECTED:
                log.error("O'lchov rad etildi (%s): %s", detail, cmid)
                self._move_to_rejected(item, detail)
            else:
                self._mark_failed(cmid, detail)
                log.warning("Navbat: hali yuborib bo'lmadi — %s", detail)
                break          # tarmoq yo'q — qolganlarini urinib o'tirmaymiz

    def start_worker(self, interval=30):
        def loop():
            delay = 5          # ishga tushgach tez: o'chib-yonishdan qolganlar
            while True:
                time.sleep(delay)
                delay = interval
                try:
                    if self.pending():
                        self.flush()
                except Exception:
                    log.exception("Navbat ishchisi xatosi")

        threading.Thread(target=loop, daemon=True, name="bodytester-queue").start()
