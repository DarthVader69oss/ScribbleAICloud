"""
scripts/make_tiny_model.py -- build a throw-away RANDOM-WEIGHT checkpoint in the same format as
scripts/export_model.py produces. It recognises nothing useful; it exists so that the whole cloud
path (handler, local server, tests, CI) can be exercised without the real 14 MB model.

    python scripts/make_tiny_model.py --out .local_models        # creates .local_models/{finetuned,base}/
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ml"))

from src.decoding.lm import CharNgramLM            # noqa: E402
from src.models.bilstm_ctc import BiLSTMCTC        # noqa: E402

CHARS = list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,'-") + [" "]

CFG = {
    "preprocessing": {"duplicate_point_eps": 0.02, "hook_max_len_frac": 0.10, "hook_min_angle_deg": 90,
                      "hook_min_stroke_points": 12, "deslant": True, "baseline_correction": True,
                      "max_baseline_angle_deg": 15, "resample_step": 0.12},
    "features": {"input_dim": 8},
    "model": {"hidden_size": 32, "num_layers": 1, "bidirectional": True, "dropout": 0.0, "pack_sequences": True},
    "decoding": {"default_beam_width": 10, "char_lm_file": "data/processed/char_lm.json", "lm_alpha": 0.5,
                 "lm_beta": 1.0, "spell_max_distance": 1},
    "data": {"corpus_file": "data/raw/corpus.txt"},
}

TEXT = ["hello world", "the quick brown fox jumps over the lazy dog", "machine learning is fun",
        "handwriting recognition on the cloud", "write something here"] * 20


def build(out_dir, seed):
    torch.manual_seed(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = BiLSTMCTC.from_config(CFG, len(CHARS) + 1)
    torch.save({"model": model.state_dict(), "vocab": CHARS, "norm_mean": [0.0] * 8, "norm_std": [1.0] * 8,
                "config": CFG, "epoch": seed, "best_cer": 0.99}, out_dir / "model.pt")
    CharNgramLM(order=4).train(TEXT).save(out_dir / "char_lm.json")
    (out_dir / "corpus.txt").write_text("\n".join(TEXT), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".local_models"))
    a = ap.parse_args()
    for i, name in enumerate(("finetuned", "base")):
        build(Path(a.out) / name, i + 1)
    print(f"wrote random-weight test models to {a.out}/finetuned and {a.out}/base")
