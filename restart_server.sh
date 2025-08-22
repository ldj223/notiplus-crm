#!/bin/bash

echo "=== AdStat 서버 재기동 ==="

# 1. 기존 컨테이너 중지
echo "기존 Docker 컨테이너를 중지합니다..."
sudo docker compose down

# 2. 서버 재시작
echo "서버를 재시작합니다..."
sudo docker compose up -d

# 서버 로그를 server.log 파일로 리다이렉트
echo "서버 로그를 server.log 파일에 기록합니다..."
sudo docker compose logs -f web > server.log 2>&1 &

echo "재기동 완료!"
echo "로그 확인: tail -f server.log" 