# Setup

## Standalone Linux or macOS grandmaster

Connect the grandmaster TimeStick over USB and connect its Ethernet port directly to the follower TimeStick. Both devices need compatible MIDI timing firmware. Identify the intended USB serial and MAC address before starting a session.

Use Python 3 with both `tools/peer.py` and `tools/midi_transport.py` in the same
directory. On macOS the controller uses CoreMIDI and CoreFoundation through
Python's standard library; no MIDI package, Swift compiler, or driver detachment
is needed. On Linux, ALSA should expose `/dev/snd/midiC*D*`. Your user must have
read/write access to that device. Check the existing desktop ACL or distribution
audio-device permissions rather than detaching the USB driver.

List online TimeSticks without sending commands:

```sh
python3 tools/peer.py --list
```

The transport defaults to CoreMIDI on macOS and ALSA on Linux. Set
`--transport coremidi` or `--transport alsa` to require one explicitly.
CoreMIDI filters by USB vendor/product and exact serial, ignores saved offline
devices, and requires one identified input/output pair on the same entity.
Missing or duplicate serials and ambiguous endpoint layouts are rejected. The
controller never chooses by display name or by the first MIDI device in a list.

Check passive reception using that serial and the independently known MAC:

```sh
python3 tools/peer.py \
  --serial YOUR_TIMESTICK_SERIAL \
  --mac YOUR_TIMESTICK_MAC \
  --passive 3
```

Passive mode creates only an input port on macOS and opens ALSA read-only. It
sends no commands, including IDENTIFY or STOP, and requires CRC-valid telemetry
matching the supplied MAC and domain 42. Its duration is limited to 1..60 seconds.
The final JSON record reports the valid frame count and last firmware flags.
An inactive TimeStick can emit identity telemetry without starting its PTP clock.

Once both devices are available for timing work, start the grandmaster:

```sh
python3 tools/peer.py \
  --serial YOUR_TIMESTICK_SERIAL \
  --mac YOUR_TIMESTICK_MAC \
  --seconds 0 \
  --status /tmp/ptp4d-status.json
```

The controller first verifies identity through passive telemetry, then checks
availability and the acknowledged 4 Hz rate before starting the hardware
grandmaster in domain 42. It renews the 15-second lease every five seconds and
emits JSON lines to stdout. Ctrl+C or SIGTERM sends STOP and checks restoration.
Replies must match the session nonce, sequence, operation, device MAC and domain;
renewal and STOP also check the active generation. One lock shared by all
`peer.py` instances prevents overlapping controllers on the same host.

CoreMIDI keeps a bounded input queue and stops on overflow, device disappearance,
endpoint replacement, MIDI setup/removal notifications, or I/O failure. It never
rebinds after a replug. If the connection fails, STOP cannot be verified; the
firmware lease provides the remaining expiry mechanism. Restore connectivity
and explicitly restart the controller. Opening or changing another MIDI setup
during a run may also terminate it.

The Mac controls the TimeStick's free-running hardware grandmaster. The laptop's
system clock is neither changed nor copied into the TimeStick. This peer does
not establish a UTC source for PHC2DOS.

Start the DOS follower promptly after the grandmaster. The firmware waits for an Ethernet link during startup; it can stop if the other endpoint is not ready. If startup fails, resolve the connection, stop both controllers, and restart them together.

## Optional SSH/COMrade pair controller

This helper requires:

1. A Linux serial bridge with the `comrade` Python package in a `.venv`, a running DOS COMrade agent, and a working serial connection.
2. A Linux grandmaster host with a working user systemd manager and an accessible TimeStick MIDI device.
3. SSH key access from the controlling computer to both hosts.
4. `C:\PTP4D.EXE` installed on the DOS machine, which must be at `C:\>` before starting.

Copy `tools/peer.py` and `tools/midi_transport.py` into a dedicated directory on the grandmaster host. Create that directory before starting, because systemd writes its logs there:

```sh
ssh retro@ptp-peer.example.net 'mkdir -p /home/retro/ptp4d'
scp tools/peer.py tools/midi_transport.py retro@ptp-peer.example.net:/home/retro/ptp4d/
```

Copy `config.example.json` to `config.local.json` and replace every example field. `peer_serial` and `peer_mac` select the grandmaster, not the follower. Remote filesystem paths must be absolute. Set `serial_lock` to the same lock used by all other COMrade processes on your bridge; its parent directory must exist.

The helper expects COMrade's `server._lifespan`, `run_command`, `screen_read`, `keys_send`, and console-capture interfaces. It was tested with the PC110 serial bridge used for this project. Adapt it if your COMrade version exposes a different API. Local DOS operation and the standalone grandmaster do not require this helper.

```sh
python3 tools/control.py start --seconds 60
python3 tools/control.py status
python3 tools/control.py stop
```

Omit `--seconds` for continuous operation. The grandmaster runs as the transient user unit `ptp4d-gm`. The controller refuses to start a second instance. The stop action sends Esc to the DOS PTP program, verifies the DOS prompt, then stops the grandmaster. It refuses keystrokes when the foreground screen does not identify the PTP utility.

Logs are written under the configured `dos_log_dir` and `peer_dir`. No passwords are stored, and neither service is enabled automatically at boot.

This optional pair helper still requires a Linux/systemd grandmaster host. For a
TimeStick connected to a Mac, run `peer.py` locally and start the follower on DOS.

## Direct USB and programming

The verified arrangement connects TimeStick directly to PicoPCMCIA's USB-C breakout. The programming computer must be disconnected from that data path while Pico is the USB host.

A readable microSD is required for the tested card firmware's startup. Firmware v0.22 and the matching PICOCARD driver must already be installed. PTP4D does not flash either device. Pico's RP2350 can be programmed with the official Raspberry Pi `picotool`; entering BOOTSEL and safely stopping the resident driver are separate setup steps.

## Clock modes and shared hardware

The commands above describe the existing hardware-only follower pair. The
0.5 release offers [runtime servos and clock direction](clock-modes.md). The
host helpers continue to launch the compatible PI/default direction; advanced
switches are entered directly on DOS. The free-running peer supplied here has
no independently verified UTC epoch and is not automatically eligible for
PHC2DOS. No firmware or hardware ownership change is performed by the build or
portable tests. Keep live tests deferred while the Pico or its SD is owned by
storage-transfer work, including saved SWD state.

## Servo trials after storage transfers finish

Keep one TimeStick connected directly to PicoPCMCIA and the other to the laptop,
with Ethernet between them. Wait for all SD transfers and storage ownership to
be released before launching the DOS utility or changing Pico ownership. The
published `bin/PTP4D.EXE` and the latest release download are version 0.5 and
include all six servo selections.

For each trial, start the standalone laptop grandmaster above and promptly start
a 60-second follower run on DOS. Begin with the firmware PI baseline:

```dos
PTP4D /PTP 60 /SERVO PI /SYNC NONE > C:\PI01.LOG
```

After the follower returns to DOS, stop the laptop controller with Ctrl+C and
check its `stopped` record with `restoration_verified: true`. Restart the pair
for each of `HOST_PI`, `AUTO_PI`, `LINREG`, `KALMAN`, and `PLLFLL`, changing the
`/SERVO` value. Preserve each run's CSV and the laptop JSON log under distinct
names before the next trial. Compare acquisition, reported offset, path delay,
frequency corrections, timestamp errors, and clean STOP restoration.

Use a different DOS log filename for each trial. Redirection saves the complete
report after the utility releases card ownership; the live BIOS display remains
visible. Read the file after the DOS prompt returns. Streaming the final 128-row
report through COMrade's console capture can overflow that capture buffer.

These trials use `/SYNC NONE`, which leaves DOS time unchanged. They test the
DOS-side servos against the laptop-controlled hardware clock. All six selections
completed [one-minute hardware trials](validation/servo-20261120/) after storage
transfers finished. Enumeration, passive reception, and virtual CoreMIDI I/O are
recorded in the earlier [local validation note](validation/coremidi-local.md).
