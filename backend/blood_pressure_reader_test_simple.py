import serial, time, sys, select

# Константы протокола
S, E = b'\x02', b'\x03'
CMDS = {
    'send': S + b'22;;DA' + E + S + b'01;;D7' + E,
    'stat': S + b'18;;DF' + E
}

def parse_bp(data):
    """Парсинг: ищет 'P' и берет 3 блока по 3 цифры."""
    try:
        idx = data.find('P') + 1
        # SYS (верхнее), DIA (нижнее), PULSE
        res = [int(data[idx + i*3 : idx + (i+1)*3]) for i in range(3)]
        return f"SYS={res[0]} DIA={res[1]} PULSE={res[2]}"
    except (ValueError, IndexError):
        return data[:42]

def main():
    ser = serial.Serial("/dev/ttyAMA2", 4800, timeout=0.1)
    print(" '1' + Enter -> Старт | Ctrl+C -> Выход")

    try:
        while True:
            # Читаем ввод пользователя
            if select.select([sys.stdin], [], [], 0)[0]:
                if sys.stdin.readline().strip() == '1':
                    ser.write(CMDS['send'])

            # Читаем данные из порта
            if ser.in_waiting > 0:
                time.sleep(0.1) # Ждем догрузки буфера
                raw = ser.read(ser.in_waiting)
                
                # Логика подтверждения статуса (если пришло '9')
                if len(raw) >= 3 and raw[-3] == 57:
                    ser.write(CMDS['stat'])
                
                txt = raw.decode(errors='ignore').strip()
                if txt:
                    print(parse_bp(txt), flush=True)

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nСтоп.")
    finally:
        ser.close()

if __name__ == "__main__":
    main()