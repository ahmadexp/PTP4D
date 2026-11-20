# Runtime servos and clock modes (0.5 development)

These changes are implemented in the source checkout and local development
build. The published 0.4 executable and its hardware evidence remain unchanged.
The new paths have portable simulations, protocol/session fault tests and a
Borland build. All six follower servos with `/SYNC NONE` also completed
[one-minute PC110 hardware trials](validation/servo-20261120/) against a
Mac-controlled TimeStick. PHC2DOS and DOS-controlled GM operation remain
unverified on the physical PC110.

## Supported combinations

| Role and direction | Implementation | Status |
| --- | --- | --- |
| Follower, `NONE`, `PI` | Firmware profile 1 disciplines PHC | Compatible default; original hardware-verified path |
| Follower, `NONE`, other servos | DOS controller, profile 3 measurements and op 7 corrections | Implemented; requires successful op 6 capability query |
| Follower, `PHC2DOS` | Either follower controller, fresh op 8 capture, DOS date/time services | Implemented with explicit civil-time assumptions and validity period |
| GM, `NONE` | Firmware profile 2, fixed-peer Sync/Follow_Up/Delay_Resp | Implemented DOS control and monitoring; raw free-running epoch |
| GM, `DOS2PHC` | Requires clock actuation and source-quality support in GM firmware | **Unavailable; rejected before hardware access** |

`/MODE GM` defaults to the requested `DOS2PHC` direction and therefore refuses
to run on this protocol. Selecting `/SYNC NONE` explicitly permits the limited,
free-running source. It is not a DOS-synchronized grandmaster. No mode silently
substitutes another direction or servo.

The firmware's profile 4 permits a standalone initial clock step and frequency
adjustment, but disables Ethernet. Profile 2 has no clock-write operation, no
Announce, no BMCA, and no programmable time-properties or clock-quality dataset.
Starting profile 4, setting an epoch, stopping it and starting profile 2 does
not establish a supported clock handover. PTP4D does not attempt that sequence.
See [the protocol audit and firmware requirements](servo-inventory.md).

## Commands

```dos
PTP4D /PTP 0
PTP4D /PTP 60 /SERVO AUTO_PI
PTP4D /PTP 0 /SERVO LINREG
PTP4D /PTP 0 /SERVO KALMAN
PTP4D /PTP 0 /SERVO PLLFLL
PTP4D /PTP 60 /SERVO HOST_PI
PTP4D /MODE GM /SYNC NONE /PTP 60
```

`/PTP 0` runs until Esc; other durations are 10 through 3600 seconds. `/MODE`
without `/PTP` implies continuous operation. Follower is the default role.
`/SERVO PI` means the existing on-device PI. `HOST_PI` is an additional DOS PI
implementation useful for comparing the host control path. All PTP modes use
domain 42 and request 4 Hz. Domain and rate are not configurable in this build.

For a source independently known to carry valid Unix-epoch UTC:

```dos
PTP4D /PTP 0 /SYNC PHC2DOS /EPOCH UNIX /SCALE UTC /DOS UTC /VALID 3600
```

The preceding command makes one startup date/time step after acquisition.
Add `/UPDATE TRACK` to continue checking the DOS clock every 30 seconds. A
local-time DOS setup uses `/DOS LOCAL /TZ minutes`, where minutes is DOS local
time minus UTC, for example `-480` for a fixed UTC-08:00 offset. There is no
automatic DST conversion. TAI sources require `/SCALE TAI /TAIOFF seconds` with
the source's independently verified current TAI-minus-UTC value. Neither offset
is guessed from the machine, hardcoded as a contemporary default, or obtained
from the firmware. The conventional 126-character DOS command-tail limit
applies; omit redundant `/MODE FOLLOWER` when using longer clock options.

`/VALID 10..3600` is an operator assertion that the source has a valid civil
epoch and that its leap/UTC-offset and local DST mapping will remain unchanged
for that many seconds after START acknowledgment. The entire session stops at
that deadline, including `/PTP 0`. This is necessary because this protocol
supplies neither leap announcements nor UTC-offset validity. It is not evidence
of external traceability. Do not use the raw free-running peer in this repository
as a civil-time source unless its epoch and timescale are separately established.

`/CLOCK`, passive reads, `/LIST`, `/PORT`, `/DIAG`, `/HOST`, and `/CARD` retain
their hardware-only functions. Help is `/?` or `/HELP`, with exit status zero.
Conflicting or duplicate options and unsupported directions fail with status 1
before the resident driver is probed. Servo selection is a startup choice;
stop and restart the foreground program to change it.

## Three distinct clocks

1. **TimeStick PHC:** the hardware counter used for Ethernet timestamps. Its
   48-bit seconds are not automatically UTC. The follower firmware acquires an
   initial epoch from its network peer before producing full exchanges.
2. **DOS/BIOS system clock:** DOS maintains the date and uses the approximately
   18.2 Hz BIOS tick clock for time. Its centisecond API does not imply 10 ms
   resolution. PTP4D does not reprogram the PIT, install a TSR, or implement a
   high-resolution software clock.
3. **Battery RTC:** a separate persistent clock. PTP4D does not directly access
   its registers or independently discipline it. DOS date/time setters can
   mirror the new values to this clock. This side effect is stated in help,
   startup status and the report. RTC preservation is not offered by this build.

The documented MS-DOS CLOCK$ implementation updates BIOS ticks and, when a CMOS
clock is present, invokes the RTC date/time setters. See Microsoft's
[MSCLOCK.ASM](https://github.com/microsoft/MS-DOS/blob/main/v4.0/src/BIOS/MSCLOCK.ASM).
Exact PC110/MS-DOS 6.22 behavior still needs physical verification.

Conversion accepts Gregorian dates from 1980 through 2099, using unsigned
epoch arithmetic rather than a signed 32-bit `time_t`. It handles the year
2000 leap day and dates beyond 2038. Nonzero high PHC seconds, dates outside
the supported range, invalid nanoseconds, or invalid timestamps are rejected
instead of truncated. Leap seconds cannot be represented by DOS; leap handling
requires stopping, obtaining a fresh timescale assertion and restarting after
the transition. No leap smear is assumed or performed.

## Startup and tracking behavior

- The follower requires eight distinct, advancing exchanges with reported
  absolute offset at most 1 ms. Bad samples or a gap over approximately 1.5 s
  clear qualification. This is an acquisition gate, not a UTC-quality test.
- A clock write uses a separate nonce/sequence/MAC/domain/profile/generation
  checked op 8 capture. It requires active epoch-ready PHC flags and fresh PTP
  progress. A capture may span at most 110 ms and at most two BIOS timer ticks
  of host round trip. Firmware RX/TX snapshots bound processing time; symmetric
  USB transit is approximated from the remaining round trip. USB asymmetry and
  tick quantization remain errors. These are not USB hardware timestamps.
- STEP performs one initial date/time set, including a large correction in
  either direction. TRACK performs that same initial step, then checks every
  30 seconds. It writes only for errors beyond an approximately 110 ms deadband.
  A later discrepancy of 1 s or more stops the session and requires an explicit
  restart. TRACK is periodic coarse phase correction, not a DOS frequency slew.
- DOS time/date is read using a date/time/date sandwich to detect midnight.
  Writes set time then date, check both return codes, and verify readback within
  220 ms. Writes are deferred during the last two seconds of the target day.
  A failed pair may leave the clock partially changed; it stops and reports that
  condition. The setters are not an atomic transaction.
- A private deadline counter extends raw BIOS tick differences across midnight
  and is rebased after intentional clock writes. It never consumes DOS's BDA
  rollover flag. Date/time services are the only DOS calls used while USB
  staging is held; console output still uses BIOS, and file/console DOS I/O
  remains deferred until the card is released.
- No valid source, capability failure, excessive capture latency, stale PTP,
  generation change, or failed correction acknowledgment can trigger a clock
  write from the rejected measurement. Host correction failures stop the run
  rather than falling back to PI. Failure before the initial DOS set returns an
  error. The ordinary 15-second lease and verified STOP remain in use.

Only one clock direction is active. PHC2DOS never reads DOS time as input to
the network servo, and GM cannot select a follower servo or PHC2DOS. Hardware
offset reports and DOS clock-copy quality are separate quantities. Neither a
small reported PTP offset nor a DOS-derived source establishes external UTC
traceability or nanosecond wall-clock accuracy.

## Validation and next hardware run

`python3 tools/test.py` runs C89 ASan/UBSan tests, simulated oscillator models,
calendar/CLI tests, protocol checks and the real session loop with a fake MIDI
device and DOS services. Faults include absent host capability, rejected
frequency commands, replaced generations, GM timestamp errors, missing STOP,
unqualified samples, invalid capture epochs, unarmed captures and DOS setter
failure. Further cases exercise tracking corrections, validity expiry, clock
discontinuity, source loss, corrupt or mismatched acknowledgments, excessive
capture latency, and a lost START acknowledgment. The original packet tests, host-tool tests and published timestamp
evidence remain part of the suite.

`build-dos.py` builds with Borland huge model, runs help and refusal checks, and
runs the portable servo/calendar/options/MIDI tests inside DOSBox-X configured
as a 486 with FPU emulation disabled. Emulator throughput is not a PC110 timing
measurement. All new controllers require a later CPU-load and watchdog-margin
measurement at 4 Hz on the 486SX33.

Hardware integration must wait until storage transfers release the devices.
Do not run PTP4D, change USB ownership, reset, flash, or unmap/remap the card while
another job owns it. After release, verify the currently installed firmware
and matching resident driver, reconnect the intended TimeStick, check its
serial/MAC, and test hardware-only modes first. The original v0.22 measurements
do not establish compatibility of every path with v0.22-usbfix4. Test each host
servo, lease expiry, Esc/STOP, reconnect, midnight, and DOS/RTC behavior before
using PHC2DOS with a separately verified civil-time source.
