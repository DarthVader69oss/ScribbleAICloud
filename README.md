# ScribbleAI on AWS

Online handwriting recognition (BiLSTM + CTC on pen strokes) served as a cloud application: Lambda inference behind API Gateway,
nginx on EC2 for the live-canvas page, model files in S3, every prediction logged to DynamoDB, everything provisioned by Terraform and
deployed by GitHub Actions, monitored by CloudWatch/SNS/Budgets.

```
Browser ─> EC2 (nginx) ─> API Gateway ─> Lambda ─┬─> S3 (models)      GitHub ─> Actions ─> ECR ─> Lambda
                                                 └─> DynamoDB (log)             CloudWatch ─> SNS e-mail
```

**Start with [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md)** (step-by-step, git + AWS + GitHub) and rehearse with
[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

| Folder | Contents |
|---|---|
| `lambda/handler.py` | The API: `POST /predict`, `GET /info /stats /health`; model loading from S3; DynamoDB logging |
| `ml/src/` | Vendored inference code from the ScribbleAI repo (refresh with `scripts/sync_ml.sh`) |
| `Dockerfile` | Lambda container image (CPU-only PyTorch) |
| `infra/terraform/` | All AWS resources |
| `ui/` | `index.html` (live canvas + cloud strip), `dashboard.html` (live stats from DynamoDB) |
| `deploy/` | nginx template and the script that refreshes the EC2 box |
| `scripts/` | `export_model.py`, `first_deploy.sh`, `upload_models.sh`, `local_server.py`, `smoke_test.py`, `make_tiny_model.py`, `sync_ml.sh` |
| `.github/workflows/ci-cd.yml` | test → terraform validate → build → deploy → smoke test → notify |
| `tests/` | 15 tests, including S3 loading and DynamoDB logging against mocked AWS |

Quick local rehearsal (no AWS): `pip install -r lambda/requirements.txt -r tests/requirements.txt torch`, `python scripts/make_tiny_model.py`,
`python scripts/local_server.py --models .local_models`.

## Exact ScribbleAI demo interface

`ui/index.html`, `ui/dashboard.html`, and `ui/space-bg.jpg` come directly from the supplied ScribbleAI `demo/static/` folder. The only addition to the HTML is a `cloud-adapter.js` script tag. The adapter translates cloud `/api/info` and `/api/stats` responses to the demo's expected fields without changing the original appearance. Trace replay can show writing created in this browser after the page was updated; older or other users' traces are unavailable because the cloud API does not persist them. Clear dashboard only hides entries in this browser. The original `/gradio/` link remains part of the exact demo interface, but the batch scorer is not deployed on this cloud stack.
