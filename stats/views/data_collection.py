from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
import json
from ..models import PlatformCredential
from ..platforms import get_platform_display_name

def get_platform_aliases_grouped(user):
    """DB에서 플랫폼별 계정 정보를 그룹화하여 반환합니다."""
    credentials = PlatformCredential.objects.filter(user=user)
    grouped = {}
    for cred in credentials:
        platform = cred.platform or 'unknown'
        alias = cred.alias or 'default'
        grouped.setdefault(platform, []).append(alias)
    return grouped

def get_last_fetched_times(user):
    """각 플랫폼별 마지막 데이터 수집 시간을 반환합니다."""
    credentials = PlatformCredential.objects.filter(user=user)
    times = {}
    for cred in credentials:
        # alias가 있으면 alias 기준, 없으면 platform 기준
        key = cred.alias if cred.platform in ['adpost', 'taboola'] else cred.platform
        times[key] = cred.last_fetched_at
    return times

def data_collection_view(request):
    """데이터 수집 페이지를 렌더링합니다."""
    # 플랫폼별 계정 정보 가져오기 (DB 기반)
    platform_aliases_grouped = get_platform_aliases_grouped(request.user)
    # 계정이 1개 이상인 플랫폼만 필터링
    platform_aliases_grouped = {k: v for k, v in platform_aliases_grouped.items() if v}
    # 마지막 수집 시간 정보 가져오기
    last_fetched_times = get_last_fetched_times(request.user)
    # 플랫폼 표시 이름 매핑
    display_name = {k: get_platform_display_name(k) for k in platform_aliases_grouped}
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    context = {
        'platform_aliases_grouped': platform_aliases_grouped,
        'last_fetched_times': last_fetched_times,
        'display_name': display_name,
        'today': today,
        'week_ago': week_ago,
    }
    return render(request, 'data_collection.html', context) 