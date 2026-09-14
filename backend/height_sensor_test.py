
import serial
import time

# Portni aniqlab oling: /dev/ttyS0 yoki /dev/ttyAMA0
# ls -l /dev/serial0 buyrug'i natijasiga qarab o'zgartiring
SERIAL_PORT = '/dev/ttyAMA0' 
BAUD_RATE = 9600

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
except Exception as e:
    print(f"Portni ochishda xato: {e}")
    exit()

MAX_DISTANCE = 2000 # Misol uchun 2 metr (mm da)

def get_height():
    # 1. So'rov yuborish (Arduino kodingizdagi bilan bir xil)
    address = 0x01
    command = 0x01
    # Checksum hisoblash: (0x55 + 0xAA + 0x01 + 0x01) & 0xFF
    checksum = (0x55 + 0xAA + address + command) & 0xFF
    
    cmd_packet = bytearray([0x55, 0xAA, address, command, checksum])
    
    # Portni tozalab olamiz va so'rov yuboramiz
    ser.reset_input_buffer()
    ser.write(cmd_packet)
    
    # Javob kutish (Arduino'dagi delay(50) o'rniga)
    time.sleep(0.1)
    
    # 2. Javobni o'qish (7 bayt kutamiz)
    if ser.in_waiting >= 7:
        data = ser.read(7)
        
        start_byte = data[0]
        user_addr = data[1]
        resp_addr = data[2]
        resp_cmd = data[3]
        high_data = data[4]
        low_data = data[5]
        resp_checksum = data[6]
        
        # Checksum tekshirish
        expected_checksum = sum(data[:6]) & 0xFF
        
        if resp_checksum == expected_checksum:
            # Masofani hisoblash (mm da)
            distance_mm = (high_data << 8) | low_data
            distance_cm = distance_mm / 10
            
            print(f"Masofa: {distance_cm} cm")
            
            # Balandlikni qaytarish (Sizning kodingiz bo'yicha)
            return (MAX_DISTANCE / 10) - distance_cm
        else:
            print("Xato: Checksum mos kelmadi")
    else:
        print("Xato: Sensordan javob kelmadi")
    
    return None

try:
    print("O'lchash boshlandi...")
    while True:
        height = get_height()
        if height is not None:
            print(f"Hisoblangan balandlik: {height} cm")
        
        time.sleep(0.3) # Har 1 sekundda o'lchash
        
except KeyboardInterrupt:
    ser.close()
    print("\nDastur to'xtatildi")
