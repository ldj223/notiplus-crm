import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta
from time import gmtime, strftime
import requests
from django.utils import timezone
from django.db import transaction
from stats.models import AdStats, PlatformCredential

# 로거 설정
logger = logging.getLogger(__name__)

def generate_hmac(method, url, secret_key, access_key):
    """HMAC 생성"""
    # URL 파싱
    path, *query = url.split("?")
    
    # GMT 시간 생성 (YYYYMMDD'T'HHMMSS'Z')
    datetimeGMT = strftime('%y%m%d', gmtime()) + 'T' + strftime('%H%M%S', gmtime()) + 'Z'
    
    # 메시지 생성 (시간 + 메소드 + 경로 + 쿼리)
    message = datetimeGMT + method + path + (query[0] if query else "")
    
    # HMAC SHA256 서명 생성
    signature = hmac.new(
        bytes(secret_key, "utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    # Authorization 헤더 생성
    return f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={datetimeGMT}, signature={signature}"

def make_api_request_with_retry(url, headers, max_retries=3, retry_delay=2):
    """API 요청을 재시도 로직과 함께 수행"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"API 요청 실패 (시도 {attempt + 1}/{max_retries}): {url}, 에러: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # 지수 백오프
            else:
                raise e

def save_stats_batch(user, cred, stats_batch, batch_size=100):
    """배치 단위로 통계 데이터 저장"""
    saved_count = 0
    failed_count = 0
    
    for i in range(0, len(stats_batch), batch_size):
        batch = stats_batch[i:i + batch_size]
        
        try:
            with transaction.atomic():
                for date_str, stats in batch:
                    try:
                        AdStats.objects.update_or_create(
                            user=user,
                            platform="coupang",
                            alias=cred.alias or "default",
                            date=datetime.strptime(date_str, "%Y%m%d").date(),
                            defaults={
                                "earnings": stats["earnings"],
                                "clicks": stats["clicks"],
                                "order_count": stats["order_count"],
                                "total_amount": stats["total_amount"],
                                "credential": cred
                            }
                        )
                        saved_count += 1
                    except Exception as e:
                        # logger.error(f"개별 데이터 저장 실패: {date_str}, stats={stats}, 에러: {str(e)}")  # stats 데이터가 길어질 수 있음
                        logger.error(f"개별 데이터 저장 실패: {date_str}, 에러: {str(e)[:200]}...")  # 에러 메시지 길이 제한
                        failed_count += 1
                        # 개별 실패는 계속 진행
        except Exception as e:
            logger.error(f"배치 저장 실패 (배치 {i//batch_size + 1}): {str(e)[:200]}...")  # 에러 메시지 길이 제한
            failed_count += len(batch)
    
    return saved_count, failed_count

def fetch_coupang_stats_by_credential(cred, start_date, end_date):
    """쿠팡 파트너스 통계 데이터 가져오기 (안정성 개선)"""
    user = cred.user
    credentials = cred.get_credentials()
    access_key = credentials.get("client_id")
    secret_key = credentials.get("secret")

    if not all([access_key, secret_key]):
        raise ValueError("쿠팡 파트너스 인증 정보가 부족합니다.")

    # API 엔드포인트
    base_url = "https://api-gateway.coupang.com"
    method = "GET"

    # 날짜를 datetime 객체로 변환
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # 더 작은 단위로 날짜 범위 분할 (주별 또는 7일 단위)
    date_ranges = []
    current_start = start_dt
    while current_start <= end_dt:
        # 7일 단위로 분할 (더 안정적인 처리)
        current_end = min(current_start + timedelta(days=6), end_dt)
        date_ranges.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)

    # API 요청 헤더
    headers = {
        "Content-Type": "application/json"
    }

    total_saved = 0
    total_failed = 0

    try:
        for start_dt, end_dt in date_ranges:
            # 날짜 형식 변환 (YYYY-MM-DD -> YYYYMMDD)
            start_date_str = start_dt.strftime("%Y%m%d")
            end_date_str = end_dt.strftime("%Y%m%d")
            
            logger.info(f"데이터 수집 기간: {start_dt.date()} ~ {end_dt.date()}")
            
            try:
                # 1. 커미션 데이터 요청
                commission_params = {
                    "startDate": start_date_str,
                    "endDate": end_date_str
                }
                commission_query_string = "&".join([f"{k}={v}" for k, v in commission_params.items()])
                commission_path = f"/v2/providers/affiliate_open_api/apis/openapi/v1/reports/commission?{commission_query_string}"
                commission_url = f"{base_url}{commission_path}"
                commission_auth = generate_hmac(method, commission_path, secret_key, access_key)

                headers["Authorization"] = commission_auth
                commission_data = make_api_request_with_retry(commission_url, headers)
                
                # JSON 데이터 원본 로깅
                # logger.info(f"쿠팡 커미션 데이터 원본: {json.dumps(commission_data, ensure_ascii=False, indent=2)}")  # 응답 데이터가 길어질 수 있음
                
                time.sleep(1)  # API 요청 사이에 1초 지연

                # 2. 클릭 데이터 요청 (스트리밍 방식으로 처리)
                clicks_by_date = {}
                page = 0
                max_pages = 50  # 최대 페이지 수 제한 (안전장치)
                
                while page < max_pages:
                    clicks_params = {
                        "startDate": start_date_str,
                        "endDate": end_date_str,
                        "page": page
                    }
                    clicks_query_string = "&".join([f"{k}={v}" for k, v in clicks_params.items()])
                    clicks_path = f"/v2/providers/affiliate_open_api/apis/openapi/v1/reports/clicks?{clicks_query_string}"
                    clicks_url = f"{base_url}{clicks_path}"
                    clicks_auth = generate_hmac(method, clicks_path, secret_key, access_key)

                    headers["Authorization"] = clicks_auth
                    clicks_data = make_api_request_with_retry(clicks_url, headers)
                
                    time.sleep(1)  # API 요청 사이에 1초 지연

                    if clicks_data.get("rCode") == "0" and clicks_data.get("data"):
                        # 스트리밍 방식으로 즉시 처리 (메모리 절약)
                        for click_item in clicks_data["data"]:
                            date_str = click_item["date"]
                            clicks = int(click_item.get("click", 0))
                            clicks_by_date[date_str] = clicks_by_date.get(date_str, 0) + clicks
                        
                        # 다음 페이지가 있는지 확인 (1000개 미만이면 마지막 페이지)
                        if len(clicks_data["data"]) < 1000:
                            break
                        page += 1
                    else:
                        break

                # 3. 데이터 통합 및 배치 저장
                stats_batch = []
                
                # 커미션 데이터 처리 - 같은 날짜 데이터 합치기
                date_stats = {}  # 날짜별로 데이터 누적
                
                if commission_data.get("rCode") == "0" and commission_data.get("data"):
                    for item in commission_data["data"]:
                        date_str = item["date"]
                        
                        if date_str not in date_stats:
                            date_stats[date_str] = {
                                "clicks": 0,
                                "earnings": 0,
                                "order_count": 0,
                                "total_amount": 0
                            }
                        
                        # 데이터 누적
                        date_stats[date_str]["earnings"] += float(item.get("commission", 0))
                        date_stats[date_str]["order_count"] += int(item.get("order", 0))
                        date_stats[date_str]["total_amount"] += float(item.get("gmv", 0))
                
                # 누적된 데이터를 stats_batch에 추가
                for date_str, stats in date_stats.items():
                    stats["clicks"] = clicks_by_date.get(date_str, 0)
                    stats_batch.append((date_str, stats))
                    logger.info(f"날짜 {date_str}: 수익 {stats['earnings']:,.0f}원, 주문 {stats['order_count']}건, 클릭 {stats['clicks']}회")
                
                # 클릭만 있고 커미션이 없는 날짜도 처리
                for date_str, clicks in clicks_by_date.items():
                    # 이미 커미션 데이터로 처리된 날짜는 건너뛰기
                    if not any(date_str == batch_date for batch_date, _ in stats_batch):
                        stats = {
                            "clicks": clicks,
                            "earnings": 0,
                            "order_count": 0,
                            "total_amount": 0
                        }
                        stats_batch.append((date_str, stats))

                # 배치 저장
                if stats_batch:
                    saved_count, failed_count = save_stats_batch(user, cred, stats_batch)
                    total_saved += saved_count
                    total_failed += failed_count
                    logger.info(f"기간 {start_dt.date()} ~ {end_dt.date()}: {saved_count}개 저장, {failed_count}개 실패")

            except Exception as e:
                logger.error(f"기간 {start_dt.date()} ~ {end_dt.date()} 처리 실패: {str(e)[:200]}...")  # 에러 메시지 길이 제한
                # 개별 기간 실패는 전체 프로세스를 중단하지 않음
                continue

    except Exception as e:
        logger.error(f"Coupang API 전체 처리 실패: {str(e)[:200]}...")  # 에러 메시지 길이 제한
        # 전체 실패 시에도 마지막 수집 시간은 업데이트
    finally:
        # 마지막 수집 시간 업데이트
        cred.last_fetched_at = timezone.now()
        cred.save()
        
        logger.info(f"쿠팡 데이터 수집 완료: 총 {total_saved}개 저장, {total_failed}개 실패")