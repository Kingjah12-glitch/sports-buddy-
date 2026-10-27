"""Probability calibration: map the raw model probability to the frequency the
event actually happened at (isotonic-style, pure Python, JSON-serialisable)."""
import bisect


def fit_calibrator(probs, outcomes, bins=40):
    """Equal-count bins + pool-adjacent-violators => monotone knots."""
    pairs = sorted(zip(probs, outcomes))
    n = len(pairs)
    if n < bins * 20:
        raise ValueError("Not enough data to calibrate.")
    blocks = []                                   # [sum_p, sum_y, count]
    for b in range(bins):
        chunk = pairs[b * n // bins:(b + 1) * n // bins]
        blocks.append([sum(p for p, _ in chunk), sum(y for _, y in chunk), len(chunk)])

    merged = []
    for block in blocks:                          # PAV on mean outcome
        merged.append(block)
        while len(merged) > 1 and (
            merged[-2][1] / merged[-2][2] > merged[-1][1] / merged[-1][2]
        ):
            last = merged.pop()
            merged[-1] = [merged[-1][0] + last[0], merged[-1][1] + last[1],
                          merged[-1][2] + last[2]]

    return {
        "x": [round(b[0] / b[2], 5) for b in merged],
        "y": [round(b[1] / b[2], 5) for b in merged],
        "n": n,
    }


def apply_calibrator(calibrator, p):
    if not calibrator:
        return p
    xs, ys = calibrator["x"], calibrator["y"]
    if p <= xs[0]:
        out = ys[0]
    elif p >= xs[-1]:
        out = ys[-1]
    else:
        i = bisect.bisect_right(xs, p)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        out = y0 + (y1 - y0) * (p - x0) / (x1 - x0) if x1 > x0 else y0
    return min(0.99, max(0.01, out))
