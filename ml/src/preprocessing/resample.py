"""
src/preprocessing/resample.py  (C1.8)

Arc-length resampling: every stroke is re-sampled so consecutive points are
`step` apart along the pen path. This removes writing speed and device sampling
rate as nuisance variables (UJI has no timestamps; the collector samples at the
browser's pointer rate), so both datasets look the same to the model.
"""
import numpy as np

from .clean import Ink


def resample_stroke(s: np.ndarray, step: float) -> np.ndarray:
    if step <= 0:
        raise ValueError("step must be > 0")
    if len(s) == 1:
        return s.copy()
    seg = np.hypot(*np.diff(s, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total < 1e-12:
        return s[:1].copy()
    n = max(2, int(round(total / step)) + 1)
    t = np.linspace(0.0, total, n)
    # remove zero-length segments so np.interp has strictly increasing xp
    keep = np.concatenate([[True], seg > 1e-12])
    cum_k, s_k = cum[keep], s[keep]
    x = np.interp(t, cum_k, s_k[:, 0])
    y = np.interp(t, cum_k, s_k[:, 1])
    return np.stack([x, y], axis=1)


def resample_ink(ink: Ink, step: float) -> Ink:
    """Vectorised over all strokes (same result as resample_stroke on each)."""
    if step <= 0:
        raise ValueError("step must be > 0")
    lens = np.array([len(s) for s in ink])
    P = np.concatenate(ink)
    starts = np.concatenate([[0], np.cumsum(lens)[:-1]])
    seg = np.zeros(len(P))
    seg[1:] = np.hypot(*np.diff(P, axis=0).T)
    seg[starts] = 0.0                                   # no length across pen-ups
    cum = np.cumsum(seg)
    cum_start = cum[starts]
    local = cum - np.repeat(cum_start, lens)            # arc length within each stroke
    totals = np.add.reduceat(seg, starts)
    n = np.where((lens == 1) | (totals < 1e-12), 1,
                 np.maximum(2, np.round(totals / step).astype(int) + 1))
    offsets = np.concatenate([[0.0], np.cumsum(totals + 1.0)[:-1]])   # +1 gap keeps strokes apart
    g = local + np.repeat(offsets, lens)
    # all target positions at once
    grp_start = np.concatenate([[0], np.cumsum(n)[:-1]])
    within = np.arange(n.sum()) - np.repeat(grp_start, n)
    denom = np.repeat(np.maximum(n - 1, 1), n)
    t = np.repeat(offsets, n) + within / denom * np.repeat(totals, n)
    xy = np.stack([np.interp(t, g, P[:, 0]), np.interp(t, g, P[:, 1])], axis=1)
    # single-point strokes: take the stroke's first point exactly
    single = np.where(n == 1)[0]
    xy[grp_start[single]] = P[starts[single]]
    return np.split(xy, np.cumsum(n)[:-1])


def ink_length(ink: Ink) -> float:
    return float(sum(np.hypot(*np.diff(s, axis=0).T).sum() for s in ink if len(s) > 1))
