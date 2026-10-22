"""Klien Modbus sederhana (RTU via serial & TCP via gateway) + pembaca meter Acrel ADL400.

PENTING: alamat register di FIELDS di bawah harus DICEK dengan manual Modbus
ADL400 yang kamu pakai (bisa beda antar versi/firmware). Gunakan
`python collector.py --probe 1 0 130` untuk dump register mentah lalu
cocokkan dengan tabel di manual.
"""
import socket
import struct

import serial  # pyserial


class ModbusError(Exception):
    pass


# --------------------------------------------------------------------------
# Peta register ADL400  -> (alamat, jumlah_register, skala, signed)
# Nilai 32-bit dibaca big-endian (word tinggi dulu).
# >>> VERIFIKASI semua alamat & skala ini dengan manual meter kamu! <<<
# --------------------------------------------------------------------------
FIELDS = {
    "kwh": (0x0000, 2, 0.01, False),    # total energi aktif (kWh)
    "v_a": (0x0061, 1, 0.1, False),     # tegangan fasa A (V)
    "v_b": (0x0062, 1, 0.1, False),
    "v_c": (0x0063, 1, 0.1, False),
    "i_a": (0x0064, 1, 0.001, False),   # arus fasa A (A)
    "i_b": (0x0065, 1, 0.001, False),
    "i_c": (0x0066, 1, 0.001, False),
    "kw": (0x0067, 2, 0.001, True),     # daya aktif total (kW)
    "pf": (0x006B, 1, 0.001, True),     # faktor daya total
}


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


class RTUClient:
    """Modbus RTU lewat port serial (konverter RS485-USB)."""

    def __init__(self, port, baud=9600, parity="N", timeout=1.0):
        self.ser = serial.Serial(port, baud, bytesize=8, parity=parity,
                                 stopbits=1, timeout=timeout)

    def read_holding(self, slave, addr, count):
        req = struct.pack(">BBHH", slave, 3, addr, count)
        req += crc16(req)
        self.ser.reset_input_buffer()
        self.ser.write(req)
        resp = self.ser.read(5 + 2 * count)
        if len(resp) < 5:
            raise ModbusError(f"slave {slave}: tidak ada respon")
        if resp[-2:] != crc16(resp[:-2]):
            raise ModbusError(f"slave {slave}: CRC salah")
        if resp[1] & 0x80:
            raise ModbusError(f"slave {slave}: exception code {resp[2]}")
        if len(resp) < 5 + 2 * count:
            raise ModbusError(f"slave {slave}: respon terpotong")
        return list(struct.unpack(">" + "H" * count, resp[3:3 + 2 * count]))

    def close(self):
        self.ser.close()


class TCPClient:
    """Modbus TCP, untuk gateway RS485-Ethernet/WiFi (mode Modbus TCP)."""

    def __init__(self, host, port=502, timeout=2.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.tid = 0

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ModbusError("koneksi TCP terputus")
            buf += chunk
        return buf

    def read_holding(self, slave, addr, count):
        self.tid = (self.tid + 1) & 0xFFFF
        req = struct.pack(">HHHBBHH", self.tid, 0, 6, slave, 3, addr, count)
        self.sock.sendall(req)
        hdr = self._recv(9)  # MBAP(7) + function + byte count / exception
        if hdr[7] & 0x80:
            raise ModbusError(f"slave {slave}: exception code {hdr[8]}")
        data = self._recv(hdr[8])
        return list(struct.unpack(">" + "H" * (len(data) // 2), data))

    def close(self):
        self.sock.close()


def open_client(settings):
    """Buat klien sesuai pengaturan (dict dari tabel settings)."""
    if settings.get("conn_type") == "tcp":
        return TCPClient(settings["host"], int(settings["tcp_port"]))
    return RTUClient(settings["serial_port"], int(settings["baud"]),
                     settings.get("parity", "N"))


def read_meter(client, slave):
    """Baca semua field satu meter -> dict angka."""
    out = {}
    for name, (addr, count, scale, signed) in FIELDS.items():
        regs = client.read_holding(slave, addr, count)
        raw = (regs[0] << 16 | regs[1]) if count == 2 else regs[0]
        if signed:
            bits = 16 * count
            if raw >= 1 << (bits - 1):
                raw -= 1 << bits
        out[name] = round(raw * scale, 4)
    return out
