# Docker용 Gunicorn 설정 파일
bind = "0.0.0.0:8000"
workers = 3
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 120
keepalive = 2

# 로깅 (Docker 로그에 출력)
accesslog = "-"
errorlog = "-"
loglevel = "info"

# 프로세스 이름
proc_name = "adstat-docker"

# 데몬 모드 비활성화 (Docker에서는 필요없음)
daemon = False

# Docker 환경 최적화
preload_app = True
worker_tmp_dir = "/dev/shm"  # 메모리 기반 임시 디렉토리 사용 