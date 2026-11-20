"""Time-based settling and descriptive stability statistics for PTP captures."""
import math
import statistics


def percentile(values, fraction):
    """Linear interpolation between sorted observations (inclusive/type 7)."""
    ordered = sorted(values)
    if not ordered or not 0 <= fraction <= 1:
        raise ValueError('Percentile requires observations and a fraction in [0, 1]')
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def summarize(rows, band_ns=100, dwell_seconds=20, stability_seconds=300, max_gap_seconds=.375):
    """Measure from the first complete exchange; never infer missing samples.

    Settling is the entry time of the first uninterrupted in-band dwell, with
    a separate confirmation time. Last-exit settling requires staying in band
    through the end and at least one full dwell of remaining observation.
    """
    if not rows or band_ns <= 0 or dwell_seconds <= 0 or stability_seconds <= 0:
        raise ValueError('Nonempty capture and positive thresholds are required')
    origin = rows[0]['t_ns'][0]
    times = [(r['t_ns'][0] - origin) / 1e9 for r in rows]
    offsets = [r['offset_ns'] for r in rows]
    if any(not math.isfinite(v) for v in offsets):
        raise ValueError('Nonfinite offset')
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Master timestamps must be strictly increasing')
    if times[-1] < stability_seconds:
        raise ValueError('Capture is shorter than the requested stability window')
    first = confirmed = None
    start = None
    gaps = 0
    for i, (time, offset) in enumerate(zip(times, offsets)):
        gap = i > 0 and time - times[i - 1] > max_gap_seconds
        if gap:
            start = None
            gaps += 1
        if abs(offset) > band_ns:
            start = None
        else:
            if start is None:
                start = time
            if first is None and time - start >= dwell_seconds:
                first, confirmed = start, time
    last_exit = start if start is not None and times[-1] - start >= dwell_seconds else None
    after = [(t, o) for t, o in zip(times, offsets) if confirmed is not None and t > confirmed]
    tail_start = times[-1] - stability_seconds
    tail = [(t, r) for t, r in zip(times, rows) if t >= tail_start]
    values = [r['offset_ns'] for _, r in tail]
    x = [t for t, _ in tail]
    mean = statistics.mean(values)
    x_mean = statistics.mean(x)
    denominator = sum((t - x_mean) ** 2 for t in x)
    trend = sum((t - x_mean) * (o - mean) for t, o in zip(x, values)) / denominator
    return dict(
        records=len(rows), span_seconds=times[-1], initial_offset_ns=offsets[0],
        sample_gaps_over_limit=gaps, maximum_sample_gap_seconds=max(b - a for a, b in zip(times, times[1:])),
        settling_band_ns=band_ns, settling_dwell_seconds=dwell_seconds,
        settling_entry_seconds=first, settling_confirmed_seconds=confirmed,
        last_exit_settling_seconds=last_exit,
        excursions_after_confirmation=sum(abs(o) > band_ns for _, o in after),
        stability_requested_seconds=stability_seconds, stability_records=len(tail),
        stability_start_seconds=x[0], stability_span_seconds=x[-1] - x[0],
        stability_mean_offset_ns=mean, stability_stddev_offset_ns=statistics.pstdev(values),
        stability_rms_offset_ns=math.sqrt(statistics.mean(o * o for o in values)),
        stability_p95_absolute_offset_ns=percentile([abs(o) for o in values], .95),
        stability_max_absolute_offset_ns=max(map(abs, values)),
        stability_offset_trend_ns_per_second=trend,
        stability_in_band_fraction=sum(abs(o) <= band_ns for o in values) / len(values),
        stability_mean_correction_ppb=statistics.mean(r['rate_ppb'] for _, r in tail),
        stability_stddev_correction_ppb=statistics.pstdev(r['rate_ppb'] for _, r in tail))


def rolling_mean(times, values, seconds=10):
    """Trailing time-window mean, shown only after a full window is observed."""
    if not times or len(times) != len(values) or seconds <= 0:
        raise ValueError('Aligned observations and a positive window are required')
    result = []
    start = 0
    total = 0.0
    for i, (time, value) in enumerate(zip(times, values)):
        total += value
        while times[start] < time - seconds:
            total -= values[start]
            start += 1
        result.append(total / (i - start + 1) if time - times[0] >= seconds else float('nan'))
    return result
