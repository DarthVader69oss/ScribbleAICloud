"""
src/inference.py -- one object that turns raw pen strokes into text.

Used by the demo AND the evaluation script, so both run exactly the training-time
preprocessing (pipeline.preprocess) with the checkpoint's own config, vocab and
feature statistics.

    rec = Recognizer("checkpoints/best.pt")
    rec.recognize(strokes, mode="greedy")      # strokes: [[(x, y[, t, p]), ...], ...]

Decoding modes: greedy | beam | beam_lm | beam_lm_spell
"""
import time

import numpy as np
import torch

from src.utils import resolve
from src.preprocessing.pipeline import preprocess
from src.preprocessing.features import FeatureNormalizer
from src.preprocessing.vocab import Vocab
from src.models.bilstm_ctc import BiLSTMCTC
from src.decoding.greedy import greedy_decode
from src.decoding.beam import prefix_beam_search

MODES = ("greedy", "beam", "beam_lm", "beam_lm_spell")


class Recognizer:
    def __init__(self, ckpt_path, device="cpu", char_lm_path=None, load_lm=True, load_spell=True,
                 decoding_overrides=None):
        st = torch.load(ckpt_path, map_location=device, weights_only=False)
        self.cfg = st["config"]
        if decoding_overrides:
            self.cfg["decoding"].update(decoding_overrides)
        self.vocab = Vocab(st["vocab"])
        self.norm = FeatureNormalizer(st["norm_mean"], st["norm_std"])
        self.model = BiLSTMCTC.from_config(self.cfg, self.vocab.size).to(device).eval()
        self.model.load_state_dict(st["model"])
        self.device = device
        self.pcfg = self.cfg["preprocessing"]
        self.epoch, self.best_cer = st.get("epoch"), st.get("best_cer")
        dc = self.cfg["decoding"]
        self.alpha, self.beta = dc["lm_alpha"], dc["lm_beta"]
        self.default_beam = dc.get("default_beam_width", 10)
        self.lm, self.spell = None, None
        if load_lm:
            p = resolve(char_lm_path or dc["char_lm_file"])
            if p.exists():
                from src.decoding.lm import CharNgramLM
                self.lm = CharNgramLM.load(p)
        if load_spell:
            try:
                from src.decoding.spell import SpellCorrector
                words = set()
                corpus = resolve(self.cfg["data"].get("corpus_file", ""))
                if corpus.is_file():
                    words = set(corpus.read_text(encoding="utf-8", errors="ignore").split())
                self.spell = SpellCorrector(words, dc.get("spell_max_distance", 1))
            except ImportError:
                self.spell = None

    def available_modes(self):
        m = ["greedy", "beam"]
        if self.lm is not None:
            m.append("beam_lm")
            if self.spell is not None:
                m.append("beam_lm_spell")
        return m

    @torch.no_grad()
    def log_probs_from_features(self, F):
        x = torch.from_numpy(self.norm(F)).unsqueeze(0).to(self.device)
        lp, _ = self.model(x, torch.tensor([F.shape[0]]))
        return lp[:, 0].cpu().numpy()                   # (T, C)

    def decode(self, lp, mode="greedy", beam_width=None):
        bw = beam_width or self.default_beam
        if mode == "greedy":
            return self.vocab.decode(greedy_decode(lp, self.vocab.blank))
        if mode == "beam":
            return prefix_beam_search(lp, self.vocab.chars, self.vocab.blank, bw)[0]
        if mode in ("beam_lm", "beam_lm_spell"):
            if self.lm is None:
                raise RuntimeError("no character LM found -- run python -m src.decoding.lm")
            text = prefix_beam_search(lp, self.vocab.chars, self.vocab.blank, bw, self.lm,
                                      self.alpha, self.beta)[0]
            if mode == "beam_lm_spell" and self.spell is not None:
                text = self.spell(text)
            return text
        raise ValueError(f"unknown mode {mode}")

    def recognize(self, strokes, mode="greedy", beam_width=None):
        t0 = time.perf_counter()
        F, ink = preprocess(strokes, self.pcfg)
        t1 = time.perf_counter()
        lp = self.log_probs_from_features(F)
        t2 = time.perf_counter()
        text = self.decode(lp, mode, beam_width)
        t3 = time.perf_counter()
        return {"text": text, "frames": int(F.shape[0]),
                "ms": {"preprocess": (t1 - t0) * 1000, "model": (t2 - t1) * 1000,
                       "decode": (t3 - t2) * 1000, "total": (t3 - t0) * 1000},
                "ink": [s.tolist() for s in ink]}
