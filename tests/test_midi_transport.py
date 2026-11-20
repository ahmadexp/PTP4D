"""Transport identity, packet ABI, failures, and virtual CoreMIDI loopback."""
import copy
import ctypes as C
import pathlib
import queue
import struct
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
import midi_transport as midi


def packets(chunks, arm=True):
    raw = bytearray(struct.pack('<I', len(chunks)))
    for chunk in chunks:
        raw.extend(struct.pack('<QH', 0, len(chunk)))
        raw.extend(chunk)
        if arm:
            raw.extend(b'\0' * (-len(raw) % 4))
    return C.create_string_buffer(bytes(raw))


class FakeNative:
    read_type = midi.NativeCoreMIDI.read_type
    notify_type = midi.NativeCoreMIDI.notify_type

    def __init__(self):
        self.records = [dict(serial='chosen', device=10, device_uid=-10,
                             location=1, pairs=1, entity=11, source=12,
                             destination=13, source_uid=-12, destination_uid=-13)]
        self.calls = []

    def inventory(self): return copy.deepcopy(self.records)
    def make_client(self, notify): self.notify = notify; return 20
    def make_input(self, client, callback): self.callback = callback; return 21
    def make_output(self, client): self.calls.append(('output', client)); return 22
    def connect(self, port, source): self.calls.append(('connect', port, source))
    def disconnect(self, port, source): self.calls.append(('disconnect', port, source))
    def dispose_port(self, port): self.calls.append(('dispose_port', port))
    def dispose_client(self, client): self.calls.append(('dispose_client', client))
    def poll(self): pass
    def send(self, *args): self.calls.append(('send', *args))

    def receive(self, data):
        storage = packets([data], arm=sys.platform == 'darwin')
        self.callback(C.addressof(storage), None, None)


class PacketTests(unittest.TestCase):
    def test_variable_packets_and_architecture_padding(self):
        chunks = [b'\xf0\x7dT', bytes(range(256)) * 2, b'\xf7', b'']
        for arm in (True, False):
            with self.subTest(arm=arm):
                storage = packets(chunks, arm)
                self.assertEqual(midi.packet_bytes(C.addressof(storage), arm), b''.join(chunks))

    def test_packet_limits(self):
        storage = C.create_string_buffer(midi.MAX_PACKET_LIST + 20)
        struct.pack_into('<I', storage, 0, 4097)
        with self.assertRaisesRegex(RuntimeError, 'count'):
            midi.packet_bytes(C.addressof(storage))
        struct.pack_into('<I', storage, 0, 1)
        struct.pack_into('<H', storage, 12, 65535)
        with self.assertRaisesRegex(RuntimeError, 'packet'):
            midi.packet_bytes(C.addressof(storage))


class TransportTests(unittest.TestCase):
    def test_platform_selection(self):
        for system, expected in [('darwin', 'coremidi'), ('linux', 'alsa')]:
            with mock.patch.object(midi.sys, 'platform', system):
                self.assertEqual(midi.backend(), expected)
                with self.assertRaises(RuntimeError):
                    midi.backend('alsa' if expected == 'coremidi' else 'coremidi')

    def test_inventory_filters_usb_identity_offline_and_split_entities(self):
        native = midi.NativeCoreMIDI.__new__(midi.NativeCoreMIDI)
        props = {1: dict(offline=1, USBVendorProduct=midi.USB_ID, SerialNumber='old'),
                 2: dict(USBVendorProduct=123, SerialNumber='wrong'),
                 3: dict(USBVendorProduct=midi.USB_ID, SerialNumber='chosen', uniqueID=3),
                 4: dict(USBVendorProduct=midi.USB_ID, SerialNumber='split', uniqueID=4),
                 30: dict(uniqueID=-30), 31: dict(uniqueID=-31)}
        native.properties = props.__getitem__
        native.midi = types.SimpleNamespace(
            MIDIGetNumberOfDevices=lambda: 4, MIDIGetDevice=lambda n: n + 1,
            MIDIDeviceGetNumberOfEntities=lambda d: 2 if d == 4 else 1,
            MIDIDeviceGetEntity=lambda d, n: d * 10 + n,
            MIDIEntityGetNumberOfSources=lambda e: 0 if e == 41 else 1,
            MIDIEntityGetNumberOfDestinations=lambda e: 0 if e == 40 else 1,
            MIDIEntityGetSource=lambda e, n: 30,
            MIDIEntityGetDestination=lambda e, n: 31)
        found = native.inventory()
        self.assertEqual([d['serial'] for d in found], ['chosen', 'split'])
        self.assertEqual(found[0]['source_uid'], -30)
        self.assertNotIn('source', found[1])

    def test_missing_ambiguous_and_unpaired_devices_fail_before_output(self):
        for mode in ('missing', 'duplicate', 'split'):
            native = FakeNative()
            if mode == 'missing': native.records.clear()
            if mode == 'duplicate': native.records *= 2
            if mode == 'split': del native.records[0]['destination']
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                midi.CoreMIDI('chosen', native=native)
            self.assertEqual(native.calls, [('dispose_client', 20)])

    def test_passive_copies_fragments_without_an_output_port(self):
        native = FakeNative()
        transport = midi.CoreMIDI('chosen', receive_only=True, native=native)
        try:
            native.receive(b'\xf0\x7d')
            native.receive(b'TSK\xf7')
            self.assertEqual(transport.read(0), b'\xf0\x7d')
            self.assertEqual(transport.read(0), b'TSK\xf7')
            self.assertEqual(transport.read(0), b'')
            with self.assertRaises(PermissionError): transport.write(b'anything', 1)
        finally:
            transport.close(); transport.close()
        self.assertEqual(native.calls, [('connect', 21, 12), ('disconnect', 21, 12),
                                       ('dispose_port', 21), ('dispose_client', 20)])

    def test_partial_initialization_disposes_owned_resources(self):
        native = FakeNative()
        with mock.patch.object(native, 'make_output', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                midi.CoreMIDI('chosen', native=native)
        self.assertEqual(native.calls, [('dispose_port', 21), ('dispose_client', 20)])

    def test_replacement_or_disappearance_latches_failure(self):
        for change in ('gone', 'endpoint', 'uid', 'duplicate'):
            native = FakeNative()
            transport = midi.CoreMIDI('chosen', native=native)
            original = copy.deepcopy(native.records)
            if change == 'gone': native.records.clear()
            if change == 'endpoint': native.records[0]['source'] += 1
            if change == 'uid': native.records[0]['device_uid'] -= 1
            if change == 'duplicate': native.records *= 2
            try:
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    transport.read(0)
                native.records = original
                with self.assertRaises(RuntimeError): transport.write(b'anything', 1)
                self.assertFalse(any(c[0] == 'send' for c in native.calls))
            finally:
                transport.close()

    def test_setup_notifications_and_overflow_stop_io(self):
        for fault in (1, 3, 7, 'overflow'):
            native = FakeNative()
            transport = midi.CoreMIDI('chosen', native=native)
            try:
                if fault == 'overflow':
                    for _ in range(65): native.receive(b'fragment')
                else:
                    message = C.c_uint32(fault)
                    native.notify(C.addressof(message), None)
                with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                    transport.read(0)
                with self.assertRaises(RuntimeError): transport.write(b'anything', 1)
            finally:
                transport.close()

    def test_output_is_bounded_sysex_and_uses_selected_pair(self):
        native = FakeNative()
        transport = midi.CoreMIDI('chosen', native=native)
        message = b'\xf0\x7dTSK\x03\x20' + b'\x00' * 48 + b'\xf7'
        try:
            for invalid in (b'', message[:-1], message.replace(b'T', b'\x80'),
                            message[:-1] + b'\x00' * 900 + b'\xf7'):
                with self.assertRaises(ValueError): transport.write(invalid, 1)
            with self.assertRaises(TimeoutError): transport.write(message, 0)
            transport.write(message, 1)
            self.assertEqual(native.calls[-1], ('send', 22, 13, message))
        finally:
            transport.close()

    def test_alsa_partial_write_and_timeout(self):
        transport = midi.ALSA.__new__(midi.ALSA)
        transport.fd = 9; transport.receive_only = False
        with mock.patch.object(midi.select, 'select', return_value=([], [9], [])), \
                mock.patch.object(midi.os, 'write', side_effect=[BlockingIOError(), 2, 2]) as write:
            transport.write(b'abcd', 1)
            self.assertEqual([c.args[1] for c in write.call_args_list], [b'abcd', b'abcd', b'cd'])
        with mock.patch.object(midi.os, 'write') as write:
            with self.assertRaises(TimeoutError): transport.write(b'abcd', 0)
            write.assert_not_called()
        transport.receive_only = True
        with self.assertRaises(PermissionError): transport.write(b'abcd', 1)


@unittest.skipUnless(sys.platform == 'darwin', 'CoreMIDI system frameworks require macOS')
class NativeLoopbackTests(unittest.TestCase):
    def test_virtual_source_and_destination_without_usb_devices(self):
        """Exercise the actual ctypes ABI using only temporary virtual endpoints."""
        native = midi.NativeCoreMIDI()
        ref, ptr = C.c_uint32, C.c_void_p
        for name, args in (
            ('MIDISourceCreate', [ref, ptr, C.POINTER(ref)]),
            ('MIDIDestinationCreate', [ref, ptr, native.read_type, ptr, C.POINTER(ref)]),
            ('MIDIReceived', [ref, ptr]), ('MIDIEndpointDispose', [ref])):
            fn = getattr(native.midi, name); fn.restype = C.c_int32; fn.argtypes = args
        received = queue.Queue()
        callback = native.read_type(lambda p, *_: received.put(midi.packet_bytes(p)))
        notify = native.notify_type(lambda *_: None)
        client = native.make_client(notify)
        source, destination = ref(), ref()
        transport = None
        payload = b'\xf0\x7dTSK\x03\x20' + bytes(range(128)) * 3 + b'\xf7'
        try:
            native.check(native.named('PTP4D virtual test source', lambda label:
                native.midi.MIDISourceCreate(client, label, C.byref(source))))
            native.check(native.named('PTP4D virtual test destination', lambda label:
                native.midi.MIDIDestinationCreate(client, label, callback, None, C.byref(destination))))
            record = dict(serial='virtual-test', device=1, device_uid=1, entity=1,
                          source=source.value, destination=destination.value,
                          source_uid=native.properties(source.value)['uniqueID'],
                          destination_uid=native.properties(destination.value)['uniqueID'])
            # Only override discovery: every I/O call uses native virtual refs.
            native.inventory = lambda: [record.copy()]
            transport = midi.CoreMIDI('virtual-test', native=native)
            transport.write(payload, 1)
            self.assertEqual(received.get(timeout=2), payload)
            storage = C.create_string_buffer(1024)
            packet = native.midi.MIDIPacketListInit(storage)
            for n, chunk in enumerate((payload[:3], payload[3:])):
                data = C.create_string_buffer(chunk)
                packet = native.midi.MIDIPacketListAdd(storage, len(storage), packet, n + 1, len(chunk), data)
                self.assertTrue(packet)
            native.check(native.midi.MIDIReceived(source.value, storage))
            combined = b''
            end = time.monotonic() + 2
            while len(combined) < len(payload) and time.monotonic() < end:
                combined += transport.read(max(0, end - time.monotonic()))
            self.assertEqual(combined, payload)
        finally:
            if transport: transport.close()
            for endpoint in (source, destination):
                if endpoint.value: native.midi.MIDIEndpointDispose(endpoint.value)
            native.dispose_client(client)


if __name__ == '__main__':
    unittest.main()
