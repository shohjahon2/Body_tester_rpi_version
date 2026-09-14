from smbus2 import SMBus
import time

# MLX90614 ning standart manzili 0x5a
address = 0x5a
bus = SMBus(1) # Raspberry Pi 5-da I2C-1 ishlatiladi

def read_temp(reg):
    # I2C orqali 2 bayt ma'lumot o'qish
    data = bus.read_word_data(address, reg)
    # Formulasi: (data * 0.02) - 273.15
    temp = (data * 0.02) - 273.15
    return temp

try:
    while True:
        ambient_temp = read_temp(0x06) # Atrof-muhit
        object_temp = read_temp(0x07)  # Obyekt harorati
        
        print(f"Atrof: {ambient_temp:.2f}°C | Obyekt: {object_temp:.2f}°C")
        time.sleep(1)
except KeyboardInterrupt:
    print("To'xtatildi")
finally:
    bus.close()
