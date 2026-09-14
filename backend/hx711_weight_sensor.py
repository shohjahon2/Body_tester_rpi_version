import gpiod
import time

class HX711:
    def __init__(self, dat_pin=27, clk_pin=17, chip_path='/dev/gpiochip4', factor=14950.0):
        try:
            self.chip = gpiod.Chip(chip_path)
        except FileNotFoundError:
            self.chip = gpiod.Chip('/dev/gpiochip0')

        self.dat_pin = dat_pin
        self.clk_pin = clk_pin
        self.factor = factor
        self.offset = 0

        # Настройка DAT как вход
        self.dat_line = self.chip.request_lines(
            config={
                self.dat_pin: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT
                )
            }
        )
        
        # Настройка CLK как выход с начальным значением LOW (INACTIVE)
        self.clk_line = self.chip.request_lines(
            config={
                self.clk_pin: gpiod.LineSettings(
                    direction=gpiod.line.Direction.OUTPUT,
                    output_value=gpiod.line.Value.INACTIVE # Вместо 0
                )
            }
        )

    def read_raw(self):
        # Ждем, пока датчик будет готов (DAT перейдет в LOW/INACTIVE)
        timeout = time.time() + 1
        while self.dat_line.get_value(self.dat_pin) == gpiod.line.Value.ACTIVE:
            if time.time() > timeout:
                return 0

        val = 0
        for _ in range(24):
            # Подаем HIGH на CLK
            self.clk_line.set_value(self.clk_pin, gpiod.line.Value.ACTIVE)
            
            # Читаем бит
            if self.dat_line.get_value(self.dat_pin) == gpiod.line.Value.ACTIVE:
                val = (val << 1) | 1
            else:
                val = (val << 1) | 0
            
            # Подаем LOW на CLK
            self.clk_line.set_value(self.clk_pin, gpiod.line.Value.INACTIVE)

        # 25-й импульс (Gain 128)
        self.clk_line.set_value(self.clk_pin, gpiod.line.Value.ACTIVE)
        self.clk_line.set_value(self.clk_pin, gpiod.line.Value.INACTIVE)

        # Обработка отрицательных чисел
        return val - 0x1000000 if val & 0x800000 else val

    def tare(self, times=10):
        total = 0
        for _ in range(times):
            total += self.read_raw()
        self.offset = total / times

    def get_weight(self):
        val = self.read_raw()
        return (val - self.offset) / self.factor

    def cleanup(self):
        self.dat_line.release()
        self.clk_line.release()
        self.chip.close()