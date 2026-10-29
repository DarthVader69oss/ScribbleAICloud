#!/usr/bin/env bash
# Refresh the vendored inference code (ml/src) from your ScribbleAI repository.
# Run it whenever preprocessing, the model class or the decoders change in ScribbleAI.
#   bash scripts/sync_ml.sh /path/to/scribbleai
set -euo pipefail
SRC="${1:?usage: sync_ml.sh /path/to/scribbleai}/src"
DST="$(dirname "$0")/../ml/src"
for f in __init__.py utils.py inference.py \
         preprocessing/__init__.py preprocessing/pipeline.py preprocessing/clean.py preprocessing/features.py \
         preprocessing/normalize.py preprocessing/resample.py preprocessing/vocab.py \
         models/__init__.py models/bilstm_ctc.py \
         decoding/__init__.py decoding/greedy.py decoding/beam.py decoding/lm.py decoding/spell.py; do
  mkdir -p "$DST/$(dirname "$f")"; cp "$SRC/$f" "$DST/$f"
done
echo "ml/src updated from $SRC. Run: pytest"
