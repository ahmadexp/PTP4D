#!/usr/bin/env python3
"""Run portable C protocol tests and Python host-tool regression checks."""
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    cc = shlex.split(os.environ.get('CC', 'clang'))
    if not cc or not shutil.which(cc[0]):
        raise SystemExit('Install clang or set CC to a C compiler with sanitizer support')
    flags = ['-x', 'c', '-std=c89', '-Wall', '-Wextra', '-Werror',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', 'src']
    with tempfile.TemporaryDirectory(prefix='ptp4d-tests-') as tmp:
        for name, sources in (
            ('wire', ['src/TSWIRE.C', 'tests/test_wire.c']),
            ('options', ['src/OPTIONS.C', 'tests/test_options.c']),
            ('servo', ['src/SERVO.C', 'tests/test_servo.c']),
            ('clock', ['src/CLOCK.C', 'tests/test_clock.c']),
            ('midi', ['src/TSWIRE.C', 'src/TSMIDI.C', 'tests/test_midi.c']),
        ):
            output = str(pathlib.Path(tmp) / name)
            subprocess.run([*cc, *flags, *sources, '-lm', '-o', output], cwd=ROOT, check=True)
            subprocess.run([output], cwd=ROOT, check=True)
        output = str(pathlib.Path(tmp) / 'capture')
        subprocess.run([*cc, *flags, '-DPTP_FULL_CAPTURE', 'tests/test_capture.c', '-o', output],
                       cwd=ROOT, check=True)
        subprocess.run([output], cwd=ROOT, check=True)
        output = str(pathlib.Path(tmp) / 'session')
        subprocess.run([*cc, *flags, '-Wno-deprecated-declarations', '-I', 'tests/support',
                        'src/TSMIDI.C', 'src/CLOCK.C', 'src/OPTIONS.C', 'src/SERVO.C',
                        'tests/test_session.c', '-lm', '-o', output], cwd=ROOT, check=True)
        cases = [(0, servo, 1) for servo in range(6)] + [(0, 0, 2)]
        cases += [(fault, 2, 2 if fault == 4 else 1) for fault in range(1, 21)]
        cases += [(fault, servo, 1) for fault in (21, 22) for servo in range(1, 6)]
        for case in cases:
            subprocess.run([output, *map(str, case)], cwd=ROOT, check=True)
        output = str(pathlib.Path(tmp) / 'full-session')
        subprocess.run([*cc, *flags, '-DPTP_FULL_CAPTURE', '-Wno-deprecated-declarations',
                        '-I', 'tests/support', 'src/TSMIDI.C', 'src/CLOCK.C', 'src/OPTIONS.C',
                        'src/SERVO.C', 'tests/test_session.c', '-lm', '-o', output], cwd=ROOT, check=True)
        for fault in (23, 24):
            for servo in range(6):
                subprocess.run([output, str(fault), str(servo), '1'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                   cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
