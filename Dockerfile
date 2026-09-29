FROM python:3.11-slim

WORKDIR /app

# Disable python buffering
ENV PYTHONUNBUFFERED=1

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files (accounts/ folder EXCLUDE karo — bot GitHub API se live uthata hai)
COPY bot.py .
COPY Procfile .

# Run the bot
CMD ["python", "bot.py"]
