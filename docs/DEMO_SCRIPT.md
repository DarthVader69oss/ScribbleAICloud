# ScribbleAI Azure demo cues

Open the HTTPS URL from `terraform -chdir=infra/azure output -raw demo_url`. Show `/api/info` and confirm the fine-tuned checkpoint. On the original ScribbleAI canvas, write a short line, run recognition and compare decoder outputs. Open `/dashboard` to show the traced ink, timing, decoder costs and recent-line ledger. The dashboard data is in process memory and resets on container restart.

Explain the path: Docker packages the original ScribbleAI demo UI and server, vendored inference code and fine-tuned model; Terraform provisions Azure Container Registry, Container Apps, Log Analytics and a managed image-pull identity. GitHub Actions checks code; a laptop script builds and deploys because model weights are excluded from Git.

This Azure version does not include the optional `/gradio/` file-scoring tab.
