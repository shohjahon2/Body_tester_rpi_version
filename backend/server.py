import serial
import time
import os
import logging
import statistics
import uvicorn
import numpy as np
import threading
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from smbus2 import SMBus
from collections import deque
from hx711_weight_sensor import HX711

import bodytester_api as bt

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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


if __name__ == "__main__":
    # KIOSK_HOST=127.0.0.1 — UI shu qurilmada bo'lsa, tarmoqqa ochmaslik uchun
    uvicorn.run(app, host=os.getenv("KIOSK_HOST", "0.0.0.0"), port=8000)
