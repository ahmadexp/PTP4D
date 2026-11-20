#!/usr/bin/env python3
"""Build PTP4D with a supplied Borland C++ 3.1 installation in DOSBox-X."""
import argparse, os, pathlib, shutil, subprocess, tempfile
root = pathlib.Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bcc-dir', default=os.environ.get('BORLAND_HOME'),
                    help='Root of a licensed Borland C++ 3.1 installation (BIN, INCLUDE, LIB)')
parser.add_argument('--dosbox', default=shutil.which('dosbox-x'), help='DOSBox-X executable')
parser.add_argument('--full-capture', action='store_true',
                    help='Build a separate RAM capture executable with 2560 records, stopping when full')
args = parser.parse_args()
if not args.bcc_dir: parser.error('Provide --bcc-dir or BORLAND_HOME')
compiler = pathlib.Path(args.bcc_dir).expanduser().resolve()
if not all((compiler / name).is_dir() for name in ('BIN','INCLUDE','LIB')):
    parser.error('Compiler directory must contain BIN, INCLUDE and LIB')
exe = args.dosbox
if not exe:
    raise SystemExit('DOSBox-X is required')
with tempfile.TemporaryDirectory(prefix='ptp4d-build-') as tmp:
    stage = pathlib.Path(tmp)
    shutil.copytree(compiler, stage / 'BCC')
    shutil.copytree(root / 'src', stage / 'SRC')
    if args.full_capture:
        batch = stage / 'SRC/BUILD.BAT'
        batch.write_bytes(batch.read_bytes().replace(b'BCC -mh', b'BCC -DPTP_FULL_CAPTURE -mh'))
    shutil.copy2(root / 'tests/TESTDOS.H', stage / 'SRC/TESTDOS.H')
    for name in ('servo', 'clock', 'options', 'midi', 'capture'):
        short = {'options': 'OPTS', 'capture': 'CAP'}.get(name, name.upper())
        shutil.copy2(root / 'tests' / f'test_{name}.c', stage / 'SRC' / f'TST{short}.C')
    (stage / 'SRC' / 'CHECK.BAT').write_text("""@echo off
BCC -mh -O -w -eSVTEST.EXE TSTSERVO.C SERVO.C > SVBUILD.LOG
SVTEST > SERVO.LOG
if errorlevel 1 echo FAILED >> SERVO.LOG
BCC -mh -O -w -eCKTEST.EXE TSTCLOCK.C CLOCK.C > CKBUILD.LOG
CKTEST > CLOCK.LOG
if errorlevel 1 echo FAILED >> CLOCK.LOG
BCC -mh -O -w -eOPTEST.EXE TSTOPTS.C OPTIONS.C > OPBUILD.LOG
OPTEST > OPTIONS.LOG
if errorlevel 1 echo FAILED >> OPTIONS.LOG
BCC -mh -O -w -eMDTEST.EXE TSTMIDI.C TSWIRE.C TSMIDI.C > MDBUILD.LOG
MDTEST > MIDI.LOG
if errorlevel 1 echo FAILED >> MIDI.LOG
BCC -mh -O -w -DPTP_FULL_CAPTURE -eCPTEST.EXE TSTCAP.C > CPBUILD.LOG
CPTEST > CAPTURE.LOG
if errorlevel 1 echo FAILED >> CAPTURE.LOG
""", newline='\r\n')
    conf = stage / 'dosbox.conf'
    conf.write_text('''[sdl]
output=surface
[cpu]
cputype=486
fpu=false
cycles=max
[mixer]
nosound=true
[autoexec]
@echo off
mount c .
c:
path C:\\BCC\\BIN
set INCLUDE=C:\\BCC\\INCLUDE
set LIB=C:\\BCC\\LIB
cd \\SRC
call BUILD.BAT
PTP4D /? > HELP.LOG
PTP4D > PROBE.LOG
PTP4D /MODE GM > GMBLOCK.LOG
PTP4D /PTP 10 /SERVO KALMAN > SERPROBE.LOG
call CHECK.BAT
exit
''')
    env = os.environ.copy()
    env.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
    result = subprocess.run([exe, '-fastlaunch', '-silent', '-nogui', '-conf', str(conf)],
                            cwd=stage, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=300)
    dest = root / 'build' / 'full-capture' if args.full_capture else root / 'build'
    dest.mkdir(parents=True, exist_ok=True)
    for name in ['BUILD.LOG','HELP.LOG','PROBE.LOG','PTP4D.EXE','GMBLOCK.LOG','SERPROBE.LOG',
                 'SVBUILD.LOG','CKBUILD.LOG','OPBUILD.LOG','MDBUILD.LOG',
                 'SERVO.LOG','CLOCK.LOG','OPTIONS.LOG','MIDI.LOG','CPBUILD.LOG','CAPTURE.LOG']:
        src = stage / 'SRC' / name
        if src.exists(): shutil.copy2(src, dest / name)
    if not (stage / 'SRC/PTP4D.EXE').exists():
        print((dest / 'BUILD.LOG').read_text(errors='replace'))
        print(result.stdout.decode(errors='replace')[-2000:])
        raise SystemExit('Borland build failed')
    print((dest / 'BUILD.LOG').read_text(errors='replace'))
    print((dest / 'PROBE.LOG').read_text(errors='replace'))
    help_log=(dest/'HELP.LOG').read_text(errors='replace')
    probe_log=(dest/'PROBE.LOG').read_text(errors='replace')
    if 'Usage: PTP4D' not in help_log or 'PICOCARD resident driver is not loaded.' not in probe_log:
        raise SystemExit('DOS smoke check failed')
    for name in ('SERVO', 'CLOCK', 'OPTIONS', 'MIDI', 'CAPTURE'):
        log = (dest / f'{name}.LOG').read_text(errors='replace')
        if 'PASS' not in log or 'Assertion failed' in log or 'FAILED' in log:
            raise SystemExit(f'DOS no-FPU {name} test failed: {log}')
        print(f'DOS 486, FPU disabled: {name} passed')
    if 'PICOCARD resident driver is not loaded.' not in (dest / 'SERPROBE.LOG').read_text():
        raise SystemExit('Advanced-servo CLI probe failed')
    if 'DOS2PHC unavailable' not in (dest / 'GMBLOCK.LOG').read_text():
        raise SystemExit('Unsupported grandmaster mode did not fail before hardware access')
    print(f'Built {dest / "PTP4D.EXE"}')
