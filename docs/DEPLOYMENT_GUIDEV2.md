# ScribbleAI on AWS: deployment guide

Everything below is done from a **new folder / new GitHub repository**. Your ScribbleAI repository is not modified; the only
thing taken from it is a vendored copy of the inference code (`ml/src`) and your trained model files.

Windows users: run the commands in **Git Bash** (installed with Git for Windows). They are written for bash.

---

## 0. What you are building

```
Browser ──> EC2 (nginx) ──> API Gateway ──> Lambda (BiLSTM+CTC, container image)
 tablet      page + key       key, throttle      │  ├── S3        model weights, versioned (downloaded on cold start)
 laptop                                          │  └── DynamoDB  one row per prediction (30-day TTL)
                                                 │
GitHub ──> GitHub Actions ──> ECR (image) ──> Lambda update + S3 sync + EC2 refresh
                                  CloudWatch dashboard + alarms ──> SNS e-mail      AWS Budgets ($5)
```

| Part of the synopsis | What is actually built |
|---|---|
| Lambda inference endpoint behind API Gateway, API key, throttling | Yes: REST API, usage plan (10 req/s, 5000/day), `POST /predict`, `GET /info /stats /health` |
| EC2 hosts a live-canvas demo | Yes, but the page is the ScribbleAI canvas UI served by nginx (not Gradio). nginx also forwards `/api/*` to API Gateway and adds the API key server-side |
| S3 stores dataset, checkpoints, logs | S3 stores **model artifacts and the web files**, versioned. The dataset stays in Drive (it is not needed at inference time) |
| Every prediction logged to DynamoDB | Yes: text, confidence, latency split, model, S3 model version, cold-start flag, build id. `GET /stats` feeds `dashboard.html` |
| Terraform provisions everything | Yes: VPC, IAM, EC2, ECR, Lambda, API Gateway, S3, DynamoDB, SNS, CloudWatch, Budgets, GitHub OIDC role |
| GitHub Actions: test, build, push to ECR, redeploy | Yes, plus a Lambda smoke test, S3 sync, EC2 refresh via SSM, an end-to-end check and an SNS e-mail |
| CloudWatch + SNS + $5 billing alarm | CloudWatch dashboard, 3 alarms, SNS e-mail, and **AWS Budgets** (the CloudWatch billing metric exists only in us-east-1; Budgets works in every region) |

Deliberate differences you should be ready to explain:

* **Region `ap-south-1` (Mumbai)** instead of `us-east-1`: much lower latency from Manipal. Change `region` in `terraform.tfvars` if your faculty wants `us-east-1`.
* **Model weights live in S3, not in the image.** Swapping or adding a model needs no image rebuild, and the S3 `VersionId` is returned with every prediction.
* **Two models are served** (`finetuned` and `base`) so the demo can show the generalisation gap live: the page has a model switch.
* **Gradio is dropped.** Inference runs on Lambda, and a 1 GB EC2 instance cannot comfortably hold PyTorch plus Gradio. The batch scorer for collector files remains in your ScribbleAI repo.
* **ML section of the synopsis** (IAM-OnDB, ≤12% / ≤9% CER targets): see section 9 for what to say instead.

---

## 1. One-time setup (accounts and tools)

1. **AWS account.** Sign in as root only once to: enable MFA, then create an admin user for daily work
   (IAM Identity Center, or IAM user with `AdministratorAccess` + MFA). Never create access keys for the root user.
2. **Billing safety.** Billing → *Billing preferences* → turn on *Receive Free Tier usage alerts* and *Receive billing alerts*,
   and (Account → *IAM user and role access to Billing information*) activate it so your admin user can create budgets.
3. **Install:** Git, [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html),
   [Terraform ≥ 1.5](https://developer.hashicorp.com/terraform/install), **Docker Desktop** (must be *running* for the first deploy),
   Python 3.12 (only for rehearsing locally).
4. **Log the CLI in:**
   ```bash
   aws configure            # access key of the admin IAM user, region ap-south-1, output json
   aws sts get-caller-identity   # must print your account id
   ```
5. **GitHub:** create an **empty** repository named `scribbleai-cloud` (no README, no .gitignore). Note the `owner/name`.

## 2. Put the files in a new folder and push to GitHub

**2.0 Before the first push (skip what you already have)**

1. **GitHub account:** sign up at github.com and verify your e-mail.
2. **Install Git:** download "Git for Windows" from git-scm.com and accept the defaults. This also installs **Git Bash** and Git Credential Manager.
3. **Tell Git who you are** (once per laptop; use the e-mail of your GitHub account):
   ```bash
   git config --global user.name  "Your Name"
   git config --global user.email "you@example.com"
   ```
4. **Create the repository:** github.com → *New repository* → name `scribbleai-cloud` → Private is fine → leave "Add a README", ".gitignore" and "licence" **unchecked** → *Create repository*. Copy its HTTPS URL.
5. **How you sign in on the first `git push`:**
   * Easiest: Git Credential Manager (installed with Git for Windows) opens a browser window; choose *Sign in with your browser* and authorise. Nothing else to do.
   * If it asks for a password in the terminal instead: GitHub no longer accepts your account password. Create a token at GitHub → *Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token*, tick the **repo** scope, copy it once, and paste it as the password. Treat it like a password and never commit it.

**2.1 Push the project**

```bash
mkdir scribbleai-cloud && cd scribbleai-cloud
# copy the CONTENTS of the zip you were given into this folder (so that Dockerfile is directly inside it)
git init -b main
git add .
git status                      # check: no *.tfstate, no *.pt, no terraform.tfvars in the list
git commit -m "ScribbleAI cloud: Lambda inference, Terraform, CI/CD"
git remote add origin https://github.com/<you>/scribbleai-cloud.git
git push -u origin main
```

The first push starts the workflow. The `test` and `terraform` jobs run; `deploy` is **skipped** until you set the GitHub variables in
section 6, so a first green run with a grey "deploy" is expected.

## 3. Rehearse everything locally (no AWS needed, 5 minutes)

```bash
python -m venv .venv && source .venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r lambda/requirements.txt -r tests/requirements.txt
pytest                                                        # 15 tests: handler, S3 loading, DynamoDB logging (mocked)
python scripts/make_tiny_model.py                             # random-weight models, only to test the plumbing
python scripts/local_server.py --models .local_models         # open http://127.0.0.1:7870
```

You see the full UI and the dashboard, served by the **same handler code** that runs in Lambda. (Text from the random models is
gibberish by design.) Stop with Ctrl+C.

## 4. Export your real models

Do this on the machine that has your ScribbleAI environment (it needs `torch`). Files you need from ScribbleAI:

| File | Where it is |
|---|---|
| `best_finetune.pt` | Drive (`.../scribbleai/checkpoints/`) or `checkpoints/` of your ScribbleAI clone |
| `best.pt` (base model) | same |
| `char_lm.json` | `data/processed/char_lm.json` (restored from Drive; or rebuild with the LM cell/command you ran in Colab) |
| `corpus.txt` *(optional)* | `data/raw/corpus.txt`; gives the spell checker the training vocabulary |

```bash
python scripts/export_model.py --ckpt  /path/best_finetune.pt --lm /path/char_lm.json --corpus /path/corpus.txt --out build/models/finetuned
python scripts/export_model.py --ckpt  /path/best.pt          --lm /path/char_lm.json --corpus /path/corpus.txt --out build/models/base
```

Each output folder is about 15 MB (a full checkpoint is 40-60 MB because it carries the optimizer state). `build/` is git-ignored.
Check the real thing locally before touching AWS:

```bash
python scripts/local_server.py --models build/models      # real predictions at http://127.0.0.1:7870
```

If the vendored code ever drifts from ScribbleAI (you change preprocessing or the model class): `bash scripts/sync_ml.sh /path/to/scribbleai`, then `pytest`.

## 5. Deploy to AWS (about 15 minutes, mostly waiting)

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
# edit it: alert_email, github_repo = "<you>/scribbleai-cloud"
bash scripts/first_deploy.sh
```

What the script does, so you can explain it (and run the steps by hand if anything fails):

1. `terraform init`, then `terraform apply -target=aws_ecr_repository.inference`: Lambda cannot be created from an image that does not exist,
   so the registry is created first.
2. Logs Docker in to ECR, **builds the image** (`Dockerfile`: Lambda Python 3.12 base + CPU-only PyTorch + `ml/src` + `handler.py`) and pushes `:latest`.
3. `terraform apply`: creates the other ~50 resources (review the plan, type `yes` if you removed `-auto-approve`).

Then:

```bash
# a) open your mailbox and click "Confirm subscription" in the AWS Notifications e-mail (alerts are silent until you do)
# b) upload the models and warm Lambda
bash scripts/upload_models.sh
# c) open the demo
terraform -chdir=infra/terraform output demo_url
# d) optional: command-line check through the whole chain
python scripts/smoke_test.py --url "$(terraform -chdir=infra/terraform output -raw demo_url)"
```

First boot of the EC2 box takes 2-3 minutes after Terraform finishes; if the URL does not answer yet, wait and retry
(`/healthz` answers as soon as nginx is up).

Check in the console (screenshots for your report): **Lambda** (function, image, env vars), **API Gateway** (stage `prod`, usage plan),
**DynamoDB** (Explore items after a few predictions), **S3** (`models/…/model.pt` with versions), **CloudWatch → Dashboards → scribbleai**.

Hand-run equivalent of step 5 if you prefer typing it:

```bash
cd infra/terraform
terraform init && terraform apply -target=aws_ecr_repository.inference
REPO=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin ${REPO%%/*}
cd ../.. && docker build --provenance=false -t $REPO:latest . && docker push $REPO:latest
cd infra/terraform && terraform apply
```

## 6. Connect GitHub Actions (this is the CI/CD the synopsis promises)

```bash
terraform -chdir=infra/terraform output -raw github_actions_variables
```

In GitHub: repository → *Settings → Secrets and variables → Actions → **Variables** tab → New repository variable*. Create one variable
per printed line (`AWS_REGION`, `AWS_ROLE_ARN`, `ECR_REPOSITORY`, `LAMBDA_FUNCTION`, `S3_BUCKET`, `EC2_INSTANCE_ID`, `SNS_TOPIC_ARN`, `DEMO_URL`).
**Variables, not secrets**: there is no password anywhere. GitHub proves its identity to AWS with a short-lived OIDC token, and the IAM role
only trusts branch `main` of your repo.

Test the pipeline end to end:

```bash
# make a visible change, e.g. edit the subtitle text in ui/index.html
git add -A && git commit -m "Tweak subtitle" && git push
```

*Actions* tab → watch `test` → `terraform` → `deploy`. Expected result: the page changes within about 5 minutes and an e-mail
"ScribbleAI deploy success" arrives. To demonstrate the safety net, push a change that breaks a test and show that `deploy` never runs.

Recommended (2 minutes): *Settings → Branches → Add rule* for `main`: require pull requests and the `test` and `terraform` checks.
Faculty like seeing that nothing reaches production untested.

## 7. Day-to-day operations

| I want to… | Do |
|---|---|
| Change the UI | edit `ui/…`, commit, push (CI syncs to S3 and refreshes nginx) |
| Change inference code | edit `lambda/handler.py` or `ml/`, push (CI rebuilds the image and updates Lambda) |
| Ship a retrained model | `export_model.py` → `bash scripts/upload_models.sh` (new S3 version; `aws lambda invoke … warmup` or push any commit to refresh the container) |
| Change infrastructure | edit `infra/terraform/*.tf`, `terraform -chdir=infra/terraform plan`, then `apply` |
| See why a request failed | CloudWatch → Log groups → `/aws/lambda/scribbleai-inference` (the request id is shown on the page) |
| Keep costs near zero between demos | `aws ec2 stop-instances --instance-ids <id>` (the Elastic IP is kept; start it again before a demo) |

## 8. Tear everything down

```bash
terraform -chdir=infra/terraform destroy        # type yes; empties the S3 bucket and ECR repo automatically
```

If `create_github_oidc_provider = true` the OIDC provider is destroyed too; if another project in the same account uses it, set the variable to
`false` first. Afterwards *Billing → Bills* should show no running services. Do this after the evaluation: the synopsis promised the stack can be
"torn down through code".

## 9. What to say about the ML part (synopsis vs what was built)

The synopsis was written before the ML plan changed. Present it as an evolution, with the reasons:

| Synopsis | Built | Why |
|---|---|---|
| IAM-OnDB + small in-house set | Synthetic handwriting lines + UJIpenchars2 characters for training, writer-disjoint in-house tablet set for fine-tuning/evaluation | IAM-OnDB needs registration/licence and was not available in time; synthetic lines give unlimited labelled continuous handwriting |
| 3-layer BiLSTM, 256 units, CTC | Same (3.75 M parameters), 8-dim features | unchanged |
| Beam 10 + character n-gram LM | Same, plus dictionary spell correction; four decoders compared live | extension |
| Targets: CER ≤12% greedy, ≤9% beam+LM on IAM-OnDB test | Synthetic test: 5.2% greedy, 2.24% beam+LM+spell. **In-house real handwriting: 46.9% → 22.4% greedy and 38.8% → 18.9% beam+LM+spell after fine-tuning** | The IAM-OnDB targets no longer apply; the honest headline is the generalisation gap and how fine-tuning closes half of it |
| < 200 ms through Lambda | Measure it: the dashboard shows inference time and p95, the page shows round trip | Report your own numbers after deploying. Expect the first request after an idle period to be much slower (cold start: container start plus loading the model from S3) |

Suggested one-paragraph amendment for the report: *"The recognition engine was retrained on synthetic handwriting lines and
fine-tuned on in-house tablet data because IAM-OnDB was unavailable; the cloud architecture is unchanged. Success is measured on in-house
character error rate (18.9% with beam search, language model and spell correction) and on the operational axis: reproducible deployment,
observed latency and cost."*

## 10. Cost and safety notes

* Expected spend for a demo-scale project is a few dollars or less per month; **verify in Billing → Free Tier**, because eligibility depends on when your
  account was created. The usual non-free items: public IPv4 address (about $3.6/month if not covered by the free tier), ECR storage of a ~1 GB image
  (cents), CloudWatch logs (cents). The $5 budget e-mails you at 80% actual and 100% forecast.
* Throttling at three layers: nginx (10 req/s per address), API Gateway usage plan (10 req/s, 5000/day), Lambda memory/timeout. A runaway client
  cannot run up a bill.
* The API key is stored in SSM Parameter Store (encrypted) and injected by nginx; it is not in the browser, the repo or the AMI. It **is** in the
  Terraform state file, so never commit `*.tfstate` (the `.gitignore` already excludes it).
* Handwriting text is logged to DynamoDB for 30 days. Tell test users, and do not enter personal data on the demo.
* The page is plain HTTP (a campus demo). For HTTPS add CloudFront + ACM in front of EC2; mention it as future work.
* Security group has no SSH port; use *EC2 → Connect → Session Manager* if you must log in.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `terraform apply` fails: *source image … does not exist* | You skipped the image push. Run the ECR-first steps in section 5 |
| `InvalidParameterCombination … not eligible for Free Tier` | Set `instance_type` to the one the EC2 launch wizard marks *Free tier eligible* (`t3.micro` / `t2.micro`) |
| Budget creation: `AccessDenied` | Activate IAM access to billing (section 1, step 2) or run apply as the root-linked admin |
| `EntityAlreadyExists` for the OIDC provider | Set `create_github_oidc_provider = false` |
| Page opens but shows *Can't reach the cloud service* | EC2 still booting (wait 3 min), or nginx failed: Systems Manager → Run Command → `/usr/local/bin/refresh-ui.sh` |
| Page says *no model has been uploaded to S3 yet* | Run `bash scripts/upload_models.sh` |
| `HTTP 403 Forbidden` from API Gateway when you call it yourself | Missing header `x-api-key` (value: `terraform output -raw api_key`) |
| `HTTP 429` | Throttled by design; wait a second |
| First stroke takes several seconds | Cold start. Keep-warm is on (`enable_warmup`), but a second concurrent user or an idle gap beyond a few minutes can still hit one |
| Lambda error `Runtime.ImportModuleError` / image rejected | The image must be built with `--provenance=false` (already in the script and workflow) |
| Deploy job skipped | GitHub variables not set yet (section 6) |
| Deploy job: `AccessDenied` on `AssumeRoleWithWebIdentity` | `github_repo` in `terraform.tfvars` does not match the repository, or you pushed from a branch other than `main` |
