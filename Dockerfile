FROM python:3.13-slim@sha256:881d80734ee05dca6f7f42dcb080975652a53c7eda9ba1f03bb8da31aa6a6ec2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/mpl \
    JOBS_DIR=/data/jobs \
    HOST=0.0.0.0 \
    PORT=8765

RUN apt-get update && apt-get install -y --no-install-recommends \
        libfreetype6 libpng16-16 libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py process.py version.py ./
COPY engine ./engine
COPY templates ./templates
COPY static ./static

RUN mkdir -p /tmp/mpl /data/jobs \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /data/jobs /tmp/mpl

USER appuser
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8765') + '/healthz')"

CMD ["python", "app.py"]
