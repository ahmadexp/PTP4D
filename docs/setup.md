# Setup

## Standalone Linux grandmaster

Connect the grandmaster TimeStick over USB and connect its Ethernet port directly to the follower TimeStick. Both devices need compatible MIDI timing firmware. Identify the intended USB serial and MAC address before starting a session.

ALSA should expose the device under `/dev/snd/midiC*D*`. Your user must have read/write access to that device. Check the existing desktop ACL or distribution audio-device permissions rather than detaching the USB driver.

Run:

```sh
python3 tools/peer.py \
  --serial YOUR_TIMESTICK_SERIAL \
  --mac YOUR_TIMESTICK_MAC \
  --seconds 0 \
  --status /tmp/ptp4d-status.json
```

The controller verifies the USB vendor/product and serial, binds timing replies to the supplied MAC, configures the hardware grandmaster at 4 Hz in domain 42, and renews its 15-second lease every five seconds. It emits JSON lines to stdout. Ctrl+C or SIGTERM sends STOP and checks restoration.

Start the DOS follower promptly after the grandmaster. The firmware waits for an Ethernet link during startup; it can stop if the other endpoint is not ready. If startup fails, resolve the connection, stop both controllers, and restart them together.

## Optional SSH/COMrade pair controller

This helper requires:

1. A Linux serial bridge with the `comrade` Python package in a `.venv`, a running DOS COMrade agent, and a working serial connection.
2. A Linux grandmaster host with a working user systemd manager and an accessible TimeStick MIDI device.
3. SSH key access from the controlling computer to both hosts.
4. `C:\PTP4D.EXE` installed on the DOS machine, which must be at `C:\>` before starting.

Copy `tools/peer.py` into a dedicated directory on the grandmaster host. Create that directory before starting, because systemd writes its logs there:

```sh
ssh retro@ptp-peer.example.net 'mkdir -p /home/retro/ptp4d'
scp tools/peer.py retro@ptp-peer.example.net:/home/retro/ptp4d/peer.py
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

## Direct USB and programming

The verified arrangement connects TimeStick directly to PicoPCMCIA's USB-C breakout. The programming computer must be disconnected from that data path while Pico is the USB host.

A readable microSD is required for the tested card firmware's startup. Firmware v0.22 and the matching PICOCARD driver must already be installed. PTP4D does not flash either device. Pico's RP2350 can be programmed with the official Raspberry Pi `picotool`; entering BOOTSEL and safely stopping the resident driver are separate setup steps.
