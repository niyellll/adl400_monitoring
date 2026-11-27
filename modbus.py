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
    "i_a": (0x0064, 1, 0.01, False),    # arus fasa A (A), teruji Slave 31
    "i_b": (0x0065, 1, 0.01, False),
    "i_c": (0x0066, 1, 0.01, False),
    "kw": (0x006A, 1, 0.001, True),     # daya aktif total (kW), teruji
    "pf": (0x0076, 1, 0.001, True),     # faktor daya total, teruji
}


# Map ADL200 menurut manual Acrel (1 fase).
# Field tidak tersedia pada satu fase HARUS None, bukan disimulasikan.
ADL200_FIELDS = {
    "kwh": (0x0000, 2, 0.01, False),
    "v_a": (0x000B, 1, 0.1, False),
    "i_a": (0x000C, 1, 0.01, False),
    "kw": (0x000D, 1, 0.001, True),
    "pf": (0x0010, 1, 0.001, True),
}

METER_MODELS = ("ADL200", "ADL400", "ADL400-D")
MODEL_FIELDS = {
    "ADL200": ADL200_FIELDS,
    "ADL400": FIELDS,
    "ADL400-D": FIELDS,
}
MODEL_PHASES = {"ADL200": 1, "ADL400": 3, "ADL400-D": 3}


def fields_for(model):
    """Only supported models are allowed. Unknown register maps must not be guessed."""
    if model not in MODEL_FIELDS:
        raise ValueError(f"Model meter tidak dikenal: {model!r}")
    return MODEL_FIELDS[model]


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
    """Modbus TCP client for an RS485 gateway in TCP/RTU conversion mode.

    Each response must match the request (transaction, unit, function, length).
    Invalid or truncated packets must never be decoded as meter readings.
    """

    def __init__(self, host, port=502, timeout=3.0):
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        self.sock.settimeout(timeout)
        self.tid = 0

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
            except (socket.timeout, OSError) as exc:
                raise ModbusError(f"koneksi TCP gagal saat membaca respons: {exc}") from exc
            if not chunk:
                raise ModbusError("koneksi TCP terputus sebelum respons lengkap")
            buf += chunk
        return buf

    def read_holding(self, slave, addr, count):
        if not (isinstance(slave, int) and 1 <= slave <= 247):
            raise ValueError("slave harus integer 1..247")
        if not (isinstance(addr, int) and 0 <= addr <= 0xFFFF):
            raise ValueError("alamat register tidak valid")
        if not (isinstance(count, int) and 1 <= count <= 125
                and addr + count <= 0x10000):
            raise ValueError("jumlah/alamat register Modbus tidak valid")

        self.tid = (self.tid + 1) & 0xFFFF
        req = struct.pack(">HHHBBHH", self.tid, 0, 6, slave, 3, addr, count)
        try:
            self.sock.sendall(req)
        except OSError as exc:
            raise ModbusError(f"gagal mengirim permintaan TCP: {exc}") from exc

        # Modbus TCP MBAP: transaction(2), protocol(2), length(2), unit(1).
        header = self._recv(7)
        response_tid, protocol, length, unit = struct.unpack(">HHHB", header)
        if response_tid != self.tid:
            raise ModbusError("transaction ID respons tidak cocok")
        if protocol != 0:
            raise ModbusError("protocol ID respons bukan Modbus TCP")
        if unit != slave:
            raise ModbusError(f"slave respons {unit}, diharapkan {slave}")
        if not 3 <= length <= 253:
            raise ModbusError(f"panjang frame Modbus tidak valid: {length}")

        pdu = self._recv(length - 1)
        function = pdu[0]
        if function == 0x83:
            if len(pdu) != 2:
                raise ModbusError("panjang exception Modbus tidak valid")
            raise ModbusError(f"slave {slave}: exception code {pdu[1]}")
        if function != 0x03:
            raise ModbusError(f"function code tidak cocok: 0x{function:02X}")
        expected_bytes = 2 * count
        if len(pdu) != 2 + expected_bytes or pdu[1] != expected_bytes:
            raise ModbusError(
                f"ukuran data register tidak cocok: {len(pdu) - 2} byte, "
                f"diharapkan {expected_bytes}"
            )
        return list(struct.unpack(">" + "H" * count, pdu[2:]))

    def close(self):
        self.sock.close()


def open_client(settings):
    """Buat klien sesuai pengaturan (dict dari tabel settings)."""
    if settings.get("conn_type") == "tcp":
        return TCPClient(settings["host"], int(settings["tcp_port"]))
    return RTUClient(settings["serial_port"], int(settings["baud"]),
                     settings.get("parity", "N"))


def read_meter(client, slave, model="ADL400-D"):
    """Baca meter dengan peta register khusus model.

    Default ADL400-D menjaga kompatibilitas dengan pembacaan COM10 sebelumnya.
    ADL400 menggunakan map keluarga ADL400, wajib cocokkan dengan manual unit.
    """
    out = {"kwh": None, "v_a": None, "v_b": None, "v_c": None,
           "i_a": None, "i_b": None, "i_c": None, "kw": None, "pf": None}
    for name, (addr, count, scale, signed) in fields_for(model).items():
        regs = client.read_holding(slave, addr, count)
        raw = (regs[0] << 16 | regs[1]) if count == 2 else regs[0]
        if signed:
            bits = 16 * count
            if raw >= 1 << (bits - 1):
                raw -= 1 << bits
        out[name] = round(raw * scale, 4)
    return out
