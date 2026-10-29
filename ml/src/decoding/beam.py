"""
src/decoding/beam.py -- beam search decoders.

prefix_beam_search()   Our own CTC prefix beam search (pure Python/NumPy). Optional
                       character n-gram LM fused during search (shallow fusion):
                         score = log P_ctc + alpha * log P_lm + beta * len
                       This is what evaluation and the demo use for "beam" and "beam+LM".

PyCTCDecoder           Thin wrapper around pyctcdecode (beam search; word KenLM if the
                       kenlm module is installed). Optional comparison only.
"""
import math

import numpy as np

NEG_INF = -float("inf")


def _lse(a, b):
    if a == NEG_INF:
        return b
    if b == NEG_INF:
        return a
    m = max(a, b)
    return m + math.log(math.exp(a - m) + math.exp(b - m))


def prefix_beam_search(log_probs, chars, blank, beam_width=10, lm=None, alpha=0.5, beta=1.0,
                       prune_logp=-8.0, max_candidates=12, blank_skip=0.999):
    """
    log_probs: (T, C) numpy log-softmax output for ONE sequence.
    chars: list mapping id -> character (blank excluded).
    Returns (best_text, [(text, score), ...] for the final beam).
    """
    lp = np.asarray(log_probs, dtype=np.float64)
    T = lp.shape[0]
    log_skip = math.log(blank_skip)
    # beam: prefix(tuple of ids) -> [log p ending in blank, log p ending in non-blank]
    beams = {(): [0.0, NEG_INF]}
    lm_cache = {}

    def lm_score(prefix, c):
        if lm is None:
            return 0.0
        key = (prefix, c)
        if key not in lm_cache:
            ctx = "".join(chars[i] for i in prefix[-(lm.order - 1):]) if lm.order > 1 else ""
            lm_cache[key] = alpha * lm.logp(ctx, chars[c]) + beta
        return lm_cache[key]

    for t in range(T):
        row = lp[t]
        if row[blank] > log_skip:                     # nearly-certain blank frame: cheap update
            for v in beams.values():
                v[0], v[1] = _lse(v[0], v[1]) + row[blank], NEG_INF
            continue
        cand = np.where(row > prune_logp)[0]
        if len(cand) > max_candidates:
            cand = cand[np.argsort(row[cand])[-max_candidates:]]
        nxt = {}

        def add(prefix, pb, pnb):
            e = nxt.get(prefix)
            if e is None:
                nxt[prefix] = [pb, pnb]
            else:
                e[0] = _lse(e[0], pb)
                e[1] = _lse(e[1], pnb)

        for prefix, (pb, pnb) in beams.items():
            ptot = _lse(pb, pnb)
            for c in cand:
                p = row[c]
                if c == blank:
                    add(prefix, ptot + p, NEG_INF)
                    continue
                last = prefix[-1] if prefix else None
                new = prefix + (int(c),)
                bonus = lm_score(prefix, int(c))
                if c == last:
                    add(new, NEG_INF, pb + p + bonus)      # repeat needs a blank in between
                    add(prefix, NEG_INF, pnb + p)          # or it collapses into the same char
                else:
                    add(new, NEG_INF, ptot + p + bonus)
        beams = dict(sorted(nxt.items(), key=lambda kv: -_lse(*kv[1]))[:beam_width])

    def final(prefix, v):
        s = _lse(*v)
        if lm is not None:
            from src.decoding.lm import EOS
            ctx = "".join(chars[i] for i in prefix[-(lm.order - 1):]) if lm.order > 1 else ""
            s += alpha * lm.logp(ctx, EOS)
        return s

    ranked = sorted(((final(p, v), p) for p, v in beams.items()), reverse=True)
    out = [("".join(chars[i] for i in p), s) for s, p in ranked]
    return out[0][0], out


class PyCTCDecoder:
    """pyctcdecode wrapper. Needs `pip install --no-deps pyctcdecode pygtrie` (see requirements)."""

    def __init__(self, chars, blank, arpa_path=None, alpha=0.5, beta=1.0):
        from pyctcdecode import build_ctcdecoder
        if blank != len(chars):
            raise ValueError("expects blank as last index")
        labels = list(chars) + [""]                         # "" marks the blank for pyctcdecode
        kenlm_ok = False
        if arpa_path:
            try:
                import kenlm  # noqa: F401
                kenlm_ok = True
            except ImportError:
                pass
        self.has_lm = kenlm_ok
        self.dec = build_ctcdecoder(labels, kenlm_model_path=str(arpa_path) if kenlm_ok else None,
                                    alpha=alpha, beta=beta)

    def __call__(self, log_probs, beam_width=10):
        return self.dec.decode(np.asarray(log_probs, dtype=np.float32), beam_width=beam_width)
