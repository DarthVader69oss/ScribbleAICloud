#!/usr/bin/env bash
# Run from Git Bash: bash scripts/deploy_azure.sh v1
set -euo pipefail
cd "$(dirname "$0")/.."
tag="${1:?Usage: bash scripts/deploy_azure.sh IMAGE_TAG (example: v1)}"
[[ "$tag" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || { echo "Invalid Docker tag" >&2; exit 2; }
test -s build/models/finetuned/model.pt || { echo "Export the fine-tuned checkpoint to build/models/finetuned/model.pt first" >&2; exit 1; }
test -f infra/azure/terraform.tfvars || { echo "Create infra/azure/terraform.tfvars from the example" >&2; exit 1; }

az account show --query '{name:name,id:id}' -o table
terraform -chdir=infra/azure init
# Bootstrap ACR before the app: the image must exist before Container Apps can pull it.
terraform -chdir=infra/azure apply \
  -target=azurerm_container_registry.app -var="image_tag=$tag"
registry="$(terraform -chdir=infra/azure output -raw acr_name)"
server="$(terraform -chdir=infra/azure output -raw acr_login_server)"
az acr login --name "$registry"
docker build --platform linux/amd64 -f Dockerfile.azure -t "$server/scribbleai:$tag" .
docker push "$server/scribbleai:$tag"
terraform -chdir=infra/azure apply -var="image_tag=$tag"
terraform -chdir=infra/azure output -raw demo_url
