#!/usr/bin/env python3
"""Regenerate the published timing figure from CSV. Requires matplotlib."""
import csv
import pathlib
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = pathlib.Path(__file__).resolve().parents[1]
with (root / 'docs/validation/exchanges.csv').open() as source:
    rows = list(csv.DictReader(source))
start = int(rows[0]['t1_ns'])
seconds = [(int(row['t1_ns']) - start) / 1e9 for row in rows]
offsets = [float(row['offset_ns']) for row in rows]
tail = offsets[-40:]

plt.rcParams.update({'font.size': 12})
fig, ax = plt.subplots(figsize=(10.2, 4.7), layout='constrained')
ax.plot(seconds, offsets, color='#086eaa', linewidth=1.5)
ax.axhline(0, color='#666666', linewidth=0.8)
ax.set(title='PTP4D: PC110 TimeStick follower vs. hardware grandmaster',
       xlabel='Seconds since first retained exchange', ylabel='Reported PTP offset (ns)')
ax.grid(alpha=0.2)
fig.supxlabel(f'{len(rows)} retained hardware exchanges, 4 Hz. Final 40: mean '
              f'{statistics.mean(tail):.3f} ns, maximum |offset| {max(map(abs, tail)):.1f} ns.',
              fontsize=10)
output = root / 'docs/validation/offset.png'
fig.savefig(output, dpi=150)
print(output)
