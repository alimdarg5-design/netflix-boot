FROM python:3.11-slim
# cache-bust: 2026-09-30

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY Procfile .

CMD ["python", "bot.py"]
