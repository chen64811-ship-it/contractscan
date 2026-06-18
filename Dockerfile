# ============================================================
# ContractScan Docker Image (CPU version)
# ============================================================

FROM python:3.11-slim-bookworm

ARG DEBIAN_MIRROR=""
RUN if [ -n "$DEBIAN_MIRROR" ]; then \
        echo "deb $DEBIAN_MIRROR bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
        echo "deb $DEBIAN_MIRROR bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb ${DEBIAN_MIRROR}-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    fi

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y --fix-missing && apt-get install -y --no-install-recommends \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt

RUN sed -i '/paddlepaddle-gpu/d' /app/requirements.txt && \
    pip install --no-cache-dir paddlepaddle==2.6.2 && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/

RUN mkdir -p /app/uploads /app/outputs

EXPOSE 8000

CMD ["sh", "-c", "alembic -c backend/alembic.ini upgrade head || true; uvicorn backend.app:app --host 0.0.0.0 --port 8000"]
