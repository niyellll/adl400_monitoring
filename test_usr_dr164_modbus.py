"""Hardware-free tests for USR-DR164 commissioning and strict Modbus TCP."""
import math
import struct
import unittest
from unittest.mock import patch

import modbus
import usr_dr164_modbus


def reply(pdu, tid=1, unit=39, protocol=0):
    return struct.pack(">HHHB", tid, protocol, 1 + len(pdu), unit) + pdu


class FragmentingSocket:
    def __init__(self, packet, chunk_size=3):
        self.buffer = packet
        self.chunk_size = chunk_size
        self.sent = []
        self.timeout = None
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, request):
        self.sent.append(request)

    def recv(self, n):
        if not self.buffer:
            return b""
        take = min(n, self.chunk_size, len(self.buffer))
        out, self.buffer = self.buffer[:take], self.buffer[take:]
        return out

    def close(self):
        self.closed = True


def read_with(packet, count=2):
    fake = FragmentingSocket(packet)
    with patch.object(modbus.socket, "create_connection", return_value=fake):
        client = modbus.TCPClient("192.168.1.80", 8899)
        try:
            return client.read_holding(39, 0, count), fake
        finally:
            client.close()


class ModbusTcpValidationTests(unittest.TestCase):
    def test_valid_fragmented_response_and_correct_request(self):
        regs, fake = read_with(reply(b"\x03\x04\x00\x01\x00\x64"))
        self.assertEqual(regs, [1, 100])
        self.assertEqual(
            fake.sent[0],
            struct.pack(">HHHBBHH", 1, 0, 6, 39, 3, 0, 2),
        )
        self.assertTrue(fake.closed)

    def test_transaction_mismatch_is_rejected(self):
        with self.assertRaisesRegex(modbus.ModbusError, "transaction"):
            read_with(reply(b"\x03\x04\x00\x01\x00\x64", tid=2))

    def test_wrong_meter_is_rejected(self):
        with self.assertRaisesRegex(modbus.ModbusError, "slave respons"):
            read_with(reply(b"\x03\x04\x00\x01\x00\x64", unit=31))

    def test_wrong_protocol_is_rejected(self):
        with self.assertRaisesRegex(modbus.ModbusError, "protocol"):
            read_with(reply(b"\x03\x04\x00\x01\x00\x64", protocol=1))

    def test_wrong_function_is_rejected(self):
        with self.assertRaisesRegex(modbus.ModbusError, "function"):
            read_with(reply(b"\x04\x04\x00\x01\x00\x64"))

    def test_wrong_register_count_is_rejected(self):
        with self.assertRaisesRegex(modbus.ModbusError, "ukuran data"):
            read_with(reply(b"\x03\x02\x00\x64"), count=2)

    def test_incomplete_packet_is_rejected(self):
        with self.assertRaisesRegex(modbus.ModbusError, "terputus"):
            read_with(reply(b"\x03\x04\x00\x01\x00\x64")[:-2])

    def test_exception_is_rejected(self):
        with self.assertRaisesRegex(modbus.ModbusError, "exception code 2"):
            read_with(reply(b"\x83\x02"), count=2)

    def test_invalid_request_does_not_send_bytes(self):
        fake = FragmentingSocket(b"")
        with patch.object(modbus.socket, "create_connection", return_value=fake):
            client = modbus.TCPClient("192.168.1.80", 8899)
            try:
                with self.assertRaises(ValueError):
                    client.read_holding(0, 0, 2)
                with self.assertRaises(ValueError):
                    client.read_holding(39, 0, 126)
                self.assertFalse(fake.sent)
            finally:
                client.close()


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.closed = False

    def read_holding(self, slave, addr, count):
        self.calls.append((slave, addr, count))
        if (addr, count) == (0x0000, 2):
            return [0, 32148]  # candidate kWh: 321.48
        if (addr, count) == (0x0061, 1):
            return [2301]  # candidate V_A: 230.1
        raise AssertionError(f"unexpected address: {addr}")

    def close(self):
        self.closed = True


class ReadOnlyGatewayTests(unittest.TestCase):
    def test_probe_reads_only_two_register_fields_without_db(self):
        fake = FakeGateway()
        with patch.object(usr_dr164_modbus.modbus, "TCPClient", return_value=fake):
            res = usr_dr164_modbus.run("192.168.1.80", 8899, 39, "ADL400", 3)
        self.assertEqual(res["candidate"]["kwh"], 321.48)
        self.assertEqual(res["candidate"]["v_a"], 230.1)
        self.assertEqual(fake.calls, [(39, 0x0000, 2), (39, 0x0061, 1)])
        self.assertFalse(res["saved_to_database"])
        self.assertTrue(fake.closed)

    def test_failed_probe_closes_connection(self):
        fake = FakeGateway()
        def fail(*args):
            raise modbus.ModbusError("no response")
        fake.read_holding = fail
        with patch.object(usr_dr164_modbus.modbus, "TCPClient", return_value=fake):
            with self.assertRaises(modbus.ModbusError):
                usr_dr164_modbus.run("192.168.1.80", 8899, 39, "ADL400", 3)
        self.assertTrue(fake.closed)

    def test_reject_nonfinite_or_impossible_values(self):
        for invalid in (math.nan, math.inf, -1, 1e13):
            with self.assertRaises(ValueError):
                usr_dr164_modbus.validate_candidate({"kwh": invalid})


if __name__ == "__main__":
    unittest.main()
