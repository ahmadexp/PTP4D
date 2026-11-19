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
            ('midi', ['src/TSWIRE.C', 'src/TSMIDI.C', 'tests/test_midi.c']),
        ):
            output = str(pathlib.Path(tmp) / name)
            subprocess.run([*cc, *flags, *sources, '-o', output], cwd=ROOT, check=True)
            subprocess.run([output], cwd=ROOT, check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                   cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
