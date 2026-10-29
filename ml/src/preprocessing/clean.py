"""
src/preprocessing/clean.py  (C1.4, C1.5)

"Ink" everywhere in the pipeline = list of strokes, each an (N, 2) float array of
(x, y) with y pointing DOWN (screen convention, same as the collector canvas).

  * to_ink()             -- convert parser output (lists of tuples, maybe with t/p) to Ink
  * remove_duplicates()  -- drop points that barely move (19.4% of UJI points are duplicates)
  * remove_hooks()       -- trim small curls at stroke start/end (conservative)
"""
from typing import List, Sequence

import numpy as np

Ink = List[np.ndarray]


def to_ink(strokes: Sequence[Sequence[Sequence[float]]], flip_y: bool = False) -> Ink:
    """Keep only x, y; drop empty strokes. Works for UJI (x,y) and in-house (x,y,t,p)."""
    ink = []
    for s in strokes:
        if len(s) == 0:
            continue
        a = np.asarray(s, dtype=np.float64)[:, :2].copy()
        if flip_y:
            a[:, 1] = -a[:, 1]
        ink.append(a)
    if not ink:
        raise ValueError("ink has no points")
    return ink


def remove_duplicates(ink: Ink, eps: float = 0.0) -> Ink:
    """
    Drop each point closer than `eps` to the last KEPT point of the same stroke
    (eps=0 removes exact repeats). The first point of a stroke is always kept,
    and so is the last one (moved onto the final position) so the stroke's end
    is not shortened. Never returns an empty stroke.
    """
    out = []
    for s in ink:
        if len(s) == 1:
            out.append(s.copy())
            continue
        if eps <= 0:                                   # vectorised exact-repeat removal
            m = np.ones(len(s), bool)
            m[1:] = np.any(s[1:] != s[:-1], axis=1)
            out.append(s[m].copy())
            continue
        xs, ys = s[:, 0].tolist(), s[:, 1].tolist()   # plain floats: much faster loop
        kx, ky = [xs[0]], [ys[0]]
        e2 = eps * eps
        for x, y in zip(xs[1:], ys[1:]):
            dx, dy = x - kx[-1], y - ky[-1]
            if dx * dx + dy * dy > e2:
                kx.append(x); ky.append(y)
        if len(kx) > 1:
            kx[-1], ky[-1] = xs[-1], ys[-1]
        out.append(np.stack([kx, ky], axis=1))
    return out


def _angle_between(v1, v2):
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    c = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return float(np.degrees(np.arccos(c)))


def _trim_start(s, max_len_frac, min_angle):
    seg = np.hypot(*np.diff(s, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return s
    i_max = int(np.searchsorted(cum, max_len_frac * total, side="right") - 1)
    best_i, best_ang = 0, 0.0
    for i in range(1, min(i_max, len(s) - 2) + 1):          # candidate cut points inside the hook zone
        j = int(np.searchsorted(cum, cum[i] + max_len_frac * total, side="right") - 1)
        j = min(max(j, i + 1), len(s) - 1)
        ang = _angle_between(s[i] - s[0], s[j] - s[i])
        if ang > best_ang:
            best_i, best_ang = i, ang
    if best_i and best_ang >= min_angle:
        return s[best_i:]
    return s


def remove_hooks(ink: Ink, max_len_frac: float = 0.10, min_angle_deg: float = 90.0,
                 min_points: int = 12) -> Ink:
    """
    A hook = the first/last `max_len_frac` of a stroke's arc length heading in a
    direction that differs by >= `min_angle_deg` from where the stroke then goes.
    Strokes with fewer than `min_points` points are left alone (short UJI strokes
    such as dots and accents would otherwise be destroyed).
    """
    out = []
    for s in ink:
        if len(s) >= min_points:
            s = _trim_start(s, max_len_frac, min_angle_deg)
            s = _trim_start(s[::-1], max_len_frac, min_angle_deg)[::-1]
        out.append(np.ascontiguousarray(s))
    return out


def ink_points(ink: Ink) -> np.ndarray:
    return np.concatenate(ink, axis=0)


def ink_bbox(ink: Ink):
    p = ink_points(ink)
    return p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
