# ScribbleAI on Azure

The original ScribbleAI live canvas and interactive trace dashboard from `demo.zip`, plus fine-tuned BiLSTM+CTC inference, run in one Azure Container App. Docker packages `build/models/finetuned/model.pt`; Terraform provisions the Azure Container Registry, Container App and Log Analytics workspace.

Read [docs/DEPLOYMENT_GUIDE_AZURE.md](docs/DEPLOYMENT_GUIDE_AZURE.md) before deploying. This project is a replacement for the AWS deployment. The original `demo/app.py` serves the page and the full dashboard API; it loads the exported `model.pt` and vendored inference code without AWS credentials.

Prediction history is kept in the running process's memory and resets on a restart or deployment. The GitHub workflow runs checks, while deployment is run from the laptop holding the fine-tuned checkpoint. No model weights or Terraform state are committed.
