import gpiod
import time

# Pinlarni belgilash (BCM raqamlari)
DAT_PIN = 27
CLK_PIN = 17

# GPIO chipini ochish (Pi 5 da odatda gpiochip4)
chip = gpiod.Chip('gpiochip4')

# Pinlarni sozlash
dat_line = chip.get_line(DAT_PIN)
clk_line = chip.get_line(CLK_PIN)

dat_line.request(consumer="HX711", type=gpiod.LINE_REQ_DIR_IN)
clk_line.request(consumer="HX711", type=gpiod.LINE_REQ_DIR_OUT)

def read_hx711():
    count = 0
    # HX711 tayyor bo'lishini kutish (Data pin LOW bo'lishi kerak)
    while dat_line.get_value() != 0:
        pass

    # 24 bit ma'lumotni o'qish
    for i in range(24):
        clk_line.set_value(1)
        count = count << 1
        clk_line.set_value(0)
        if dat_line.get_value():
            count += 1

    # Oxirgi impuls (Gain sozlamasi uchun)
    clk_line.set_value(1)
    clk_line.set_value(0)

    # 24-bitli sonni 2-to'ldiruvchi (signed int) holatiga keltirish
    if count & 0x800000:
        count -= 0x1000000

    return count

print("Tarozi ishga tushdi. Nolga sozlanmoqda...")
offset = read_hx711() # Dastlabki qiymatni (tare) olish

try:
    while True:
        raw_value = read_hx711()
        weight = (raw_value - offset)/14950
        # Bu yerda 'weight'ni kalibrovka koeffitsiyentiga bo'lish kerak
        print(f"Xom qiymat: {weight}")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nTo'xtatildi.")
finally:
    dat_line.release()
    clk_line.release()
