FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0

WORKDIR /app

COPY requirements.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt

COPY . .

# По умолчанию SQLite и фото лежат в /app/storage.
ENV DB_PATH=/app/storage/barbershop.db \
    MEDIA_DIR=/app/storage/media

RUN mkdir -p /app/storage/media
VOLUME ["/app/storage"]

EXPOSE 8080
CMD ["python", "main.py"]
