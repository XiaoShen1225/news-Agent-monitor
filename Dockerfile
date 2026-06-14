FROM python:3.12-slim

WORKDIR /app

# Install system deps: nginx, Chromium browser + Chinese fonts, curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    chromium \
    fonts-wqy-microhei \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (use Alibaba mirror for speed in CN)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# Install only Playwright's system deps (skip browser download — use system Chromium)
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN playwright install-deps chromium

# Tell Playwright where to find the system Chromium
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

# HuggingFace mirror for downloading embedding models in CN
ENV HF_ENDPOINT=https://hf-mirror.com

# Copy project
COPY . .

# Create dirs for runtime data
RUN mkdir -p data/history data/vector_db outputs/data

# Replace default nginx config with ours
COPY nginx.conf /etc/nginx/nginx.conf

# start script (nginx + uvicorn)
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:8080/api/health || exit 1

CMD ["/app/start.sh"]
