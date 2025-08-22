# AdStat - 광고 수익 통합 관리 시스템

## 프로젝트 개요

AdStat은 다양한 광고 플랫폼의 수익 데이터를 통합 관리하고 분석하는 Django 기반 웹 애플리케이션입니다. 구글 애드센스, 애드매니저, 쿠팡 파트너스 등 여러 광고 플랫폼의 데이터를 자동으로 수집하고, 매입 비용 관리, 수익 분석, 정산 보고서 생성 기능을 제공합니다.

## 주요 기능

### 자동 데이터 수집
- **APScheduler 기반 스케줄링**: 1시간마다 자동으로 모든 플랫폼 데이터 수집
- **다중 플랫폼 지원**: 9개 광고 플랫폼 통합 관리
- **사용자별 설정**: 개별 사용자가 자동 수집 주기 설정 가능

### 수익 분석 및 보고서
- **일별/월별 수익 분석**: 퍼블리셔, 파트너스, 스탬플리 구분별 수익 추적
- **매입 비용 관리**: 퍼블리셔별 매입 단가 설정 및 비용 계산
- **순익 계산**: 매출에서 매입 비용을 제외한 순익 분석
- **엑셀 다운로드**: 분석 결과를 엑셀 형태로 내보내기

### 정산 관리
- **정산주관부서 관리**: 부서별 정산 업무 분담
- **환율 관리**: 월별 USD/KRW 환율 설정
- **기타수익 관리**: 수기 입력을 통한 추가 수익 관리
- **월별 조정**: 매출/매입 조정 항목 관리

## 지원 플랫폼

| 플랫폼 | 한국어명 | 주요 기능 |
|--------|----------|-----------|
| adsense | 구글 애드센스 | 광고 수익, 노출수, 클릭수 |
| admanager | 구글 애드매니저 | 광고 단위별 수익 분석 |
| coupang | 쿠팡 파트너스 | 주문건수, 합산금액 |
| cozymamang | 코지마망 | 파트너스 수익 |
| mediamixer | 디온미디어 | 광고 수익 |
| teads | 티즈 | 광고 수익 |
| aceplanet | 에이스플래닛 | 광고 수익 |
| adpost | 네이버 애드포스트 | 광고 수익 |
| taboola | 타불라 | 광고 수익 |

## 기술 스택

### Backend
- **Django4.2
- **Django REST Framework**: API 개발
- **APScheduler**: 자동 작업 스케줄링
- **MySQL/MariaDB**: 데이터베이스
- **Selenium**: 웹 스크래핑
- **Pandas**: 데이터 처리

### Frontend
- **HTML/CSS/JavaScript**: 웹 인터페이스
- **Bootstrap**: UI 프레임워크

### Infrastructure
- **Docker**: 컨테이너화
- **Docker Compose**: 멀티 컨테이너 관리
- **phpMyAdmin**: 데이터베이스 관리 도구

## 데이터베이스 모델 구조

### 🔐 인증 및 사용자 관리
- **PlatformCredential**: 플랫폼별 인증 정보 (암호화 저장)
- **UserPreference**: 사용자별 자동 수집 설정
- **UserProfile**: 사용자 프로필 (메인/서브 계정 구분)

### 📈 광고 통계 데이터
- **AdStats**: 일별 광고 수익 및 성과 데이터
  - 수익, 노출수, 클릭수, CTR, PPC 등
  - 플랫폼별, 광고 단위별 구분

### 💼 정산 및 매입 관리
- **SettlementDepartment**: 정산주관부서 정보
- **Member**: 퍼블리셔/파트너 정보
- **PurchaseGroup**: 매입 그룹 메타데이터
  - 그룹명, 거래처명, 서비스명, 기본 단가
- **PurchasePrice**: 월별 매입 단가 설정
- **PurchaseGroupAdUnit**: 퍼블리셔 그룹과 광고 단위 매핑

### 💱 환율 및 매출 관리
- **ExchangeRate**: 월별 USD/KRW 환율
- **ServiceGroup**: 서비스 그룹 관리
- **MonthlySales**: 월별 매출 데이터

### 📊 통계 데이터
- **MemberStat**: 제휴사 통계 (클릭수, 포인트)
- **TotalStat**: 전체 통계 (페이지뷰, 파워링크)

### ✏️ 수기 입력 데이터
- **OtherRevenue**: 일별 기타수익 수기 입력
  - 퍼블리셔, 파트너스, 스탬플리 구분
- **MonthlyAdjustment**: 월별 매출/매입 조정
  - 조정 금액, 조정 내역, 세금계산서 수취기한

## 주요 API 엔드포인트

### 인증 및 계정 관리
- `POST /login/` - 로그인
- `POST /signup/` - 회원가입
- `GET /credentials/` - 플랫폼 인증 정보 목록
- `POST /credentials/add/` - 인증 정보 추가

### 데이터 수집
- `POST /api/fetch/[object Object]platform}/` - 플랫폼별 데이터 수집
- `GET /api/auto-fetch-days/` - 자동 수집 설정 조회
- `POST /api/save-auto-fetch-setting/` - 자동 수집 설정 저장

### 보고서 및 분석
- `GET /report/` - 통합 수익 보고서
- `GET /publisher-report/` - 퍼블리셔별 상세 보고서
- `GET /purchase-report/` - 매입 비용 보고서
- `GET /sales-report/` - 매출 보고서

### 관리 기능
- `GET /settlement-departments/` - 정산주관부서 관리
- `GET /exchange-rates/` - 환율 관리
- `GET /ad-units/` - 광고 단위 매핑 관리

## 실행

### 1. Docker Compose로 실행
```bash
docker compose up -d
```

### 2. 데이터베이스 마이그레이션
```bash
docker-compose exec web python manage.py migrate
```

### 3. 접속
- 웹 애플리케이션: http://localhost
- phpMyAdmin: http://localhost:5050

## 자동화 기능

### 스케줄러 설정
- **실행 주기**: 1시간마다
- **작업 내용**: `auto_fetch_all` 관리 명령 실행
- **설정 방법**: 사용자별 `UserPreference.auto_fetch_days` 설정

### 수동 실행
```bash
# 모든 플랫폼 데이터 수집
docker compose exec web python manage.py auto_fetch_all

# 특정 플랫폼 데이터 수집
docker compose exec web python manage.py fetch_adsense
```

## 보안 기능

### 데이터 암호화
- **PlatformCredential**: 플랫폼 인증 정보 암호화 저장
- **Fernet 암호화**: 민감한 정보 보호
- **환경 변수**: 암호화 키 분리 관리

### 사용자 권한
- **메인 계정**: 계정별 플랫폼 관리
- **사용자별 데이터 분리**: 개별 사용자 데이터 격리

## 개발 환경

### 환경 변수
```bash
MYSQL_DB=adstat_db
MYSQL_USER=adstat_user
MYSQL_PASSWORD=adstat_password
MYSQL_HOST=db
MYSQL_PORT=336NCRYPTION_KEY=user_encryption_key
DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,12700.1```

### 로그 관리
- 로그 파일 위치: `./logs/`
- 스케줄러 로그: 실시간 작업 상태 모니터링

## 라이선스

이 프로젝트는 내부 사용을 위한 전용 시스템입니다.
