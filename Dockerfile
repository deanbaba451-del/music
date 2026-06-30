FROM python:3.10-slim

# sistem kütüphanelerini güncelle
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# çalışma dizinini ayarla
WORKDIR /app

# bağımlılıkları kopyala ve yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# proje dosyalarını kopyala
COPY . .

# flask portunu dışarı aç
EXPOSE 10000

# uygulamayı gunicorn ile başlat
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "main:app"]
