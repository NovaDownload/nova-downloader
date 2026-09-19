FROM python:3.12-slim

# Instala ffmpeg (necesario para extraer audio y unir vídeo+audio en calidades altas)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 10000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "10000"]
