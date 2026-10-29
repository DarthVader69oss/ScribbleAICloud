"""
src/preprocessing/normalize.py  (C1.6, C1.7)

Slant, baseline and height normalisation, applied to a WHOLE LINE (or word).
Never call these per character: normalising each character to the same height
would make a/A, o/O, s/S, c/C indistinguishable.

Coordinates: y points down.
"""
import numpy as np

from .clean import Ink, ink_points
from .resample import resample_ink


def _uniform_points(ink: Ink, n_target: int = 400) -> np.ndarray:
    """Points spread evenly along the pen path (so slow, dense regions don't dominate)."""
    p = ink_points(ink)
    span = max(np.ptp(p[:, 0]), np.ptp(p[:, 1]), 1e-9)
    return ink_points(resample_ink(ink, span / n_target))


def baseline_angle(ink: Ink, max_deg: float = 15.0) -> float:
    """Angle (degrees) of the writing direction, from a least-squares line fit.
    Returns 0 for ink that is not clearly wider than tall (e.g. single characters)."""
    p = _uniform_points(ink)
    w, h = np.ptp(p[:, 0]), np.ptp(p[:, 1])
    if len(p) < 3 or w < 2.0 * max(h, 1e-9):
        return 0.0
    slope = np.polyfit(p[:, 0], p[:, 1], 1)[0]
    return float(np.clip(np.degrees(np.arctan(slope)), -max_deg, max_deg))


def rotate(ink: Ink, deg: float) -> Ink:
    if deg == 0:
        return [s.copy() for s in ink]
    c = ink_points(ink).mean(axis=0)
    t = np.radians(deg)
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    return [(s - c) @ R.T + c for s in ink]


def slant_angle(ink: Ink, max_deg: float = 35.0, min_aspect: float = 1.5) -> float:
    """
    Dominant slant (degrees) from near-vertical segments, weighted by length.
    Negative = right-leaning (top of the letters is to the right of the bottom).
    Returns 0 for ink that is not clearly wider than tall: on a single character the
    estimate is unreliable (the diagonal of a 'z' would be "corrected" away).
    """
    pts = ink_points(ink)
    w, h = float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1]))
    if h <= 0 or w <= 0:
        return 0.0
    # Flat ink (e.g. '-', '_', '.') has no measurable slant, and a ~0 height would give
    # a ~0 resampling step and billions of points.
    if h < 1e-2 * w or w < min_aspect * h:
        return 0.0
    segs = []
    for s in resample_ink(ink, h / 50):
        if len(s) > 1:
            segs.append(np.diff(s, axis=0))
    if not segs:
        return 0.0
    d = np.concatenate(segs)
    d = d * np.where(d[:, 1:2] < 0, -1, 1)          # orient every segment downwards
    length = np.hypot(d[:, 0], d[:, 1])
    ang = np.degrees(np.arctan2(d[:, 0], d[:, 1]))   # 0 = straight down
    m = (np.abs(ang) < 40) & (length > 0)
    if m.sum() < 3:
        return 0.0
    return float(np.clip(np.average(ang[m], weights=length[m]), -max_deg, max_deg))


def shear(ink: Ink, slant_deg: float) -> Ink:
    """Remove a slant measured by slant_angle(): x' = x - (y - y_mid) * tan(slant)."""
    if slant_deg == 0:
        return [s.copy() for s in ink]
    k = np.tan(np.radians(slant_deg))
    ymid = np.median(ink_points(ink)[:, 1])
    out = []
    for s in ink:
        s2 = s.copy()
        s2[:, 0] = s[:, 0] - (s[:, 1] - ymid) * k
        out.append(s2)
    return out


def core_height(ink: Ink) -> float:
    """Robust height estimate (10th-90th percentile of y along the pen path)."""
    p = _uniform_points(ink)
    h = np.percentile(p[:, 1], 90) - np.percentile(p[:, 1], 10)
    if h < 1e-9:                        # flat ink, e.g. a single dash
        h = max(np.ptp(p[:, 0]), np.ptp(p[:, 1])) or 1.0
    return float(h)


def normalize_height(ink: Ink, target: float = 1.0) -> Ink:
    """Scale the whole line so its core height == target; move it to x>=0, median y = 0."""
    s = target / core_height(ink)
    p = ink_points(ink)
    x0, ymid = p[:, 0].min(), np.median(p[:, 1])
    return [np.stack([(st[:, 0] - x0) * s, (st[:, 1] - ymid) * s], axis=1) for st in ink]


def normalize_line(ink: Ink, deslant: bool = True, baseline: bool = True,
                   max_baseline_deg: float = 15.0) -> Ink:
    """Baseline -> slant -> height, in that order. Output units: core height = 1."""
    ink = normalize_height(ink)                       # first pass: sane scale for angle estimates
    if baseline:
        ink = rotate(ink, -baseline_angle(ink, max_baseline_deg))
    if deslant:
        ink = shear(ink, slant_angle(ink))
    return normalize_height(ink)
