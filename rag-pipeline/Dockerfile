# rag-api — Track B retrieval service (rag-pipeline/api). Non-root, read-only
# rootfs friendly (no writes at runtime), no build tools in the final image.
# Base pinned tag@digest like every other image in the platform (bump
# procedure in project-1-basic-ai-platform-k8s/values.yaml).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src
COPY pyproject.toml README.md ./
COPY pipeline ./pipeline
COPY api ./api
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-compile ".[api]"

FROM ${PYTHON_IMAGE}
# Dedicated uid/gid; nothing in the image is writable by it.
RUN groupadd -g 10001 rag && useradd -r -u 10001 -g rag -d /nonexistent -s /usr/sbin/nologin rag
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000
# Single worker: the pool is the concurrency unit; scale with replicas.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers"]
