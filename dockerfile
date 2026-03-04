FROM python:3.11-slim

# Install system dependencies required by Playwright and for building Python packages
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    libnss3 \
    libatk-bridge2.0-0 \
    libxkbcommon0 \
    libgtk-3-0 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libatk1.0-0 \
    libdbus-1-3 \
    libnspr4 \
    libgbm1 \
    libcups2 \
    libatspi2.0-0 \
    libxrandr2 \
    libxfixes3 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

# Copy the rest of the bot code
COPY bot.py .

# Set environment variables
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PORT=10000

# Run the bot
CMD ["python", "bot.py"]
