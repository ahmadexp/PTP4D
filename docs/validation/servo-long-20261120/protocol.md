# Ten-minute servo comparison protocol

The plan was recorded before the long runs on 2026-11-20. Each selection runs
for 600 seconds on the same IBM PC110, PicoPCMCIA, and TimeStick pair, in domain
42 at 4 Hz with `/SYNC NONE`. The laptop controls the grandmaster through CoreMIDI.
No DOS date/time or RTC setters are enabled.

The recorded randomized order, using seed 20261120, is AUTO_PI, PI, HOST_PI,
PLLFLL, KALMAN, LINREG. A separate 30-second KALMAN capture check precedes this
batch and is excluded from the comparison. Each controller gets one long run.
There is no injected common phase step or temperature control. Initial offsets
are therefore reported, and the results describe these runs rather than a
definitive ranking of the controller algorithms.

## Full capture

The published 0.5 executable retains only its final 128 exchanges. These trials
use a separate `PTPLONG.EXE`, built from the same servo and protocol code with
`build-dos.py --full-capture`. The capture build allocates five 47-KiB RAM banks
before taking PICOCARD ownership, for 2560 complete 94-byte records. It stops
with an explicit error if the buffer fills; records are never overwritten.
At 4 Hz this provides headroom for a ten-minute run.

The complete CSV report is written to a DOS file after STOP and card restoration.
No DOS file I/O is added to the active control loop. The report is then read back
through COMrade, with transfer checksums verified. The original release binary
and previous test executable remain separate.

All complete accepted exchanges from the follower are retained, from first
measurement through the end of the run. Configuration, link acquisition, and
the firmware's initial epoch acquisition precede the first complete measurement;
their timing is not included in the settling metric. Plot time is computed from
the grandmaster's hardware t1 timestamps, relative to the first retained exchange.
The laptop's wall clock does not supply this axis.

## Acceptance

- The number of CSV records must equal the DOS exchange count.
- Every t1 and t4 must match the corresponding grandmaster record, including a
  second correlation restricted to the active grandmaster generation.
- Independent t1..t4 calculations must reproduce every offset and path delay.
- Sync and Delay sequence numbers must be consecutive throughout the capture.
- Samples must be monotonically timed; a gap greater than 375 ms at the requested
  4 Hz interrupts any settling dwell and invalidates the continuous comparison.
- No grandmaster timestamp error, command failure, capture overflow, or forced
  Esc is accepted. Host servos must acknowledge corrections across the full run.
- Both endpoints must acknowledge STOP/restoration, and the PC110 must return
  to its DOS prompt before another trial begins.

## Settling definition

The fixed settling band is **-100 to +100 ns**, inclusive. The entry time is
the first sample inside that band followed by at least **20 continuous seconds**
of samples remaining inside it. Confirmation time is reported separately, since
the qualifying interval cannot be known at entry. A missing sample interval
breaks the dwell; missing points are never filled or interpolated.

The comparison also reports the number of out-of-band samples after confirmation
and a separate last-exit settling time. Last-exit settling requires remaining
inside the band through the end of the capture, with at least 20 seconds observed
after entry. If a criterion is not met, it is reported as unestablished, not zero.
This band is an analysis criterion, not a calibrated physical accuracy bound.

## Stability definition

The final **300 seconds** of each capture form the common stability window.
Report its sample count, mean offset, population standard deviation, RMS offset,
95th percentile of absolute offset, maximum absolute offset, in-band fraction,
and fitted offset trend in ns/s. RMS includes mean bias and sample variation.
The percentile uses linear interpolation between sorted observations (type 7).

Plots preserve raw observations and separately label a trailing 10-second mean.
Sequential measurements are not independent repetitions; no confidence interval
or uncertainty of the mean is inferred. The correction trace is the reported
frequency actuation, not a direct estimate of the oscillator's intrinsic drift.

The observed difference between the two TimeStick clocks is a PTP-reported offset
under the symmetric-path assumption. It is not an external PPS comparison or
an absolute UTC calibration. Ten minutes tests settling and short-term behavior,
not hours-long temperature drift, holdover, or long-term stability.
