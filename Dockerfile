FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KB_WORKSPACE_ROOT=/workspace \
    KB_WEB_HOST=0.0.0.0 \
    KB_WEB_PORT=8088

WORKDIR /app

ARG INSTALL_MINERU=false

COPY pyproject.toml README.md ./
COPY poc_workflow ./poc_workflow

RUN pip install --no-cache-dir . \
    && if [ "$INSTALL_MINERU" = "true" ]; then pip install --no-cache-dir "mineru[core]"; fi \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /workspace \
    && chown -R appuser:appuser /workspace

USER appuser

EXPOSE 8088

CMD ["python", "-m", "poc_workflow.webapp"]
