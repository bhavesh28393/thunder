FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 libgtk-3-0 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

COPY bot.py .

CMD ["python", "bot.py"]
