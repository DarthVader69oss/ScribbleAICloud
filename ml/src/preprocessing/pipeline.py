"""
src/preprocessing/pipeline.py

THE preprocessing function. Training (synthetic lines), evaluation (in-house data)
and the live demo all call `preprocess()` so they can never drift apart.

    raw strokes -> Ink -> exact-dup removal -> baseline/slant/height normalisation
                -> near-dup removal -> hook removal -> arc-length resampling -> 8-dim features
"""
from .clean import to_ink, remove_duplicates, remove_hooks
from .normalize import normalize_line
from .resample import resample_ink
from .features import encode


def normalize_ink(strokes, pcfg, flip_y=False):
    ink = to_ink(strokes, flip_y=flip_y)
    ink = remove_duplicates(ink, 0.0)
    ink = normalize_line(ink, deslant=pcfg.get("deslant", True),
                         baseline=pcfg.get("baseline_correction", True),
                         max_baseline_deg=pcfg.get("max_baseline_angle_deg", 15))
    ink = remove_duplicates(ink, pcfg["duplicate_point_eps"])
    ink = remove_hooks(ink, pcfg["hook_max_len_frac"], pcfg["hook_min_angle_deg"],
                       pcfg["hook_min_stroke_points"])
    return resample_ink(ink, pcfg["resample_step"])


def preprocess(strokes, pcfg, flip_y=False):
    """Returns (features T x 8 float32, normalised+resampled ink)."""
    ink = normalize_ink(strokes, pcfg, flip_y)
    return encode(ink), ink
