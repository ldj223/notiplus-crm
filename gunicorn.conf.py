# 로컬 환경용 Gunicorn 설정 파일
bind = "0.0.0.0:80"
workers = 3
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 30
keepalive = 2

# 로깅
accesslog = "-"
errorlog = "-"
loglevel = "debug"  # 디버깅을 위해 debug 레벨로 설정

# 프로세스 이름
proc_name = "adstat-local"

# 데몬 모드 비활성화
daemon = False

# 개발 환경 최적화
preload_app = False  # 개발 시에는 False로 설정
reload = True  # 코드 변경 시 자동 재시작 