import datetime
import json
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from django.utils import timezone
from stats.models import AdStats, PlatformCredential

# 로거 설정
logger = logging.getLogger(__name__)

def fetch_adsense_stats_by_credential(cred, start_date, end_date):
    # 1. 사용자 및 자격정보
    user = cred.user
    token_json = cred.token
    client_secret_json = cred.get_credentials().get("secret")

    if not token_json:
        raise ValueError("인증되지 않은 자격입니다. token 없음")

    try:
        creds = Credentials.from_authorized_user_info(
            info=json.loads(token_json),
            scopes=["https://www.googleapis.com/auth/adsense.readonly"]
        )

        service = build("adsense", "v2", credentials=creds)

        # 2. 계정 ID 추출
        accounts = service.accounts().list().execute()
        account_id = accounts["accounts"][0]["name"]  # 예: "accounts/pub-..."

        # 3. 보고서 요청
        report = service.accounts().reports().generate(
            account=account_id,
            dateRange="CUSTOM",
            startDate_year=int(start_date[:4]),
            startDate_month=int(start_date[5:7]),
            startDate_day=int(start_date[8:10]),
            endDate_year=int(end_date[:4]),
            endDate_month=int(end_date[5:7]),
            endDate_day=int(end_date[8:10]),
            dimensions=["DATE", "AD_UNIT_ID", "AD_UNIT_NAME"],
            metrics=["ESTIMATED_EARNINGS", "CLICKS", "PAGE_VIEWS"]
        ).execute()

        # API 응답 로깅
        # logger.info(f"AdSense API 응답: {json.dumps(report, indent=2, ensure_ascii=False)}")

        # 4. 결과 파싱 및 저장
        for row in report.get("rows", []):
            try:
                # dimensionValues: [DATE, AD_UNIT_ID, AD_UNIT_NAME]
                date_str = row["cells"][0]["value"]
                ad_unit_id = row["cells"][1]["value"]
                ad_unit_name = row["cells"][2]["value"]
                
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

                # metricValues: [ESTIMATED_EARNINGS, CLICKS, PAGE_VIEWS]
                earnings = float(row["cells"][3]["value"])
                clicks = int(row["cells"][4]["value"])
                impressions = int(row["cells"][5]["value"])

                ctr = round(clicks / impressions * 100, 2) if impressions else 0
                ppc = round(earnings / clicks, 2) if clicks else 0

                AdStats.objects.update_or_create(
                    user=user,
                    platform="adsense",
                    alias=cred.alias or "default",
                    date=date_obj,
                    ad_unit_id=ad_unit_id,
                    defaults={
                        "ad_unit_name": ad_unit_name,
                        "earnings_usd": earnings,
                        "clicks": clicks,
                        "impressions": impressions,
                        "ctr": ctr,
                        "ppc": ppc
                    }
                )
            except Exception as e:
                logger.error(f"행 데이터 파싱 실패: {json.dumps(row, indent=2, ensure_ascii=False)}")
                logger.error(f"에러 상세: {str(e)}")
                raise

        # 5. ✅ 마지막 수집 일시 업데이트
        cred.last_fetched_at = timezone.now()
        cred.save(update_fields=["last_fetched_at"])

    except Exception as e:
        logger.error(f"보고서 생성 실패: {str(e)}")
        raise RuntimeError(f"보고서 생성 실패: {e}")