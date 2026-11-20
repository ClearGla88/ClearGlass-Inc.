# ClearGlass Active Defense image (lab). Written and validated with `docker compose config`;
# not built in the authoring session (no Docker daemon). Pin the base image by digest before
# any non-lab use: see docs/PRODUCTION_READINESS.md.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin defense \
    && mkdir /data && chown 10001:10001 /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY active_defense ./active_defense
COPY config ./config
COPY rules ./rules
COPY playbooks ./playbooks
COPY deploy ./deploy
COPY defense.py .
USER 10001
ENTRYPOINT ["python", "defense.py"]
