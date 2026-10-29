# ScribbleAI Azure demo cues

Open the HTTPS URL from `terraform -chdir=infra/azure output -raw demo_url`. Show `/api/info`: only `finetuned` is available. On the canvas, write a short line, run recognition, and compare the decoder outputs. Open `dashboard.html` to show recent requests and timing. The dashboard is process-memory data and resets on container restart.

Explain the path: Docker packages the fine-tuned BiLSTM+CTC model and UI; Terraform creates Azure Container Registry, Container Apps, Log Analytics and a managed image-pull identity. The browser sends pen points to the Container App. The Python service preprocesses them, runs the model, decodes the text and returns timing information. GitHub Actions checks code; a local script builds and deploys because model weights are excluded from Git.

Do not describe this build as using AWS Lambda, API Gateway, DynamoDB, S3, ECR, CloudWatch alarms, or continuous deployment. Those were in the earlier AWS implementation.
