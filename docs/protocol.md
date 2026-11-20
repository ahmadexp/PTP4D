# Protocol and implementation notes

## DOS and PicoPCMCIA

PTP4D uses the PicoPCMCIA v0.22 USB pass-through mailbox, protocol 2. The historical run used stock firmware; numeric version words do not distinguish patch suffixes. The later [servo trials](validation/servo-20261120/) exercised all follower servos with `/SYNC NONE`; civil-time writes remain unverified on hardware. PTP4D first asks the resident PICOCARD driver for its memory window, verifies firmware version and startup state, and obtains exclusive staging ownership. Saved SWD state, busy mailboxes, active block-disk mode, or unsupported firmware cause a refusal before transfers begin.

USB slot 0 is at offset `04E8h`, the four port-generation words at `0568h`, and shared staging at `1000h`. A command's tag byte is written before the opcode byte. Completion requires the matching tag, successful status, a bounded returned length, and an unchanged port generation. USB control requests in the utility are IN-only. Selected MIDI timing commands use bulk OUT.

The utility disarms PICOCARD and stops SD/CD streams before accessing staging. It avoids DOS console and filesystem calls while holding staging. Explicit PHC2DOS mode uses only the DOS date/time CLOCK$ services during ownership; the live display uses BIOS video services. A transfer timeout requests a USB stack reset and waits for the old generation to disappear before releasing memory. Failed recovery leaves the resident disarmed and requires a DOS reboot.

## TimeStick identification and transport

The tested device identifies as vendor `0B95h`, product `1790h`, device revision `0500h`, with product string AX88279A. This identifies the controller, not an authenticated board identity.

The timing firmware exposes a MIDIStreaming USB interface. PTP4D parses the configuration descriptor and finds full-speed 64-byte bulk endpoints. The tested endpoints are IN `84h` and OUT `05h`. USB MIDI event packets are reassembled across USB transfers, then checked for canonical 7-bit encoding and CRC-16/CCITT.

The timing SysEx prefix is `F0 7D 54 53 4B`, followed by version and message kind. Every raw payload byte is encoded as low seven bits followed by its high bit. The little-endian CRC uses seed `FFFFh` and polynomial `1021h`. Messages end with `F7h`.

The host rejects unsolicited or mismatched ACKs. A command reply must match its nonce, sequence, operation, device MAC, domain and expected payload length. The protocol is specific to the TimeStick timing firmware; ordinary ASIX Ethernet firmware is not sufficient.

## Servo and leases

The compatible default chooses firmware profile 1, the PI follower. New host controllers use profile 3 after an op 6 capability query. DOS and the Linux/macOS peer can select profile 2, the fixed-peer free-running source. These use domain 42 and a 4 Hz exchange rate. Clock-only reads use profile 4. See the [protocol capability audit](servo-inventory.md).

The PI controller runs inside TimeStick firmware. Hardware timestamps yield the offset and path-delay measurement; the firmware applies bounded frequency corrections with anti-windup. In profile 1, PTP4D observes the acknowledged correction. In profile 3, the firmware disables its network PI controller and DOS supplies bounded op 7 corrections. The two controllers never run together.

Host corrections are sent as soon as a complete measurement is available. The
receiver consumes the current USB packet, then returns before another blocking
IN request can wait for a newer exchange and invalidate the measurement token.
Telemetry received while waiting for an ACK is serviced before the next input
request as well. The firmware's latest-exchange binding and rejection checks
remain in force; a rejected correction stops the session. Failure reports retain
the host-command ACK details before STOP replaces the normal last-ACK fields.

PTP sessions explicitly negotiate renewable operation with a 15-second lease. DOS renews roughly every four seconds, and the Linux/macOS peer every five. Renewals bind to the active generation. STOP must acknowledge an unarmed session and restored nominal frequency/buffers. A missing renewal cannot revive an expired generation. A stale follower exchange stream terminates the DOS run.

## Measurements

A complete follower telemetry record carries t1 through t4, Sync and Delay sequence numbers, signed Q17 offset and delay numerators, frequency correction in ppb, and the hardware addend. PTP4D decodes signed 64-bit values without requiring a 64-bit DOS compiler integer type.

For the included direct grandmaster run, correction fields are zero, so the independent checks use:

```text
offset = ((t2 - t1) - (t4 - t3)) / 2
mean path delay = ((t2 - t1) + (t4 - t3)) / 2
```

The last 128 unique exchanges are retained in memory and emitted as CSV after releasing the card. The published evidence contains the timing records and omits machine/account/network identifiers. Screenshots are direct, unedited KVM captures of the physical PC110 display.

A small reported PTP offset assumes symmetric path delay. It is not proof of absolute UTC accuracy or externally calibrated PPS alignment. DOS and Linux system clocks remained unchanged in that evidence run. The new explicit PHC2DOS path has separate [civil-time gates and limitations](clock-modes.md); it has not been hardware-validated.
