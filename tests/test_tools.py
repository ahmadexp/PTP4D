"""Host tools: framing, configuration isolation, and recorded timestamp evidence."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import pathlib
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


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
    def test_full_servo_timestamp_evidence_and_metrics(self):
        from servo_metrics import summarize
        folder = ROOT / 'docs/validation/servo-long-20261120'
        summary = json.loads((folder / 'summary.json').read_text())
        comparison = json.loads((folder / 'comparison.json').read_text())
        plan = json.loads((folder / 'plan.json').read_text())
        self.assertEqual({t['servo'] for t in summary['trials']},
                         {'PI', 'HOST_PI', 'AUTO_PI', 'LINREG', 'KALMAN', 'PLLFLL'})
        with (folder / 'exchanges.csv').open() as stream:
            csv_rows = list(csv.DictReader(stream))
        self.assertEqual(len(csv_rows), sum(t['exchanges'] for t in summary['trials']))
        for trial in summary['trials']:
            name = trial['servo']
            with self.subTest(servo=name):
                path = folder / name.lower()
                result = subprocess.run([sys.executable, str(ROOT / 'tools/analyze.py'),
                                         str(path / 'dos.json'), str(path / 'grandmaster.jsonl')],
                                        capture_output=True, text=True, check=True)
                observed = json.loads(result.stdout)
                analysis = json.loads((path / 'analysis.json').read_text())
                for key, value in observed.items():
                    self.assertEqual(value, analysis[key])
                    self.assertEqual(value, trial[key])
                count = trial['exchanges']
                self.assertEqual(trial['requested_seconds'], 600)
                if trial['completed_planned_duration']:
                    self.assertGreater(count, 2280)
                    self.assertGreater(trial['capture_span_seconds'], 595)
                    self.assertFalse(trial['forced_escape'])
                    self.assertEqual(trial['gm_exit'], 0)
                else:
                    self.assertEqual(name, 'LINREG')
                    self.assertGreater(count, 1200)
                    self.assertGreater(trial['capture_span_seconds'], 300)
                    self.assertTrue(trial['forced_escape'])
                    self.assertIsNone(trial['gm_exit'])
                for key in ('records', 't1_matches', 't4_matches', 'arithmetic_matches'):
                    self.assertEqual(observed[key], count)
                self.assertTrue(observed['dos_stop_verified'] and observed['dos_prompt_returned'] and trial['gm_stopped'])
                self.assertFalse(observed['console_overflow'] or observed['grandmaster_timestamp_errors'])
                rows = analysis['rows']
                for a, b in zip(rows, rows[1:]):
                    self.assertEqual((b['sync'] - a['sync']) & 65535, 1)
                    self.assertEqual((b['delay_sequence'] - a['delay_sequence']) & 65535, 1)
                    self.assertLessEqual(b['t_ns'][0] - a['t_ns'][0], 375000000)
                logs = [json.loads(s) for s in (path / 'grandmaster.jsonl').read_text().splitlines()]
                self.assertEqual(logs[-1]['event'], 'stopped')
                self.assertTrue(logs[-1]['restoration_verified'])
                generations = [r['generation'] for r in logs if r['event'] == 'started']
                self.assertEqual(len(generations), 1)
                active = [r['grandmaster'] for r in logs if 'grandmaster' in r and r['grandmaster']['generation'] == generations[0]]
                self.assertTrue(active)
                self.assertTrue(all(not r['timestamp_errors'] and not r['error'] for r in active))
                t1 = {(r['sync_sequence'], r['t1'][0] * 10**9 + r['t1'][1]) for r in active if r['flags'] & 4}
                t4 = {(r['delay_sequence'], r['t4'][0] * 10**9 + r['t4'][1]) for r in active if r['flags'] & 8}
                self.assertTrue(all((r['sync'], r['t_ns'][0]) in t1 and (r['delay_sequence'], r['t_ns'][3]) in t4 for r in rows))
                self.assertEqual(trial['active_generation_t1_matches'], count)
                self.assertEqual(trial['active_generation_t4_matches'], count)
                derived = summarize(rows, plan['settling_band_ns'], plan['settling_dwell_seconds'], plan['stability_window_seconds'])
                recorded = next(t for t in comparison['trials'] if t['servo'] == name)
                for key, value in derived.items():
                    if isinstance(value, float):
                        self.assertTrue(math.isclose(value, recorded[key], rel_tol=1e-12, abs_tol=1e-12), key)
                    else:
                        self.assertEqual(value, recorded[key], key)
                exported = [r for r in csv_rows if r['servo'] == name]
                self.assertEqual(len(exported), count)
                for index, (record, row) in enumerate(zip(exported, rows), 1):
                    self.assertEqual(int(record['exchange']), index)
                    self.assertEqual(int(record['sync']), row['sync'])
                    self.assertEqual(int(record['delay_sequence']), row['delay_sequence'])
                    self.assertEqual([int(record[f't{i}_ns']) for i in range(1, 5)], row['t_ns'])
                    self.assertEqual(float(record['offset_ns']), row['offset_ns'])
                    self.assertEqual(float(record['path_delay_ns']), row['delay_ns'])
                    self.assertEqual(int(record['reported_rate_ppb']), row['rate_ppb'])
                    self.assertAlmostEqual(float(record['elapsed_seconds']),
                                           (row['t_ns'][0] - rows[0]['t_ns'][0]) / 1e9, places=9)

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
