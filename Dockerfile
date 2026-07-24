FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY backend ./backend
COPY ingestion ./ingestion
COPY frontend ./frontend
COPY data ./data

RUN python -m pip install --no-cache-dir . \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /home/app --create-home app \
    && chown -R app:app /app

USER app

EXPOSE 8000 8501
