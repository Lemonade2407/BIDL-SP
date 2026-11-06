FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/bidl/backend:/opt/bidl
WORKDIR /opt/bidl
RUN apt-get update && apt-get install -y --no-install-recommends fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN useradd --create-home --uid 10001 bidl && mkdir -p /opt/bidl/.runtime && chown -R bidl:bidl /opt/bidl/.runtime

FROM base AS api
COPY backend backend
COPY algo algo
COPY transunet transunet
USER bidl
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]

# Worker 的 PyTorch 安装层位于业务代码 COPY 之前，
# 因此修改 backend/algo 不会触发 175MB 的 torch 重新下载。
FROM base AS worker
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY transunet ./transunet
# 优先使用仓库内的 transunet/TransUNet（submodule）源码，避免构建期依赖 GitHub；
# 缺失时才按固定 commit 拉取，并对不稳定网络重试。
RUN if [ -f /opt/bidl/transunet/TransUNet/networks/vit_seg_modeling.py ]; then \
        echo "using vendored TransUNet sources"; \
    else \
        git init -q /tmp/transunet-source \
        && git -C /tmp/transunet-source remote add origin https://github.com/Beckschen/TransUNet.git \
        && for attempt in 1 2 3 4 5; do \
             echo "fetch attempt $attempt"; \
             git -C /tmp/transunet-source -c http.version=HTTP/1.1 fetch --depth 1 origin 02ef0010b36eb8328b5e689eadaf613602edf9b8 && break; \
             sleep 5; \
           done \
        && git -C /tmp/transunet-source checkout --detach FETCH_HEAD \
        && rm -rf /tmp/transunet-source/.git \
        && mkdir -p /opt/bidl/transunet/TransUNet \
        && cp -a /tmp/transunet-source/. /opt/bidl/transunet/TransUNet/ \
        && rm -rf /tmp/transunet-source; \
    fi
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir scipy ml_collections tqdm
COPY backend backend
COPY algo algo
USER bidl
CMD ["celery", "-A", "app.worker:app", "worker", "-Q", "default,inference.cpu,eval", "-c", "1", "-l", "info"]
