#!/bin/bash

echo "=== AdStat 서버 상태 확인 ==="

# 1. 프로세스 확인
echo "1. Gunicorn 프로세스 확인:"
ps aux | grep gunicorn | grep -v grep

# 2. 포트 사용 확인
echo -e "\n2. 80번 포트 사용 상태:"
sudo netstat -tlnp | grep :80

# 3. HTTP 응답 확인
echo -e "\n3. HTTP 응답 확인:"
curl -s -o /dev/null -w "HTTP 상태: %{http_code}\n" http://localhost

# 4. 로그 확인 (최근 10줄)
echo -e "\n4. 최근 로그 (server.log):"
if [ -f "server.log" ]; then
    tail -10 server.log
else
    echo "server.log 파일이 없습니다."
fi

# 5. 메모리 사용량
echo -e "\n5. 메모리 사용량:"
ps aux | grep gunicorn | grep -v grep | awk '{print $2, $4, $5}' | head -1 