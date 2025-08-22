import datetime
import json
import logging
from google.oauth2.credentials import Credentials
from google.ads import admanager_v1
from django.utils import timezone
from stats.models import AdStats, PlatformCredential
import requests

# 로거 설정
logger = logging.getLogger(__name__)

def fetch_admanager_stats_by_credential(cred, start_date, end_date, report_id=None):
    """
    AdManager 통계 데이터 수집
    
    Args:
        cred: PlatformCredential 객체
        start_date: 시작 날짜
        end_date: 종료 날짜
        report_id: 보고서 ID (선택사항, 없으면 자격증명에서 가져옴)
    """
    user = cred.user
    token_json = cred.token
    if not token_json:
        raise ValueError("인증되지 않은 자격입니다. token 없음")

    creds = Credentials.from_authorized_user_info(
        info=json.loads(token_json),
        scopes=["https://www.googleapis.com/auth/admanager"]
    )
    client = admanager_v1.ReportServiceClient(credentials=creds)

    # report_resource_name 결정
    if report_id:
        # 직접 제공된 보고서 ID 사용
        network_code = cred.network_code
        if not network_code:
            raise ValueError("AdManager network_code가 자격증명에 없습니다.")
        report_resource_name = f"networks/{network_code}/reports/{report_id}"
    else:
        # 자격증명에서 저장된 보고서 정보 사용 (자동 수집용)
        report_resource_name = cred.report_resource_name
        if not report_resource_name:
            raise ValueError("AdManager report_resource_name이 자격증명에 없습니다. 수동으로 보고서를 선택하여 저장해주세요.")

    logger.info(f"AdManager 보고서 실행: {report_resource_name}")

    # 1. 리포트 실행 (비동기)
    operation = client.run_report(name=report_resource_name)
    #logger.info("AdManager report operation started. Waiting for completion...")

    # 2. 완료 대기
    response = operation.result()
    result_resource_name = response.report_result  # networks/NETWORK_CODE/reports/REPORT_ID/results/RESULT_ID

    # 3. 결과 행 반복 조회
    request = admanager_v1.FetchReportResultRowsRequest(name=result_resource_name)
    for row in client.fetch_report_result_rows(request=request):
        try:
            dim = row.dimension_values
            metrics = row.metric_value_groups[0].primary_values

            # 날짜 파싱 (int_value: 20250611 -> 2025-06-11)
            date_int = getattr(dim[0], 'int_value', None)
            if date_int:
                date_str = f"{date_int//10000}-{(date_int//100)%100:02d}-{date_int%100:02d}"
            else:
                date_str = getattr(dim[0], 'string_value', '')
            
            # 광고 단위 정보 파싱
            ad_unit_id = ''
            ad_unit_name = ''
            content_id = ''
            content_name = ''

            # dim[1] is ad_unit_id ("interstitial")
            if len(dim) > 1:
                ad_unit_id = getattr(dim[1], 'string_value', 'N/A')

            # dim[2] has content_id and ad_unit_name
            if len(dim) > 2:
                ad_unit_info = getattr(dim[2], 'string_list_value', None)
                if ad_unit_info and ad_unit_info.values:
                    # "파트너스" -> content_id, content_name
                    if len(ad_unit_info.values) > 0:
                        content_id = ad_unit_info.values[0]
                        content_name = ad_unit_info.values[0]
                    # "파트너스_전면배너_240617" -> ad_unit_name
                    if len(ad_unit_info.values) > 1:
                        ad_unit_name = ad_unit_info.values[1]

            # Fallback if ad_unit_name is empty
            if not ad_unit_name:
                ad_unit_name = ad_unit_id

            # 메트릭 파싱 (9개 값 중 필요한 것들 추출)
            # 로그에서 보면: [수익, CTR, 노출수, 수익2, 노출수2, CTR2, 노출수3, 클릭수, CPC]
            earnings = float(getattr(metrics[0], 'double_value', 0) or getattr(metrics[0], 'int_value', 0) or 0)
            impressions = int(getattr(metrics[2], 'int_value', 0) or getattr(metrics[2], 'double_value', 0) or 0)
            clicks = int(getattr(metrics[7], 'int_value', 0) or getattr(metrics[7], 'double_value', 0) or 0)

            ctr = round(clicks / impressions * 100, 2) if impressions else 0
            ppc = round(earnings / clicks, 2) if clicks else 0

            # logger.info(f"AdManager 파싱 결과: 날짜={date_str}, 광고단위={ad_unit_name}, 수익={earnings}, 클릭={clicks}, 노출={impressions}")

            AdStats.objects.update_or_create(
                user=user,
                platform="admanager",
                alias=cred.alias or "default",
                date=date_str,
                ad_unit_id=ad_unit_id,
                defaults={
                    "ad_unit_name": ad_unit_name,
                    "content_id": content_id,
                    "content_name": content_name,
                    "earnings": earnings,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": ctr,
                    "ppc": ppc,
                    "credential": cred
                }
            )
        except Exception as e:
            logger.error(f"AdManager 행 파싱 실패: {row} / {e}")
            # 디버깅을 위해 전체 row 정보 로깅
            logger.error(f"Row 구조: dim_count={len(dim)}, metrics_count={len(metrics)}")
            for i, d in enumerate(dim):
                logger.error(f"  dim[{i}]: {d}")
            for i, m in enumerate(metrics):
                logger.error(f"  metric[{i}]: {m}")

    # 5. ✅ 마지막 수집 일시 업데이트
    cred.last_fetched_at = timezone.now()
    cred.save(update_fields=["last_fetched_at"])

def get_admanager_reports(cred):
    """AdManager 리포트 목록 조회"""
    if not cred.token:
        raise ValueError("인증되지 않은 자격입니다. token 없음")

    creds = Credentials.from_authorized_user_info(
        info=json.loads(cred.token),
        scopes=["https://www.googleapis.com/auth/admanager"]
    )
    client = admanager_v1.ReportServiceClient(credentials=creds)

    # 1. 네트워크 ID 추출
    network_code = cred.network_code
    if not network_code:
        raise ValueError("AdManager network_code가 자격증명에 없습니다.")

    # logger.info(f"AdManager 네트워크 코드: {network_code}")

    # 2. 리포트 목록 조회
    parent = f"networks/{network_code}"
    request = admanager_v1.ListReportsRequest(parent=parent)
    
    # logger.info(f"AdManager 보고서 조회 요청: {parent}")
    
    try:
        reports = []
        response = client.list_reports(request=request)
        # logger.info(f"AdManager API 응답 타입: {type(response)}")
        
        # 페이지네이션 처리
        page_count = 0
        for page in response.pages:
            page_count += 1
            # logger.info(f"AdManager 페이지 {page_count} 처리 중...")
            
            for report in page.reports:
                # logger.info(f"AdManager 보고서 발견: {report.name} - {getattr(report, 'display_name', 'Unknown')}")
                
                # 시간 필드 안전하게 처리
                create_time = getattr(report, 'create_time', None)
                last_modified_time = getattr(report, 'last_modified_time', None)
                
                reports.append({
                    "id": report.name.split('/')[-1],  # 보고서 ID만 추출
                    "full_name": report.name,  # 전체 리소스 이름
                    "name": getattr(report, 'display_name', 'Unknown'),
                    "status": getattr(report, 'status', 'UNKNOWN'),
                    "created_at": create_time.strftime("%Y-%m-%d %H:%M:%S") if create_time else None,
                    "last_modified": last_modified_time.strftime("%Y-%m-%d %H:%M:%S") if last_modified_time else None
                })
        
        # logger.info(f"AdManager 총 페이지 수: {page_count}, 총 보고서 수: {len(reports)}")
        return reports
    except Exception as e:
        logger.error(f"AdManager 리포트 목록 조회 실패: {str(e)}")
        raise

def save_report_to_credential(cred, report_id):
    """자격증명에 보고서 ID 저장"""
    network_code = cred.network_code
    if not network_code:
        raise ValueError("AdManager network_code가 자격증명에 없습니다.")
    
    report_resource_name = f"networks/{network_code}/reports/{report_id}"
    
    # 자격증명에 보고서 정보 저장
    cred.report_resource_name = report_resource_name
    cred.report_id = report_id
    cred.save()
    
    # logger.info(f"보고서 정보가 자격증명에 저장되었습니다: {report_resource_name}")

def get_admanager_network(cred):
    """AdManager 네트워크 정보 조회"""
    if not cred.token:
        raise Exception("토큰이 없습니다.")

    try:
        # Google Ads API v1 클라이언트 생성
        creds = Credentials.from_authorized_user_info(
            info=json.loads(cred.token),
            scopes=["https://www.googleapis.com/auth/admanager"]
        )
        
        # AdManager 서비스 클라이언트 생성
        client = admanager_v1.NetworkServiceClient(credentials=creds)
        
        # 네트워크 목록 조회
        request = admanager_v1.ListNetworksRequest()
        response = client.list_networks(request=request)
        
        networks = response.networks
        if not networks:
            raise Exception("사용 가능한 네트워크가 없습니다.")

        # 첫 번째 네트워크 정보 반환
        network = networks[0]
        return {
            "id": str(network.network_code),
            "name": network.display_name,
            "currency_code": network.currency_code
        }

    except Exception as e:
        logger.error(f"AdManager 네트워크 조회 중 오류: {str(e)}")
        raise Exception(f"네트워크 조회 중 오류: {str(e)}")