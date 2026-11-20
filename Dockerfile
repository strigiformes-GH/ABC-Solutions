FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; host=os.getenv('TRUSTED_HOSTS', '').split(',')[0].strip() or 'localhost'; req=urllib.request.Request('http://127.0.0.1:'+os.getenv('PORT','8000')+'/healthz', headers={'Host':host}); urllib.request.urlopen(req, timeout=3)"
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
