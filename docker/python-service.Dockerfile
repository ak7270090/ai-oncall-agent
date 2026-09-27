# Shared image for the Python services. Build with the service folder as context:
#   docker build -f docker/python-service.Dockerfile \
#     --build-arg APP_ENTRYPOINT=server.py --build-arg APP_PORT=9000 mcp-server
FROM python:3.11-slim

ARG APP_ENTRYPOINT
ARG APP_PORT

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    APP_ENTRYPOINT=${APP_ENTRYPOINT}

WORKDIR /app
RUN useradd --create-home --uid 10001 app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Numeric UID so Kubernetes `runAsNonRoot` can verify it.
USER 10001
EXPOSE ${APP_PORT}
CMD ["sh", "-c", "exec python \"$APP_ENTRYPOINT\""]
