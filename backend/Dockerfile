FROM python:3.12.10-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/mediafetch
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS test
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY pyproject.toml .
COPY app ./app
COPY tests ./tests
RUN mkdir -p /data/downloads /data/temp /credentials \
    && chown -R nobody:nogroup /srv/mediafetch /data /credentials
USER nobody
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "pytest"]

FROM base AS runtime
COPY app ./app
RUN mkdir -p /data/downloads /data/temp /credentials \
    && chown -R nobody:nogroup /srv/mediafetch /data /credentials
USER nobody
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
