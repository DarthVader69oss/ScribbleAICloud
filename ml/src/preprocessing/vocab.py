"""
src/preprocessing/vocab.py  (guide 4.3)

The vocabulary is computed FROM THE DATA (the UJIpenchars2 labels + a space),
never hardcoded. The CTC blank is always the LAST index.
"""
import json
import unicodedata
from pathlib import Path

SPACE = " "


class Vocab:
    def __init__(self, chars):
        chars = list(chars)
        if len(set(chars)) != len(chars):
            raise ValueError("duplicate characters in vocab")
        if "" in chars:
            raise ValueError("empty string is reserved for the blank")
        self.chars = chars
        self.index = {c: i for i, c in enumerate(chars)}
        self.blank = len(chars)

    @classmethod
    def from_labels(cls, labels):
        chars = sorted({unicodedata.normalize("NFC", l) for l in labels} - {SPACE})
        return cls(chars + [SPACE])

    @property
    def size(self):
        """Number of model outputs = characters + blank."""
        return len(self.chars) + 1

    def normalize_text(self, text):
        """NFC-normalise, collapse whitespace, map typographic quotes/dashes to plain ones."""
        table = {"‘": "'", "’": "'", "“": '"', "”": '"',
                 "–": "-", "—": "-", " ": " "}
        text = unicodedata.normalize("NFC", "".join(table.get(c, c) for c in text))
        return " ".join(text.split())

    def unknown_chars(self, text):
        return sorted({c for c in self.normalize_text(text) if c not in self.index})

    def encode(self, text, on_unknown="error"):
        out = []
        for c in self.normalize_text(text):
            if c in self.index:
                out.append(self.index[c])
            elif on_unknown == "error":
                raise KeyError(f"character {c!r} not in vocabulary")
        return out

    def decode(self, ids):
        return "".join(self.chars[i] for i in ids if i != self.blank)

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"chars": self.chars, "blank": self.blank},
                                         ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        v = cls(d["chars"])
        assert v.blank == d["blank"], "vocab file blank index is inconsistent"
        return v
