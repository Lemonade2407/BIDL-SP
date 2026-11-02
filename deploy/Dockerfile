FROM python:3.11-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/bidl/backend:/opt/bidl
WORKDIR /opt/bidl
RUN apt-get update && apt-get install -y --no-install-recommends fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend backend
COPY algo algo
COPY transunet transunet
RUN useradd --create-home --uid 10001 bidl && mkdir -p /opt/bidl/.runtime && chown -R bidl:bidl /opt/bidl/.runtime
USER bidl
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]

FROM api AS worker
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git init /tmp/transunet-source \
    && git -C /tmp/transunet-source remote add origin https://github.com/Beckschen/TransUNet.git \
    && git -C /tmp/transunet-source fetch --depth 1 origin 02ef0010b36eb8328b5e689eadaf613602edf9b8 \
    && git -C /tmp/transunet-source checkout --detach FETCH_HEAD \
    && rm -rf /tmp/transunet-source/.git \
    && mkdir -p /opt/bidl/transunet/TransUNet \
    && cp -a /tmp/transunet-source/. /opt/bidl/transunet/TransUNet/ \
    && rm -rf /tmp/transunet-source
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir scipy ml_collections tqdm
USER bidl
CMD ["celery", "-A", "app.worker:app", "worker", "-Q", "default,inference.cpu,eval", "-c", "1", "-l", "info"]
