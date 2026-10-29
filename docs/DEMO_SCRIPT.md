# Demo script for the cloud faculty (about 8 minutes)

Before you walk in: open the **demo page** on the laptop, the **dashboard** in a second tab, the **AWS console** (CloudWatch dashboard,
Lambda, DynamoDB items, S3 versions) in a third, and the **GitHub Actions** tab in a fourth. Open the demo page on the **tablet** by typing the EC2
address. Send one stroke 2 minutes earlier so Lambda is warm.

| Min | Show | Say |
|---|---|---|
| 0:00 | Architecture figure at the bottom of `dashboard.html` | "A handwriting recogniser is only half a project. This is the operational half: it is reachable by URL, logged, monitored, rebuilt by a pipeline, and cost-capped." |
| 1:00 | Write *hello world* on the **tablet** | "The browser talks only to nginx on EC2. nginx adds the API key server-side, so no secret is in the browser. API Gateway checks the key and throttles. Lambda runs the model." |
| 2:00 | Cloud strip under the sheet | "This request: Lambda took X ms, the rest was network and API Gateway. Warm container: the model was already in memory." |
| 2:45 | Switch **Fine-tuned ↔ Base**, press *Compare decoders* | "Both models are files in S3, not baked into the image. Same pipeline, and the page shows the S3 version id of the model that answered." |
| 3:30 | **Dashboard**: KPIs, latency chart, latest predictions | "Every prediction is a DynamoDB row: text, confidence, latency split, model version, cold-start flag. Rows expire after 30 days." |
| 4:15 | AWS console → **DynamoDB** items, **S3** versions | Proof it is the real service, not a mock. |
| 5:00 | Wait 10+ min beforehand / or show the CloudWatch **Duration max** line | "Cold start: a fresh container downloads the model from S3 and loads PyTorch. We keep one warm with an EventBridge ping every 5 minutes, which costs almost nothing." |
| 5:45 | **GitHub Actions** run | "Push to main: tests (with mocked AWS), `terraform validate`, build the container, push to ECR, update Lambda, smoke-test the function, sync the UI, refresh EC2, check end to end, e-mail the team. Authentication is OIDC; there are no AWS keys in GitHub." |
| 6:45 | `infra/terraform` folder, then `terraform plan` (shows *No changes*) | "The whole stack, about 50 resources, is code. One `apply` rebuilds it; `destroy` removes it. IAM roles are scoped to single resources." |
| 7:30 | CloudWatch dashboard, alarms list, budget | "Errors, 5xx and instance health alarm to SNS e-mail; a $5 budget warns before cost matters." |

## Questions to expect

* **Why Lambda and not EC2 for inference?** Spiky, demo-scale traffic: you pay per request, nothing to patch, scales to zero. Trade-off: cold starts, handled with keep-warm and a slim 15 MB model.
* **Why is the model not in the container?** Decouples model releases from code releases; S3 versioning gives rollback and traceability.
* **How do you stop abuse?** nginx rate limit, API key + usage plan quota, Lambda timeout and memory, input size limits in the handler, budget alert.
* **Single point of failure?** The EC2 front end (one instance). Mitigation: it holds no state and can be rebuilt by Terraform in minutes; the API itself is regional and managed. Future: CloudFront + S3 static hosting.
* **What does it cost?** Show the Billing page and the budget.
* **How would you scale it?** Provisioned concurrency or more memory for latency; DynamoDB on-demand already scales; SQS + async if long jobs appear.
