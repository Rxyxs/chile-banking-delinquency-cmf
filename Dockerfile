# Imagen de la API del motor de estres: solo dependencias de ejecucion, usuario sin privilegios.
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    CMF_DATA_DIR=/app/data

WORKDIR /app

COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

COPY src/ src/
COPY data/panel_mora90.csv data/macro_indicators.csv data/

RUN useradd --create-home --uid 10001 app && mkdir -p warehouse && chown app warehouse
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "cmf_delinquency.api:app", "--host", "0.0.0.0", "--port", "8000"]
