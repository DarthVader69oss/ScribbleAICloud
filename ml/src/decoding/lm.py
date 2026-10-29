"""
src/decoding/lm.py -- language models for the decoder.

1. CharNgramLM (pure Python, always available)
   Character n-gram with interpolated Witten-Bell smoothing. Used by our own prefix
   beam search (src/decoding/beam.py). This is the "character-level n-gram LM rescoring
   the beam" from the synopsis, and needs no compiled dependency.

2. write_word_arpa() (pure Python)
   Writes a word n-gram in standard ARPA format (absolute-discount backoff), which
   KenLM / pyctcdecode can load IF the kenlm Python module is installed. kenlm often
   fails to build on Colab; everything works without it.

Build both:
    python -m src.decoding.lm [--lines 200000]
Training text: data/raw/corpus.txt if present, else text from the same English
word-frequency sampler used for synthetic lines.
"""
import argparse
import json
import math
import random
from collections import defaultdict, Counter
from pathlib import Path

BOS, EOS = "\x02", "\x03"


class CharNgramLM:
    def __init__(self, order=6):
        self.order = order
        self.counts = [defaultdict(Counter) for _ in range(order)]   # counts[k][ctx(len k)][char]
        self.vocab = set()
        self._cache = {}

    # ------------------------------------------------------------ training
    def train(self, lines):
        for line in lines:
            s = BOS * (self.order - 1) + line + EOS
            for i in range(self.order - 1, len(s)):
                c = s[i]
                self.vocab.add(c)
                for k in range(self.order):
                    self.counts[k][s[i - k:i]][c] += 1
        self._finalize()
        return self

    def prune(self, min_count=2):
        """Drop rare contexts of the top two orders to keep the file small."""
        for k in range(max(1, self.order - 2), self.order):
            for ctx in list(self.counts[k]):
                if sum(self.counts[k][ctx].values()) < min_count:
                    del self.counts[k][ctx]
        self._finalize()
        return self

    def _finalize(self):
        self.tot = [{ctx: sum(c.values()) for ctx, c in ck.items()} for ck in self.counts]
        self.types = [{ctx: len(c) for ctx, c in ck.items()} for ck in self.counts]
        self._cache = {}

    # ------------------------------------------------------------ scoring
    def prob(self, context, c):
        """P(c | context) with interpolated Witten-Bell smoothing."""
        context = (BOS * (self.order - 1) + context)[-(self.order - 1):] if self.order > 1 else ""
        key = (context, c)
        if key in self._cache:
            return self._cache[key]
        p = 1.0 / (len(self.vocab) + 1)                       # uniform floor
        for k in range(self.order):
            ctx = context[len(context) - k:] if k else ""
            tot = self.tot[k].get(ctx)
            if not tot:
                continue
            typ = self.types[k][ctx]
            lam = tot / (tot + typ)
            p = lam * self.counts[k][ctx].get(c, 0) / tot + (1 - lam) * p
        if len(self._cache) > 2_000_000:
            self._cache.clear()
        self._cache[key] = p
        return p

    def logp(self, context, c):
        return math.log(self.prob(context, c))

    def score(self, text, eos=True):
        lp = sum(self.logp(text[:i], ch) for i, ch in enumerate(text))
        return lp + (self.logp(text, EOS) if eos else 0.0)

    def perplexity(self, lines):
        lp = sum(self.score(l) for l in lines)
        n = sum(len(l) + 1 for l in lines)
        return math.exp(-lp / max(n, 1))

    # ------------------------------------------------------------ io
    def save(self, path):
        d = {"order": self.order, "vocab": sorted(self.vocab),
             "counts": [{ctx: dict(c) for ctx, c in ck.items()} for ck in self.counts]}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        lm = cls(d["order"])
        lm.vocab = set(d["vocab"])
        lm.counts = [defaultdict(Counter, {ctx: Counter(c) for ctx, c in ck.items()}) for ck in d["counts"]]
        lm._finalize()
        return lm


def write_word_arpa(lines, path, order=3, discount=0.75, min_count=1):
    """Word n-gram with absolute discounting + properly normalised backoff weights, ARPA format."""
    counts = [Counter() for _ in range(order + 1)]
    for line in lines:
        w = ["<s>"] + line.split() + ["</s>"]
        for n in range(1, order + 1):
            for i in range(len(w) - n + 1):
                g = tuple(w[i:i + n])
                if n == 1 and g == ("<s>",):
                    continue
                counts[n][g] += 1
    for n in range(2, order + 1):
        counts[n] = Counter({g: c for g, c in counts[n].items() if c >= min_count})
    total = sum(counts[1].values())
    uni = {g: c / total for g, c in counts[1].items()}
    uni[("<s>",)] = 0.0
    uni[("<unk>",)] = 0.5 / total
    s = sum(uni.values())
    probs = {1: {g: p / s for g, p in uni.items()}}
    hist_tot = [defaultdict(int) for _ in range(order + 1)]
    for n in range(2, order + 1):
        for g, c in counts[n].items():
            hist_tot[n][g[:-1]] += c
        probs[n] = {g: (c - discount) / hist_tot[n][g[:-1]] for g, c in counts[n].items()}

    def lower_p(g):
        """probability of g's last word under the backoff chain of g[1:]"""
        n = len(g)
        if n == 1:
            return probs[1].get(g, probs[1][("<unk>",)])
        if g in probs[n]:
            return probs[n][g]
        return backoff.get(g[:-1], 1.0) * lower_p(g[1:])

    backoff = {}
    for n in range(1, order):
        children = defaultdict(list)
        for g in probs[n + 1]:
            children[g[:-1]].append(g)
        for h, gs in children.items():
            num = 1.0 - sum(probs[n + 1][g] for g in gs)
            den = 1.0 - sum(lower_p(g[1:]) for g in gs)
            backoff[h] = max(num, 1e-12) / max(den, 1e-12)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\\data\\\n")
        for n in range(1, order + 1):
            f.write(f"ngram {n}={len(probs[n])}\n")
        for n in range(1, order + 1):
            f.write(f"\n\\{n}-grams:\n")
            for g, p in probs[n].items():
                lp = -99.0 if p <= 0 else math.log10(p)
                line = f"{lp:.6f}\t{' '.join(g)}"
                if n < order and g in backoff:
                    line += f"\t{math.log10(backoff[g]):.6f}"
                elif n < order:
                    line += "\t0.000000"
                f.write(line + "\n")
        f.write("\n\\end\\\n")


def training_lines(cfg, n_lines, seed=7):
    from src.utils import resolve
    from src.preprocessing.vocab import Vocab
    from src.preprocessing.synth_lines import TextSampler
    vocab = Vocab.load(resolve(cfg["data"]["vocab_file"]))
    corpus = resolve(cfg["data"]["corpus_file"])
    if corpus.exists():
        allowed = set(vocab.chars)
        lines = []
        for raw in corpus.read_text(encoding="utf-8", errors="ignore").splitlines():
            t = "".join(c for c in vocab.normalize_text(raw) if c in allowed)
            if t.strip():
                lines.append(" ".join(t.split()))
        return lines, "corpus file"
    s = cfg["synthetic"]
    sampler = TextSampler(vocab.chars, None, 1, 12, 120, 0.0)
    rng = random.Random(seed)
    return [sampler.sample(rng) for _ in range(n_lines)], "English word-frequency sampler"


def main(argv=None):
    from src.utils import load_config, resolve
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/base.yaml")
    ap.add_argument("--lines", type=int, default=200000)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    dc = cfg["decoding"]
    lines, src = training_lines(cfg, a.lines)
    print(f"LM training text: {len(lines)} lines from {src}")
    held = lines[:2000]
    lm = CharNgramLM(dc["char_lm_order"]).train(lines[2000:]).prune(2)
    print(f"char {lm.order}-gram perplexity on held-out lines: {lm.perplexity(held):.2f}")
    lm.save(resolve(dc["char_lm_file"]))
    print("wrote", resolve(dc["char_lm_file"]))
    write_word_arpa(lines, resolve(dc["word_arpa_file"]))
    print("wrote", resolve(dc["word_arpa_file"]), "(usable by pyctcdecode only if kenlm is installed)")


if __name__ == "__main__":
    main()
