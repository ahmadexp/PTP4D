# Controller inventory and protocol audit

Audit date: 2026-11-19. Both local tinyPTP trees inspected identify revision
`b5ec4bfa4b74105e4000ad8eb4cd254f98dfc4bb`. Their documented controller set is
fixed PI, adaptive PI (`auto_pi`), eight-point linear regression (`linreg`),
two-state Kalman, and PLL/FLL (`pllfll`). Selection there is compile-time.
No additional follower controller was identified in those implementations.
Its automatic role selection is separate from servo selection. The existing
DOS timing workspace uses the same firmware PI path as PTP4D 0.4.

The inspected tinyPTP revision did not declare a top-level reuse license.
The project owner subsequently selected MIT for both projects, and the primary
tinyPTP checkout now has the same MIT license and copyright notice as PTP4D.
The pinned reference snapshot remains unchanged. tinyPTP's documentation also
identifies GPL-licensed ASIX driver references; these retain their own licenses.
PTP4D does not copy those drivers or the private firmware. The new controllers
are independent C89 implementations of the mathematical controller families,
covered by the existing MIT license. Compiler files and private firmware sources
remain outside this repository.

LinuxPTP also documents `nullf` (zero frequency for SyncE), `ntpshm`, and
`refclock_sock` (handoff to another clock service). These are not additional
standalone servo algorithms suited to this DOS/MIDI path, and are not exposed
as working switches. See the upstream [servo options](https://www.linuxptp.org/documentation/ptp4l/).

## Where control runs

| Selector | Location | Implementation in PTP4D |
| --- | --- | --- |
| `PI` | TimeStick, profile 1 | Existing firmware PI, unchanged default |
| `HOST_PI` | DOS, profile 3 | Additional fixed PI for comparing the host path |
| `AUTO_PI` | DOS, profile 3 | Bounded gain scheduling with persistence/sign-change windows |
| `LINREG` | DOS, profile 3 | Eight-point ordinary least squares on reconstructed free-running phase |
| `KALMAN` | DOS, profile 3 | Two-state phase/frequency estimator with known applied correction |
| `PLLFLL` | DOS, profile 3 | Phase removal plus a smoothed windowed frequency estimate |

Profile 3 is a measurement/actuation interface, not an on-device named servo
selector. The device performs Ethernet exchange, timestamp validation, initial
epoch acquisition and hardware actuation. DOS computes the host controller's
frequency command. Only one controller owns the PHC. The DOS civil-time copier
is a separate low-bandwidth function downstream of that PHC.

All host controllers use the accepted master Sync timestamp for relative
elapsed milliseconds and the reported applied correction. They hold the current
command on first sample and reinitialize after intervals outside 100..1500 ms,
including duplicates and wrap handling. These bounds suit the requested 4 Hz
exchange stream; arbitrary rates are not validated. Commands are limited to
100,000 ppb magnitude and 10,000 ppb change per update, matching the device.
No host controller is allowed to step the network PHC after initial firmware
acquisition. Missing accepted samples are not integrated as if they existed.

`HOST_PI` uses Kp 0.5/s and Ki 0.05/s². Conditional integration checks both
amplitude and slew saturation. `AUTO_PI` schedules Kp 0.25, 0.5, 0.75 and Ki
0.02, 0.05, 0.10, with 32-sample windows, two quiet-window hysteresis, persistent
bias detection and compensation when proportional gain changes. Offsets above
10 us select fast gains. These parameters are provisional 4 Hz choices, not a
port of tinyPTP's 1 Hz tuning or LinuxPTP's automatic gain law.

`LINREG` subtracts integrated applied correction from successive phase changes,
centers and rebases its bounded eight-point history, and begins fitting after
four points. It cancels fitted intrinsic frequency and removes fitted current
phase over four seconds. `PLLFLL` estimates intrinsic frequency from endpoint
phase change minus accumulated applied correction over at least four seconds,
then smooths successive estimates by one half. Its phase-removal time constant
is four seconds. Both explicitly account for their own clock corrections.

`KALMAN` estimates phase and intrinsic frequency. Prediction is
`phase += (frequency + applied_ppb) * dt`; the frequency is a random walk.
Measurement variance is 400 ns², frequency process density is 4 ppb²/s, and
phase process density is 1 ns²/s. Covariance uses a two-by-two Joseph update;
initial phase/frequency variances are 400 ns² and 1,000,000 ppb². The command
is `-frequency - phase/4`, with the same device bounds. These are fixed model
assumptions, not noise calibration or an accuracy certificate.

The implementations use bounded double-precision arithmetic and small fixed
arrays, without heap allocation, general matrix libraries, or compiler-specific
64-bit integers. Borland's software floating-point runtime supports the 486SX.
The existing telemetry decoder already uses that runtime. Calculations run at
4 Hz, not in an interrupt handler. Absolute epochs never enter the estimators.
The actual USB actuation delay is checked in the ACK but is not modeled within
an interval; reported correction is approximated as applying over that interval.
Large delay variation and path asymmetry can degrade results. Physical CPU cost,
worst-case serial/display delay and relative servo performance need measurement.

## Verified wire capabilities

| Command | Meaning and restriction |
| --- | --- |
| 1 | Identify/negotiate renewable lease; refuses taking over an active owner |
| 2 | START profile 1 (PI), 2 (fixed-peer GM), 3 (host follower), 4 (standalone clock) |
| 3 | STOP; restore nominal addend and buffers; require restored and unarmed ACK |
| 4 | Renew the active generation's 15-second lease |
| 5 | Set/query 1, 2 or 4 Hz while idle; rate ACK capability value 63 |
| 6 | Query host-control extension; capability value 95 |
| 7 | Profile 3 frequency adjustment; 30-byte payload, 44-byte ACK |
| 8 | Active clock RX/TX snapshots; 64-byte ACK, capability value 127 |
| 9, 10 | Frequency / one initial epoch step in profile 4 only; not emitted by PTP4D |

Op 7 binds the command to both the generation and the latest combined Sync and
Delay sequence token. The device accepts at most one correction for a completed
exchange and has a separate two-second host-actuation watchdog. Ordinary lease
renewal cannot keep that watchdog alive. PTP4D checks the returned applied ppb,
exact hardware addend, active profile/state, generation and bounded application
delay. Negative acknowledgments stop the run; commands are not blindly retried.
USB MIDI framing, canonical seven-bit encoding, CRC, nonce, sequence, opcode,
MAC, domain, endpoint, transfer length, mailbox tag and port generation checks
remain mandatory. Passive/clock-only command restrictions remain separate.

Protocol-only source audit identifiers, not installed-device version evidence:

| Reference file | SHA-256 |
| --- | --- |
| `ts_midi_control.c` | `fca2d80d91c64204e2a0e4974e81d3df9a04c94dfb6f34c196b6aa70d444e793` |
| `ts_auto_ptp.c` | `b0f18c72cfe77f4454645ad37206f2a895fbc0bb67c51e4f131f779355eaa859` |
| `ts_gm_core.c` | `b173cd49e22243f7f38d3e0d9417950f4abf0429aa0db34998c1b7f4766012ce` |
| `ts_midi_telemetry.c` | `bf2eaccfa45c2368718d690001316694fbc53686016b87ca800c57daa9a1241c` |

## Firmware work required for DOS-derived grandmaster time

A future protocol must negotiate these capabilities explicitly before PTP4D
enables `DOS2PHC`:

1. A GM preparation state with Ethernet transmission inhibited while the host
   captures, validates and seeds the PHC from DOS, followed by an acknowledged
   transition to serving without resetting the PHC or changing its generation.
2. Bounded, generation- and capture-bound GM frequency adjustment, a watchdog
   independent of lease renewal, verified actuation, and stop-on-source-loss.
   A later large DOS step must stop serving and restart acquisition.
3. Explicit epoch/timescale, UTC-offset validity, leap flags and validity expiry.
   DOS input has BIOS-tick granularity and USB transfer uncertainty. No claim of
   nanosecond accuracy is justified by the PHC timestamp resolution.
4. Conservative Announce/source-quality handling if general PTP grandmaster
   interoperability is implemented: ordinary free-running clock class (for
   example 248), unknown accuracy (0xFE), unspecified variance (0xFFFF),
   internal-oscillator source (0xA0), and time/frequency traceability flags clear.
   UTC/PTP-timescale flags must follow validated source metadata, never an
   assumption that DOS time is externally synchronized. Wire values must be
   verified against the applicable PTP profile before implementing that extension.
   The proposed conservative values follow LinuxPTP's
   [default dataset](https://github.com/richardcochran/linuxptp/blob/master/configs/default.cfg)
   and [source definitions](https://github.com/richardcochran/linuxptp/blob/master/ds.h).
5. Regression tests for role transitions, epoch preservation, source invalidity,
   loss of host, stale capture, leap behavior, quality announcements, STOP and
   mutual exclusion with the network follower. Hardware validation must follow
   after the occupied device is released.

This is a required firmware contract, not an implemented or advertised feature
of the current executable. The private firmware has not been modified or flashed.
