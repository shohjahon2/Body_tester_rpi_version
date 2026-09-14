from smbus2 import SMBus
import time
import numpy as np

ADDR = 0x57
bus = SMBus(1)

FINGER_THRESHOLD = 5000


# ======================
# INIT (FIXED)
# ======================
def init():
    bus.write_byte_data(ADDR, 0x06, 0x40)  # reset
    time.sleep(0.1)

    # FIFO clear (MUHIM!!!)
    bus.write_byte_data(ADDR, 0x02, 0x00)
    bus.write_byte_data(ADDR, 0x03, 0x00)
    bus.write_byte_data(ADDR, 0x04, 0x00)

    bus.write_byte_data(ADDR, 0x06, 0x03)  # SpO2 mode
    bus.write_byte_data(ADDR, 0x07, 0x27)  # config
    bus.write_byte_data(ADDR, 0x09, 0x7F)  # max LED current

init()


# ======================
def read_sample():
    data = bus.read_i2c_block_data(ADDR, 0x05, 4)
    ir = (data[0] << 8) | data[1]
    red = (data[2] << 8) | data[3]
    return ir, red


ir_buf = []
red_buf = []

print("Ishga tushdi...")

while True:
    try:
        ir, red = read_sample()

        # finger detection
        if ir < FINGER_THRESHOLD:
            print("Finger yo'q")
            time.sleep(0.1)
            continue

        ir_buf.append(ir)
        red_buf.append(red)

        if len(ir_buf) > 120:
            ir_buf.pop(0)
            red_buf.pop(0)

            ir_np = np.array(ir_buf)
            red_np = np.array(red_buf)

            ir_dc = np.mean(ir_np)
            red_dc = np.mean(red_np)

            ir_ac = np.std(ir_np)
            red_ac = np.std(red_np)

            R = (red_ac/red_dc) / (ir_ac/ir_dc)
            spo2 = 110 - 25 * R
            spo2 = max(0, min(100, spo2))

            diff = np.diff(ir_np)
            peaks = np.where((diff[:-1] > 0) & (diff[1:] < 0))[0]
            hr = len(peaks) * 50

            print(f"HR: {int(hr)} bpm   SpO2: {spo2:.1f}%")

        time.sleep(0.01)

    except Exception as e:
        print("I2C restart...")
        init()
