"""Host tools: framing, configuration isolation, and recorded timestamp evidence."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


control = module('control')
peer = module('peer')


class HostTests(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads((ROOT / 'config.example.json').read_text())

    def config(self, settings):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'config.json'
            path.write_text(json.dumps(settings))
            return control.load_config(path)

    def test_example_and_defaults(self):
        self.assertEqual(self.config(self.settings)['dos_prompt'], 'C:\\>')
        for key in ('dos_executable', 'dos_prompt', 'baud'):
            del self.settings[key]
        result = self.config(self.settings)
        self.assertEqual(result['dos_executable'], r'C:\PTP4D.EXE')
        self.assertEqual(result['dos_prompt'], 'C:\\>')
        self.assertEqual(result['baud'], 115200)

    def test_invalid_config_fails_before_ssh(self):
        cases = [[], {}, {**self.settings, 'peer_dir': 'relative'},
                 {**self.settings, 'serial_host': '-oProxyCommand=example'},
                 {**self.settings, 'peer_host': 'two hosts'},
                 {**self.settings, 'dos_executable': None},
                 {**self.settings, 'baud': False}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.config(value)

    def test_remote_paths_and_identity_are_single_arguments(self):
        self.settings['peer_dir'] = "/home/retro/a space's $(literal)"
        self.settings['peer_serial'] = "serial's $(literal)"
        args = shlex.split(control.peer_start_command(self.settings, 80))
        self.assertEqual(args[args.index('--serial') + 1], self.settings['peer_serial'])
        self.assertEqual(args[args.index('--mac') + 1], self.settings['peer_mac'])
        self.assertEqual(args[args.index('--status') + 1], self.settings['peer_dir'] + '/status.json')
        self.assertIn(self.settings['peer_dir'] + '/peer.py', args)
        self.assertIn('--unit=ptp4d-gm', args)

    def test_dos_settings_cannot_rewrite_rpc_source(self):
        self.settings['dos_log_dir'] = "/home/retro/a 'quoted' $(literal) directory"
        with mock.patch.object(control, 'remote', return_value=types.SimpleNamespace(stdout='{}')) as call:
            control.dos(self.settings, 'status')
        host, command, code = call.call_args.args
        namespace = {}
        prefix, rpc = code.split(control.RPC, 1)
        exec(prefix, namespace)
        self.assertEqual(namespace['settings'], self.settings)
        self.assertEqual(namespace['action'], 'status')
        self.assertEqual(rpc, '')
        self.assertEqual(host, self.settings['serial_host'])
        self.assertIn(self.settings['serial_lock'], shlex.split(command))

    def test_mac_identity_validation(self):
        self.assertEqual(peer.mac_address('02:AB:CD:00:00:02'), '02:ab:cd:00:00:02')
        self.assertEqual(peer.mac_address('02abcd000002'), '02:ab:cd:00:00:02')
        for value in ('00:00:00:00:00:00', '01:00:00:00:00:02', 'not a mac',
                      '0200000000  ', '02:00:00:00:00:ZZ'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                peer.mac_address(value)

    def test_midi_fragmentation_realtime_and_corruption(self):
        raw = bytes(range(128, 150))
        encoded = peer.frame(raw)
        parser = peer.Framer()
        received = []
        for byte in encoded:
            received.extend(parser.feed(bytes([byte, 0xF8])))
        self.assertEqual(received, [(3, 0x20, raw)])
        corrupted = bytearray(encoded)
        corrupted[7] ^= 1
        self.assertEqual(list(peer.Framer().feed(corrupted)), [])
        corrupted = bytearray(encoded)
        corrupted[8] = 2
        self.assertEqual(list(peer.Framer().feed(corrupted)), [])
        parser = peer.Framer()
        self.assertEqual(list(parser.feed(b'\xf0' + b'\x00' * 900)), [])
        self.assertEqual(list(parser.feed(encoded)), [(3, 0x20, raw)])


class EvidenceTests(unittest.TestCase):
    def test_hardware_timestamp_evidence(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/analyze.py'),
                                 str(ROOT / 'docs/validation/dos.json'),
                                 str(ROOT / 'docs/validation/grandmaster.jsonl')],
                                capture_output=True, text=True, check=True)
        observed = json.loads(result.stdout)
        recorded = json.loads((ROOT / 'docs/validation/summary.json').read_text())
        for key, value in observed.items():
            with self.subTest(key=key):
                self.assertEqual(value, recorded[key])
        self.assertEqual(observed['records'], 128)
        for key in ('t1_matches', 't4_matches', 'arithmetic_matches'):
            self.assertEqual(observed[key], observed['records'])
        self.assertTrue(observed['dos_stop_verified'])
        self.assertTrue(observed['dos_prompt_returned'])
        self.assertFalse(observed['console_overflow'])

    def test_published_binary_digest(self):
        expected, name = (ROOT / 'bin/SHA256SUMS').read_text().split()
        self.assertEqual(hashlib.sha256((ROOT / 'bin' / name).read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
