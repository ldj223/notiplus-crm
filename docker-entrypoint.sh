#!/bin/bash

# Docker 엔트리포인트 스크립트

echo "AdStat Docker 컨테이너를 시작합니다..."

# Xvfb 시작 (Selenium용)
Xvfb :99 -screen 0 1024x768x24 > /dev/null 2>&1 &
export DISPLAY=:99

# 데이터베이스 마이그레이션 실행
echo "데이터베이스 마이그레이션을 실행합니다..."
python manage.py migrate

# Gunicorn으로 서버 실행
echo "Gunicorn 서버를 시작합니다..."
gunicorn -c gunicorn.docker.conf.py config.wsgi:application 