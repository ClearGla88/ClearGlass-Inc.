# ClearGlass Agent Office API and worker image.
# Build from clearglass-agent-office/:  docker build -f infra/docker/api.Dockerfile -t cg-office-api .
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY config ./config
COPY demo ./demo
COPY packages ./packages
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY office.py .
RUN useradd --uid 10001 --create-home office && mkdir -p /app/var && chown office /app/var
USER office
ENV OFFICE_DB=/app/var/office.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready').status==200 else 1)"
CMD ["python", "office.py", "--db", "/app/var/office.db", "serve", "--host", "0.0.0.0", "--port", "8000"]
