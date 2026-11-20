"""Bounded MIDI byte transports. CoreMIDI uses only macOS system frameworks."""
import ctypes as C
import os
import pathlib
import platform
import plistlib
import queue
import select
import sys
import time

USB_ID = (0x0B95 << 16) | 0x1790
MAX_PACKET_LIST = 65536


def backend(name='auto'):
    if name == 'auto':
        name = 'coremidi' if sys.platform == 'darwin' else 'alsa'
    if name not in ('alsa', 'coremidi'):
        raise ValueError('Unknown MIDI transport')
    if name == 'coremidi' and sys.platform != 'darwin':
        raise RuntimeError('CoreMIDI requires macOS')
    if name == 'alsa' and not sys.platform.startswith('linux'):
        raise RuntimeError('ALSA raw MIDI requires Linux; use --transport coremidi on macOS')
    return name


def alsa_devices():
    found = []
    for path in pathlib.Path('/sys/class/sound').glob('midiC*D*'):
        for parent in path.resolve().parents:
            if (parent / 'idVendor').exists():
                try:
                    vid = int((parent / 'idVendor').read_text().strip(), 16)
                    pid = int((parent / 'idProduct').read_text().strip(), 16)
                    serial = (parent / 'serial').read_text().strip()
                except (OSError, ValueError):
                    break
                if (vid << 16) | pid == USB_ID:
                    found.append(dict(serial=serial, path='/dev/snd/' + path.name))
                break
    return found


def choose(devices, serial):
    matches = [d for d in devices if d['serial'] == serial]
    if len(matches) != 1:
        raise RuntimeError(f'Expected exactly one online TimeStick with serial {serial}; found {len(matches)}')
    return matches[0]


class ALSA:
    def __init__(self, serial, receive_only=False):
        self.description = dict(transport='alsa', **choose(alsa_devices(), serial))
        self.receive_only = receive_only
        self.fd = os.open(self.description['path'],
                          (os.O_RDONLY if receive_only else os.O_RDWR) | os.O_NONBLOCK)

    def read(self, timeout):
        if not select.select([self.fd], [], [], max(0, timeout))[0]:
            return b''
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return b''
        if not data:
            raise RuntimeError('MIDI device disconnected')
        return data

    def write(self, data, timeout):
        if self.receive_only:
            raise PermissionError('Receive-only MIDI transport')
        end = time.monotonic() + timeout
        while data:
            remaining = end - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError('MIDI output timeout')
            try:
                count = os.write(self.fd, data)
            except BlockingIOError:
                continue
            if not count:
                raise RuntimeError('MIDI output closed')
            data = data[count:]

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def packet_bytes(address, arm=None):
    """Read Apple's packed(4) MIDI 1.0 list, including variable-size packets.

    The framework owns this pointer only during its callback. ARM aligns the
    next packet to four bytes; Intel advances without padding (MIDIPacketNext).
    Reject oversized lists before copying. No pointer is retained by callers.
    """
    if arm is None:
        arm = platform.machine().lower() in ('arm64', 'aarch64')
    count = C.c_uint32.from_address(address).value
    if count > 4096:
        raise RuntimeError('Oversized CoreMIDI packet count')
    offset = 4
    chunks = []
    for _ in range(count):
        if offset + 10 > MAX_PACKET_LIST:
            raise RuntimeError('Oversized CoreMIDI packet list')
        length = C.c_uint16.from_address(address + offset + 8).value
        if offset + 10 + length > MAX_PACKET_LIST:
            raise RuntimeError('Oversized CoreMIDI packet')
        chunks.append(C.string_at(address + offset + 10, length))
        offset += 10 + length
        if arm:
            offset = (offset + 3) & ~3
    return b''.join(chunks)


class NativeCoreMIDI:
    """Small ctypes binding for the MIDI 1.0 SysEx API used by this firmware."""
    read_type = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_void_p)
    notify_type = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)

    def __init__(self):
        if sys.platform != 'darwin':
            raise RuntimeError('CoreMIDI requires macOS')
        self.midi = C.CDLL('/System/Library/Frameworks/CoreMIDI.framework/CoreMIDI')
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        ref, ptr, size, status = C.c_uint32, C.c_void_p, C.c_ulong, C.c_int32
        for name, result, args in (
            ('MIDIGetNumberOfDevices', size, []), ('MIDIGetDevice', ref, [size]),
            ('MIDIDeviceGetNumberOfEntities', size, [ref]), ('MIDIDeviceGetEntity', ref, [ref, size]),
            ('MIDIEntityGetNumberOfSources', size, [ref]), ('MIDIEntityGetSource', ref, [ref, size]),
            ('MIDIEntityGetNumberOfDestinations', size, [ref]), ('MIDIEntityGetDestination', ref, [ref, size]),
            ('MIDIObjectGetProperties', status, [ref, C.POINTER(ptr), C.c_ubyte]),
            ('MIDIClientCreate', status, [ptr, self.notify_type, ptr, C.POINTER(ref)]),
            ('MIDIInputPortCreate', status, [ref, ptr, self.read_type, ptr, C.POINTER(ref)]),
            ('MIDIOutputPortCreate', status, [ref, ptr, C.POINTER(ref)]),
            ('MIDIPortConnectSource', status, [ref, ref, ptr]),
            ('MIDIPortDisconnectSource', status, [ref, ref]),
            ('MIDIPortDispose', status, [ref]), ('MIDIClientDispose', status, [ref]),
            ('MIDIPacketListInit', ptr, [ptr]),
            ('MIDIPacketListAdd', ptr, [ptr, size, ptr, C.c_uint64, size, ptr]),
            ('MIDISend', status, [ref, ref, ptr]),
        ):
            fn = getattr(self.midi, name); fn.restype = result; fn.argtypes = args
        for name, result, args in (
            ('CFStringCreateWithCString', ptr, [ptr, C.c_char_p, C.c_uint32]),
            ('CFRelease', None, [ptr]),
            ('CFPropertyListCreateData', ptr, [ptr, ptr, C.c_long, size, C.POINTER(ptr)]),
            ('CFDataGetLength', C.c_long, [ptr]), ('CFDataGetBytePtr', ptr, [ptr]),
            ('CFRunLoopRunInMode', C.c_int32, [ptr, C.c_double, C.c_ubyte]),
        ):
            fn = getattr(self.cf, name); fn.restype = result; fn.argtypes = args
        self.default_mode = C.c_void_p.in_dll(self.cf, 'kCFRunLoopDefaultMode').value

    @staticmethod
    def check(status):
        if status:
            raise RuntimeError(f'CoreMIDI returned OSStatus {status}')

    def properties(self, obj):
        props = C.c_void_p()
        self.check(self.midi.MIDIObjectGetProperties(obj, C.byref(props), False))
        data = None
        try:
            data = self.cf.CFPropertyListCreateData(None, props, 100, 0, None)
            if not data:
                raise RuntimeError('Cannot serialize CoreMIDI properties')
            length = self.cf.CFDataGetLength(data)
            if length < 0 or length > 1048576:
                raise RuntimeError('Oversized CoreMIDI properties')
            return plistlib.loads(C.string_at(self.cf.CFDataGetBytePtr(data), length))
        finally:
            if data: self.cf.CFRelease(data)
            if props: self.cf.CFRelease(props)

    def inventory(self):
        found = []
        for index in range(self.midi.MIDIGetNumberOfDevices()):
            device = self.midi.MIDIGetDevice(index)
            props = self.properties(device)
            if props.get('offline', 0) or props.get('USBVendorProduct') != USB_ID:
                continue
            serial = props.get('SerialNumber')
            if not isinstance(serial, str) or not serial:
                continue  # Display names are never a substitute for USB serial.
            pairs = []
            for n in range(self.midi.MIDIDeviceGetNumberOfEntities(device)):
                entity = self.midi.MIDIDeviceGetEntity(device, n)
                inputs = self.midi.MIDIEntityGetNumberOfSources(entity)
                outputs = self.midi.MIDIEntityGetNumberOfDestinations(entity)
                if inputs or outputs:
                    pairs.append((entity, inputs, outputs))
            record = dict(serial=serial, device=device, device_uid=props.get('uniqueID'),
                          location=props.get('USBLocationID'), pairs=len(pairs))
            if len(pairs) == 1 and pairs[0][1:] == (1, 1):
                entity = pairs[0][0]
                source = self.midi.MIDIEntityGetSource(entity, 0)
                destination = self.midi.MIDIEntityGetDestination(entity, 0)
                record.update(entity=entity, source=source, destination=destination,
                              source_uid=self.properties(source).get('uniqueID'),
                              destination_uid=self.properties(destination).get('uniqueID'))
            found.append(record)
        return found

    def named(self, name, fn, *args):
        label = self.cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
        if not label:
            raise RuntimeError('Cannot allocate CoreMIDI client name')
        try:
            return fn(label, *args)
        finally:
            self.cf.CFRelease(label)

    def make_client(self, notify):
        out = C.c_uint32()
        status = self.named('PTP4D', self.midi.MIDIClientCreate, notify, None, C.byref(out))
        if status:
            raise RuntimeError(f'Cannot open CoreMIDI client (OSStatus {status}); '
                               'no MIDI ports opened. Exit and retry the command.')
        return out.value

    def make_input(self, client, callback):
        out = C.c_uint32()
        self.check(self.named('TimeStick input', lambda label: self.midi.MIDIInputPortCreate(
            client, label, callback, None, C.byref(out))))
        return out.value

    def make_output(self, client):
        out = C.c_uint32()
        self.check(self.named('TimeStick output', lambda label: self.midi.MIDIOutputPortCreate(
            client, label, C.byref(out))))
        return out.value

    def connect(self, port, source):
        self.check(self.midi.MIDIPortConnectSource(port, source, None))

    def disconnect(self, port, source):
        self.midi.MIDIPortDisconnectSource(port, source)

    def dispose_port(self, port):
        self.midi.MIDIPortDispose(port)

    def dispose_client(self, client):
        self.midi.MIDIClientDispose(client)

    def poll(self):
        self.cf.CFRunLoopRunInMode(self.default_mode, 0.0, True)

    def send(self, port, destination, data):
        storage = C.create_string_buffer(len(data) + 64)
        payload = C.create_string_buffer(data)
        packet = self.midi.MIDIPacketListInit(storage)
        if not self.midi.MIDIPacketListAdd(storage, len(storage), packet, 0, len(data), payload):
            raise RuntimeError('Cannot construct CoreMIDI packet list')
        self.check(self.midi.MIDISend(port, destination, storage))


class CoreMIDI:
    def __init__(self, serial, receive_only=False, native=None):
        self.native = native or NativeCoreMIDI()
        self.receive_only = receive_only
        self.client = self.input = self.output = 0
        self.connected = self.bound = self.closed = False
        self.failure = None
        self.incoming = queue.Queue(maxsize=64)
        self.read_callback = self.native.read_type(self._receive)
        self.notify_callback = self.native.notify_type(self._notify)
        try:
            self.client = self.native.make_client(self.notify_callback)
            self.record = choose(self.native.inventory(), serial)
            if not all(self.record.get(k) for k in ('source', 'destination', 'source_uid', 'destination_uid', 'device_uid')):
                raise RuntimeError('TimeStick must expose one identified input/output pair on the same entity')
            self.description = dict(transport='coremidi', serial=serial,
                                    source_uid=self.record['source_uid'],
                                    destination_uid=self.record['destination_uid'])
            self.input = self.native.make_input(self.client, self.read_callback)
            if not receive_only:
                self.output = self.native.make_output(self.client)
            self.native.connect(self.input, self.record['source'])
            self.connected = True
            # Drain notifications created by our own port setup before binding.
            self.native.poll()
            self.bound = True
            self._health()
        except BaseException:
            self.close()
            raise

    def _notify(self, message, _context):
        try:
            kind = C.c_uint32.from_address(message).value
            # Any setup/removal/I/O change invalidates this connection. Never
            # rebind automatically, even if a replug reuses an endpoint's UID.
            if self.bound and not self.closed and kind in (1, 3, 7):
                self.failure = 'MIDI setup changed; stop and explicitly reopen the selected TimeStick'
        except Exception as exc:
            self.failure = f'CoreMIDI notification failed: {exc}'

    def _receive(self, packets, _context, _source):
        if self.closed:
            return
        try:
            data = packet_bytes(packets)
            if data:
                self.incoming.put_nowait(data)
        except queue.Full:
            self.failure = 'CoreMIDI input overflow; buffered telemetry is no longer trustworthy'
        except Exception as exc:
            self.failure = f'CoreMIDI receive failed: {exc}'

    def _health(self):
        if self.closed:
            raise RuntimeError('CoreMIDI transport closed')
        self.native.poll()
        if self.failure:
            raise RuntimeError(self.failure)
        # Properties plus endpoint refs detect disappearance, replacement,
        # serial ambiguity, and changes within the selected MIDI entity.
        try:
            if choose(self.native.inventory(), self.record['serial']) != self.record:
                raise RuntimeError('Selected TimeStick identity or endpoints changed')
        except Exception as exc:
            self.failure = str(exc)
            raise

    def read(self, timeout):
        end = time.monotonic() + max(0, timeout)
        while True:
            self._health()
            try:
                data = self.incoming.get(timeout=max(0, min(0.05, end - time.monotonic())))
            except queue.Empty:
                if time.monotonic() >= end:
                    return b''
            else:
                self._health()
                return data

    def write(self, data, timeout):
        if self.receive_only:
            raise PermissionError('Receive-only MIDI transport')
        self._health()
        if timeout <= 0:
            raise TimeoutError('MIDI output timeout')
        if not (12 <= len(data) <= 848 and data.startswith(b'\xf0\x7dTSK') and
                data[-1] == 0xf7 and all(b < 128 for b in data[1:-1])):
            raise ValueError('Expected a bounded TimeStick SysEx message')
        self.native.send(self.output, self.record['destination'], data)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.connected:
            self.native.disconnect(self.input, self.record['source'])
        if self.input:
            self.native.dispose_port(self.input)
        if self.output:
            self.native.dispose_port(self.output)
        if self.client:
            self.native.dispose_client(self.client)


def devices(name='auto'):
    name = backend(name)
    if name == 'alsa':
        return [dict(transport=name, **d) for d in alsa_devices()]
    native = NativeCoreMIDI()
    callback = native.notify_type(lambda *_: None)
    client = native.make_client(callback)
    try:
        return [dict(transport=name, **d) for d in native.inventory()]
    finally:
        native.dispose_client(client)


def open_transport(serial, name='auto', receive_only=False):
    return (CoreMIDI if backend(name) == 'coremidi' else ALSA)(serial, receive_only)
