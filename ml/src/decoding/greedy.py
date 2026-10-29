"""
src/decoding/greedy.py

Best-path decoding: argmax per frame -> COLLAPSE REPEATS FIRST -> remove blanks.
(Doing it in the other order would merge genuine double letters: "ll" -> "l".)
"""
import numpy as np


def collapse(path, blank):
    out, prev = [], None
    for p in path:
        p = int(p)
        if p != prev and p != blank:
            out.append(p)
        prev = p
    return out


def greedy_decode(log_probs, blank):
    """log_probs: (T, C) numpy/torch for ONE sequence (already cut to its true length)."""
    lp = log_probs.detach().cpu().numpy() if hasattr(log_probs, "detach") else np.asarray(log_probs)
    return collapse(lp.argmax(axis=-1), blank)


def greedy_decode_batch(log_probs, lengths, blank):
    """log_probs: (T, B, C) torch tensor from the model; lengths: (B,)."""
    best = log_probs.argmax(dim=-1).cpu().numpy()          # (T, B)
    lengths = lengths.cpu().numpy() if hasattr(lengths, "cpu") else np.asarray(lengths)
    return [collapse(best[:int(L), b], blank) for b, L in enumerate(lengths)]
