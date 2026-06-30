# Resmi Python hafif imajını kullanıyoruz
FROM python:3.10-slim

# Çalışma dizinini ayarla
WORKDIR /app

# Gerekli sistem paketlerini yükle (SQLite kararlılığı için)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Bağımlılık listesini kopyala ve yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tüm proje kodlarını içeri aktar
COPY . .

# Flask API için portu dışarı aç (Render otomatik yakalar)
EXPOSE 10000

# Uygulamayı başlat
CMD ["python", "main.py"]
