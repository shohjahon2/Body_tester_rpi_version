import base64
import serial
import time
import os
import logging
import statistics
import uvicorn
import numpy as np
import requests
import threading
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from smbus2 import SMBus
from collections import deque
from hx711_weight_sensor import HX711

import bodytester_api as bt
import face_cache
import face_recognition


def _load_dotenv():
    """.env faylini (bo'lsa) os.environ ga yuklaydi. Maxfiy kalitlar
    kodga yozilmasligi uchun — yangi pip bog'liqlik qo'shmaslik uchun
    o'zimiz o'qiymiz."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass


_load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bodytester.server")

# --- НАСТРОЙКИ ---
MAX_DISTANCE = 2000
ADDR_OX = 0x57
FINGER_THRESHOLD = 5000
S, E = b'\x02', b'\x03'
CMDS = {
    'send': S + b'22;;DA' + E + S + b'01;;D7' + E,
    'stat': S + b'18;;DF' + E
}

# Глобальные переменные
bp_cache = {"systolic": "0", "diastolic": "0", "pulse": "0"}
raw_accumulator = ""
spo2_history = deque(maxlen=10)
last_valid_spo2 = "--"

# --- ИНИЦИАЛИЗАЦИЯ ОБОРУДОВАНИЯ ---
try:
    # Рост (AMA0)
    ser_height = serial.Serial('/dev/ttyAMA0', 9600, timeout=1)
    # Давление (AMA2)
    ser_bp = serial.Serial("/dev/ttyAMA2", 4800, timeout=0.1)
    # Весы
    hx = HX711(dat_pin=27, clk_pin=17, factor=14950.0)
    hx.tare()
    # I2C (Температура и Кислород)
    bus = SMBus(1)
    print("✅ Все оборудование готово")
except Exception as e:
    print(f"❌ Ошибка инициализации: {e}")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# BODYTESTER — backend'ga yuborish
# ============================================================
# Sozlama muhit o'zgaruvchilaridan (secret kodda YO'Q):
#   BODYTESTER_SERIAL, BODYTESTER_SECRET, BODYTESTER_API_URL
#   BODYTESTER_QUEUE_PATH — yuborilmagan o'lchovlar fayli
#
# Sozlanmagan bo'lsa sensorlar odatdagidek ishlayveradi, faqat /submit
# 503 qaytaradi.

session = bt.SessionCache()
api_client, api_config_error = bt.client_from_env()

QUEUE_PATH = os.getenv(
    "BODYTESTER_QUEUE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_measurements.json"),
)
measurement_queue = bt.MeasurementQueue(api_client, QUEUE_PATH) if api_client else None

# --- Yuz keshi (Kiosk API qo'llanmasi, 5-bo'lim) ---
# Kesh mavjud bo'lmagan client bilan ham ishlaydi (bo'sh qoladi, find_match
# doim None qaytaradi) — shuning uchun sozlanmagan holatda ham xavfsiz.
FACE_CACHE_PATH = os.getenv(
    "BODYTESTER_FACE_CACHE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_cache.sqlite3"),
)
cache = face_cache.FaceCache(FACE_CACHE_PATH)

if api_client:
    api_client.on_token_401 = cache.clear
    api_client.on_new_token = lambda: face_cache.sync(api_client, cache, bt.MODEL_VERSION)
    api_client.on_patient_not_found = lambda pid: (
        cache.remove(pid),
        face_cache.sync(api_client, cache, bt.MODEL_VERSION),
    )
    face_cache.start_sync_worker(api_client, cache, bt.MODEL_VERSION)

if api_config_error:
    print(f"⚠️ Backend'ga yuborish o'chiq: {api_config_error}")
else:
    print(f"✅ Backend: {api_client.base_url} (qurilma {api_client.serial_number})")


# --- ЛОГИКА ДАВЛЕНИЯ (ФОНОВЫЙ ПОТОК) ---

# --- ИСПРАВЛЕННАЯ ЛОГИКА ДАВЛЕНИЯ (1:1 КАК В РАБОЧЕМ СКРИПТЕ) ---

def bp_background_listener():
    """Фоновый поток, полностью повторяющий логику BPReader"""
    global bp_cache, raw_accumulator
    print("👂 Слушатель тонометра (Arduino-style) запущен...")

    while True:
        try:
            if ser_bp.in_waiting > 0:
                incoming = bytearray()
                # Читаем все доступные байты с микро-задержкой, как в рабочем скрипте
                while ser_bp.in_waiting > 0:
                    b = ser_bp.read(1)
                    if not b:
                        break
                    incoming += b
                    time.sleep(0.002) # Важно! Это склеивает пакет

                if len(incoming) > 0:
                    # Проверка на символ '9' (код 57) для подтверждения статуса
                    if incoming[-3] == 57 if len(incoming) >= 3 else False:
                        ser_bp.write(CMDS['stat'])

                    # Декодируем и обрабатываем
                    s = incoming.decode("ascii", errors="ignore").strip()

                    # Если длина совпадает с форматом тонометра (41 символ)
                    if len(s) == 41:
                        try:
                            dia = s[16:19].strip()
                            sys_val = s[19:22].strip()
                            pulse = s[27:30].strip()

                            if dia.isdigit() and sys_val.isdigit():
                                bp_cache = {
                                    "systolic": str(int(sys_val)),
                                    "diastolic": str(int(dia)),
                                    "pulse": str(int(pulse))
                                }
                                print(f"✅ ДАННЫЕ ПОЛУЧЕНЫ: {bp_cache}")

                                # BODYTESTER: joriy bemor sessiyasiga
                                session.put("systolic_bp", bp_cache["systolic"])
                                session.put("diastolic_bp", bp_cache["diastolic"])
                                session.put("heart_rate", bp_cache["pulse"])
                        except Exception as e:
                            print(f"Ошибка парсинга: {e}")
                    else:
                        # Если пакет не полный, можно глянуть в консоль (для отладки)
                        # print(f"Raw packet (len {len(s)}): {s}")
                        pass

            time.sleep(0.01)
        except Exception as e:
            print(f"BP Thread Error: {e}")
            time.sleep(1)

@app.on_event("startup")
async def startup_event():
    print("🚀 Запуск фоновых потоков...")
    # Запуск потока давления
    threading.Thread(target=bp_background_listener, daemon=True).start()
    # Запуск потока роста
    threading.Thread(target=height_background_listener, daemon=True).start()
    # BODYTESTER: yuborilmagan o'lchovlarni internet qaytganda yuborish
    if measurement_queue is not None:
        measurement_queue.start_worker(interval=30)

# --- ЭНДПОИНТЫ ---

# Увеличим буфер для роста до 10 для еще большей плавности
height_history = deque(maxlen=10)

@app.get("/weight")
def get_weight():
    try:
        measurements = []
        # Собираем 10 значений вместо 5
        for _ in range(10):
            val = hx.get_weight()
            measurements.append(val)
            time.sleep(0.01)

        # --- МЕДИАННЫЙ ФИЛЬТР ---
        # Сортируем список и берем центральное значение (убирает случайные "всплески")
        med_weight = statistics.median(measurements)

        # Отсекаем шум (если меньше 0.5 кг — считаем 0)
        if med_weight < 0.5:
            return {"weight": 0.0}

        weight = round(med_weight, 2)
        # BODYTESTER: faqat barqaror qiymat (chiqib-tushish paytidagisi emas)
        session.put_stable("weight_kg", weight, tolerance=0.3)
        return {"weight": weight}
    except Exception as e:
        return {"weight": 0.0}

# --- 1. Добавьте глобальную переменную для хранения текущего сглаженного роста ---
current_smooth_height = 0.0

measuring_active = False

@app.get("/start-sensors")
def start_sensors():
    global measuring_active
    measuring_active = True
    print("🚀 Датчики активированы")
    return {"status": "active"}

@app.get("/stop-sensors")
def stop_sensors():
    global measuring_active
    measuring_active = False
    print("🛑 Датчики остановлены")
    return {"status": "idle"}



def height_background_listener():
    """Фоновый поток для постоянного мониторинга роста"""
    global current_smooth_height
    print("📏 Мониторинг роста запущен...")

    # Сразу заполняем буфер реальными значениями при старте
    try:
        for _ in range(10):
            ser_height.reset_input_buffer()
            cmd = bytearray([0x55, 0xAA, 0x01, 0x01, (0x55+0xAA+0x01+0x01)&0xFF])
            ser_height.write(cmd)
            time.sleep(0.05)
            data = ser_height.read(7)
            if len(data) >= 6:
                val = MAX_DISTANCE / 10 - ((data[4] << 8 | data[5]) / 10)
                height_history.append(val)
    except:
        pass

    while True:
        try:
            ser_height.reset_input_buffer()
            cmd = bytearray([0x55, 0xAA, 0x01, 0x01, (0x55+0xAA+0x01+0x01)&0xFF])
            ser_height.write(cmd)
            time.sleep(0.1) # Опрос каждые 100мс

            data = ser_height.read(7)
            if len(data) >= 6:
                val = MAX_DISTANCE / 10 - ((data[4] << 8 | data[5]) / 10)
                height_history.append(val)
                # Вычисляем медиану в фоне
                current_smooth_height = round(statistics.median(list(height_history)), 1)
        except Exception as e:
            print(f"Height Thread Error: {e}")
        time.sleep(0.1)




# --- 3. Теперь эндпоинт просто отдает уже готовое число ---
@app.get("/height")
def get_height_api():
    # Если значение слишком маленькое (датчик видит потолок), возвращаем 0
    if current_smooth_height < 10:
        return {"height": 0}
    # BODYTESTER: faqat barqaror qiymat
    session.put_stable("height_cm", current_smooth_height, tolerance=1.0)
    return {"height": current_smooth_height}



@app.get("/temperature")
def get_temperature():
    try:
        data = bus.read_word_data(0x5a, 0x07)
        temp = round((data * 0.02) - 273.15, 2)
        # BODYTESTER: yaroqliligi yuborishda tekshiriladi (20..45 °C)
        session.put("temperature_c", temp)
        return {"temperature": temp}
    except:
        return {"temperature": 0}

@app.get("/start-bp")
def start_bp():
    global bp_cache, raw_accumulator
    bp_cache = {"systolic": "0", "diastolic": "0", "pulse": "0"}
    raw_accumulator = ""
    # BODYTESTER: yangi o'lchov boshlandi — eskisi yuborilmasin
    session.put("systolic_bp", None)
    session.put("diastolic_bp", None)
    session.put("heart_rate", None)
    ser_bp.reset_input_buffer()
    ser_bp.write(CMDS['send'])
    return {"status": "started"}

@app.get("/blood-pressure")
def get_bp():
    print(bp_cache)
    return bp_cache

@app.post("/oxygen/reset")
def reset_oxygen():
    global last_valid_spo2
    spo2_history.clear()
    last_valid_spo2 = "--"
    # BODYTESTER: yangi o'lchov boshlandi — eskisi yuborilmasin
    session.put("spO2", None)
    return {"status": "reset"}

# --- ИНИЦИАЛИЗАЦИЯ КИСЛОРОДА ---
def init_oxygen():
    try:
        # Сброс (Reset)
        bus.write_byte_data(ADDR_OX, 0x06, 0x40)
        time.sleep(0.1)

        # Очистка FIFO (Важно!)
        bus.write_byte_data(ADDR_OX, 0x02, 0x00)
        bus.write_byte_data(ADDR_OX, 0x03, 0x00)
        bus.write_byte_data(ADDR_OX, 0x04, 0x00)

        # Настройки режима
        bus.write_byte_data(ADDR_OX, 0x06, 0x03)  # SpO2 mode
        bus.write_byte_data(ADDR_OX, 0x07, 0x27)  # SpO2 Config
        bus.write_byte_data(ADDR_OX, 0x09, 0x7F)  # Ток светодиодов
        print("✅ Датчик кислорода настроен")
    except Exception as e:
        print(f"❌ Ошибка настройки SpO2: {e}")

# Вызовите это в блоке инициализации оборудования:
try:
    bus = SMBus(1)
    init_oxygen() # Добавьте этот вызов!
    # ... остальной код (вес, рост)
except Exception as e:
    print(f"❌ Ошибка инициализации: {e}")

# --- ОБНОВЛЕННЫЙ ЭНДПОИНТ ---
@app.get("/oxygen")
def get_oxygen():
    global last_valid_spo2
    try:
        # 1. Если мы уже собрали 10 измерений, просто отдаем результат
        if len(spo2_history) >= 10:
            session.put("spO2", last_valid_spo2)   # BODYTESTER
            return {
                "status": "completed",
                "progress": 10,
                "oxygen": last_valid_spo2
            }

        # 2. Проверка наличия пальца (чтение текущего состояния)
        data = bus.read_i2c_block_data(ADDR_OX, 0x05, 4)
        ir = (data[0] << 8) | data[1]

        if ir < FINGER_THRESHOLD:
            spo2_history.clear() # Сбрасываем прогресс, если палец убрали
            last_valid_spo2 = "--"
            return {"status": "waiting", "progress": 0, "oxygen": "--"}

        # 3. Чтение пачки данных (одна итерация измерения)
        ir_buf, red_buf = [], []
        for _ in range(50):
            d = bus.read_i2c_block_data(ADDR_OX, 0x05, 4)
            ir_buf.append((d[0] << 8) | d[1])
            red_buf.append((d[2] << 8) | d[3])
            time.sleep(0.01)

        ir_np = np.array(ir_buf)
        red_np = np.array(red_buf)

        ir_dc, red_dc = np.mean(ir_np), np.mean(red_np)
        ir_ac, red_ac = np.std(ir_np), np.std(red_np)

        # 4. Расчет одного замера
        if ir_dc > 0 and ir_ac > 5:
            R = (red_ac / red_dc) / (ir_ac / ir_dc)
            spo2_val = 110 - 25 * R
            final_val = max(90, min(100, spo2_val))

            # Добавляем в историю
            spo2_history.append(final_val)

            # Обновляем текущее среднее
            current_avg = sum(spo2_history) / len(spo2_history)
            last_valid_spo2 = str(round(current_avg, 1))

        # 5. Возвращаем текущий статус
        progress = len(spo2_history)
        if progress >= 10:
            session.put("spO2", last_valid_spo2)   # BODYTESTER
            return {"status": "completed", "progress": 10, "oxygen": last_valid_spo2}
        else:
            return {"status": "measuring", "progress": progress, "oxygen": "--"}

    except Exception as e:
        print(f"Oxygen Error: {e}")
        init_oxygen() # Перезагрузка датчика при сбое I2C
        return {"status": "error", "oxygen": "--"}


# ============================================================
# BODYTESTER — sessiya va yuborish endpointlari
# ============================================================

class SubmitRequest(BaseModel):
    patient_id: int
    recommendation: Optional[str] = None


class SavePhotoRequest(BaseModel):
    photo: str            # data:image/png;base64,... ko'rinishidagi rasm
    name: Optional[str] = None


PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")


def _persist_photo(photo_data_url, name):
    """Base64 rasmni backend/photos/ ga yozadi. Qaytaradi: fayl nomi."""
    header, _, b64data = photo_data_url.partition(",")
    raw = base64.b64decode(b64data or header)
    ext = "jpg" if "jpeg" in header or "jpg" in header else "png"

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    safe_name = "".join(c for c in (name or "guest") if c.isalnum() or c in "-_") or "guest"
    filename = f"{int(time.time())}_{safe_name}.{ext}"
    with open(os.path.join(PHOTOS_DIR, filename), "wb") as f:
        f.write(raw)
    return filename


@app.post("/save-photo")
def save_photo(req: SavePhotoRequest):
    """Rasmni diskka saqlaydi (umumiy yordamchi vosita, yozuv uchun)."""
    try:
        filename = _persist_photo(req.photo, req.name)
    except (ValueError, TypeError) as e:
        return JSONResponse(status_code=400, content={"detail": f"Rasmni o'qib bo'lmadi: {e}"})
    return {"status": "saved", "filename": filename}


# ------------------------------------------------------------ yuz tanish
# Kiosk API qo'llanmasi, 2- va 3-bo'lim: rasmdan ArcFace vektor hisoblanadi,
# so'ng identify/enroll bilan bemor patient_id'i olinadi.

class FaceIdentifyRequest(BaseModel):
    photo: str
    name: Optional[str] = None


class FaceEnrollRequest(BaseModel):
    embedding: list
    quality_score: Optional[float] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    phone_number: Optional[str] = None


@app.post("/face/identify")
def face_identify(req: FaceIdentifyRequest):
    """
    Kiosk API qo'llanmasi, 3-bo'lim: avval lokal keshdan qidiriladi
    (serverga so'rovsiz), faqat topilmasa yoki noaniq bo'lsa server
    chaqiriladi. Kamera doimiy skanerlaydi — bo'sh kadr ("no_face")
    diskka yozilmaydi, aks holda fotolar papkasi to'lib ketadi.
    """
    if api_client is None:
        return {"status": "not_configured"}

    try:
        result = face_recognition.embed_photo(req.photo)
    except Exception as e:
        log.exception("Yuz embeddingini hisoblashda xato")
        return {"status": "error", "detail": str(e)}

    if result is None:
        return {"status": "no_face"}
    embedding, quality_score = result

    try:
        _persist_photo(req.photo, req.name)
    except (ValueError, TypeError) as e:
        log.warning("Rasmni saqlab bo'lmadi: %s", e)

    local = cache.find_match(embedding)
    if local is not None:
        patient_id, similarity, name = local
        resp = {"status": "found", "patient_id": patient_id,
                "similarity": similarity, "source": "cache"}
        if name:
            resp["name"] = name
        return resp

    try:
        identify_result = api_client.identify(embedding)
    except (bt.ApiError, requests.RequestException) as e:
        return {"status": "error", "detail": str(e)}

    if identify_result.get("status") == "found":
        # Server ism qaytaradi (kesh esa hech qachon) — shu bilan birga
        # keshni ham "davolaymiz": keyingi safar shu bemor to'g'ridan-to'g'ri
        # (ismi bilan) keshdan topiladi, serverga qayta so'rov ketmaydi.
        full_name = " ".join(
            x for x in [identify_result.get("first_name"), identify_result.get("last_name")] if x
        ).strip()
        if full_name:
            identify_result["name"] = full_name
        cache.upsert(identify_result["patient_id"], embedding, name=full_name or None)
    elif identify_result.get("status") == "not_found":
        identify_result["embedding"] = embedding
        identify_result["quality_score"] = quality_score
    return identify_result


@app.post("/face/enroll")
def face_enroll(req: FaceEnrollRequest):
    if api_client is None:
        return {"status": "not_configured"}

    patient = {k: v for k, v in {
        "first_name": req.first_name,
        "last_name": req.last_name,
        "gender": req.gender,
        "age": req.age,
        "phone_number": req.phone_number,
    }.items() if v is not None}

    try:
        result = api_client.enroll(req.embedding, quality_score=req.quality_score, **patient)
    except (bt.ApiError, requests.RequestException) as e:
        return {"status": "error", "detail": str(e)}

    if result.get("patient_id") is not None:
        # Hujjat, "Keshni yangilash": keyingi sinxronlashni kutmasdan
        # darhol keshga qo'shiladi. Ism ham shu yerda saqlanadi — bu
        # qurilma sinxronlash orqali hech qachon ism olmaydi.
        full_name = " ".join(
            x for x in [result.get("first_name"), result.get("last_name")] if x
        ).strip()
        cache.upsert(result["patient_id"], req.embedding, name=full_name or None)

    if result.get("possible_duplicate_of"):
        log.warning("Yangi bemor (%s) mavjud yozuvga o'xshaydi: patient_id=%s, o'xshashlik=%s",
                    result.get("patient_id"), result["possible_duplicate_of"],
                    result.get("duplicate_similarity"))

    return {"status": "enrolled", **result}


@app.post("/session/start")
def session_start():
    """
    Yangi bemor keldi. Oldingi bemorning qiymatlari tozalanadi — aks
    holda u o'lchatmagan ko'rsatkich (masalan bosim) oldingi bemordan
    olinib, noto'g'ri odamga yozilardi.
    """
    session.start()
    return {"status": "started"}


@app.post("/submit")
def submit(req: SubmitRequest):
    """
    Joriy sessiyadagi o'lchovlarni serverga yuboradi.

      201 sent      — saqlandi
      202 queued    — internet yo'q; diskka yozildi, keyin avtomatik ketadi
      422 rejected  — server rad etdi (masalan bemor boshqa klinikaniki).
                      Sessiya saqlanadi — tuzatib qayta yuborish mumkin
      400           — bu bemor uchun hech narsa o'lchanmagan
      503           — backend sozlanmagan
    """
    if measurement_queue is None:
        return JSONResponse(status_code=503,
                            content={"detail": f"Backend sozlanmagan: {api_config_error}"})

    measurement, dropped = bt.build_measurement(session.snapshot(), req.recommendation)

    if not bt.has_vitals(measurement):
        return JSONResponse(status_code=400, content={
            "detail": "Bu bemor uchun hech qanday o'lchov olinmagan",
            "dropped": dropped,
        })

    status, detail = measurement_queue.submit(req.patient_id, measurement)
    body = {"status": status, "detail": detail,
            "measurement": measurement, "dropped": dropped}

    if status == bt.REJECTED:
        return JSONResponse(status_code=422, content=body)

    session.start()          # keyingi bemor toza boshlasin
    return JSONResponse(status_code=201 if status == bt.SENT else 202, content=body)


@app.get("/queue")
def queue_status():
    """Yuborilmay turgan o'lchovlar soni — internet yo'qligini tekshirish uchun."""
    if measurement_queue is None:
        return {"enabled": False, "detail": api_config_error}
    return {"enabled": True, "pending": measurement_queue.pending()}


FACE_CACHE_VIEW_HTML = """<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yuz keshi — sinxronlash</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 32px 20px; min-height: 100vh;
    background: #0b1220; color: #e6edf3;
    font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
    display: flex; justify-content: center;
  }
  .card {
    width: 100%; max-width: 520px; background: #121a2b;
    border: 1px solid #22304a; border-radius: 16px; padding: 28px;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #8b9bb4; font-size: 13px; margin-bottom: 24px; }
  .count { font-size: 56px; font-weight: 700; color: #54ffff; line-height: 1; }
  .count-label { color: #8b9bb4; font-size: 14px; margin-top: 4px; }
  .rows { margin-top: 24px; border-top: 1px solid #22304a; }
  .row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 0; border-bottom: 1px solid #22304a; font-size: 14px;
  }
  .row .k { color: #8b9bb4; }
  .row .v { font-weight: 600; text-align: right; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .badge.ok { background: rgba(84,255,255,0.15); color: #54ffff; }
  .badge.bad { background: rgba(255,90,90,0.15); color: #ff5a5a; }
  .error {
    margin-top: 20px; padding: 12px 16px; border-radius: 10px;
    background: rgba(255,90,90,0.12); border: 1px solid rgba(255,90,90,0.4);
    color: #ff8a8a; font-size: 13px; display: none; word-break: break-word;
  }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:8px; background:#54ffff; animation: pulse 1.5s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .3; } }
  .updated { color: #4a5a78; font-size: 12px; margin-top: 18px; text-align: center; }
  .ids-title { margin-top: 24px; font-size: 13px; color: #8b9bb4; }
  .ids {
    margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px;
    max-height: 260px; overflow-y: auto; padding-right: 4px;
  }
  .id-chip {
    background: #1a2540; border: 1px solid #22304a; border-radius: 8px;
    padding: 6px 12px; font-size: 13px; font-variant-numeric: tabular-nums;
  }
  .empty { color: #4a5a78; font-size: 13px; }
</style>
</head>
<body>
  <div class="card">
    <h1><span class="dot"></span>Yuz keshi sinxronlashi</h1>
    <div class="sub">Har 2 soniyada avtomatik yangilanadi</div>

    <div class="count" id="count">—</div>
    <div class="count-label">keshdagi bemorlar soni</div>

    <div class="rows">
      <div class="row"><span class="k">Backend</span><span class="v" id="backend">—</span></div>
      <div class="row"><span class="k">model_version</span><span class="v" id="model_version">—</span></div>
      <div class="row"><span class="k">threshold</span><span class="v" id="threshold">—</span></div>
      <div class="row"><span class="k">margin</span><span class="v" id="margin">—</span></div>
      <div class="row"><span class="k">Oxirgi sinxronlash</span><span class="v" id="last_synced_at">—</span></div>
    </div>

    <div class="error" id="error"></div>

    <div class="ids-title">Keshdagi patient_id lar</div>
    <div class="ids" id="ids"></div>

    <div class="updated" id="updated"></div>
  </div>

<script>
async function tick() {
  try {
    const res = await fetch('/face/cache/status', { cache: 'no-store' });
    const data = await res.json();

    document.getElementById('count').textContent = data.count;

    const idsEl = document.getElementById('ids');
    const ids = data.patient_ids || [];
    idsEl.innerHTML = ids.length
      ? ids.map(id => '<span class="id-chip">#' + id + '</span>').join('')
      : '<span class="empty">kesh bo\\'sh</span>';
    document.getElementById('model_version').textContent = data.model_version || '—';
    document.getElementById('threshold').textContent = data.threshold ?? '—';
    document.getElementById('margin').textContent = data.margin ?? '—';
    document.getElementById('last_synced_at').textContent = data.last_synced_at || 'hali yo\\'q';

    const backendEl = document.getElementById('backend');
    backendEl.innerHTML = data.backend_configured
      ? '<span class="badge ok">ulangan</span>'
      : '<span class="badge bad">sozlanmagan</span>';

    const errEl = document.getElementById('error');
    if (data.last_sync_error) {
      errEl.style.display = 'block';
      errEl.textContent = 'Oxirgi sinxronlash xatosi: ' + data.last_sync_error;
    } else {
      errEl.style.display = 'none';
    }

    document.getElementById('updated').textContent =
      'so\\'nggi tekshiruv: ' + new Date().toLocaleTimeString('uz-UZ');
  } catch (err) {
    document.getElementById('updated').textContent = 'Backendga ulanib bo\\'lmadi...';
  }
}
tick();
setInterval(tick, 2000);
</script>
</body>
</html>
"""


@app.get("/face/cache/status")
def face_cache_status():
    """Diagnostika: keshda nechta yuz bor va oxirgi sinxronlash holati."""
    return {
        "count": cache.count(),
        "patient_ids": sorted(cache.ids()),
        "model_version": cache.model_version(),
        "threshold": cache.threshold(),
        "margin": cache.margin(),
        "last_synced_at": cache.last_synced_at(),
        "last_sync_error": cache.last_sync_error(),
        "backend_configured": api_client is not None,
    }


@app.get("/face/cache/view")
def face_cache_view():
    """Yuz keshi sinxronlashini ko'rish uchun bitta sahifa (avtomatik yangilanadi)."""
    return HTMLResponse(FACE_CACHE_VIEW_HTML)


if __name__ == "__main__":
    # KIOSK_HOST=127.0.0.1 — UI shu qurilmada bo'lsa, tarmoqqa ochmaslik uchun
    uvicorn.run(app, host=os.getenv("KIOSK_HOST", "0.0.0.0"), port=8000)
