FROM python:3.12-slim

WORKDIR /app

# Install system deps: Playwright browser + Chinese fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (use Alibaba mirror for speed in CN)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# Install Playwright Chromium (use npmmirror for download in CN)
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
RUN playwright install --with-deps chromium

# Copy project
COPY . .

# Create dirs for runtime data
RUN mkdir -p data/history data/vector_db outputs/charts/{today,yesterday,two_days_ago,one_week_ago,one_month_ago,total} outputs/data

EXPOSE 8080
CMD ["python", "main.py", "--serve", "--port", "8080"]
