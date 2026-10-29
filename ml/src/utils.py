"""Small shared helpers: config loading, seeding, paths."""
import json
import random
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path="configs/base.yaml"):
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = ROOT / p
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(path):
    """Resolve a repo-relative path from the config."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def save_json(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def update_config_values(path, updates):
    """
    Rewrite `key: value` lines in a YAML file in place, keeping comments.
    Only touches keys that already exist (e.g. vocab_size, blank_index).
    """
    import re
    p = resolve(path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    done = set()
    for i, line in enumerate(lines):
        for key, val in updates.items():
            m = re.match(rf"^(\s*{re.escape(key)}:\s*)([^#\n]*?)(\s*#.*)?(\n?)$", line)
            if m:
                lines[i] = f"{m.group(1)}{val}{m.group(3) or ''}{m.group(4)}"
                done.add(key)
    missing = set(updates) - done
    if missing:
        raise KeyError(f"keys not found in {p}: {sorted(missing)}")
    p.write_text("".join(lines), encoding="utf-8")
