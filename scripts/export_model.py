"""
scripts/export_model.py -- turn a full ScribbleAI training checkpoint into a slim inference artifact.

A training checkpoint (best.pt / best_finetune.pt, ~40-60 MB) also carries the optimizer state, scheduler
and training history. The cloud only needs the weights, vocab, feature statistics and config, so the
exported model.pt is ~15 MB: faster to download on every Lambda cold start and cheaper to store in S3.

Run this on the machine that has your ScribbleAI environment (needs torch):

    python scripts/export_model.py --ckpt  C:/path/best_finetune.pt \
                                   --lm    C:/path/char_lm.json \
                                   --corpus C:/path/corpus.txt \
                                   --out   build/models/finetuned

    python scripts/export_model.py --ckpt C:/path/best.pt --lm C:/path/char_lm.json --out build/models/base

--lm and --corpus are optional but recommended: without char_lm.json the beam+LM decoders are unavailable,
without corpus.txt the spell checker only knows pyspellchecker's English dictionary.
"""
import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import torch

KEEP = ("model", "vocab", "norm_mean", "norm_std", "config", "epoch", "best_cer")


def plain(x):
    """numpy/torch scalars -> plain python so the file loads under any numpy/torch version."""
    if isinstance(x, np.ndarray):
        return x.astype(float).tolist()
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, dict):
        return {k: plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--lm")
    ap.add_argument("--corpus")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    st = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    missing = [k for k in KEEP if k not in st and k not in ("epoch", "best_cer")]
    if missing:
        sys.exit(f"{a.ckpt} is not a ScribbleAI training checkpoint (missing {missing})")
    slim = {k: st.get(k) for k in KEEP}
    slim["model"] = {k: v.detach().cpu().contiguous() for k, v in st["model"].items()}
    for k in ("vocab", "norm_mean", "norm_std", "config"):
        slim[k] = plain(slim[k])

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(slim, out / "model.pt")
    for src, name in ((a.lm, "char_lm.json"), (a.corpus, "corpus.txt")):
        if src:
            shutil.copyfile(src, out / name)

    mb = lambda p: p.stat().st_size / 1e6
    print(f"input  {a.ckpt}: {mb(Path(a.ckpt)):.1f} MB")
    for f in sorted(out.iterdir()):
        print(f"output {f}: {mb(f):.1f} MB")
    print(f"epoch {slim['epoch']}  val CER {slim['best_cer']}  vocab {len(slim['vocab'])}")


if __name__ == "__main__":
    main()
