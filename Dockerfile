FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install hash-verified dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

COPY . .

RUN useradd --system --no-create-home app && chown -R app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=4)"

CMD ["gunicorn", "fuel_route_api.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
