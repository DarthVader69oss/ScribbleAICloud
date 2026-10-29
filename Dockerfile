# Lambda container image for the ScribbleAI inference endpoint.
# Build context = repository root:   docker build -t scribbleai-inference --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
FROM public.ecr.aws/lambda/python:3.12

# CPU-only PyTorch (the CUDA build is ~2 GB and Lambda has no GPU). The "+cpu" local version pins the CPU wheel.
COPY lambda/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir "torch==2.5.1+cpu" --extra-index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Model code (vendored copy of ScribbleAI's inference slice) + the handler. Model WEIGHTS are not in the image: they are in S3.
COPY ml/src ${LAMBDA_TASK_ROOT}/src
COPY lambda/handler.py ${LAMBDA_TASK_ROOT}/handler.py

ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}
CMD ["handler.handler"]
