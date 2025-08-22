import os, json
from datetime import datetime
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from django.utils import timezone
from oauthlib.oauth2 import InvalidClientError
from google_auth_oauthlib.flow import Flow
import pandas as pd

from .models import AdStats
from .models import PlatformCredential
from .services.adsense_service import fetch_adsense_stats_by_credential
from .services.admanager_service import fetch_admanager_stats_by_credential, get_admanager_reports, save_report_to_credential, get_admanager_network
from .services.coupang_service import fetch_coupang_stats_by_credential
from .services.cozymamang_service import fetch_cozymamang_stats_by_credential
from .services.mediamixer_service import fetch_mediamixer_stats_by_credential
from .services.teads_service import fetch_teads_stats_by_credential
from .services.aceplanet_service import fetch_aceplanet_stats_by_credential

# ===== 유틸리티 함수 =====
def get_required(params, keys):
    """필수 파라미터 검사"""
    for key in keys:
        if not params.get(key):
            return key
    return None

# ===== API 관련 함수 =====
@csrf_exempt
@login_required
def fetch_adsense_api(request):
    """AdSense API 데이터 수집"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["start_date", "end_date"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        credentials = PlatformCredential.objects.filter(
            user=request.user, 
            platform="adsense"
        ).exclude(token__isnull=True)

        results = []
        for cred in credentials:
            try:
                fetch_adsense_stats_by_credential(cred, data["start_date"], data["end_date"])
                results.append({"alias": cred.alias, "status": "success"})
            except Exception as e:
                results.append({"alias": cred.alias, "status": "error", "message": str(e)})
        return JsonResponse({"results": results})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
# ===== API 관련 함수 =====
@csrf_exempt
@login_required
def fetch_admanager_api(request):
    """AdManager API 데이터 수집"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["start_date", "end_date"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        credentials = PlatformCredential.objects.filter(
            user=request.user, 
            platform="admanager"
        ).exclude(token__isnull=True)

        results = []
        for cred in credentials:
            try:
                # 보고서 ID가 제공되면 사용, 없으면 자격증명에서 가져옴
                report_id = data.get("report_id")
                fetch_admanager_stats_by_credential(cred, data["start_date"], data["end_date"], report_id)
                results.append({"alias": cred.alias, "status": "success"})
            except Exception as e:
                results.append({"alias": cred.alias, "status": "error", "message": str(e)})
        return JsonResponse({"results": results})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
@login_required
def get_admanager_reports_api(request):
    """AdManager 보고서 목록 조회"""
    if request.method != "GET":
        return JsonResponse({"status": "error", "message": "GET 요청만 허용됩니다."}, status=400)
    
    try:
        data = request.GET
        alias = data.get("alias")
        
        if not alias:
            return JsonResponse({"status": "error", "message": "alias 파라미터가 필요합니다."}, status=400)

        cred = PlatformCredential.objects.filter(
            user=request.user, 
            platform="admanager",
            alias=alias
        ).exclude(token__isnull=True).first()
        
        if not cred:
            return JsonResponse({"status": "error", "message": "해당 자격증명을 찾을 수 없습니다."}, status=404)

        reports = get_admanager_reports(cred)
        return JsonResponse({"status": "success", "reports": reports})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
@login_required
def save_admanager_report_api(request):
    """AdManager 보고서 ID를 자격증명에 저장"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["alias", "report_id"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        cred = PlatformCredential.objects.filter(
            user=request.user, 
            platform="admanager",
            alias=data["alias"]
        ).exclude(token__isnull=True).first()
        
        if not cred:
            return JsonResponse({"status": "error", "message": "해당 자격증명을 찾을 수 없습니다."}, status=404)

        save_report_to_credential(cred, data["report_id"])
        return JsonResponse({"status": "success", "message": "보고서가 자격증명에 저장되었습니다."})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
@login_required
def fetch_coupang_api(request):
    """쿠팡 파트너스 API 데이터 수집"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["start_date", "end_date"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        credentials = PlatformCredential.objects.filter(
            user=request.user, 
            platform="coupang"
        )

        results = []
        for cred in credentials:
            try:
                fetch_coupang_stats_by_credential(cred, data["start_date"], data["end_date"])
                results.append({"alias": cred.alias, "status": "success"})
            except Exception as e:
                results.append({"alias": cred.alias, "status": "error", "message": str(e)})
        return JsonResponse({"results": results})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
@login_required
def fetch_cozymamang_api(request):
    """코지마망 API 데이터 수집"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["start_date", "end_date"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        credentials = PlatformCredential.objects.filter(
            user=request.user, 
            platform="cozymamang"
        )

        results = []
        for cred in credentials:
            try:
                fetch_cozymamang_stats_by_credential(cred, data["start_date"], data["end_date"])
                results.append({"alias": cred.alias, "status": "success"})
            except Exception as e:
                results.append({"alias": cred.alias, "status": "error", "message": str(e)})
        return JsonResponse({"results": results})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
@login_required
def fetch_mediamixer_api(request):
    """디온믹스 API 데이터 수집"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["start_date", "end_date"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        credentials = PlatformCredential.objects.filter(
            user=request.user, 
            platform="mediamixer"
        )

        results = []
        for cred in credentials:
            try:
                fetch_mediamixer_stats_by_credential(cred, data["start_date"], data["end_date"])
                results.append({"alias": cred.alias, "status": "success"})
            except Exception as e:
                results.append({"alias": cred.alias, "status": "error", "message": str(e)})
        return JsonResponse({"results": results})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
@login_required
def fetch_teads_api(request):
    """Teads API 데이터 수집"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["start_date", "end_date"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        credentials = PlatformCredential.objects.filter(
            user=request.user, 
            platform="teads"
        )

        results = []
        for cred in credentials:
            try:
                fetch_teads_stats_by_credential(cred, data["start_date"], data["end_date"])
                results.append({"alias": cred.alias, "status": "success"})
            except Exception as e:
                results.append({"alias": cred.alias, "status": "error", "message": str(e)})
        return JsonResponse({"results": results})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
@csrf_exempt
@login_required
def fetch_aceplanet_api(request):
    """에이스플래닛 API 데이터 수집"""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST 요청만 허용됩니다."}, status=400)
    
    try:
        data = json.loads(request.body)
        missing = get_required(data, ["start_date", "end_date"])
        if missing:
            return JsonResponse({"status": "error", "message": f"{missing} 누락"}, status=400)

        credentials = PlatformCredential.objects.filter(
            user=request.user, 
            platform="aceplanet"
        )

        results = []
        for cred in credentials:
            try:
                fetch_aceplanet_stats_by_credential(cred, data["start_date"], data["end_date"])
                results.append({"alias": cred.alias, "status": "success"})
            except Exception as e:
                results.append({"alias": cred.alias, "status": "error", "message": str(e)})
        return JsonResponse({"results": results})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
@login_required
def upload_adpost_excel(request):
    """Adpost Excel/CSV 파일 업로드 처리"""
    if request.method != "POST":
        return JsonResponse({"error": "잘못된 요청입니다."}, status=400)

    try:
        file = request.FILES.get("file")
        if not file:
            return JsonResponse({"error": "파일이 없습니다."}, status=400)

        account_id = request.POST.get("account_id")
        if not account_id:
            return JsonResponse({"error": "계정이 선택되지 않았습니다."}, status=400)

        # 자격증명 조회
        cred = PlatformCredential.objects.filter(user=request.user, platform="adpost", alias=account_id).first()
        if not cred:
            return JsonResponse({"error": "등록되지 않은 계정입니다."}, status=400)

        # 파일 확장자 확인
        file_ext = file.name.split('.')[-1].lower()
        if file_ext not in ['xlsx', 'xls', 'csv']:
            return JsonResponse({"error": "지원하지 않는 파일 형식입니다. (지원: xlsx, xls, csv)"}, status=400)

        # 파일 읽기
        if file_ext == 'csv':
            df = pd.read_csv(file, encoding='utf-8')
        else:
            df = pd.read_excel(file)

        # 컬럼 매핑 정의
        column_mapping = {
            'date': ['날짜', 'date', 'Date', 'DATE'],
            'content_id': ['미디어명', 'content_id', 'Content ID', 'CONTENT_ID'],
            'content_name': ['미디어명', 'content_name', 'Content Name', 'CONTENT_NAME'],
            'ad_unit_id': ['채널명', 'ad_unit_id', 'Ad Unit ID', 'AD_UNIT_ID'],
            'ad_unit_name': ['채널명', 'ad_unit_name', 'Ad Unit Name', 'AD_UNIT_NAME'],
            'impressions': ['광고요청수', '노출수', 'impressions', 'Impressions', 'IMPRESSIONS'],
            'view_count': ['조회수', 'view_count', 'View Count', 'VIEW_COUNT'],
            'clicks': ['클릭수', 'clicks', 'Clicks', 'CLICKS'],
            'ctr': ['클릭률', 'ctr', 'CTR', 'Click Rate', 'CLICK_RATE'],
            'earnings': ['매출', '수입예정액', 'earnings', 'Earnings', 'EARNINGS', '수입', '수익']
        }

        # 실제 컬럼명 찾기
        actual_columns = {}
        for field, possible_names in column_mapping.items():
            found = False
            for col in df.columns:
                if any(name in col for name in possible_names):
                    actual_columns[field] = col
                    found = True
                    break
            if not found:
                missing_columns = {
                    'date': '날짜',
                    'content_id': '미디어명',
                    'ad_unit_id': '채널명',
                    'impressions': '광고요청수',
                    'view_count': '조회수',
                    'clicks': '클릭수',
                    'ctr': '클릭률',
                    'earnings': '매출'
                }
                return JsonResponse({
                    "error": f"필수 컬럼이 없습니다: {missing_columns[field]}"
                }, status=400)

        # 데이터 처리 및 저장
        saved_count = 0
        error_count = 0
        error_messages = []

        for index, row in df.iterrows():
            try:
                # 날짜 처리 (YYYYMMDD 형식)
                date_str = str(row[actual_columns['date']])
                if len(date_str) != 8:
                    error_messages.append(f"행 {index + 2}: 잘못된 날짜 형식 ({date_str})")
                    error_count += 1
                    continue

                try:
                    date = datetime.strptime(date_str, '%Y%m%d').date()
                except ValueError:
                    error_messages.append(f"행 {index + 2}: 날짜 변환 실패 ({date_str})")
                    error_count += 1
                    continue

                # CTR 처리
                ctr_str = str(row[actual_columns['ctr']]).replace('%', '').strip()
                try:
                    ctr = float(ctr_str)
                except ValueError:
                    error_messages.append(f"행 {index + 2}: CTR 변환 실패 ({ctr_str})")
                    error_count += 1
                    continue

                # 수입 처리
                earnings_str = str(row[actual_columns['earnings']]).replace(',', '').strip()
                try:
                    earnings = float(earnings_str)
                except ValueError:
                    error_messages.append(f"행 {index + 2}: 수입 변환 실패 ({earnings_str})")
                    error_count += 1
                    continue

                # 데이터 저장
                AdStats.objects.update_or_create(
                    user=request.user,
                    platform="adpost",
                    alias=account_id,
                    credential=cred,
                    content_id=str(row[actual_columns['content_id']]),
                    content_name=str(row[actual_columns['content_name']]),
                    ad_unit_id=str(row[actual_columns['ad_unit_id']]),
                    ad_unit_name=str(row[actual_columns['ad_unit_name']]),
                    view_count=int(row[actual_columns['view_count']]),
                    date=date,
                    impressions=int(row[actual_columns['impressions']]),
                    clicks=int(row[actual_columns['clicks']]),
                    ctr=ctr,
                    earnings=earnings
                )
                saved_count += 1

            except Exception as e:
                error_messages.append(f"행 {index + 2}: {str(e)}")
                error_count += 1
                continue

        if saved_count == 0:
            return JsonResponse({
                "error": "저장된 데이터가 없습니다.",
                "details": error_messages[:5]  # 처음 5개의 에러 메시지만 반환
            }, status=400)

        # 마지막 저장 시간 업데이트
        if saved_count > 0:
            cred.last_fetched_at = timezone.now()
            cred.save()

        message = f"{saved_count}개의 데이터가 성공적으로 저장되었습니다."
        if error_count > 0:
            message += f" ({error_count}개의 데이터 처리 실패)"

        return JsonResponse({
            "message": message,
            "saved_count": saved_count,
            "error_count": error_count,
            "errors": error_messages[:5] if error_count > 0 else []
        })

    except Exception as e:
        return JsonResponse({
            "error": f"파일 처리 중 오류가 발생했습니다: {str(e)}"
        }, status=500)

@csrf_exempt
@login_required
def upload_taboola_excel(request):
    """Taboola Excel/CSV 파일 업로드 처리"""
    if request.method != "POST":
        return JsonResponse({"error": "잘못된 요청입니다."}, status=400)

    try:
        file = request.FILES.get("file")
        if not file:
            return JsonResponse({"error": "파일이 없습니다."}, status=400)

        account_id = request.POST.get("account_id")
        if not account_id:
            return JsonResponse({"error": "계정이 선택되지 않았습니다."}, status=400)

        # 자격증명 조회
        cred = PlatformCredential.objects.filter(user=request.user, platform="taboola", alias=account_id).first()
        if not cred:
            return JsonResponse({"error": "등록되지 않은 계정입니다."}, status=400)

        # 파일 확장자 확인
        file_ext = file.name.split('.')[-1].lower()
        if file_ext not in ['xlsx', 'xls', 'csv']:
            return JsonResponse({"error": "지원하지 않는 파일 형식입니다. (지원: xlsx, xls, csv)"}, status=400)

        # 파일 읽기
        try:
            if file_ext == 'csv':
                df = pd.read_csv(file, encoding='utf-8')
            else:
                df = pd.read_excel(file)
        except Exception as e:
            return JsonResponse({
                "error": f"파일 읽기 실패: {str(e)}"
            }, status=400)

        # 디버깅: 컬럼명 출력
        print(f"파일 컬럼: {list(df.columns)}")
        print(f"데이터 샘플: {df.head()}")

        # Taboola CSV 컬럼 매핑 정의
        column_mapping = {
            'date': ['Date', 'date', '날짜', 'DATE'],
            'page_views': ['Page Views', 'page_views', '페이지뷰', 'PAGE_VIEWS'],
            'ad_clicks': ['Ad Clicks', 'ad_clicks', '광고클릭', 'AD_CLICKS'],
            'ad_revenue': ['Ad Revenue (KRW)', 'Ad Revenue', 'ad_revenue', '광고수익', 'AD_REVENUE']
        }

        # 실제 컬럼명 찾기
        actual_columns = {}
        for field, possible_names in column_mapping.items():
            found = False
            for col in df.columns:
                if any(name in col for name in possible_names):
                    actual_columns[field] = col
                    found = True
                    break
            if not found:
                missing_columns = {
                    'date': 'Date',
                    'page_views': 'Page Views',
                    'ad_clicks': 'Ad Clicks',
                    'ad_revenue': 'Ad Revenue (KRW)'
                }
                return JsonResponse({
                    "error": f"필수 컬럼이 없습니다: {missing_columns[field]} (파일 컬럼: {list(df.columns)})"
                }, status=400)

        print(f"매핑된 컬럼: {actual_columns}")

        # 데이터 처리 및 저장
        saved_count = 0
        error_count = 0
        error_messages = []

        for index, row in df.iterrows():
            try:
                # 날짜 처리 (MM/DD/YYYY 형식)
                date_str = str(row[actual_columns['date']]).strip()
                print(f"행 {index + 2}: 날짜 원본값 = '{date_str}'")
                
                try:
                    # MM/DD/YYYY 형식 처리
                    date = datetime.strptime(date_str, '%m/%d/%Y').date()
                except ValueError:
                    # YYYY-MM-DD 형식도 시도
                    try:
                        date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except ValueError:
                        error_messages.append(f"행 {index + 2}: 날짜 변환 실패 ({date_str})")
                        error_count += 1
                        continue

                # Page Views 처리
                page_views_str = str(row[actual_columns['page_views']]).replace(',', '').strip()
                print(f"행 {index + 2}: Page Views 원본값 = '{page_views_str}'")
                try:
                    page_views = int(float(page_views_str))
                except ValueError:
                    error_messages.append(f"행 {index + 2}: Page Views 변환 실패 ({page_views_str})")
                    error_count += 1
                    continue

                # Ad Clicks 처리
                ad_clicks_str = str(row[actual_columns['ad_clicks']]).replace(',', '').strip()
                print(f"행 {index + 2}: Ad Clicks 원본값 = '{ad_clicks_str}'")
                try:
                    ad_clicks = int(float(ad_clicks_str))
                except ValueError:
                    error_messages.append(f"행 {index + 2}: Ad Clicks 변환 실패 ({ad_clicks_str})")
                    error_count += 1
                    continue

                # Ad Revenue 처리 (KRW)
                ad_revenue_str = str(row[actual_columns['ad_revenue']]).replace(',', '').strip()
                print(f"행 {index + 2}: Ad Revenue 원본값 = '{ad_revenue_str}'")
                try:
                    ad_revenue = float(ad_revenue_str)
                except ValueError:
                    error_messages.append(f"행 {index + 2}: Ad Revenue 변환 실패 ({ad_revenue_str})")
                    error_count += 1
                    continue

                # CTR 계산 (Ad Clicks / Page Views * 100)
                ctr = (ad_clicks / page_views * 100) if page_views > 0 else 0

                print(f"행 {index + 2}: 처리된 데이터 - 날짜: {date}, Page Views: {page_views}, Ad Clicks: {ad_clicks}, Ad Revenue: {ad_revenue}, CTR: {ctr}")

                # 데이터 저장
                AdStats.objects.update_or_create(
                    user=request.user,
                    platform="taboola",
                    alias=account_id,
                    date=date,
                    defaults={
                        'credential': cred,
                        'impressions': int(page_views),  # int로 변환
                        'clicks': int(ad_clicks),        # int로 변환
                        'ctr': float(ctr),               # float로 변환
                        'earnings': float(ad_revenue)    # float로 변환
                    }
                )
                saved_count += 1

            except Exception as e:
                error_msg = f"행 {index + 2}: {str(e)}"
                print(f"오류 발생: {error_msg}")
                error_messages.append(error_msg)
                error_count += 1
                continue

        if saved_count == 0:
            return JsonResponse({
                "error": "저장된 데이터가 없습니다.",
                "details": error_messages[:5]  # 처음 5개의 에러 메시지만 반환
            }, status=400)

        # 마지막 저장 시간 업데이트
        if saved_count > 0:
            cred.last_fetched_at = timezone.now()
            cred.save()

        message = f"{saved_count}개의 데이터가 성공적으로 저장되었습니다."
        if error_count > 0:
            message += f" ({error_count}개의 데이터 처리 실패)"

        return JsonResponse({
            "message": message,
            "saved_count": saved_count,
            "error_count": error_count,
            "errors": error_messages[:5] if error_count > 0 else []
        })

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"전체 오류: {str(e)}")
        print(f"오류 상세: {error_traceback}")
        return JsonResponse({
            "error": f"파일 처리 중 오류가 발생했습니다: {str(e)}",
            "details": error_traceback
        }, status=500)
    
# ===== 인증 관련 함수 =====
def adsense_auth_start(request):
    """AdSense 인증 시작"""
    cred_id = request.GET.get("cred_id")
    client_id = request.GET.get("client_id")
    client_secret = request.GET.get("client_secret")
    missing = get_required(request.GET, ["cred_id", "client_id", "client_secret"])
    if missing:
        return HttpResponse("필수 파라미터 누락")

    request.session["adsense_cred_id"] = cred_id
    redirect_uri = request.build_absolute_uri(reverse("adsense_auth_callback"))

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        },
        scopes=["https://www.googleapis.com/auth/adsense.readonly", "https://www.googleapis.com/auth/admanager"],
        redirect_uri=redirect_uri
    )
    auth_url, _ = flow.authorization_url(prompt="consent", include_granted_scopes="true")
    return redirect(auth_url)

def adsense_auth_callback(request):
    """AdSense 인증 콜백"""
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    cred_id = request.session.get("adsense_cred_id")
    if not cred_id:
        return HttpResponse("<h3>❌ 세션이 만료되었습니다.</h3><script>window.close();</script>")

    cred = PlatformCredential.objects.filter(pk=cred_id).first()
    if not cred:
        return HttpResponse("<h3>❌ 등록된 계정 없음</h3><script>window.close();</script>")

    data = cred.get_credentials()
    client_id, client_secret = data.get("client_id"), data.get("secret")
    if not client_id or not client_secret:
        return HttpResponse("<h3>❌ 클라이언트 정보 누락</h3><script>window.close();</script>")

    try:
        redirect_uri = request.build_absolute_uri(reverse("adsense_auth_callback"))
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            },
            scopes=["https://www.googleapis.com/auth/adsense.readonly", "https://www.googleapis.com/auth/admanager"],

            redirect_uri=redirect_uri
        )
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        cred.token = flow.credentials.to_json()
        cred.save()
        return HttpResponse("""
            <script>
              window.opener?.postMessage("adsense-auth-success", "*");
              window.close();
            </script>
            <h3>✅ 인증 완료</h3>
        """)
    except InvalidClientError:
        return HttpResponse("""
            <script>
              window.opener?.postMessage("adsense-auth-failed", "*");
              window.close();
            </script>
            <h3 style="color:red;">❌ 잘못된 client_id 또는 secret입니다.</h3>
        """)
    except Exception as e:
        return HttpResponse(f"""
            <script>
              window.opener?.postMessage("adsense-auth-error", "*");
              window.close();
            </script>
            <h3 style="color:red;">❌ 오류: {str(e)}</h3>
        """)
    
# ===== 인증 관련 함수 =====
def admanager_auth_start(request):
    """AdManager 인증 시작"""
    cred_id = request.GET.get("cred_id")
    client_id = request.GET.get("client_id")
    client_secret = request.GET.get("client_secret")
    missing = get_required(request.GET, ["cred_id", "client_id", "client_secret"])
    if missing:
        return HttpResponse("필수 파라미터 누락")

    request.session["admanager_cred_id"] = cred_id
    redirect_uri = request.build_absolute_uri(reverse("admanager_auth_callback"))

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        },
        scopes=["https://www.googleapis.com/auth/admanager", "https://www.googleapis.com/auth/adsense.readonly"],
        redirect_uri=redirect_uri
    )
    auth_url, _ = flow.authorization_url(prompt="consent", include_granted_scopes="true")
    return redirect(auth_url)

def admanager_auth_callback(request):
    """AdManager 인증 콜백"""
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    cred_id = request.session.get("admanager_cred_id")
    if not cred_id:
        return HttpResponse("<h3>❌ 세션이 만료되었습니다.</h3><script>window.close();</script>")

    cred = PlatformCredential.objects.filter(pk=cred_id).first()
    if not cred:
        return HttpResponse("<h3>❌ 등록된 계정 없음</h3><script>window.close();</script>")

    data = cred.get_credentials()
    client_id, client_secret = data.get("client_id"), data.get("secret")
    if not client_id or not client_secret:
        return HttpResponse("<h3>❌ 클라이언트 정보 누락</h3><script>window.close();</script>")

    try:
        redirect_uri = request.build_absolute_uri(reverse("admanager_auth_callback"))
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            },
            scopes=["https://www.googleapis.com/auth/admanager", "https://www.googleapis.com/auth/adsense.readonly"],

            redirect_uri=redirect_uri
        )
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        cred.token = flow.credentials.to_json()
        
        # 네트워크 정보 가져와서 저장
        try:
            network_info = get_admanager_network(cred)
            cred.network_code = network_info["id"]
            cred.save()
        except Exception as e:
            # 네트워크 정보 가져오기 실패해도 토큰은 저장
            cred.save()
            print(f"네트워크 정보 가져오기 실패: {e}")
        
        return HttpResponse("""
            <script>
              window.opener?.postMessage("admanager-auth-success", "*");
              window.close();
            </script>
            <h3>✅ 인증 완료</h3>
        """)
    except InvalidClientError:
        return HttpResponse("""
            <script>
              window.opener?.postMessage("admanager-auth-failed", "*");
              window.close();
            </script>
            <h3 style="color:red;">❌ 잘못된 client_id 또는 secret입니다.</h3>
        """)
    except Exception as e:
        return HttpResponse(f"""
            <script>
              window.opener?.postMessage("admanager-auth-error", "*");
              window.close();
            </script>
            <h3 style="color:red;">❌ 오류: {str(e)}</h3>
        """)

# ===== 통계 관련 함수 =====
@login_required
def api_stats_view(request):
    """통계 데이터 API"""
    try:
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")
        if not start_date or not end_date:
            return JsonResponse({"error": "시작일과 종료일이 필요합니다."}, status=400)

        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

        filters = {
            "date__range": [start_date, end_date],
            "user": request.user
        }

        platform = request.GET.get("platform")
        if platform and platform != "all":
            filters["platform"] = platform

        alias = request.GET.get("alias")
        if alias and alias != "all":
            filters["alias"] = alias

        ad_unit_id = request.GET.get("ad_unit_id")
        if ad_unit_id and ad_unit_id != "all":
            filters["ad_unit_id"] = ad_unit_id

        stats = AdStats.objects.filter(**filters)

        grouping = request.GET.get("grouping", "day")
        if grouping == "month":
            stats = stats.annotate(
                year=ExtractYear('date'),
                month=ExtractMonth('date')
            ).values('year', 'month', 'platform', 'alias').annotate(
                earnings=Sum("earnings"),
                clicks=Sum("clicks"),
                impressions=Sum("impressions"),
                order_count=Sum("order_count"),
                total_amount=Sum("total_amount")
            ).order_by('year', 'month')
        else:
            stats = stats.values("date", "platform", "alias").annotate(
                earnings=Sum("earnings"),
                clicks=Sum("clicks"),
                impressions=Sum("impressions"),
                order_count=Sum("order_count"),
                total_amount=Sum("total_amount")
            ).order_by("date")

        result = []
        for stat in stats:
            if grouping == "month":
                date_str = f"{stat['year']}-{stat['month']:02d}-01"
            else:
                date_str = stat["date"].strftime("%Y-%m-%d")
                
            total_clicks = int(stat["clicks"] or 0)
            total_impressions = int(stat["impressions"] or 0)
            total_earnings = float(stat["earnings"] or 0)
            
            ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
            ppc = (total_earnings / total_clicks) if total_clicks > 0 else 0
                
            result.append({
                "date": date_str,
                "platform": stat["platform"],
                "alias": stat["alias"],
                "earnings": total_earnings,
                "clicks": total_clicks,
                "impressions": total_impressions,
                "order_count": int(stat["order_count"] or 0),
                "total_amount": float(stat["total_amount"] or 0),
                "ctr": ctr,
                "ppc": ppc
            })

        return JsonResponse(result, safe=False)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@login_required
def api_stats_excel_view(request):
    """엑셀 다운로드 API"""
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    if not start_date or not end_date:
        return JsonResponse({"error": "시작일과 종료일은 필수입니다."}, status=400)

    try:
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "잘못된 날짜 형식입니다."}, status=400)

    filters = {
        "date__range": [start_date, end_date],
        "user": request.user,
    }

    platform = request.GET.get("platform")
    if platform and platform != "all":
        filters["platform"] = platform

    alias = request.GET.get("alias")
    if alias and alias != "all":
        filters["alias"] = alias

    ad_unit_id = request.GET.get("ad_unit_id")
    if ad_unit_id and ad_unit_id != "all":
        filters["ad_unit_id"] = ad_unit_id

    stats = AdStats.objects.filter(**filters).order_by("date", "platform", "alias", "ad_unit_id")

    result = []
    for stat in stats:
        result.append({
            "date": stat.date.strftime("%Y-%m-%d"),
            "platform": stat.platform or "",
            "alias": stat.alias or "",
            "ad_unit": stat.ad_unit_name or stat.ad_unit_id or "",
            "earnings": float(stat.earnings or 0),
            "clicks": int(stat.clicks or 0),
            "impressions": int(stat.impressions or 0),
            "order_count": int(stat.order_count or 0),
            "total_amount": float(stat.total_amount or 0),
            "ctr": float(stat.ctr or 0),
            "ppc": float(stat.ppc or 0),
        })

    return JsonResponse(result, safe=False)

@login_required
def api_ad_units_view(request):
    """광고 단위 API"""
    platform = request.GET.get("platform")
    alias = request.GET.get("alias")
    
    if not platform or not alias:
        return JsonResponse({"error": "platform과 alias는 필수 파라미터입니다."}, status=400)
    
    qs = AdStats.objects.filter(
        user=request.user,
        platform=platform,
        alias=alias
    ).values('ad_unit_id', 'ad_unit_name').distinct()
    
    ad_units = []
    for item in qs:
        if item['ad_unit_id']:
            ad_units.append({
                'ad_unit_id': item['ad_unit_id'],
                'ad_unit_name': item['ad_unit_name'] or item['ad_unit_id']
            })
    
    return JsonResponse({'ad_units': ad_units})

@csrf_exempt
@login_required
def get_admanager_current_report_api(request):
    """AdManager 현재 저장된 보고서 정보 조회"""
    if request.method != "GET":
        return JsonResponse({"status": "error", "message": "GET 요청만 허용됩니다."}, status=400)
    
    try:
        data = request.GET
        alias = data.get("alias")
        
        if not alias:
            return JsonResponse({"status": "error", "message": "alias 파라미터가 필요합니다."}, status=400)

        cred = PlatformCredential.objects.filter(
            user=request.user, 
            platform="admanager",
            alias=alias
        ).first()
        
        if not cred:
            return JsonResponse({"status": "error", "message": "해당 자격증명을 찾을 수 없습니다."}, status=404)

        return JsonResponse({
            "status": "success", 
            "report_id": cred.report_id,
            "report_resource_name": cred.report_resource_name,
            "network_code": cred.network_code
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)