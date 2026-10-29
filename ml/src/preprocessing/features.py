"""
src/preprocessing/features.py  (C1.9)

8-dimensional feature vector per resampled point:

  0 dx          x offset from the previous point (includes pen-up jumps)
  1 dy          y offset from the previous point
  2 pen_up      1 if the pen was lifted before reaching this point (first point of a stroke, except the very first)
  3 sin(theta)  writing direction, as sin/cos so the angle never "wraps"
  4 cos(theta)
  5 curvature   signed turning angle at this point / pi, in [-1, 1] (0 at stroke ends)
  6 norm_y      vertical position relative to the line centre (core height = 1)
  7 stroke_end  1 at the last point of each stroke

Nothing here uses time, so UJI (no timestamps) and in-house data are encoded identically.
"""
import json
from pathlib import Path

import numpy as np

from .clean import Ink

FEATURE_NAMES = ["dx", "dy", "pen_up", "sin", "cos", "curvature", "norm_y", "stroke_end"]
CONTINUOUS = [0, 1, 5, 6]          # standardised with train-set mean/std


def encode(ink: Ink) -> np.ndarray:
    pts, pen_up, end = [], [], []
    for k, s in enumerate(ink):
        pts.append(s)
        pu = np.zeros(len(s)); pu[0] = 1.0 if k > 0 else 0.0
        en = np.zeros(len(s)); en[-1] = 1.0
        pen_up.append(pu); end.append(en)
    P = np.concatenate(pts).astype(np.float64)
    pen_up = np.concatenate(pen_up)
    end = np.concatenate(end)
    T = len(P)

    d = np.zeros_like(P)
    d[1:] = P[1:] - P[:-1]

    # direction of motion at each point: incoming segment (outgoing for the very first point)
    v = d.copy()
    if T > 1:
        v[0] = P[1] - P[0]
    norm = np.hypot(v[:, 0], v[:, 1])
    ok = norm > 1e-12
    sin = np.where(ok, v[:, 1] / np.where(ok, norm, 1), 0.0)
    cos = np.where(ok, v[:, 0] / np.where(ok, norm, 1), 0.0)

    # curvature: angle between incoming and outgoing in-stroke segments
    curv = np.zeros(T)
    start = 0
    for s in ink:
        n = len(s)
        if n >= 3:
            a_in = s[1:-1] - s[:-2]
            a_out = s[2:] - s[1:-1]
            cross = a_in[:, 0] * a_out[:, 1] - a_in[:, 1] * a_out[:, 0]
            dot = (a_in * a_out).sum(axis=1)
            curv[start + 1:start + n - 1] = np.arctan2(cross, dot) / np.pi
        start += n

    F = np.stack([d[:, 0], d[:, 1], pen_up, sin, cos, curv, P[:, 1], end], axis=1)
    return F.astype(np.float32)


class FeatureNormalizer:
    """Standardise the continuous dims using statistics from the TRAINING set only."""

    def __init__(self, mean, std):
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.asarray(std, dtype=np.float32)

    @classmethod
    def fit(cls, feature_list):
        X = np.concatenate(feature_list, axis=0)
        mean = np.zeros(X.shape[1], np.float32)
        std = np.ones(X.shape[1], np.float32)
        mean[CONTINUOUS] = X[:, CONTINUOUS].mean(axis=0)
        std[CONTINUOUS] = X[:, CONTINUOUS].std(axis=0) + 1e-6
        return cls(mean, std)

    def __call__(self, F):
        return ((F - self.mean) / self.std).astype(np.float32)

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"mean": self.mean.tolist(), "std": self.std.tolist(),
                                          "names": FEATURE_NAMES}, indent=2))

    @classmethod
    def load(cls, path):
        d = json.loads(Path(path).read_text())
        return cls(d["mean"], d["std"])
