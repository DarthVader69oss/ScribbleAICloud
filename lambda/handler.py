"""
lambda/handler.py -- ScribbleAI inference service (AWS Lambda behind API Gateway).

Routes (API Gateway REST API, Lambda proxy integration):
    POST /predict   pen strokes -> text            (same request body as the original demo's /api/recognize,
                                                    plus an optional "model": "finetuned" | "base")
    GET  /info      models available + checkpoint metadata
    GET  /stats     aggregates + recent predictions read back from DynamoDB (drives dashboard.html)
    GET  /health    liveness + cold-start information (used by CI smoke tests)
    (no httpMethod) EventBridge "keep warm" ping: loads the default model, returns immediately

Model artifacts are NOT baked into the image. They live in S3 (versioned) under
    s3://$MODEL_BUCKET/models/<model-id>/model.pt          slim checkpoint (see scripts/export_model.py)
                                         /char_lm.json     character 6-gram language model   (optional)
                                         /corpus.txt       extra words for the spell checker (optional)
and are downloaded to /tmp on a cold start, so swapping a model never needs an image rebuild.

Local mode (no AWS at all): set LOCAL_MODEL_DIR=<dir with <model-id>/model.pt> and leave PREDICTION_TABLE empty.
Predictions are then kept in memory. scripts/local_server.py uses this to rehearse the demo offline.
"""
import base64
import json
import math
import os
import time
import traceback
import uuid
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np

_PROC_START = time.time()

REGION = os.environ.get("AWS_REGION", "local")
BUCKET = os.environ.get("MODEL_BUCKET", "")
MODEL_PREFIX = os.environ.get("MODEL_PREFIX", "models").strip("/")
LOCAL_DIR = os.environ.get("LOCAL_MODEL_DIR", "")
TABLE = os.environ.get("PREDICTION_TABLE", "")
MODEL_IDS = [m.strip() for m in os.environ.get("MODEL_IDS", "finetuned,base").split(",") if m.strip()]
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL") or (MODEL_IDS[0] if MODEL_IDS else "finetuned")
TTL_DAYS = int(os.environ.get("LOG_TTL_DAYS", "30"))
GIT_SHA = os.environ.get("GIT_SHA", "dev")
MEMORY_MB = os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "local")
CACHE_DIR = Path(os.environ.get("MODEL_CACHE_DIR", "/tmp/models"))
TORCH_THREADS = int(os.environ.get("TORCH_THREADS", "2"))
MODES = ("greedy", "beam", "beam_lm", "beam_lm_spell")

# Input limits: the endpoint is public, so bound the work one request can ask for.
MAX_STROKES, MAX_POINTS, MAX_BODY_BYTES = 400, 30_000, 2_000_000

_MODELS = {}            # model id -> {"rec", "version", "checkpoint", "load_s"}
_COLD = True            # true until the first request of this execution environment has been served
_INIT_ERROR = None
_MEM_LOG = deque(maxlen=2000)   # used only when no DynamoDB table is configured (local mode)


# --------------------------------------------------------------------------------------- model loading
def _fetch_from_s3(model_id):
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client("s3")
    d = CACHE_DIR / model_id
    d.mkdir(parents=True, exist_ok=True)
    got, version = {}, None
    for name, required in (("model.pt", True), ("char_lm.json", False), ("corpus.txt", False)):
        key = f"{MODEL_PREFIX}/{model_id}/{name}"
        try:
            head = s3.head_object(Bucket=BUCKET, Key=key)
        except ClientError as e:
            if not required and e.response["Error"]["Code"] in ("404", "403", "NoSuchKey", "NotFound"):
                continue
            raise RuntimeError(f"s3://{BUCKET}/{key} not found - upload it with scripts/upload_models.sh") from e
        dest = d / name
        s3.download_file(BUCKET, key, str(dest))
        got[name] = dest
        if name == "model.pt":
            version = head.get("VersionId") or head["ETag"].strip('"')
    return got, version


def _fetch_local(model_id):
    d = Path(LOCAL_DIR) / model_id
    if not (d / "model.pt").is_file():
        raise RuntimeError(f"{d / 'model.pt'} not found")
    got = {n: d / n for n in ("model.pt", "char_lm.json", "corpus.txt") if (d / n).is_file()}
    st = (d / "model.pt").stat()
    return got, f"local-{int(st.st_mtime)}"


def _load_model(model_id):
    """Download (cold start only) and build a Recognizer. Cached for the life of the container."""
    if model_id in _MODELS:
        return _MODELS[model_id]
    if model_id not in MODEL_IDS:
        raise KeyError(model_id)
    import torch
    from src.inference import Recognizer
    torch.set_num_threads(max(1, TORCH_THREADS))
    t0 = time.perf_counter()
    files, version = _fetch_local(model_id) if LOCAL_DIR else _fetch_from_s3(model_id)
    lm = files.get("char_lm.json")
    rec = Recognizer(str(files["model.pt"]), device="cpu", char_lm_path=str(lm) if lm else None,
                     load_lm=lm is not None, load_spell=False)
    try:    # same spell checker as the local demo, but its extra words come from S3 instead of data/raw/
        from src.decoding.spell import SpellCorrector
        corpus = files.get("corpus.txt")
        words = set(corpus.read_text(encoding="utf-8", errors="ignore").split()) if corpus else set()
        rec.spell = SpellCorrector(words, rec.cfg["decoding"].get("spell_max_distance", 1))
    except ImportError:
        rec.spell = None
    for m in rec.available_modes():     # warm-up: the first real stroke should not pay for lazy initialisation
        rec.recognize([[(0, 0), (10, 12), (20, 0)], [(25, 5), (35, 5)]], m)
    _MODELS[model_id] = {"rec": rec, "version": version, "checkpoint": f"{model_id}/model.pt",
                         "load_s": round(time.perf_counter() - t0, 2)}
    return _MODELS[model_id]


def _preload():
    """Runs once in the Lambda INIT phase, so the first request does not have to wait for the model download."""
    global _INIT_ERROR
    try:
        _load_model(DEFAULT_MODEL)
    except Exception as e:      # do not crash init: the first request retries and returns a clear error
        _INIT_ERROR = f"{type(e).__name__}: {e}"
        print("PRELOAD FAILED", _INIT_ERROR)


# --------------------------------------------------------------------------------------- prediction log
class _DynamoLog:
    def __init__(self, table_name):
        import boto3
        self.table = boto3.resource("dynamodb").Table(table_name)

    def put(self, item):
        self.table.put_item(Item=json.loads(json.dumps(item), parse_float=Decimal))

    def recent(self, limit=500):
        from boto3.dynamodb.conditions import Key
        out, today = [], datetime.now(timezone.utc).date()
        for day in (today, today - timedelta(days=1)):     # yesterday too, so the UTC midnight rollover is invisible
            r = self.table.query(KeyConditionExpression=Key("day").eq(day.isoformat()),
                                 ScanIndexForward=False, Limit=limit - len(out))
            out += r["Items"]
            if len(out) >= 50:
                break
        return out


class _MemoryLog:
    def put(self, item):
        _MEM_LOG.appendleft(item)

    def recent(self, limit=500):
        return list(_MEM_LOG)[:limit]


_LOG = None


def _log():
    global _LOG
    if _LOG is None:
        _LOG = _DynamoLog(TABLE) if TABLE else _MemoryLog()
    return _LOG


# --------------------------------------------------------------------------------------- helpers
def _resp(status, body, extra_headers=None):
    h = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    h.update(extra_headers or {})
    return {"statusCode": status, "headers": h, "body": json.dumps(body, default=_json_default)}


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(f"not serialisable: {type(o)}")


def _err(status, msg):
    return _resp(status, {"detail": msg})


def _confidence(rec, lp):
    """Mean probability of the best label over the frames where the network did NOT predict blank.
    A rough 0..1 'how sure was the network' number; it is not a calibrated probability."""
    best, idx = lp.max(axis=1), lp.argmax(axis=1)
    keep = idx != rec.vocab.blank
    return float(np.exp(best[keep].mean())) if keep.any() else 0.0


def _validate_strokes(raw):
    if not isinstance(raw, list):
        raise ValueError("'strokes' must be a list of strokes")
    strokes = [s for s in raw if isinstance(s, list) and len(s) > 0]
    if len(strokes) > MAX_STROKES:
        raise ValueError(f"too many strokes (max {MAX_STROKES})")
    n = sum(len(s) for s in strokes)
    if n > MAX_POINTS:
        raise ValueError(f"too many points (max {MAX_POINTS})")
    for s in strokes:
        for p in s:
            if not (isinstance(p, (list, tuple)) and len(p) >= 2 and all(isinstance(v, (int, float)) for v in p[:2])):
                raise ValueError("every point must be [x, y, (t, pressure)] with numeric x and y")
    return strokes, n


# --------------------------------------------------------------------------------------- routes
def _predict(body, ctx, cold):
    from src.preprocessing.pipeline import preprocess
    t_req = time.perf_counter()
    strokes, n_points = _validate_strokes(body.get("strokes", []))
    mid = body.get("model") or DEFAULT_MODEL
    if mid not in MODEL_IDS:
        return _err(400, f"unknown model {mid!r}; choose one of {MODEL_IDS}")
    t_load = time.perf_counter()
    try:
        m = _load_model(mid)
    except RuntimeError as e:
        return _err(503, str(e))
    load_ms = (time.perf_counter() - t_load) * 1000
    rec = m["rec"]
    mode = body.get("mode", "greedy")
    if mode not in rec.available_modes():
        return _err(400, f"mode {mode!r} not available for model {mid!r}: {rec.available_modes()}")
    bw = body.get("beam_width")
    bw = None if bw is None else max(1, min(int(bw), 50))

    cloud = {"request_id": getattr(ctx, "aws_request_id", None) or uuid.uuid4().hex, "cold_start": cold,
             "region": REGION, "memory_mb": MEMORY_MB, "model_id": mid, "model_version": m["version"],
             "git_sha": GIT_SHA}
    if not strokes:
        return _resp(200, {"text": "", "ms": {"total": 0}, "frames": 0, "ink": [], "all": {}, "cloud": cloud})

    t0 = time.perf_counter()
    F, ink = preprocess(strokes, rec.pcfg)
    t1 = time.perf_counter()
    lp = rec.log_probs_from_features(F)
    t2 = time.perf_counter()
    text = rec.decode(lp, mode, bw)
    t3 = time.perf_counter()
    out = {"text": text, "frames": int(F.shape[0]), "confidence": _confidence(rec, lp),
           "ms": {"preprocess": (t1 - t0) * 1000, "model": (t2 - t1) * 1000, "decode": (t3 - t2) * 1000,
                  "total": (t3 - t0) * 1000},
           "ink": [s.tolist() for s in ink], "all": {}}
    if body.get("compare"):
        for md in rec.available_modes():
            a = time.perf_counter()
            out["all"][md] = {"text": rec.decode(lp, md, bw), "decode_ms": (time.perf_counter() - a) * 1000}

    now = datetime.now(timezone.utc)
    item = {"day": now.date().isoformat(), "sk": f"{now.isoformat()}#{cloud['request_id'][:8]}",
            "ts": now.isoformat(), "request_id": cloud["request_id"], "model": mid, "model_version": m["version"],
            "mode": mode, "beam_width": bw or rec.default_beam, "n_strokes": len(strokes), "n_points": n_points,
            "frames": out["frames"], "text": text, "confidence": out["confidence"],
            "preprocess_ms": out["ms"]["preprocess"], "model_ms": out["ms"]["model"],
            "decode_ms": out["ms"]["decode"], "total_ms": out["ms"]["total"], "cold_start": cold,
            "memory_mb": str(MEMORY_MB), "git_sha": GIT_SHA,
            "expires_at": int(now.timestamp()) + TTL_DAYS * 86400}
    try:
        _log().put(item)
        cloud["logged"] = True
    except Exception as e:      # logging must never break a prediction
        print("LOG WRITE FAILED", repr(e))
        cloud["logged"] = False
    cloud["handler_ms"] = (time.perf_counter() - t_req) * 1000
    cloud["model_load_ms"] = load_ms
    if cold:
        cloud["init_ms"] = (m["load_s"] or 0) * 1000
    out["cloud"] = cloud
    return _resp(200, out, {"X-Request-Id": cloud["request_id"]})


def _info():
    models = []
    for mid in MODEL_IDS:
        try:
            m = _load_model(mid)
        except Exception as e:
            models.append({"id": mid, "available": False, "error": str(e)})
            continue
        r = m["rec"]
        models.append({"id": mid, "available": True, "checkpoint": m["checkpoint"], "version": m["version"],
                       "epoch": r.epoch, "val_cer": r.best_cer, "modes": r.available_modes(),
                       "vocab_size": r.vocab.size, "params": r.model.num_parameters(), "load_s": m["load_s"]})
    d = next((m for m in models if m["id"] == DEFAULT_MODEL and m.get("available")), None) or \
        next((m for m in models if m.get("available")), {})
    return _resp(200, {"checkpoint": d.get("checkpoint"), "epoch": d.get("epoch"), "val_cer": d.get("val_cer"),
                       "modes": d.get("modes", []), "vocab_size": d.get("vocab_size"), "params": d.get("params"),
                       "default_model": DEFAULT_MODEL, "models": models,
                       "cloud": {"region": REGION, "memory_mb": MEMORY_MB, "git_sha": GIT_SHA,
                                 "runtime": os.environ.get("AWS_EXECUTION_ENV", "local"),
                                 "storage": "DynamoDB" if TABLE else "in-memory (local mode)"}})


def _pct(sorted_vals, q):
    return sorted_vals[min(len(sorted_vals) - 1, int(q * (len(sorted_vals) - 1) + 0.5))] if sorted_vals else 0.0


def _stats():
    items = _log().recent(500)
    n = len(items)
    tot = sorted(float(i["total_ms"]) for i in items)
    conf = [float(i["confidence"]) for i in items if "confidence" in i]
    body = {"count": n, "window": "last 500 predictions of the last two UTC days",
            "avg_ms": (sum(tot) / n) if n else 0.0, "p50_ms": _pct(tot, 0.5), "p95_ms": _pct(tot, 0.95),
            "cold_starts": sum(1 for i in items if i.get("cold_start")),
            "avg_confidence": (sum(conf) / len(conf)) if conf else 0.0,
            "modes": dict(Counter(i["mode"] for i in items)), "models": dict(Counter(i["model"] for i in items)),
            "series": [{"ts": i["ts"], "total_ms": float(i["total_ms"]), "cold": bool(i.get("cold_start"))}
                       for i in reversed(items[:40])],
            "recent": [{k: i.get(k) for k in ("ts", "model", "mode", "text", "total_ms", "confidence", "cold_start",
                                              "frames", "request_id")} for i in items[:12]],
            "cloud": {"region": REGION, "storage": "DynamoDB" if TABLE else "in-memory (local mode)",
                      "git_sha": GIT_SHA, "container_age_s": round(time.time() - _PROC_START)}}
    return _resp(200, body)


def _health(cold):
    return _resp(200, {"status": "ok" if not _INIT_ERROR else "degraded", "init_error": _INIT_ERROR,
                       "cold_start": cold, "models_loaded": sorted(_MODELS), "region": REGION,
                       "git_sha": GIT_SHA, "container_age_s": round(time.time() - _PROC_START)})


# --------------------------------------------------------------------------------------- entry point
def handler(event, context):
    global _COLD
    cold, _COLD = _COLD, False

    if "httpMethod" not in event:        # EventBridge keep-warm ping or a bare console test event
        try:
            _load_model(DEFAULT_MODEL)
        except Exception as e:
            return {"warmed": False, "error": str(e)}
        return {"warmed": True, "cold_start": cold, "models_loaded": sorted(_MODELS)}

    method = event["httpMethod"].upper()
    route = (event.get("path") or "/").rstrip("/").split("/")[-1]
    try:
        if route == "predict" and method == "POST":
            raw = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8")
            if len(raw) > MAX_BODY_BYTES:
                return _err(413, "request body too large")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                return _err(400, "body is not valid JSON")
            return _predict(body, context, cold)
        if route == "info" and method == "GET":
            return _info()
        if route == "stats" and method == "GET":
            return _stats()
        if route == "health" and method == "GET":
            return _health(cold)
        return _err(404, f"no route for {method} {event.get('path')}")
    except ValueError as e:
        return _err(400, str(e))
    except Exception:
        traceback.print_exc()            # goes to CloudWatch Logs; the client only sees a generic message
        return _err(500, "internal error - see CloudWatch Logs for the request id "
                         f"{getattr(context, 'aws_request_id', '')}")


if os.environ.get("PRELOAD", "1") == "1" and (BUCKET or LOCAL_DIR):
    _preload()
