FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app
RUN useradd --create-home --uid 10001 app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# The audit log (MCP_AUDIT_LOG_PATH); compose mounts it so `make audit` can read it.
RUN mkdir -p logs && chown 10001 logs

# Numeric UID so Kubernetes runAsNonRoot can verify it.
USER 10001
EXPOSE 9000
CMD ["python", "server.py"]
