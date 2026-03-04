FROM mcr.microsoft.com/playwright:v1.40.0-focal

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY bot.py .

# Render ke liye port variable set karo
ENV PORT=10000

# Run the bot
CMD ["python", "bot.py"]
