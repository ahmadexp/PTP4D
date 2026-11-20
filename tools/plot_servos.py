#!/usr/bin/env python3
"""Plot the recorded PC110 servo trials. Requires matplotlib; reads no hardware."""
import csv
import json
import math
import pathlib
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/validation/servo-20261120'
STYLE = {
    'PI': ('#0072B2', '-', 'TimeStick firmware PI'),
    'HOST_PI': ('#D55E00', '--', 'DOS fixed PI'),
    'AUTO_PI': ('#009E73', '-.', 'DOS adaptive PI'),
    'LINREG': ('#56B4E9', ':', 'DOS linear regression'),
    'KALMAN': ('#AA4499', (0, (5, 2)), 'DOS Kalman estimator'),
    'PLLFLL': ('#8C7500', (0, (3, 1, 1, 1)), 'DOS PLL/FLL'),
}


def load_trials():
    summary = json.loads((DATA / 'summary.json').read_text())
    trials = []
    for recorded in summary['trials']:
        name = recorded['servo']
        analysis = json.loads((DATA / name.lower() / 'analysis.json').read_text())
        rows = analysis['rows']
        if len(rows) != summary['retained_window_records']:
            raise ValueError(f'{name}: incomplete retained window')
        for key in ('records', 't1_matches', 't4_matches', 'arithmetic_matches'):
            if analysis[key] != len(rows) or recorded[key] != len(rows):
                raise ValueError(f'{name}: invalid evidence count {key}')
        times = [r['t_ns'][0] for r in rows]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError(f'{name}: nonmonotonic master timestamps')
        for row in rows:
            t1, t2, t3, t4 = row['t_ns']
            if (row['offset_ns'] != ((t2 - t1) - (t4 - t3)) / 2 or
                    row['delay_ns'] != ((t2 - t1) + (t4 - t3)) / 2):
                raise ValueError(f'{name}: timestamp arithmetic mismatch')
        tail = [r['offset_ns'] for r in rows[-summary['statistics_window_records']:]]
        checks = {
            'last_window_mean_offset_ns': statistics.mean(tail),
            'last_window_max_abs_offset_ns': max(map(abs, tail)),
            'last_window_stddev_offset_ns': statistics.pstdev(tail),
        }
        for key, value in checks.items():
            if not math.isclose(value, recorded[key], abs_tol=1e-12):
                raise ValueError(f'{name}: summary mismatch for {key}')
        trials.append(dict(name=name, rows=rows, tail=tail,
                           seconds=[(t - times[-1]) / 1e9 for t in times]))
    if [t['name'] for t in trials] != list(STYLE):
        raise ValueError('Unexpected servo order or missing trial')
    return summary, trials


def axes_style(ax):
    ax.set_facecolor('#FFFFFF')
    ax.spines[['top', 'right']].set_visible(False)
    ax.spines[['left', 'bottom']].set_color('#CBD5E1')
    ax.tick_params(colors='#475569', length=0, pad=7)
    ax.grid(axis='y', color='#E2E8F0', linewidth=0.7)
    ax.set_axisbelow(True)


def heading(fig, title, subtitle):
    fig.suptitle(title, x=0.075, y=0.98, ha='left', fontsize=22,
                 fontweight='bold', color='#142D45')
    fig.text(0.075, 0.92, subtitle, fontsize=11.5, color='#475569')


def save(fig, name):
    for suffix in ('png', 'svg'):
        target = DATA / (name + '.' + suffix)
        metadata = {'Software': 'PTP4D'} if suffix == 'png' else {'Creator': 'PTP4D', 'Date': None}
        fig.savefig(target, dpi=180, facecolor='white', metadata=metadata)
        if suffix == 'svg':
            target.write_text('\n'.join(line.rstrip() for line in target.read_text().splitlines()) + '\n')
        print(target.relative_to(ROOT))
    plt.close(fig)


def plot_offsets(trials):
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 7.2))
    fig.subplots_adjust(left=0.075, right=0.975, bottom=0.22, top=0.76, wspace=0.24)
    heading(fig, 'How the six servos settle',
            'Recorded PC110 trials | TimeStick pair | macOS CoreMIDI grandmaster | 4 Hz | 20 Nov 2026')
    for trial in trials:
        color, dash, _ = STYLE[trial['name']]
        for ax, first in zip(axes, (0, -40)):
            ax.plot(trial['seconds'][first:], [r['offset_ns'] for r in trial['rows'][first:]],
                    color=color, linestyle=dash, linewidth=1.8, label=trial['name'])
    for ax in axes:
        axes_style(ax)
        ax.axhline(0, color='#64748B', linewidth=0.8, zorder=0)
        ax.set_xlabel('Seconds relative to last retained exchange', labelpad=12)
        ax.set_ylabel('Reported PTP offset (ns)', labelpad=10)
    axes[0].set_title('Final 128 exchanges: about 32 seconds', loc='left', pad=14)
    axes[0].set_xlim(-32, 0)
    axes[0].set_xticks([-30, -20, -10, 0])
    axes[0].axvspan(trials[0]['seconds'][-40], 0, color='#E2E8F0', alpha=0.45, zorder=0)
    axes[1].set_title('Detail: final 40 exchanges', loc='left', pad=14)
    axes[1].set_xlim(-10, 0)
    axes[1].set_xticks([-10, -8, -6, -4, -2, 0])
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(0.07, 0.88),
               ncol=6, frameon=False, columnspacing=1.5, handlelength=2.5, fontsize=10.5)
    fig.text(0.075, 0.09,
             'Each line is a separate 60-second trial, aligned at its last retained exchange. Startup is outside this capture.\n'
             'Single runs with different initial conditions; PTP-reported offsets, without external PPS or UTC calibration.',
             fontsize=10.5, color='#475569', linespacing=1.7)
    save(fig, 'servo-offsets')


def plot_corrections(trials):
    fig, axes = plt.subplots(2, 3, figsize=(13.2, 8.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.085, right=0.975, bottom=0.21, top=0.79, wspace=0.16, hspace=0.36)
    heading(fig, 'The corrections behind the response',
            'Reported frequency correction | Final 128 exchanges per trial | Same scale in every panel')
    for ax, trial in zip(axes.flat, trials):
        color, _, description = STYLE[trial['name']]
        axes_style(ax)
        ax.step(trial['seconds'], [r['rate_ppb'] for r in trial['rows']], where='post',
                color=color, linewidth=1.6)
        ax.axhline(0, color='#64748B', linewidth=0.8, zorder=0)
        ax.set_title(f"{trial['name']}  |  {description}", loc='left', fontsize=11.5, pad=12)
        ax.set_xlim(-32, 0)
        ax.set_ylim(-250, 55)
        ax.set_xticks([-30, -20, -10, 0])
        ax.set_yticks([-200, -100, 0])
    fig.supylabel('Reported frequency correction (ppb)', x=0.017, fontsize=12)
    fig.supxlabel('Seconds relative to last retained exchange', y=0.125, fontsize=12)
    fig.text(0.085, 0.045,
             'PI runs in the TimeStick; the other five controllers run on DOS. Steps connect reports; exact actuation times are not plotted.\n'
             'Separate runs start from different oscillator states; these traces do not isolate controller quality or intrinsic drift.',
             fontsize=10.5, color='#475569', linespacing=1.7)
    save(fig, 'servo-corrections')


def plot_distribution(trials):
    fig, ax = plt.subplots(figsize=(13.2, 7.2))
    fig.subplots_adjust(left=0.13, right=0.975, bottom=0.24, top=0.78)
    heading(fig, 'Where each servo finished',
            'Final 40 exchanges per trial, about 10 seconds | Every dot is one measured PTP offset')
    axes_style(ax)
    ax.grid(False)
    ax.grid(axis='x', color='#E2E8F0', linewidth=0.7)
    boxes = ax.boxplot([t['tail'] for t in trials], orientation='horizontal',
                       tick_labels=[t['name'] for t in trials], patch_artist=True,
                       widths=0.5, whis=(0, 100), showmeans=True, showfliers=False,
                       meanprops=dict(marker='D', markerfacecolor='#142D45', markeredgecolor='white', markersize=6),
                       medianprops=dict(color='#142D45', linewidth=1.8),
                       whiskerprops=dict(color='#64748B'), capprops=dict(color='#64748B'))
    for index, (trial, box) in enumerate(zip(trials, boxes['boxes']), 1):
        color = STYLE[trial['name']][0]
        box.set(facecolor=color, edgecolor=color, alpha=0.22)
        jitter = [index + ((i * 3) % 11 - 5) * 0.025 for i in range(len(trial['tail']))]
        ax.scatter(trial['tail'], jitter, color=color, alpha=0.65, s=18, linewidths=0, zorder=2)
    ax.axvline(0, color='#64748B', linewidth=0.8, zorder=0)
    ax.invert_yaxis()
    ax.set_xlabel('Reported PTP offset (ns)', labelpad=12)
    ax.set_xlim(-30, 105)
    fig.legend([Line2D([], [], color='#142D45', marker='D', linestyle='None'),
                Line2D([], [], color='#142D45', linewidth=1.8)], ['Mean', 'Median'],
               loc='upper left', bbox_to_anchor=(0.07, 0.88), ncol=2, frameon=False, fontsize=10.5)
    fig.text(0.075, 0.085,
             'Boxes show the middle 50% of samples; whiskers span the observed minimum and maximum. No confidence interval is implied.\n'
             'HOST_PI retained a positive residual in this run. Repeated, longer trials are needed to compare performance.',
             fontsize=10.5, color='#475569', linespacing=1.7)
    save(fig, 'servo-final-offsets')


def main():
    matplotlib.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                                'axes.labelcolor': '#334155', 'text.color': '#142D45',
                                'svg.hashsalt': 'ptp4d-servo-20261120'})
    _, trials = load_trials()
    with (DATA / 'exchanges.csv').open('w', newline='') as handle:
        writer = csv.writer(handle, lineterminator='\n')
        writer.writerow(['servo', 'seconds_to_last_exchange', 'sync', 'delay_sequence',
                         'offset_ns', 'path_delay_ns', 'reported_rate_ppb',
                         't1_ns', 't2_ns', 't3_ns', 't4_ns'])
        for trial in trials:
            for seconds, row in zip(trial['seconds'], trial['rows']):
                writer.writerow([trial['name'], f'{seconds:.9f}', row['sync'], row['delay_sequence'],
                                 row['offset_ns'], row['delay_ns'], row['rate_ppb'], *row['t_ns']])
    plot_offsets(trials)
    plot_corrections(trials)
    plot_distribution(trials)


if __name__ == '__main__':
    main()
