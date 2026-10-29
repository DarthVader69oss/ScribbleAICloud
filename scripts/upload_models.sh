#!/usr/bin/env bash
# Upload the exported models (scripts/export_model.py output) to the S3 bucket created by Terraform.
# Usage:  bash scripts/upload_models.sh            (run from the repository root, AWS credentials configured)
set -euo pipefail
BUCKET=$(terraform -chdir=infra/terraform output -raw model_upload_prefix)     # s3://<bucket>/models/
for id in finetuned base; do
  if [ -f "build/models/$id/model.pt" ]; then
    aws s3 sync "build/models/$id/" "${BUCKET}${id}/" --exclude "*" --include "model.pt" --include "char_lm.json" --include "corpus.txt"
  else
    echo "skipping $id: build/models/$id/model.pt not found"
  fi
done
aws s3 ls "$BUCKET" --recursive --human-readable
FN=$(terraform -chdir=infra/terraform output -raw lambda_function_name)
echo "Warming the function (loads both models from S3)..."
aws lambda invoke --function-name "$FN" --payload '{"warmup":true}' --cli-binary-format raw-in-base64-out /tmp/warm.json >/dev/null && cat /tmp/warm.json && echo
