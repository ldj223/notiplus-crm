FROM python:3.9-slim

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    xvfb \
    chromium \
    chromium-driver \
    libxi6 \
    libgconf-2-4 \
    libnss3 \
    libxss1 \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    wget \
    gnupg \
    unzip \
    default-jdk \
    default-libmysqlclient-dev \
    pkg-config \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Chromium을 기본 브라우저로 설정
RUN ln -fs /usr/bin/chromium /usr/bin/google-chrome
RUN ln -s /usr/bin/chromedriver /usr/local/bin/chromedriver

WORKDIR /app

# Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 데이터베이스 마이그레이션 실행
# CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]

# Gunicorn으로 실행 (기본값)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "config.wsgi:application"]