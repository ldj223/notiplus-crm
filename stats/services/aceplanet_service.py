import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta
from time import gmtime, strftime
import requests
from django.utils import timezone
from stats.models import AdStats, PlatformCredential
import pandas as pd

# 로거 설정
logger = logging.getLogger(__name__)

def fetch_aceplanet_stats_by_credential(cred, start_date, end_date):
    """에이스플래닛 통계 데이터 가져오기"""
    user = cred.user
    credentials = cred.get_credentials()
    access_key = credentials.get("client_id")

    if not all([access_key]):
        raise ValueError("에이스플래닛 인증 정보가 부족합니다.")

    # API 엔드포인트
    base_url = "https://www.aceplanet.co.kr"
    method = "GET"

    # 날짜를 datetime 객체로 변환
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # 월별로 날짜 범위 분할
    date_ranges = []
    current_start = start_dt
    while current_start <= end_dt:
        # 현재 월의 마지막 날 계산
        if current_start.month == 12:
            next_month = current_start.replace(year=current_start.year + 1, month=1, day=1)
        else:
            next_month = current_start.replace(month=current_start.month + 1, day=1)
        
        # 현재 월의 마지막 날과 end_dt 중 작은 값 선택
        current_end = min(next_month - timedelta(days=1), end_dt)
        
        date_ranges.append((current_start, current_end))
        current_start = next_month

    # API 요청 헤더
    headers = {
        "Content-Type": "application/json"
    }

    try:
        for start_dt, end_dt in date_ranges:
            # 날짜 형식 변환 (YYYY-MM-DD -> YYYYMMDD)
            start_date_str = start_dt.strftime("%Y%m%d")
            end_date_str = end_dt.strftime("%Y%m%d")
            
            logger.info(f"데이터 수집 기간: {start_dt.date()} ~ {end_dt.date()}")
            
            # 데이터 요청
            api_url = f"https://www.aceplanet.co.kr/apps/api/rpt_export.html?apiKey={access_key}&sdate={start_date_str}&edate={end_date_str}"
            
            # logger.info(f"aceplanet API 요청 URL: {api_url}")
            response = requests.get(api_url)
            response.raise_for_status()
            data = response.json()
            # logger.info(f"aceplanet API 응답: {json.dumps(data, indent=2, ensure_ascii=False)}")

            # 데이터 처리 및 저장
            if data.get("result") == "success" and data.get("data"):
                for item in data["data"]:
                    try:
                        # 날짜 가져오기
                        date = pd.to_datetime(item['date'], format='%Y%m%d').date()
                        
                        # ad_unit_id 생성
                        ad_unit_id = str(item['impCode'])
                        
                        # 숫자 데이터에서 쉼표 제거
                        revenue = float(item['revenue'].replace(',', '')) if item['revenue'] else 0
                        impressions = int(item['impression'].replace(',', '')) if item['impression'] else 0
                        clicks = int(item['click'].replace(',', '')) if item['click'] else 0
                        sales = int(item['sales'].replace(',', '')) if item['sales'] else 0
                        
                        # 데이터 업데이트 또는 생성
                        AdStats.objects.update_or_create(
                            user=user,
                            platform='aceplanet',
                            alias=cred.alias,
                            date=date,
                            ad_unit_id=ad_unit_id,
                            defaults={
                                'ad_unit_name': item['impName'],
                                'earnings': revenue,
                                'impressions': impressions,
                                'clicks': clicks,
                                'order_count': sales,
                                'credential': cred
                            }
                        )
                    except Exception as e:
                        logger.error(f"aceplanet 데이터 처리 중 오류 발생: {str(e)}")
                        continue

    except requests.exceptions.RequestException as e:
        logger.error(f"aceplanet API 요청 실패: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"에러 응답 상태 코드: {e.response.status_code}")
            logger.error(f"에러 응답 본문: {e.response.text}")
        raise
    except Exception as e:
        logger.error(f"예상치 못한 에러 발생: {str(e)}")
        raise

    # 마지막 수집 시간 업데이트
    cred.last_fetched_at = timezone.now()
    cred.save()