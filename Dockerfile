FROM python:3.12-slim

WORKDIR /app

# Install system deps: Playwright browser + Chinese fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (system deps included)
RUN playwright install --with-deps chromium

# Copy project
COPY . .

# Create dirs for runtime data
RUN mkdir -p data/history outputs/charts/{today,yesterday,two_days_ago,one_week_ago,one_month_ago,total} outputs/data

CMD ["python", "main.py", "--schedule"]
