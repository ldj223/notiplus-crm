#!/bin/bash

# 사내용 서버 실행 스크립트

echo "AdStat 서버를 시작합니다..."

# Docker 환경에서 서버 실행
echo "Docker 환경에서 서버를 시작합니다..."

# Docker Compose로 서버 실행
sudo docker compose up -d

# 서버 로그를 server.log 파일로 리다이렉트
echo "서버 로그를 server.log 파일에 기록합니다..."
sudo docker compose logs -f web > server.log 2>&1 &

echo "서버가 시작되었습니다. http://localhost"
echo "로그 확인: tail -f server.log"