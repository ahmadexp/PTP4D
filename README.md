<img src="docs/branding/ptp4d-icon.png" alt="PTP4D: an IBM PC110 with a clock and synchronized pulses" width="144" height="144" align="right">

# PTP4D: PTP for DOS

**PTP4D stands for PTP for DOS.** It brings hardware-clock PTP control to real-mode DOS through PicoPCMCIA and a TimeStick v3.

**[Download PTP4D.EXE](https://github.com/ahmadexp/PTP4D/releases/latest/download/PTP4D.EXE)** | [Release notes](https://github.com/ahmadexp/PTP4D/releases/latest) | [SHA-256 checksum](https://github.com/ahmadexp/PTP4D/releases/latest/download/SHA256SUMS)

**Version 0.5 is released.** The download and `bin/PTP4D.EXE` include five DOS-side servos alongside the default firmware PI, explicit follower/GM roles, and guarded PHC-to-DOS time copying. All six follower selections have completed PC110 hardware trials. [Release notes](docs/releases/v0.5.md) | [Switches and clock behavior](docs/clock-modes.md) | [Servo inventory and protocol limits](docs/servo-inventory.md). PHC-to-DOS writes and DOS-controlled GM operation have local tests but remain unverified on hardware. DOS-derived grandmaster time is unavailable with the inspected firmware and is rejected before hardware access.

The host controller also supports **macOS CoreMIDI** alongside Linux
ALSA, including device listing and a receive-only check. Mac enumeration, passive
TimeStick telemetry, and virtual MIDI input/output have been tested. All six
follower servo selections completed one-minute PC110 hardware trials against
the Mac-controlled TimeStick, with complete timestamp matches and verified STOPs.
[Hardware comparison and evidence](docs/validation/servo-20261120/).
[Mac setup and servo trial procedure](docs/setup.md) |
[CoreMIDI validation](docs/validation/coremidi-local.md).

The first working setup is an IBM PC110 running MS-DOS 6.22. PTP4D configures and monitors the TimeStick's on-device PI servo, while the TimeStick exchanges hardware-timestamped PTP messages over Ethernet. In that original 0.4 configuration, the DOS system clock is unchanged.

![PTP4D AUTO_PI results on the IBM PC110's built-in display](docs/photos/pc110-auto-pi-servo.jpg)

*A one-minute AUTO_PI trial from the 0.5 development build, photographed on the physical PC110. The release uses the same timing code with an updated version banner. The display shows reported offset, path delay, and frequency correction. [Full-size photo](docs/photos/pc110-auto-pi-servo.jpg).*

## Hardware-verified behavior

- TimeStick identification and hardware-clock reads over USB MIDI.
- PTP follower operation in domain **42**, at **4 exchanges per second**.
- Live offset, mean path delay, and acknowledged frequency-correction display.
- Timed runs or continuous operation until **Esc**.
- Renewable 15-second device leases and verified STOP acknowledgements.
- CSV output containing the last 128 complete hardware timestamp exchanges.
- Runtime selection of firmware `PI` or DOS-side `HOST_PI`, `AUTO_PI`, `LINREG`, `KALMAN`, and `PLLFLL`.
- A Linux/macOS TimeStick grandmaster controller and an optional Linux SSH/COMrade pair controller.

The default configures a **PI (proportional-integral) servo inside the TimeStick firmware**. Version 0.5 additionally offers the five DOS-side controllers through the firmware's host-control profile. Ethernet timestamps always come from the TimeStick hardware. See [controller placement and licensing](docs/servo-inventory.md).

![PTP4D running on a real IBM PC110, captured through a Lantronix KVM](docs/screenshots/ptp4d-live.png)

*Actual PC110 display during continuous synchronization. The screenshot is an unedited capture of the Lantronix console, not an emulated or reconstructed terminal.*

## Hardware path

```mermaid
flowchart LR
    DOS[IBM PC110 / DOS / PTP4D] -->|PCMCIA mailbox| Pico[PicoPCMCIA / RP2350]
    Pico -->|USB MIDI| Follower[TimeStick v3 / AX88279A / hardware clock]
    Follower <-->|Ethernet PTP, domain 42| GM[TimeStick v3 / hardware grandmaster]
    Host[Linux ALSA or macOS CoreMIDI / peer.py] -->|USB MIDI commands and telemetry| GM
```

Tested configuration:

| Component | Tested version or behavior |
| --- | --- |
| Computer | IBM PC110, MS-DOS 6.22 |
| PCMCIA card | PicoPCMCIA hardware v4.4, stock firmware v0.22, protocol 2 |
| DOS resident driver | Matching v0.22 `PICOCARD.EXE` |
| Timing devices | Two TimeStick v3 devices with USB MIDI timing firmware |
| USB connection | TimeStick connected directly to the PicoPCMCIA USB-C breakout |
| Ethernet | Direct cable between the two TimeSticks |
| Grandmaster host | Linux ALSA or macOS CoreMIDI |

A readable microSD card must be installed in PicoPCMCIA for the tested firmware to finish starting. The initial powered-hub arrangement did not enumerate; direct USB is the verified arrangement. Generic ASIX Ethernet-only firmware is not supported by this utility. Firmware, DOS, and the compiler are obtained separately.

![TimeStick V3 connected directly to the PicoPCMCIA USB-C breakout on the IBM PC110](docs/photos/timestick-v3-picopcmcia.jpg)

*TimeStick v3 on the left, plugged directly into the PicoPCMCIA USB-C breakout on the right. The Ethernet cable connects the TimeStick to its PTP peer.*

## Run on DOS

Download [`PTP4D.EXE` from the latest release](https://github.com/ahmadexp/PTP4D/releases/latest/download/PTP4D.EXE) and copy it to `C:\`. Verify it against the release's [`SHA256SUMS`](https://github.com/ahmadexp/PTP4D/releases/latest/download/SHA256SUMS). The same tested executable is also kept in [`bin/`](bin/).

Start the grandmaster first, then run the follower promptly so both Ethernet PHYs are active within the firmware's link-start deadline:

```dos
C:\PTP4D /HOST
C:\PTP4D /PTP 0
```

`/HOST` saves host ownership of PicoPCMCIA USB. It disables the card's own USB storage/HID binding until `/CARD` restores it. Enable it once before testing.

| Command | Action |
| --- | --- |
| `PTP4D /PTP 0` | Continuous PTP follower; Esc stops it |
| `PTP4D /PTP 60` | PTP follower for approximately 60 seconds |
| `PTP4D /PTP 60 /SERVO KALMAN` | One-minute follower using the DOS Kalman servo |
| `PTP4D /CLOCK` | Brief clock-only session and hardware snapshots |
| `PTP4D` | Passive MIDI clock read; reports an inactive clock when appropriate |
| `PTP4D /LIST` | Enumerate USB devices |
| `PTP4D /PORT 1 /CLOCK` | Select a USB pass-through port |
| `PTP4D /DIAG` | Passive read with additional status |
| `PTP4D /CARD` | Restore card-managed USB ownership |

PTP durations are `0` or `10..3600` seconds. PTP4D runs in the foreground. Stop it before running another DOS command. The build deliberately rejects Windows and firmware reporting versions other than v0.22/protocol 2. The version words do not identify patch suffixes such as usbfix4; matching resident-driver and hardware validation remain necessary. Never run it while the card is exported for storage transfers or has saved SWD state.

![PTP4D command help on the physical PC110](docs/screenshots/ptp4d-help.png)

## Servo selection and clock modes

Version 0.5 includes these commands:

```dos
PTP4D /PTP 60 /SERVO KALMAN
PTP4D /MODE GM /SYNC NONE /PTP 60
PTP4D /PTP 0 /SYNC PHC2DOS /EPOCH UNIX /SCALE UTC /DOS UTC /VALID 3600
```

The last command requires an independently verified Unix-epoch UTC source.
It steps DOS date/time once after acquisition; `/UPDATE TRACK` adds 30-second
checks and coarse corrections. DOS setters may also update the battery-backed
RTC. `/VALID` asserts source validity and an unchanged leap/timezone mapping
for a bounded period. The existing raw-clock peer is not a verified UTC source.
Read the [full clock-mode guide](docs/clock-modes.md) before enabling writes.

`/MODE GM /SYNC NONE` serves a free-running fixed-peer hardware clock without
Announce/BMCA or a known civil epoch. `/MODE GM` defaults to the requested
DOS-to-PHC direction, which the current firmware cannot perform while serving
PTP, and refuses to start. These new modes have local tests and DOS builds;
they have no new hardware accuracy claim.

## Start both ends from a modern host

See [setup instructions](docs/setup.md) for the standalone Linux/macOS grandmaster and the optional Linux SSH/COMrade pair controller.

With SSH access and COMrade already configured:

```sh
cp config.example.json config.local.json
# Edit config.local.json with your hosts, remote paths, serial device, and TimeStick identity.
python3 tools/control.py start --config config.local.json
python3 tools/control.py status --config config.local.json
python3 tools/control.py stop --config config.local.json
```

The pair controller starts a transient `ptp4d-gm` user service, launches PTP4D through COMrade, and stops both ends. It does not install a boot-time service. The configuration file is ignored by Git.

## Servo comparison

All six selections completed separate one-minute hardware trials with the
Mac-controlled TimeStick. All **768 retained exchanges** matched the grandmaster
timestamps and independent arithmetic, with zero grandmaster timestamp errors
and verified STOP/restoration at both ends.

![Six servo offset traces and final-window detail](docs/validation/servo-20261120/servo-offsets.png)

The graphs show the final 128 exchanges, about 32 seconds, from each run.
The shaded portion is the final 40 exchanges, enlarged on the right. Startup
is outside the retained window. HOST_PI still had a positive residual in this
trial; the other final-window means were within 5 ns of zero. These separate
runs have different initial conditions and do not establish a controller ranking
or independent PPS/UTC accuracy.

[Frequency-correction graphs, offset distributions, and results](docs/validation/servo-20261120/#graphs)
include PNG and SVG figures, all 768 samples in CSV, and reproducible plotting code.

## Original 0.4 measurement

A one-minute hardware run completed **237 exchanges** with **14 successful DOS lease renewals** and **zero grandmaster timestamp errors**.

| Final 40 exchanges, approximately 10 seconds | Reported result |
| --- | ---: |
| Mean clock offset | 2.175 ns |
| Maximum absolute clock offset | 20.5 ns |
| Offset standard deviation | 7.544 ns |
| Final mean path delay | 2,766 ns |

All **128 retained t1 and t4 timestamps** matched the grandmaster's hardware logs. Independently recomputing offset and delay from t1 through t4 reproduced every retained result.

![PTP offset convergence from the recorded hardware run](docs/validation/offset.png)

These are PTP-reported offsets under the symmetric-path assumption. They are not an independent calibration of physical PPS alignment or absolute UTC accuracy. UTC traceability has not been established. The detailed measurement run used the initial name `TSREAD`; it was renamed to PTP4D without changing the servo or USB transport, and live operation was checked again.

[CSV samples](docs/validation/exchanges.csv), [validation summary](docs/validation/summary.json), and [timestamp evidence](docs/validation/) are included. Recompute the evidence with:

```sh
python3 tools/analyze.py docs/validation/dos.json docs/validation/grandmaster.jsonl
```

To regenerate the original figure, install `matplotlib` in a Python environment
and run `python3 tools/plot.py`. The six-servo figures use
`python3 tools/plot_servos.py` with Matplotlib 3.11.2; see the
[plotting instructions](docs/validation/servo-20261120/#reproduce-the-graphs).

## Build and test

The verified DOS build uses **Borland C++ 3.1**, huge memory model, inside **DOSBox-X**. Supply your own licensed compiler installation; neither the compiler nor its SDK files are included.

```sh
python3 build-dos.py --bcc-dir /path/to/BORLAND --dosbox /path/to/dosbox-x
```

The compiler directory must contain `BIN`, `INCLUDE`, and `LIB`. The result and smoke-test logs are written to `build/`. Alternatively, run `src/BUILD.BAT` in DOS after setting up `BCC`, `INCLUDE`, and `LIB`.

Portable protocol tests run on a modern host:

```sh
python3 tools/test.py
```

These cover USB mailbox handling, CRC and MIDI framing, descriptor bounds, signed 64-bit Q17 decoding, timestamp validation, lease-generation binding, command restrictions, every host servo, civil-time conversion, option conflicts, and fake-device session faults. Host tests cover device selection, packet layouts, passive mode, disconnection, and the grandmaster lifecycle. On macOS they also exercise real CoreMIDI input/output through temporary virtual endpoints, without sending to USB hardware. The Borland build also runs controller/calendar/options/MIDI tests with DOSBox-X FPU emulation disabled. They do not emulate the PCMCIA bus or prove hardware accuracy. GitHub Actions is configured for Linux and macOS; the proprietary DOS compiler is not needed for CI.

## Scope and recovery

The current implementation is specific to the tested PicoPCMCIA and TimeStick MIDI protocols. It is not a generic DOS packet-driver PTP stack. DOS time changes only with the explicit `PHC2DOS` options described above. Linux and macOS system time are unchanged.

PTP4D temporarily disarms PICOCARD and stops SD/CD prefetch while it owns shared USB staging. BIOS display output remains available; normal card services resume after a clean stop. Firmware leases expire if a controller disappears. A failed USB recovery leaves PICOCARD disarmed and requires a DOS reboot. Read [protocol and recovery notes](docs/protocol.md) before changing the low-level transport.

## Related projects

- [PicoPCMCIA](https://github.com/yyzkevin/PicoPCMCIA): PCMCIA hardware and firmware.
- [TimeStick](https://github.com/Time-Appliances-Project/TimeStick) and [TimeStick product information](https://time-stick.com/): hardware and timing-firmware setup.
- [COMrade](https://github.com/yyzkevin/COMrade): optional serial control of the DOS machine.

PTP4D includes its DOS utility, host helpers, tests, screenshots, and timing data. The separate firmware projects and development toolchain are not bundled.

## License

[MIT](LICENSE). Copyright (c) 2026 Ahmad Byagowi.
