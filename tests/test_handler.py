"""Handler tests. They use random-weight models, so they check the CLOUD plumbing (routing, validation,
logging, cold-start flag, S3 loading), not recognition accuracy."""
import importlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "lambda")]

STROKES = [[[10 + i * 3, 40 + 12 * math.sin(i / 3), i * 0.01, 0.5] for i in range(40)],
           [[140 + i * 3, 40 + 12 * math.cos(i / 3), 1 + i * 0.01, 0.5] for i in range(40)]]
CTX = SimpleNamespace(aws_request_id="11111111-2222-3333-4444-555555555555")


@pytest.fixture(scope="session")
def model_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("models")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_tiny_model.py"), "--out", str(d)], check=True)
    return d


def load_handler(monkeypatch, **env):
    for k in ("LOCAL_MODEL_DIR", "MODEL_BUCKET", "PREDICTION_TABLE", "DEFAULT_MODEL", "MODEL_IDS", "MODEL_CACHE_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PRELOAD", "0")
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    sys.modules.pop("handler", None)
    return importlib.import_module("handler")


def call(h, method, path, body=None):
    ev = {"httpMethod": method, "path": path, "body": json.dumps(body) if body is not None else None}
    r = h.handler(ev, CTX)
    return r["statusCode"], json.loads(r["body"]), r["headers"]


@pytest.fixture
def local(monkeypatch, model_dir):
    return load_handler(monkeypatch, LOCAL_MODEL_DIR=model_dir)


def test_health_reports_cold_start_once(local):
    s, b, _ = call(local, "GET", "/health")
    assert s == 200 and b["status"] == "ok" and b["cold_start"] is True
    assert call(local, "GET", "/health")[1]["cold_start"] is False


def test_info_lists_both_models(local):
    s, b, _ = call(local, "GET", "/info")
    assert s == 200 and {m["id"] for m in b["models"]} == {"finetuned", "base"}
    assert b["default_model"] == "finetuned" and b["params"] > 0 and "beam_lm_spell" in b["modes"]


def test_predict_returns_original_fields_plus_cloud_block(local):
    s, b, h = call(local, "POST", "/predict", {"strokes": STROKES, "mode": "beam_lm", "compare": True})
    assert s == 200
    assert {"text", "frames", "ms", "ink", "all", "confidence", "cloud"} <= set(b)
    assert set(b["ms"]) == {"preprocess", "model", "decode", "total"}
    assert set(b["all"]) == {"greedy", "beam", "beam_lm", "beam_lm_spell"}
    c = b["cloud"]
    assert c["request_id"] == CTX.aws_request_id and c["model_id"] == "finetuned" and c["logged"] is True
    assert h["X-Request-Id"] == CTX.aws_request_id and 0 <= b["confidence"] <= 1


def test_model_switch_and_unknown_model(local):
    s, b, _ = call(local, "POST", "/predict", {"strokes": STROKES, "model": "base"})
    assert s == 200 and b["cloud"]["model_id"] == "base"
    assert call(local, "POST", "/predict", {"strokes": STROKES, "model": "nope"})[0] == 400


@pytest.mark.parametrize("body", [{"strokes": "abc"}, {"strokes": [[["x", 1]]]}, {"strokes": STROKES, "mode": "magic"},
                                  {"strokes": [[[0, 0]]] * 401}])
def test_bad_input_is_400_not_500(local, body):
    assert call(local, "POST", "/predict", body)[0] == 400


def test_invalid_json_and_unknown_route(local):
    r = local.handler({"httpMethod": "POST", "path": "/predict", "body": "{not json"}, CTX)
    assert r["statusCode"] == 400
    assert call(local, "GET", "/nothing")[0] == 404


def test_empty_strokes_is_ok(local):
    s, b, _ = call(local, "POST", "/predict", {"strokes": []})
    assert s == 200 and b["text"] == ""


def test_stats_reads_back_what_was_logged(local):
    for m in ("greedy", "beam", "greedy"):
        call(local, "POST", "/predict", {"strokes": STROKES, "mode": m})
    s, b, _ = call(local, "GET", "/stats")
    assert s == 200 and b["count"] >= 3 and b["modes"]["greedy"] >= 2
    assert b["p95_ms"] >= b["p50_ms"] > 0 and len(b["recent"]) >= 3 and b["series"]
    assert b["recent"][0]["request_id"] == CTX.aws_request_id


def test_warmup_event_without_http_method(local):
    r = local.handler({"source": "aws.events"}, CTX)
    assert r["warmed"] is True and "finetuned" in r["models_loaded"]


def test_missing_model_gives_503_with_hint(monkeypatch, tmp_path):
    h = load_handler(monkeypatch, LOCAL_MODEL_DIR=tmp_path)
    s, b, _ = call(h, "POST", "/predict", {"strokes": STROKES})
    assert s == 503 and "not found" in b["detail"]


# ------------------------------------------------------------------ the real AWS code paths, against moto
moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")


@pytest.fixture
def aws(monkeypatch, model_dir, tmp_path):
    from moto import mock_aws
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x"); monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1"); monkeypatch.setenv("AWS_REGION", "ap-south-1")
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="scribbleai-test-bucket", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        s3.put_bucket_versioning(Bucket="scribbleai-test-bucket", VersioningConfiguration={"Status": "Enabled"})
        for mid in ("finetuned", "base"):
            for f in ("model.pt", "char_lm.json", "corpus.txt"):
                if mid == "base" and f == "corpus.txt":
                    continue                                  # optional files really are optional
                s3.upload_file(str(model_dir / mid / f), "scribbleai-test-bucket", f"models/{mid}/{f}")
        ddb = boto3.client("dynamodb")
        ddb.create_table(TableName="t", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "day", "AttributeType": "S"},
                                               {"AttributeName": "sk", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "day", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        yield load_handler(monkeypatch, MODEL_BUCKET="scribbleai-test-bucket", PREDICTION_TABLE="t", MODEL_CACHE_DIR=tmp_path / "cache")


def test_loads_models_from_s3_and_logs_to_dynamodb(aws):
    s, b, _ = call(aws, "POST", "/predict", {"strokes": STROKES, "mode": "beam_lm_spell"})
    assert s == 200 and b["cloud"]["logged"] is True and b["cloud"]["cold_start"] is True
    assert b["cloud"]["model_version"] not in (None, "")            # S3 VersionId travels with every prediction
    items = boto3.resource("dynamodb").Table("t").scan()["Items"]
    assert len(items) == 1 and items[0]["text"] == b["text"] and items[0]["expires_at"] > 0
    s, st, _ = call(aws, "GET", "/stats")
    assert s == 200 and st["count"] == 1 and st["cloud"]["storage"] == "DynamoDB"


def test_optional_s3_files_missing_degrades_gracefully(aws):
    s, b, _ = call(aws, "POST", "/predict", {"strokes": STROKES, "model": "base", "mode": "beam"})
    assert s == 200
    s, b, _ = call(aws, "GET", "/info")
    base = next(m for m in b["models"] if m["id"] == "base")
    assert base["available"] and "beam_lm" in base["modes"]
