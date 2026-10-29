# ScribbleAI on Azure

The live canvas and fine-tuned BiLSTM+CTC inference run in one Azure Container App. Docker packages `build/models/finetuned/model.pt`; Terraform provisions the Azure Container Registry, Container App and Log Analytics workspace.

Read [docs/DEPLOYMENT_GUIDE_AZURE.md](docs/DEPLOYMENT_GUIDE_AZURE.md) before deploying. This project is a replacement for the AWS deployment. The existing `lambda/handler.py` is reused as a request handler through `scripts/local_server.py`; it runs in local-model mode, without AWS credentials.

Prediction history is kept in the running process's memory and resets on a restart or deployment. The GitHub workflow runs checks, while deployment is run from the laptop holding the fine-tuned checkpoint. No model weights or Terraform state are committed.
