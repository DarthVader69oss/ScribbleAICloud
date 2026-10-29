"""
scripts/smoke_test.py -- call the deployed API the way a client would (also useful as a Postman substitute).

    python scripts/smoke_test.py --url http://<EC2 ip>                    # through nginx (no key needed)
    python scripts/smoke_test.py --url https://<id>.execute-api.<region>.amazonaws.com/prod --key <api key> --direct
"""
import argparse
import json
import math
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", required=True)
ap.add_argument("--key")
ap.add_argument("--direct", action="store_true", help="--url is the API Gateway URL (paths /predict, /health) instead of nginx (/api/recognize)")
a = ap.parse_args()
base = a.url.rstrip("/")
paths = {"predict": "/predict", "health": "/health", "info": "/info"} if a.direct else \
        {"predict": "/api/recognize", "health": "/api/health", "info": "/api/info"}


def call(path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", **({"x-api-key": a.key} if a.key else {})})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r), (time.perf_counter() - t) * 1000


h, ms = call(paths["health"]); print(f"health   {ms:6.0f} ms  {h}")
i, ms = call(paths["info"]);   print(f"info     {ms:6.0f} ms  models: {[(m['id'], m['available']) for m in i['models']]}")
strokes = [[[10 + k * 3, 40 + 12 * math.sin(k / 3), k * 0.01, 0.5] for k in range(40)]]
for n in range(1, 4):
    r, ms = call(paths["predict"], {"strokes": strokes, "mode": "greedy"})
    c = r["cloud"]
    print(f"predict{n} {ms:6.0f} ms  service {c['handler_ms']:.0f} ms  cold={c['cold_start']}  logged={c['logged']}  text={r['text']!r}")
