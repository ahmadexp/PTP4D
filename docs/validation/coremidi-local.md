# CoreMIDI local validation, 2026-11-20

Host: Apple Silicon (`arm64`), macOS 27.0.1 (26A434), Python 3.14.6.
The implementation uses Python's standard library and the installed CoreMIDI
and CoreFoundation frameworks. It does not require a MIDI package or compiler.

## Software checks

`python3 tools/test.py` passed:

- C89 protocol, options, servo, clock and MIDI suites under AddressSanitizer
  and UndefinedBehaviorSanitizer.
- All 27 simulated DOS sessions, including the servo variants and injected
  command, lease, timestamp and cleanup faults.
- All 33 Python tests, including exact USB/serial selection, offline filtering,
  same-entity endpoint pairing, ARM and Intel packet layouts, packets larger
  than 256 bytes, fragmentation, queue overflow, disconnection, and cleanup.
- The peer lifecycle with correlated ACKs, passive identity checks, verified
  rate selection, generation-bound renewals, cancellation, missing START ACK,
  and rejected or missing STOP restoration.
- Actual CoreMIDI input and output through temporary virtual endpoints. The
  native packet-list constructors and callbacks were exercised in both
  directions, including fragmented SysEx larger than 256 bytes. These tests
  selected only the virtual endpoints and sent nothing to USB hardware.

The CI workflow now includes Linux and macOS. The virtual CoreMIDI test is
skipped on Linux; its portable identity and packet tests run on both. No new
CI result is claimed here. Intel packet layout is unit-tested but has not been
exercised on a physical Intel Mac. The DOS source and binaries are unchanged
by this transport addition.

## Passive physical-device check

`python3 tools/peer.py --list` selected one online USB device with vendor/product
`0b95:1790`, its expected serial, and one identified CoreMIDI source/destination
pair. Saved offline CoreMIDI device records were excluded.

Two three-second receive-only checks completed with the expected MAC and
domain 42. They received 13 and 14 CRC-valid version 2, kind `0x10` telemetry
records respectively. Both reported firmware flags 0, generation 0, and zero
commands sent. Receive-only mode creates no output port.

One separate client-creation attempt returned CoreMIDI OSStatus `-304` before
any port was opened. A fresh command succeeded. The cause was not established;
the controller reports startup errors and requires an explicit retry, without
automatically reopening a device or retrying timing commands. No MIDI server
or device was reset by the controller.

No physical START, rate change, renewal, STOP, clock adjustment, or firmware
operation was sent. PicoPCMCIA ownership and SD transfers were untouched.
The device identifiers and raw local logs are kept outside the published
evidence. Live Mac-to-DOS PTP, servo convergence, accuracy, and PC110 recovery
remain unverified for this transport and are deferred until SD transfers finish.

Follow the [setup and servo trial procedure](../setup.md) for the later run.
