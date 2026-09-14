import serial
import time
import sys
import select

STX = 0x02
ETX = 0x03

def cmd_send():
    return bytes([
        STX, ord('2'), ord('2'), ord(';'), ord(';'), ord('D'), ord('A'), ETX,
        STX, ord('0'), ord('1'), ord(';'), ord(';'), ord('D'), ord('7'), ETX
    ])

def cmd_getstatus():
    return bytes([STX, ord('1'), ord('8'), ord(';'), ord(';'), ord('D'), ord('F'), ETX])

def extract_dia_sys_pulse(data: str):
    """
    Arduino logikasi 1:1:
    if(Data.length() == 41){
        DIA = Data.substring(16,19);
        SYS = Data.substring(19,22);
        Pulse = Data.substring(27,30);
        trim + toInt
    }
    """
    if len(data) != 41:
        return None

    try:
        DIA = data[16:19].strip()
        SYS = data[19:22].strip()
        Pulse = data[27:30].strip()

        dia = int(DIA)
        sys_val = int(SYS)
        pulse = int(Pulse)

        return dia, sys_val, pulse
    except ValueError:
        return None


class BPReader:
    def __init__(self, port: str, baud: int = 4800, timeout: float = 0.2):
        self.ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)

    def send_measure_request(self):
        self.ser.write(cmd_send())

    def send_status_request(self):
        self.ser.write(cmd_getstatus())

    def read_like_arduino(self):
        if self.ser.in_waiting <= 0:
            return None

        incoming = bytearray()
        while self.ser.in_waiting > 0:
            b = self.ser.read(1)
            if not b:
                break
            incoming += b
            time.sleep(0.002)

        if len(incoming) >= 3:
            j = incoming[-3]
            if j == 57:  # ASCII '9'
                self.send_status_request()

        return incoming if incoming else None

    def extract_and_print(self, incoming: bytes):
        s = incoming.decode("ascii", errors="ignore").strip()
        if not s:
            return

        # Avval DIA/SYS/Pulse ajratishga urinib ko'ramiz
        result = extract_dia_sys_pulse(s)
        if result:
            dia, sys_val, pulse = result
            print(f"DIA={dia} SYS={sys_val} PULSE={pulse}", flush=True)
        else:
            # bo'lmasa raw holatda chiqaramiz
            print(s[:42], flush=True)


def main():
    PORT = "/dev/ttyAMA2"
    BAUD = 4800

    bp = BPReader(PORT, BAUD)

    print("Tayyor. Konsolda '1' yozib Enter bos -> send() yuboriladi.")
    print("Chiqish: Ctrl+C")

    try:
        while True:
            if select.select([sys.stdin], [], [], 0.0)[0]:
                line = sys.stdin.readline().strip()
                if line and line[0] == '1':
                    bp.send_measure_request()

            pkt = bp.read_like_arduino()
            if pkt:
                bp.extract_and_print(pkt)

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
    finally:
        bp.ser.close()


if __name__ == "__main__":
    main()
