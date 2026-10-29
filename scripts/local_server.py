"""
scripts/local_server.py -- run the SAME Lambda handler and the SAME web pages on your laptop, no AWS.

It plays the roles of nginx + API Gateway: static files from ui/, and /api/recognize|info|stats|health
translated into API-Gateway-style events for lambda/handler.py. Use it to rehearse the demo and to
develop the UI before anything is deployed.

    python scripts/make_tiny_model.py                                    # random weights, plumbing test only
    python scripts/local_server.py --models .local_models                # http://127.0.0.1:7870

    # with your real models, exported by scripts/export_model.py into build/models/{finetuned,base}:
    python scripts/local_server.py --models build/models
"""
import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
ROUTES = {"recognize": ("POST", "/predict"), "info": ("GET", "/info"), "stats": ("GET", "/stats"),
          "health": ("GET", "/health")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="folder containing <model-id>/model.pt")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7870)
    a = ap.parse_args()

    os.environ["LOCAL_MODEL_DIR"] = str(Path(a.models).resolve())
    os.environ.pop("PREDICTION_TABLE", None)
    found = sorted((p.name for p in Path(a.models).iterdir() if (p / "model.pt").is_file()), key=lambda n: (n != "finetuned", n))
    os.environ.setdefault("MODEL_IDS", ",".join(found))
    os.environ.setdefault("DEFAULT_MODEL", "finetuned" if "finetuned" in os.environ["MODEL_IDS"] else os.environ["MODEL_IDS"].split(",")[0])
    sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "lambda")]

    import uuid

    import uvicorn
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import FileResponse

    import handler as H

    app = FastAPI(title="ScribbleAI cloud (local rehearsal)")

    @app.api_route("/api/{name}", methods=["GET", "POST"])
    async def api(name: str, request: Request):
        if name not in ROUTES:
            return Response('{"detail":"not found"}', 404, media_type="application/json")
        method, path = ROUTES[name]
        ev = {"httpMethod": method, "path": path, "body": (await request.body()).decode() or None}
        r = H.handler(ev, SimpleNamespace(aws_request_id=uuid.uuid4().hex))
        return Response(r["body"], r["statusCode"], headers=r["headers"])

    ui = ROOT / "ui"

    @app.get("/")
    def index():
        return FileResponse(ui / "index.html")

    @app.get("/cloud-adapter.js")
    def adapter():
        return FileResponse(ui / "cloud-adapter.js", media_type="application/javascript")

    @app.get("/space-bg.jpg")
    def background():
        return FileResponse(ui / "space-bg.jpg", media_type="image/jpeg")

    @app.get("/dashboard")
    def dashboard():
        return FileResponse(ui / "dashboard.html")

    @app.get("/{page}.html")
    def page(page: str):
        f = ui / f"{page}.html"
        return FileResponse(f) if f.is_file() else Response(status_code=404)

    print(f"open http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}/   (models: {os.environ['MODEL_IDS']})")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
