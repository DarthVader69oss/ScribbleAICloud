# ScribbleAI on Azure: step by step

Use **Git Bash on Windows**. Commands run from the root of `scribbleai-cloud` unless stated otherwise. The Azure subscription must permit resource groups, Azure Container Registry, Container Apps, Log Analytics, managed identities, and role assignments. The role assignment needs Owner or User Access Administrator (or an equivalent role assignment permission); Contributor alone cannot create it.

## 1. What changed from both AWS guides

| AWS guide | This Azure build |
|---|---|
| ECR → Lambda → API Gateway; EC2/nginx serves UI | Azure Container Registry → one Azure Container App serves UI and API over HTTPS |
| S3 model objects, switched without image rebuild | Only the fine-tuned `model.pt` is built into the Docker image; updating it needs a new image |
| DynamoDB 30-day prediction log | Recent predictions live in process memory; history resets on restart, redeploy, or replica replacement |
| AWS CloudWatch/SNS/Budgets | Log Analytics receives container logs; no SNS alarms or budget are provisioned |
| GitHub Actions AWS deployment | GitHub Actions runs tests and Terraform validation; deploy from the laptop containing the uncommitted model |
| Two models and model switch | One fine-tuned model; the model switch is hidden |

The same vendored `ml/src`, export script, HTML canvas, dashboard, and `lambda/handler.py` inference logic are reused. The Lambda handler is called by the local HTTP adapter in Azure. `MODEL_IDS=finetuned`, and no AWS credentials are needed. This is a functional Azure demo, not an exact replacement for AWS's persistent logging, API key, throttling or alerts. The public URL accepts anonymous handwriting requests; use synthetic demo text.

## 2. Replace the folder and update the GitHub repo

1. Make a copy of your current `scribbleai-cloud` directory. Keep your existing `.git` folder if this directory is already connected to GitHub.
2. Extract `scribbleai-azure-project.zip` and copy its **contents** into the root of your `scribbleai-cloud` folder. Merge folders and overwrite matching files. The `Dockerfile.azure` must sit beside `README.md`.
3. Delete these **old AWS-only paths** from your working folder if they remain after copying:

   ```bash
   rm -rf infra/terraform deploy
   rm -f Dockerfile scripts/first_deploy.sh scripts/upload_models.sh .github/workflows/ci-cd.yml docs/DEPLOYMENT_GUIDE.md
   ```

   The Azure package already omits those files, but copying over an existing folder does not remove them.
4. Do **not** delete `lambda/`, `ml/`, `ui/`, `scripts/export_model.py`, `scripts/local_server.py`, or `.git`. The Azure server needs them.
5. Check the resulting files:

   ```bash
   ls Dockerfile.azure infra/azure/main.tf scripts/deploy_azure.sh docs/DEPLOYMENT_GUIDE_AZURE.md
   git status --short
   ```

## 3. Install and sign in

Install Docker Desktop, Azure CLI (`az`), Terraform, Git and Python with PyTorch available in your local environment. Start Docker Desktop. Sign in to an Azure subscription you control:

```bash
az login
az account list -o table
az account set --subscription "YOUR-SUBSCRIPTION-ID"
az account show --query '{name:name,id:id}' -o table
docker info
terraform version
```

If `az account list` has no subscription, you cannot deploy until an Azure subscription is assigned. Some student subscriptions restrict resource providers or role assignments; ask the subscription administrator if a permission error appears.

## 4. Export only the fine-tuned checkpoint

The input is the **training** checkpoint from the original ScribbleAI repo. From `scribbleai-cloud`, replace the paths below with yours:

```bash
python scripts/export_model.py \
  --ckpt "../scribbleai/checkpoints/best_finetune.pt" \
  --lm "../scribbleai/data/processed/char_lm.json" \
  --out build/models/finetuned
ls -lh build/models/finetuned/model.pt
```

Omit the `--lm` line if you do not have the character language model. That also removes the beam+LM modes. Optionally add `--corpus "../scribbleai/data/raw/corpus.txt"` if that file exists. The model is git-ignored. Verify it locally:

```bash
MODEL_IDS=finetuned DEFAULT_MODEL=finetuned python scripts/local_server.py --models build/models
```

Open `http://127.0.0.1:7870/api/info` and confirm `finetuned` is available, then press Ctrl+C.

## 5. Configure Azure Terraform

```bash
cp infra/azure/terraform.tfvars.example infra/azure/terraform.tfvars
```

Edit `infra/azure/terraform.tfvars` with a text editor. Set `subscription_id` to the `id` shown by `az account show`. Leave `image_tag = "v1"` initially. `centralindia` is the suggested region; change it if Container Apps or ACR is unavailable there in your subscription. Do not commit `terraform.tfvars` or `.tfstate` files.

Check provider availability if your subscription reports it is not registered:

```bash
az provider show --namespace Microsoft.App --query registrationState -o tsv
az provider show --namespace Microsoft.ContainerRegistry --query registrationState -o tsv
```

If you are permitted to register providers, run `az provider register --namespace Microsoft.App` and the same command for `Microsoft.ContainerRegistry`; otherwise contact the subscription administrator.

## 6. Deploy from Git Bash

Run this from `scribbleai-cloud`:

```bash
bash scripts/deploy_azure.sh v1
```

The script first runs Terraform to create the resource group and private registry. It then logs Docker into the registry, builds the image with `build/models/finetuned/`, pushes `scribbleai:v1`, and runs full Terraform apply to create the Container App, its environment, managed identity, AcrPull assignment, and Log Analytics. Review each Terraform plan and type `yes` for each apply. The script prints the HTTPS demo URL at the end. Azure resource creation may take several minutes.

The targeted apply is **only** the registry bootstrap; the second full apply is essential. If `az acr login` or `docker push` fails, check that your Azure identity has `AcrPush` on this registry. If `azurerm_role_assignment.pull` fails, the subscription owner must grant role assignment permission or provision the identity's `AcrPull` role.

## 7. Verify the demo

```bash
terraform -chdir=infra/azure output -raw demo_url
python scripts/smoke_test.py --url "$(terraform -chdir=infra/azure output -raw demo_url)"
```

Open the printed HTTPS URL. `https://.../api/info` should show `default_model: finetuned` and `available: true`. Draw on the canvas and check the dashboard. For service logs:

```bash
az containerapp logs show \
  --name "$(terraform -chdir=infra/azure output -raw app_name)" \
  --resource-group "$(terraform -chdir=infra/azure output -raw resource_group)" \
  --follow
```

## 8. Push code to GitHub

The model and `.tfvars` stay on your laptop. Push the **code** to your existing repo:

```bash
git status --short
git add -A
git status --short
git commit -m "Port ScribbleAI demo to Azure Container Apps"
git push origin main
```

Before committing, confirm `build/`, `.pt`, `terraform.tfvars`, `.terraform/`, and `*.tfstate` are **absent** from staged changes. `.github/workflows/azure-check.yml` tests the repo and validates Terraform. It does not deploy because the checkpoint is intentionally absent from GitHub. Deployment remains the explicit step 6 on the machine holding the model.

## 9. Updates and teardown

For a UI, code or checkpoint update, export the checkpoint again if needed and run the script with a **new tag** (`v2`, `v3`, etc.):

```bash
bash scripts/deploy_azure.sh v2
```

Use that same tag when running any later `terraform plan` or `apply` directly: `terraform -chdir=infra/azure plan -var='image_tag=v2'`. Tags are immutable by convention; never reuse `v1` for a different build. The Terraform state is stored locally; keep a private backup of the entire `infra/azure` state directory if you need to manage the deployed resources from another laptop.

To delete the Azure resources after the demo, run with the last deployed tag:

```bash
terraform -chdir=infra/azure destroy -var='image_tag=v2'
```

Resource consumption, registry storage, and logs can incur charges while deployed; the project does not create an Azure budget. Container Apps has `min_replicas = 1` to keep the demo ready. Inspect Azure Cost Management and delete the stack when finished.
