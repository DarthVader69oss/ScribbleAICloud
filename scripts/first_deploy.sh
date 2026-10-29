#!/usr/bin/env bash
# One-time bootstrap. Terraform cannot create a Lambda from an image that is not in ECR yet, so:
#   1) create the ECR repository   2) build + push the first image   3) create everything else.
# Needs: terraform, docker (running), aws CLI configured, infra/terraform/terraform.tfvars filled in.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=infra/terraform"
$TF init
$TF apply -auto-approve -target=aws_ecr_repository.inference
REPO=$($TF output -raw ecr_repository_url)
REGION=$($TF output -raw region)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}"
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo dev)
docker build --provenance=false --build-arg GIT_SHA="$SHA" -t "$REPO:latest" .
docker push "$REPO:latest"
$TF apply
echo
echo "== Next =="
echo "1. Confirm the SNS subscription e-mail AWS just sent you."
echo "2. Upload the models:           bash scripts/upload_models.sh"
echo "3. Open the demo:               $($TF output -raw demo_url)"
echo "4. Copy these into GitHub (Settings > Secrets and variables > Actions > Variables):"
$TF output -raw github_actions_variables
