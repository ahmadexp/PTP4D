#!/usr/bin/env python3
"""Recompute and plot PC110 servo captures, retaining interruption labels."""
import argparse
import csv
import json
import math
import pathlib

from servo_metrics import rolling_mean, summarize

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / 'docs/validation/servo-long-20261120'
ORDER = ['PI', 'HOST_PI', 'AUTO_PI', 'LINREG', 'KALMAN', 'PLLFLL']
COLORS = ['#0072B2', '#D55E00', '#009E73', '#56B4E9', '#AA4499', '#8C7500']


def load(data):
    plan = json.loads((data / 'plan.json').read_text())
    evidence = json.loads((data / 'summary.json').read_text())
    trials = []
    for name, color in zip(ORDER, COLORS):
        analysis = json.loads((data / name.lower() / 'analysis.json').read_text())
        accepted = next(t for t in evidence['trials'] if t['servo'] == name)
        rows = analysis['rows']
        if len(rows) != accepted['exchanges']:
            raise ValueError(f'{name}: capture is incomplete')
        for key in ('records', 't1_matches', 't4_matches', 'arithmetic_matches'):
            if analysis[key] != len(rows):
                raise ValueError(f'{name}: {key} does not cover the full capture')
        for row in rows:
            t1, t2, t3, t4 = row['t_ns']
            if row['offset_ns'] != ((t2-t1)-(t4-t3))/2 or row['delay_ns'] != ((t2-t1)+(t4-t3))/2:
                raise ValueError(f'{name}: timestamp arithmetic mismatch')
        metrics = summarize(rows, plan['settling_band_ns'], plan['settling_dwell_seconds'],
                            plan['stability_window_seconds'])
        metrics.update(servo=name, host_commands=accepted['host_commands'],
                       renewals=accepted['renewals'], sync_gaps=accepted['sync_gaps'],
                       delay_gaps=accepted['delay_gaps'],
                       completed_planned_duration=accepted['completed_planned_duration'],
                       requested_seconds=accepted['requested_seconds'], end_reason=accepted['end_reason'])
        if metrics['sample_gaps_over_limit'] or metrics['sync_gaps'] or metrics['delay_gaps']:
            raise ValueError(f'{name}: missing samples invalidate a continuous comparison')
        times = [(r['t_ns'][0] - rows[0]['t_ns'][0]) / 1e9 for r in rows]
        label=name if accepted['completed_planned_duration'] else name+'*'
        trials.append(dict(name=name, label=label, color=color, rows=rows, times=times, metrics=metrics))
    return plan, trials


def export(data, plan, trials):
    comparison = dict(time_origin=plan['time_origin'], settling_band_ns=plan['settling_band_ns'],
                      settling_dwell_seconds=plan['settling_dwell_seconds'],
                      stability_window_seconds=plan['stability_window_seconds'],
                      trials=[t['metrics'] for t in trials])
    (data / 'comparison.json').write_text(json.dumps(comparison, indent=2) + '\n')
    with (data / 'comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(trials[0]['metrics']), lineterminator='\n')
        writer.writeheader()
        writer.writerows(t['metrics'] for t in trials)
    with (data / 'exchanges.csv').open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['servo', 'exchange', 'elapsed_seconds', 'sync', 'delay_sequence',
                         'offset_ns', 'path_delay_ns', 'reported_rate_ppb', 't1_ns', 't2_ns', 't3_ns', 't4_ns'])
        for trial in trials:
            for i, (time, row) in enumerate(zip(trial['times'], trial['rows']), 1):
                writer.writerow([trial['name'], i, f'{time:.9f}', row['sync'], row['delay_sequence'],
                                 row['offset_ns'], row['delay_ns'], row['rate_ppb'], *row['t_ns']])


def figures(data, plan, trials):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from plot_servos import axes_style, heading

    matplotlib.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                                'axes.labelcolor': '#334155', 'text.color': '#142D45',
                                'svg.hashsalt': 'ptp4d-long-servo-20261120'})

    def save(fig, name):
        for suffix in ('png', 'svg'):
            path = data / (name + '.' + suffix)
            metadata = {'Software': 'PTP4D'} if suffix == 'png' else {'Creator': 'PTP4D', 'Date': None}
            fig.savefig(path, dpi=180, facecolor='white', metadata=metadata)
            if suffix == 'svg':
                path.write_text('\n'.join(s.rstrip() for s in path.read_text().splitlines()) + '\n')
            print(path)
        plt.close(fig)

    band = plan['settling_band_ns']
    dwell = plan['settling_dwell_seconds']
    span = plan['seconds_per_servo']
    max_offset = max(abs(r['offset_ns']) for t in trials for r in t['rows'])
    ylim = 10 ** math.ceil(math.log10(max(max_offset, 1000)))
    for name, title, xmax in (
        ('long-servo-offsets', 'Full captures from six servo runs', span),
        ('long-servo-settling', 'Settling from the first complete exchange', 120),
    ):
        fig, axes = plt.subplots(2, 3, figsize=(13.2, 8.4), sharex=True, sharey=True)
        fig.subplots_adjust(left=.095, right=.98, bottom=.22, top=.79, wspace=.15, hspace=.35)
        heading(fig, title, f'PC110 + TimeStick | 4 Hz | Green band: +/-{band} ns | Required dwell: {dwell} s')
        for ax, trial in zip(axes.flat, trials):
            axes_style(ax)
            ax.axhspan(-band, band, color='#D8EEE5', alpha=.65, zorder=0)
            ax.plot(trial['times'], [r['offset_ns'] for r in trial['rows']], color=trial['color'], linewidth=1.1)
            ax.set_yscale('symlog', linthresh=band)
            ax.set_ylim(-ylim, ylim)
            ax.set_xlim(0, xmax)
            if not trial['metrics']['completed_planned_duration'] and xmax > trial['times'][-1]:
                ax.axvspan(trial['times'][-1], xmax, color='#E2E8F0', alpha=.65)
                ax.text(.98, .08, 'No data after 379.8 s', transform=ax.transAxes, ha='right', fontsize=8)
            entry = trial['metrics']['settling_entry_seconds']
            confirmed = trial['metrics']['settling_confirmed_seconds']
            label = 'No qualifying dwell' if entry is None else f'Entry {entry:.1f} s; confirmed {confirmed:.1f} s'
            if entry is not None:
                ax.axvline(entry, color=trial['color'], linestyle='--', linewidth=1)
                ax.axvspan(entry, confirmed, color=trial['color'], alpha=.07)
            ax.set_title(trial['label'], loc='left', fontsize=12, fontweight='bold', pad=10)
            ax.text(.02, .96, label, transform=ax.transAxes, va='top', fontsize=9,
                    bbox=dict(facecolor='white', edgecolor='none', alpha=.8, pad=2))
        fig.supylabel('Reported PTP offset (ns), symmetric log scale', x=.012, fontsize=12)
        fig.supxlabel('Seconds since first complete accepted exchange', y=.13, fontsize=12)
        fig.text(.075, .048,
                 'All accepted exchanges retained; axes match. Linear inside the green band, logarithmic outside. Hardware startup is excluded.\n'
                 '* LINREG ended at 379.8 s after a serial-console timeout; other runs span about 599 s. No missing data is filled.',
                 fontsize=9.8, color='#475569', linespacing=1.7)
        save(fig, name)

    window = plan['stability_window_seconds']
    tail_extreme = max(abs(r['offset_ns']) for t in trials
                       for sec, r in zip(t['times'], t['rows']) if sec >= t['times'][-1] - window)
    limit = max(25, math.ceil(tail_extreme / 10) * 10)
    fig, axes = plt.subplots(2, 3, figsize=(13.2, 8.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=.085, right=.98, bottom=.22, top=.79, wspace=.15, hspace=.35)
    heading(fig, 'Stability over the final five minutes',
            'Thin trace: every reported offset | Thick trace: trailing 10-second mean | Same axes in every panel')
    for ax, trial in zip(axes.flat, trials):
        axes_style(ax)
        times = [s - trial['times'][-1] for s in trial['times']]
        values = [r['offset_ns'] for r in trial['rows']]
        ax.plot(times, values, color=trial['color'], alpha=.35, linewidth=.6)
        ax.plot(times, rolling_mean(trial['times'], values, plan['rolling_window_seconds']),
                color=trial['color'], linewidth=1.6)
        ax.axhline(0, color='#64748B', linewidth=.7, zorder=0)
        ax.set_xlim(-window, 0)
        ax.set_ylim(-limit, limit)
        ax.set_xticks([-300, -200, -100, 0])
        m = trial['metrics']
        ax.set_title(f"{trial['label']}  |  mean {m['stability_mean_offset_ns']:.2f}, SD {m['stability_stddev_offset_ns']:.2f} ns",
                     loc='left', fontsize=10.5, pad=12)
    fig.supylabel('Reported PTP offset (ns)', x=.015, fontsize=12)
    fig.supxlabel('Seconds relative to last complete exchange', y=.13, fontsize=12)
    fig.text(.075, .05,
             '* LINREG: final 300 s of its interrupted 379.8 s capture; others: final 300 s of about 599 s. Every raw point is shown.\n'
             'Reported offsets assume symmetric paths. No external PPS/UTC calibration or long-term stability measurement was made.',
             fontsize=10, color='#475569', linespacing=1.7)
    save(fig, 'long-servo-stability')

    max_rate = max(abs(r['rate_ppb']) for t in trials for r in t['rows'])
    rate_limit = 10 ** math.ceil(math.log10(max(100, max_rate)))
    fig, axes = plt.subplots(2, 3, figsize=(13.2, 8.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=.095, right=.98, bottom=.22, top=.79, wspace=.15, hspace=.35)
    heading(fig, 'Frequency corrections through the full runs',
            'PI runs in the TimeStick | The other five controllers run on DOS | Same scale in every panel')
    for ax, trial in zip(axes.flat, trials):
        axes_style(ax)
        ax.step(trial['times'], [r['rate_ppb'] for r in trial['rows']], where='post',
                color=trial['color'], linewidth=1.1)
        ax.axhline(0, color='#64748B', linewidth=.7, zorder=0)
        ax.set_yscale('symlog', linthresh=10)
        ax.set_ylim(-rate_limit, rate_limit)
        ax.set_xlim(0, span)
        if not trial['metrics']['completed_planned_duration']:
            ax.axvspan(trial['times'][-1], span, color='#E2E8F0', alpha=.65)
            ax.text(.98, .08, 'No data after 379.8 s', transform=ax.transAxes, ha='right', fontsize=8)
        ax.set_title(trial['label'], loc='left', fontsize=12, fontweight='bold', pad=10)
    fig.supylabel('Reported frequency correction (ppb), symmetric log scale', x=.012, fontsize=12)
    fig.supxlabel('Seconds since first complete accepted exchange', y=.13, fontsize=12)
    fig.text(.075, .05,
             'Linear scale between -10 and +10 ppb, logarithmic outside. Steps connect reports; exact USB actuation times are not plotted.\n'
             '* LINREG was interrupted at 379.8 s. Large early corrections remove phase error; they do not directly measure oscillator drift.',
             fontsize=10, color='#475569', linespacing=1.7)
    save(fig, 'long-servo-corrections')

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 7.2))
    fig.subplots_adjust(left=.12, right=.95, bottom=.23, top=.77, wspace=.35)
    heading(fig, 'Settling and observed stability',
            f'Settling: +/-{band} ns for {dwell} continuous seconds | Stability: RMS offset over the final {window} seconds')
    for ax in axes:
        axes_style(ax)
        ax.grid(False)
        ax.grid(axis='x', color='#E2E8F0', linewidth=.7)
        ax.set_yticks(range(6), [t['label'] for t in trials])
        ax.invert_yaxis()
    for i, trial in enumerate(trials):
        entry = trial['metrics']['settling_entry_seconds']
        rms = trial['metrics']['stability_rms_offset_ns']
        axes[0].barh(i, entry if entry is not None else span, color=trial['color'], alpha=.8,
                     hatch=None if entry is not None else '//', height=.55)
        axes[0].text(entry or 0, i, f'  {entry:.1f} s' if entry is not None else '  No qualifying dwell', va='center', fontsize=10)
        axes[1].barh(i, rms, color=trial['color'], alpha=.8, height=.55)
        axes[1].text(rms, i, f'  {rms:.2f} ns', va='center', fontsize=10)
    axes[0].set_xlabel('Entry time since first complete exchange (s)', labelpad=12)
    axes[1].set_xlabel('Final-five-minute RMS offset (ns)', labelpad=12)
    axes[0].set_title('First qualifying settling interval', loc='left', pad=16)
    axes[1].set_title('Bias and variation combined', loc='left', pad=16)
    for ax in axes:
        ax.set_xlim(0, ax.get_xlim()[1] * 1.3)
    fig.text(.075, .065,
             'RMS includes both mean offset and sample variation. The accompanying table also reports SD, 95th percentile, peak, and later excursions.\n'
             '* LINREG was interrupted at 379.8 s; five other runs completed 10 minutes. Different durations and initial offsets limit ranking.',
             fontsize=9.8, color='#475569', linespacing=1.7)
    save(fig, 'long-servo-comparison')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=pathlib.Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    plan, trials = load(args.data)
    export(args.data, plan, trials)
    figures(args.data, plan, trials)


if __name__ == '__main__':
    main()
