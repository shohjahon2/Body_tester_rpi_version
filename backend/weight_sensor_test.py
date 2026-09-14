# main.py
from hx711_weight_sensor import HX711  # Импортируем класс из созданного файла
import time

# Создаем объект
# Указываем пины: DAT=27, CLK=17
hx = HX711(dat_pin=27, clk_pin=17, factor=14950.0)

# Выполняем тарирование (обнуление веса при старте)
print("Настройка весов...")
hx.tare()

try:
    while True:
        # Получаем вес
        w = hx.get_weight()
        print(f"Вес: {w:.3f} кг", end='\r')
        time.sleep(0.2)
finally:
    hx.cleanup() # Освобождаем GPIO