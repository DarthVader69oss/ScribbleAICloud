"""
src/decoding/spell.py -- dictionary-based repair of out-of-vocabulary words.

Only touches purely alphabetic tokens that are not known words; keeps leading/trailing
punctuation and the original capitalisation pattern; never touches numbers.
Known words = pyspellchecker's English dictionary + the LM/synthetic corpus words.
"""
import re

_TOKEN = re.compile(r"^(\W*)(.*?)(\W*)$", re.UNICODE)


class SpellCorrector:
    def __init__(self, extra_words=(), max_distance=1, language="en"):
        from spellchecker import SpellChecker
        self.sc = SpellChecker(language=language, distance=max_distance)
        extra = [w.lower() for w in extra_words if w.isalpha()]
        if extra:
            self.sc.word_frequency.load_words(extra)
        self.cache = {}

    @staticmethod
    def _match_case(src, word):
        if src.isupper() and len(src) > 1:
            return word.upper()
        if src[:1].isupper():
            return word[:1].upper() + word[1:]
        return word

    def correct_word(self, w):
        if not w.isalpha() or len(w) < 2:
            return w
        lw = w.lower()
        if lw in self.cache:
            fixed = self.cache[lw]
        else:
            if lw in self.sc:
                fixed = lw
            else:
                fixed = self.sc.correction(lw) or lw
            self.cache[lw] = fixed
        return w if fixed == lw else self._match_case(w, fixed)

    def __call__(self, text):
        out = []
        for tok in text.split(" "):
            m = _TOKEN.match(tok)
            pre, core, post = m.groups() if m else ("", tok, "")
            out.append(pre + self.correct_word(core) + post)
        return " ".join(out)
