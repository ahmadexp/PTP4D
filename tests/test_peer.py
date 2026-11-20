"""Grandmaster lifecycle over a byte transport, with no physical device access."""
import argparse
import contextlib
import io
import json
import pathlib
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
import peer

MAC = bytes.fromhex('020000000002')


def reply(raw, version=3, kind=0x21):
    encoded = bytearray(peer.frame(bytes(raw)))
    encoded[5:7] = bytes([version, kind])
    return bytes(encoded)


def telemetry(mac=MAC, domain=42):
    raw = bytearray(94)
    raw[4:10] = mac; raw[11] = domain
    return reply(raw, 2, 0x10)


class FakeTransport:
    description = {'transport': 'test', 'serial': 'chosen'}

    def __init__(self):
        self.pending = [telemetry()]
        self.requests = []
        self.now = 0
        self.closed = False
        self.on_write = lambda raw, ack: ack
        self.on_idle = lambda: None

    def read(self, timeout):
        self.now += .01 if self.pending else timeout
        if self.pending: return self.pending.pop(0)
        self.on_idle()
        return b''

    def write(self, data, timeout):
        version, kind, raw = next(peer.Framer().feed(data))
        assert (version, kind) == (3, 0x20)
        assert len(raw) == 22 and raw[9:11] == bytes([2, 42]) and raw[16:22] == MAC
        self.requests.append(raw)
        op = raw[8]
        ack = bytearray(32)
        ack[:9] = raw[:9]
        ack[10:12] = bytes([4 if op in (2, 4) else 1, 2])
        struct.pack_into('<I', ack, 16, 17)
        struct.pack_into('<H', ack, 20, 4 if op == 5 else 15)
        ack[22:28] = MAC; ack[28] = 42; ack[29] = 63 if op == 5 else 31
        ack[30] = int(op not in (2, 4)); ack[31] = int(op in (2, 4))
        ack = self.on_write(raw, ack)
        if ack is not None: self.pending.append(reply(ack))

    def close(self): self.closed = True

    @property
    def operations(self): return [r[8] for r in self.requests]


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.output = io.StringIO()
        args = argparse.Namespace(serial='chosen', mac=MAC.hex(':'), transport='auto',
                                  seconds=6, passive=None, status=None)
        self.peer = peer.Peer(args, self.transport)

    def run_peer(self):
        with mock.patch.object(peer.time, 'monotonic', side_effect=lambda: self.transport.now), \
                contextlib.redirect_stdout(self.output):
            self.peer.run()

    @property
    def events(self):
        return [json.loads(line) for line in self.output.getvalue().splitlines()]

    def test_start_renew_stop_and_session_identity(self):
        self.run_peer()
        self.assertEqual(self.transport.operations, [1, 5, 2, 4, 3])
        self.assertEqual([peer.u(r, 4) for r in self.transport.requests], [1, 2, 3, 4, 5])
        self.assertEqual({peer.u(r, 0) for r in self.transport.requests}, {self.peer.nonce})
        self.assertEqual(peer.u(self.transport.requests[1], 12), 4)
        self.assertEqual(peer.u(self.transport.requests[2], 12), 15)
        self.assertEqual(peer.u(self.transport.requests[3], 12), 17)
        self.assertEqual(self.events[-1]['event'], 'stopped')
        self.assertTrue(self.events[-1]['restoration_verified'])
        self.assertTrue(self.transport.closed)

    def test_passive_fragments_never_send_even_stop(self):
        wire = telemetry()
        self.transport.pending = [wire[:5], wire[5:83], wire[83:]]
        self.peer.passive = True; self.peer.args.passive = 1
        self.run_peer()
        self.assertEqual(self.transport.operations, [])
        self.assertEqual(self.events[-1]['event'], 'passive_complete')
        self.assertEqual(self.events[-1]['valid_frames'], 1)
        self.assertEqual(self.events[-1]['commands_sent'], 0)
        with self.assertRaises(PermissionError): self.peer.command(1)
        self.assertTrue(self.transport.closed)

    def test_identity_mismatch_and_missing_crc_telemetry_send_nothing(self):
        bad_crc = bytearray(telemetry()); bad_crc[7] ^= 1
        for wire in (b'', bytes(bad_crc), telemetry(b'\x02\x00\x00\x00\x00\x03'), telemetry(domain=1)):
            for passive in (False, True):
                self.setUp()
                self.transport.pending = [wire]
                self.peer.passive = passive; self.peer.args.passive = 1
                with self.subTest(wire=wire[:10], passive=passive), self.assertRaises(RuntimeError):
                    self.run_peer()
                self.assertEqual(self.transport.operations, [])
                self.assertTrue(self.transport.closed)

    def test_unrelated_ack_fields_are_ignored(self):
        def noise(raw, ack):
            for offset in (0, 4, 8, 22, 28):
                stale = ack.copy(); stale[offset] ^= 1
                self.transport.pending.append(reply(stale))
            broken = bytearray(reply(ack)); broken[7] ^= 1
            self.transport.pending.append(bytes(broken))
            return ack
        self.transport.on_write = noise
        self.run_peer()
        self.assertEqual(self.transport.operations, [1, 5, 2, 4, 3])
        self.assertEqual(len([r for r in self.events if r['event'] == 'ack']), 5)

    def test_occupied_device_is_not_taken_over(self):
        def busy(raw, ack): ack[31] = 1; return ack
        self.transport.on_write = busy
        with self.assertRaisesRegex(RuntimeError, 'active'): self.run_peer()
        self.assertEqual(self.transport.operations, [1])
        self.assertTrue(self.transport.closed)

    def test_bad_rate_ack_never_starts(self):
        def rate(raw, ack):
            if raw[8] == 5: ack[20] = 2
            return ack
        self.transport.on_write = rate
        with self.assertRaisesRegex(RuntimeError, 'rate'): self.run_peer()
        self.assertEqual(self.transport.operations, [1, 5])

    def test_missing_start_ack_still_attempts_stop(self):
        self.transport.on_write = lambda raw, ack: None if raw[8] == 2 else ack
        with self.assertRaisesRegex(TimeoutError, 'operation 2'): self.run_peer()
        self.assertEqual(self.transport.operations, [1, 5, 2, 3])
        self.assertEqual(self.events[-1]['event'], 'stopped')
        self.assertTrue(self.transport.closed)

    def test_wrong_renew_generation_stops(self):
        def stale(raw, ack):
            if raw[8] == 4: ack[16] += 1
            return ack
        self.transport.on_write = stale
        with self.assertRaisesRegex(RuntimeError, 'renewed'): self.run_peer()
        self.assertEqual(self.transport.operations, [1, 5, 2, 4, 3])
        self.assertTrue(self.transport.closed)

    def test_cancel_after_start_checks_stop(self):
        self.transport.on_idle = lambda: setattr(self.peer, 'stop_requested', True)
        self.run_peer()
        self.assertEqual(self.transport.operations, [1, 5, 2, 3])
        self.assertEqual(self.events[-1]['event'], 'stopped')

    def test_disconnection_never_reports_restoration(self):
        def disconnect():
            self.transport.write = mock.Mock(side_effect=RuntimeError('disconnected'))
            raise RuntimeError('disconnected')
        self.transport.on_idle = disconnect
        with self.assertRaisesRegex(RuntimeError, 'disconnected'): self.run_peer()
        self.assertNotIn('stopped', [r['event'] for r in self.events])
        self.assertTrue(self.transport.closed)

    def test_missing_or_wrong_stop_ack_never_reports_restoration(self):
        for fault in ('missing', 'generation', 'profile', 'armed', 'restored'):
            self.setUp()
            def stop(raw, ack):
                if raw[8] == 3:
                    if fault == 'missing': return None
                    offset = {'generation': 16, 'profile': 11, 'armed': 31, 'restored': 30}[fault]
                    ack[offset] ^= 1
                return ack
            self.transport.on_write = stop
            with self.subTest(fault=fault), self.assertRaises((TimeoutError, RuntimeError)):
                self.run_peer()
            self.assertNotIn('stopped', [r['event'] for r in self.events])
            self.assertTrue(self.transport.closed)

    def test_cli_list_never_opens_a_transport(self):
        with mock.patch.object(peer.midi_transport, 'devices', return_value=[]) as devices, \
                mock.patch.object(peer.midi_transport, 'open_transport') as opening, \
                contextlib.redirect_stdout(self.output):
            peer.main(['--list', '--transport', 'coremidi'])
            devices.assert_called_once_with('coremidi'); opening.assert_not_called()

    def test_cli_rejects_invalid_requests_before_opening(self):
        for args in (['--passive', '0'], ['--passive', '61'], ['--seconds', '-1'],
                     ['--list', '--serial', 'chosen'], ['--serial', 'chosen']):
            with self.subTest(args=args), mock.patch.object(peer.midi_transport, 'open_transport') as opening, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                peer.main(args)
            opening.assert_not_called()


if __name__ == '__main__':
    unittest.main()
