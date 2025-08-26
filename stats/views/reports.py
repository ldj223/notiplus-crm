import os, json
from datetime import datetime, timedelta, date
from django.conf import settings
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.db.models import Sum, Count
from django.contrib import messages
from django.utils import timezone
import openpyxl
import xlrd
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP
import logging
from rest_framework.decorators import api_view
from django.db.models import Q

from ..forms import CredentialForm, SignUpForm
from ..models import (
    AdStats, PlatformCredential, UserPreference, MonthlySales, 
    SettlementDepartment, ServiceGroup, PurchaseGroup, Member, 
    PurchasePrice, MemberStat, TotalStat, PurchaseGroupAdUnit, ExchangeRate, OtherRevenue
)
from ..platforms import get_platform_display_name, PLATFORM_ORDER
from .purchase import calculate_purchase_cost_by_date_range

logger = logging.getLogger(__name__)

def get_date_range_from_request(request, default_days=7, max_days=31):
    """요청에서 날짜 범위를 추출하고 유효성을 검사"""
    today = date.today()
    
    try:
        start_date = datetime.strptime(request.GET.get('start_date', ''), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.GET.get('end_date', ''), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        end_date = today
        start_date = end_date - timedelta(days=default_days-1)

    # 날짜 범위 유효성 검사
    if end_date > today:
        end_date = today
    if start_date > end_date:
        start_date = end_date
    if (end_date - start_date).days > max_days:
        start_date = end_date - timedelta(days=max_days-1)
    
    return start_date, end_date

def get_platform_list(user):
    """사용자의 연동된 플랫폼 목록을 정렬하여 반환"""
    credentials = PlatformCredential.objects.filter(user=user)
    platforms = credentials.values_list('platform', 'alias').distinct()
    
    # 플랫폼 정렬
    platform_list = sorted(
        list(platforms),
        key=lambda x: (PLATFORM_ORDER.get(x[0], 999), x[1])
    )
    
    return platform_list

def get_exchange_rates(user, start_date, end_date):
    """환율 데이터를 조회하여 딕셔너리로 반환"""
    year_months = [date(start_date.year, start_date.month, 1)]
    if end_date.month != start_date.month or end_date.year != start_date.year:
        year_months.append(date(end_date.year, end_date.month, 1))
    
    exchange_rates = {}
    exchange_rate_data = ExchangeRate.objects.filter(
        user=user,
        year_month__in=year_months
    ).values('year_month', 'usd_to_krw')
    
    for rate in exchange_rate_data:
        exchange_rates[rate['year_month']] = rate['usd_to_krw']
    
    return exchange_rates

def get_ad_unit_member_mapping(user):
    """광고 단위별 Member level 매핑 정보를 반환"""
    google_naver_ad_units = PurchaseGroupAdUnit.objects.filter(
        purchase_group__user=user,
        purchase_group__is_active=True,
        platform__in=['adsense', 'admanager', 'naver'],
        is_active=True
    )
    
    ad_unit_member_map = {}
    for ad_unit in google_naver_ad_units:
        ad_unit_member_map[ad_unit.ad_unit_id] = {
            'level': ad_unit.purchase_group.member.level if ad_unit.purchase_group.member else 60,
            'member_key': ad_unit.purchase_group.member_request_key
        }
    
    return ad_unit_member_map

def calculate_platform_revenue_by_member_level(user, start_date, end_date, ad_unit_member_map, exchange_rates):
    """구글/네이버 광고 수익을 Member level별로 분류하여 계산"""
    publisher_data = {}  # level 50 (퍼블리셔)
    partners_data = {}   # level 60 (파트너스) + 매핑되지 않은 광고
    
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    for d in date_list:
        publisher_data[d] = {'adsense': Decimal('0'), 'admanager': Decimal('0'), 'naver': Decimal('0')}
        partners_data[d] = {'adsense': Decimal('0'), 'admanager': Decimal('0'), 'naver': Decimal('0')}
    
    # AdStats에서 구글 데이터를 광고 단위별로 조회하여 분류
    google_stats = AdStats.objects.filter(
        user=user,
        platform__in=['adsense', 'admanager'],
        date__range=[start_date, end_date]
    ).values('date', 'platform', 'ad_unit_id', 'earnings', 'earnings_usd')
    
    for stat in google_stats:
        d = stat['date']
        platform = stat['platform']
        ad_unit_id = stat['ad_unit_id']
        
        # AdSense는 USD를 KRW로 변환, AdManager는 KRW 그대로
        if platform == 'adsense':
            month_start = d.replace(day=1)
            usd_to_krw = exchange_rates.get(month_start, Decimal('1370.00'))
            earnings_usd = Decimal(str(stat['earnings_usd'] or 0))
            earnings = earnings_usd * usd_to_krw
        else:
            earnings = Decimal(str(stat['earnings'] or 0))
        
        if ad_unit_id in ad_unit_member_map:
            # 매핑된 광고 단위
            member_level = ad_unit_member_map[ad_unit_id]['level']
            if member_level in [50, 100]:  # 퍼블리셔
                publisher_data[d][platform] += earnings
            elif member_level in [60, 61, 65]:  # 파트너스
                partners_data[d][platform] += earnings
            else:  # 기타 level은 파트너스로 처리
                partners_data[d][platform] += earnings
        else:
            # 매핑되지 않은 광고 단위는 파트너스로 처리
            partners_data[d][platform] += earnings
    
    return publisher_data, partners_data

def calculate_naver_powerlink_revenue(user, start_date, end_date, publisher_data, partners_data):
    """네이버 파워링크 수익을 Member level별로 계산"""
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    # Adpost 데이터 조회 (파워링크 단가 계산용)
    adpost_stats = AdStats.objects.filter(
        platform='adpost',
        ad_unit_id='모바일뉴스픽_컨텐츠',
        date__range=[start_date, end_date],
        user=user
    ).values('date').annotate(
        earnings=Sum('earnings'),
        clicks=Sum('clicks')
    )
    
    # 전체 파워링크 클릭수 조회
    total_powerlink_stats = TotalStat.newspic_objects().filter(
        sdate__range=[start_date, end_date]
    ).values('sdate').annotate(
        total_powerlink=Sum('powerlink_count')
    )
    
    # 데이터를 딕셔너리로 변환
    adpost_data = {}
    for stat in adpost_stats:
        adpost_data[stat['date']] = {
            'earnings': stat['earnings'] or 0,
            'clicks': stat['clicks'] or 0
        }
    
    total_powerlink_data = {}
    for stat in total_powerlink_stats:
        total_powerlink_data[stat['sdate']] = stat['total_powerlink'] or 0
    
    # tbTotalStat에서 해당 기간에 데이터가 있는 모든 퍼블리셔 조회
    totalstat_publishers = TotalStat.newspic_objects().filter(
        sdate__range=[start_date, end_date]
    ).values_list('request_key', flat=True).distinct()
    
    # Member 테이블에서 해당 퍼블리셔들의 level 정보 조회
    from stats.models import Member
    member_levels = {}
    for member in Member.newspic_objects().filter(request_key__in=totalstat_publishers):
        member_levels[member.request_key] = member.level
    
    # purchase_group에 있는 퍼블리셔들도 추가 (level 정보가 없는 경우)
    all_groups = PurchaseGroup.objects.filter(user=user, is_active=True)
    for group in all_groups:
        if group.member_request_key not in member_levels:
            member_levels[group.member_request_key] = group.member.level if group.member else 60
    
    # 모든 퍼블리셔 키 목록
    all_member_keys = list(member_levels.keys())
    
    member_powerlink_stats = TotalStat.newspic_objects().filter(
        request_key__in=all_member_keys, sdate__range=[start_date, end_date]
    ).values('request_key', 'sdate', 'powerlink_count')
    
    # 퍼블리셔별 파워링크 데이터를 딕셔너리로 변환
    member_powerlink_data = {}
    for stat in member_powerlink_stats:
        key = (stat['request_key'], stat['sdate'])
        member_powerlink_data[key] = stat['powerlink_count'] or 0
    
    # 3. 일자별 수익 계산
    for d in date_list:
        # Adpost 정보 (모바일뉴스픽_컨텐츠)
        adpost_info = adpost_data.get(d, {'earnings': 0, 'clicks': 0})
        adpost_earnings = adpost_info['earnings']
        adpost_clicks = adpost_info['clicks']
        
        # 어드민 전체 파워링크 클릭수
        admin_total_clicks = total_powerlink_data.get(d, 0)
        
        # PPC 계산: 모바일뉴스픽_컨텐츠 매출 / 모바일뉴스픽_컨텐츠 클릭수
        ppc = (Decimal(str(adpost_earnings)) / Decimal(str(adpost_clicks))) if adpost_clicks > 0 else Decimal('0')
        
        # 인정비율 계산: 모바일뉴스픽_컨텐츠 클릭수 / 파워링크 전체 클릭수
        recognition_rate = (Decimal(str(adpost_clicks)) / Decimal(str(admin_total_clicks))) if admin_total_clicks > 0 else Decimal('0')
        
        # 모든 퍼블리셔별 수익 계산 (tbTotalStat에 있는 모든 퍼블리셔)
        for request_key in all_member_keys:
            clicks = member_powerlink_data.get((request_key, d), 0)
            revenue = Decimal('0')
            
            if ppc > 0 and clicks > 0 and recognition_rate > 0:
                # 수익 계산: PPC * 파워링크 클릭수 * 59.5% * 인정비율
                revenue = (ppc * Decimal(str(clicks)) * Decimal('0.595') * recognition_rate).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
            
            # level에 따라 퍼블리셔/파트너스 구분
            member_level = member_levels.get(request_key, 60)  # 기본값은 파트너스
            if member_level == 50:  # 퍼블리셔
                publisher_data[d]['naver'] += revenue
            else:  # 파트너스 (level 60 또는 기타)
                partners_data[d]['naver'] += revenue

    return publisher_data, partners_data

def get_section_platforms(platform_list, section_type, user):
    """섹션별 플랫폼 목록을 반환"""
    if section_type == 'publisher':
        return [(p, a) for p, a in platform_list if p in ['adsense', 'admanager', 'naver']]
    elif section_type == 'partners':
        # 기본 파트너스 플랫폼들
        partners_platforms = [(p, a) for p, a in platform_list if p in ['cozymamang', 'mediamixer', 'aceplanet', 'teads', 'taboola']]
        
        # 쿠팡 계정 중 파트너스로 분류된 것들 추가
        coupang_partners = []
        for p, a in platform_list:
            if p == 'coupang':
                cred = PlatformCredential.objects.filter(
                    user=user,
                    platform=p, 
                    alias=a
                ).first()
                if cred and cred.coupang_classification == 'partners':
                    coupang_partners.append((p, a))
        
        return partners_platforms + coupang_partners
        
    elif section_type == 'stamply':
        # 쿠팡 계정 중 스템플리로 분류된 것들만
        stamply_platforms = []
        for p, a in platform_list:
            if p == 'coupang':
                cred = PlatformCredential.objects.filter(
                    user=user,
                    platform=p, 
                    alias=a
                ).first()
                if cred and cred.coupang_classification == 'stamply':
                    stamply_platforms.append((p, a))
        
        return stamply_platforms
    
    return []

def process_section_data(user, platform_list, start_date, end_date, section_platforms, google_naver_data=None, section_type=None):
    """섹션별 데이터를 처리하여 반환"""
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    # 기본 데이터 조회 - 모든 플랫폼에 대해 조회
    stats = AdStats.objects.filter(user=user, date__range=[start_date, end_date])
    data = {}
    for d in date_list:
        data[d] = {}
        for platform, alias in platform_list:
            key = f"{platform}|{alias}"
            data[d][key] = Decimal('0')

    for row in stats.values('date', 'platform', 'alias').annotate(earnings=Sum('earnings')):
        d = row['date']
        key = f"{row['platform']}|{row['alias']}"
        if d in data and key in data[d]:
            data[d][key] = Decimal(str(row['earnings'] or 0))
    
    # 섹션별 데이터 처리
    section_data = {}
    for d in date_list:
        section_data[d] = {}
        for platform, alias in section_platforms:
            key = f"{platform}|{alias}"
            if platform in ['adsense', 'admanager', 'naver'] and google_naver_data:
                # 구글/네이버는 Member level 기준으로 분류된 데이터 사용
                if platform in ['adsense', 'admanager']:
                    # AdSense와 AdManager를 구글으로 합산 (개별 플랫폼은 제외)
                    continue
                else:
                    section_data[d][key] = google_naver_data[d].get(platform, Decimal('0'))
            else:
                # 다른 플랫폼들은 기본 데이터에서 가져오기
                section_data[d][key] = data[d].get(key, Decimal('0'))
        
        # 구글/네이버 데이터 추가 (섹션에 따라)
        if google_naver_data:
            # 섹션 타입은 파라미터로 받음
            # section_type이 None이 아니면 구글/네이버 합계 추가
            
            if section_type:
                google_key = f"google|{section_type}"
                section_data[d][google_key] = google_naver_data[d].get('adsense', Decimal('0')) + google_naver_data[d].get('admanager', Decimal('0'))
                
                naver_key = f"naver|{section_type}"
                section_data[d][naver_key] = google_naver_data[d].get('naver', Decimal('0'))
    
    return section_data

def calculate_section_totals(section_data, date_list, section_name, google_naver_data=None, daily_data=None):
    """섹션별 합계를 계산"""
    # 구글/네이버 합계 제외하고 개별 플랫폼만 합산
    daily_revenue = {}
    for d in date_list:
        daily_sum = Decimal('0')
        for key, value in section_data[d].items():
            platform, alias = key.split('|', 1)
            if platform not in ['google', 'naver']:  # 합계 데이터 제외
                daily_sum += value
        
        # daily_data에서 해당 섹션의 구글/네이버 수익 추가
        if daily_data:
            if section_name == 'publisher':
                daily_sum += daily_data['publisher_daily_google'].get(d, Decimal('0')) + daily_data['publisher_daily_naver'].get(d, Decimal('0'))
            elif section_name == 'partners':
                daily_sum += daily_data['partners_daily_google'].get(d, Decimal('0')) + daily_data['partners_daily_naver'].get(d, Decimal('0'))
        
        daily_revenue[d] = daily_sum
    
    # 구글/네이버 수익 추가
    google_revenue_total = Decimal('0')
    naver_revenue_total = Decimal('0')
    if google_naver_data:
        google_revenue_total = sum(google_naver_data[d]['adsense'] + google_naver_data[d]['admanager'] for d in date_list)
        naver_revenue_total = sum(google_naver_data[d]['naver'] for d in date_list)
    
    # 개별 플랫폼 수익 + 구글/네이버 수익 = 총 수익
    total_revenue = sum(daily_revenue.values())
    
    # daily_data에서 해당 섹션의 구글/네이버 수익 추가
    if daily_data:
        if section_name == 'publisher':
            total_revenue += sum(daily_data['publisher_daily_google'].values()) + sum(daily_data['publisher_daily_naver'].values())
        elif section_name == 'partners':
            total_revenue += sum(daily_data['partners_daily_google'].values()) + sum(daily_data['partners_daily_naver'].values())
    
    totals = {
        'total_revenue': total_revenue.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        f'{section_name}_revenue': total_revenue.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        'other_revenue': Decimal('0'),
        'total_cost': Decimal('0'),
        f'{section_name}_cost': Decimal('0'),
        'google_revenue': google_revenue_total.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        'naver_revenue': naver_revenue_total.quantize(Decimal('0'), rounding=ROUND_HALF_UP)
    }
    
    # 파트너스 특별 필드 추가
    if section_name == 'partners':
        # 개별 플랫폼 수익 계산
        platform_totals = {
            'cozymamang': Decimal('0'),
            'mediamixer': Decimal('0'),
            'aceplanet': Decimal('0'),
            'teads': Decimal('0'),
            'taboola': Decimal('0'),
            'coupang': Decimal('0')  # 쿠팡 파트너스 수익 추가
        }
        
        for d in date_list:
            for key, value in section_data[d].items():
                platform, alias = key.split('|', 1)
                if platform in platform_totals:
                    platform_totals[platform] += value
        
        totals.update({
            'valid_pv': Decimal('0'),
            'revenue_per_pv': Decimal('0'),
            'cozymamang_revenue': platform_totals['cozymamang'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'mediamixer_revenue': platform_totals['mediamixer'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'aceplanet_revenue': platform_totals['aceplanet'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'teads_revenue': platform_totals['teads'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'taboola_revenue': platform_totals['taboola'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'coupang_revenue': platform_totals['coupang'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),  # 쿠팡 파트너스 수익 추가
        })
    elif section_name == 'stamply':
        totals['coupang_revenue'] = Decimal('0')
    
    return daily_revenue, totals

def calculate_section_totals_with_other_revenue(section_data, date_list, section_name, google_naver_data=None, other_revenue_data=None, daily_data=None):
    """섹션별 합계를 계산 (기타수익 및 비용 포함) - 순익과 매출을 모두 반환"""
    from decimal import Decimal, ROUND_HALF_UP
    # 기본 매출(비용 차감 전) - 구글/네이버 합계 제외하고 개별 플랫폼만 합산
    base_daily_revenue = {}
    for d in date_list:
        daily_sum = Decimal('0')
        for key, value in section_data[d].items():
            platform, alias = key.split('|', 1)
            if platform not in ['google', 'naver']:  # 합계 데이터 제외
                daily_sum += value
        
        # daily_data에서 해당 섹션의 구글/네이버 수익 추가
        if daily_data:
            if section_name == 'publisher':
                daily_sum += daily_data['publisher_daily_google'].get(d, Decimal('0')) + daily_data['publisher_daily_naver'].get(d, Decimal('0'))
            elif section_name == 'partners':
                daily_sum += daily_data['partners_daily_google'].get(d, Decimal('0')) + daily_data['partners_daily_naver'].get(d, Decimal('0'))
        
        base_daily_revenue[d] = daily_sum

    daily_profit = {}  # 순익: 매출 + 기타수익 - 매입비용
    daily_sales = {}   # 매출: 매출 + 기타수익
    other_revenue_total = Decimal('0')
    cost_total = Decimal('0')

    for d in date_list:
        base_revenue = base_daily_revenue[d]
        other_revenue = Decimal('0')
        cost = Decimal('0')
        if other_revenue_data and d in other_revenue_data:
            if section_name in other_revenue_data[d]:
                other_revenue = other_revenue_data[d][section_name]
                other_revenue_total += other_revenue
            cost_key = f"{section_name}_cost"
            if cost_key in other_revenue_data[d]:
                cost = other_revenue_data[d][cost_key]
                cost_total += cost
        daily_profit[d] = (base_revenue + other_revenue - cost).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        daily_sales[d] = (base_revenue + other_revenue).quantize(Decimal('0'), rounding=ROUND_HALF_UP)

    # 구글/네이버 수익 추가
    google_revenue_total = Decimal('0')
    naver_revenue_total = Decimal('0')
    if google_naver_data:
        google_revenue_total = sum(google_naver_data[d]['adsense'] + google_naver_data[d]['admanager'] for d in date_list)
        naver_revenue_total = sum(google_naver_data[d]['naver'] for d in date_list)
    
    # 개별 플랫폼 수익 + 구글/네이버 수익 = 총 수익
    total_revenue = sum(daily_profit.values())
    total_sales = sum(daily_sales.values())
    
    # daily_data에서 해당 섹션의 구글/네이버 수익 추가
    if daily_data:
        if section_name == 'publisher':
            total_revenue += sum(daily_data['publisher_daily_google'].values()) + sum(daily_data['publisher_daily_naver'].values())
            total_sales += sum(daily_data['publisher_daily_google'].values()) + sum(daily_data['publisher_daily_naver'].values())
        elif section_name == 'partners':
            total_revenue += sum(daily_data['partners_daily_google'].values()) + sum(daily_data['partners_daily_naver'].values())
            total_sales += sum(daily_data['partners_daily_google'].values()) + sum(daily_data['partners_daily_naver'].values())
    
    totals = {
        'total_revenue': total_revenue.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        f'{section_name}_revenue': total_revenue.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        'other_revenue': other_revenue_total.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        'total_cost': cost_total.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        f'{section_name}_cost': cost_total.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        f'{section_name}_sales': total_sales.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        'google_revenue': google_revenue_total.quantize(Decimal('0'), rounding=ROUND_HALF_UP),
        'naver_revenue': naver_revenue_total.quantize(Decimal('0'), rounding=ROUND_HALF_UP)
    }

    # 파트너스 특별 필드 추가
    if section_name == 'partners':
        platform_totals = {
            'cozymamang': Decimal('0'),
            'mediamixer': Decimal('0'),
            'aceplanet': Decimal('0'),
            'teads': Decimal('0'),
            'taboola': Decimal('0'),
            'coupang': Decimal('0')  # 쿠팡 파트너스 수익 추가
        }
        for d in date_list:
            for key, value in section_data[d].items():
                platform, alias = key.split('|', 1)
                if platform in platform_totals:
                    platform_totals[platform] += value
        totals.update({
            'valid_pv': Decimal('0'),
            'revenue_per_pv': Decimal('0'),
            'cozymamang_revenue': platform_totals['cozymamang'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'mediamixer_revenue': platform_totals['mediamixer'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'aceplanet_revenue': platform_totals['aceplanet'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'teads_revenue': platform_totals['teads'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'taboola_revenue': platform_totals['taboola'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),
            'coupang_revenue': platform_totals['coupang'].quantize(Decimal('0'), rounding=ROUND_HALF_UP),  # 쿠팡 파트너스 수익 추가
        })
    elif section_name == 'stamply':
        totals['coupang_revenue'] = Decimal('0')

    return daily_profit, daily_sales, totals

def calculate_daily_platform_revenue(date_list, publisher_google_naver_data, partners_google_naver_data, 
                                   section_results, naver_powerlink_detail=None, user=None, platform_list=None):
    """일일 개별 플랫폼 수익을 계산"""
    daily_data = {
        'publisher_daily_google': {},
        'partners_daily_google': {},
        'publisher_daily_naver': {},
        'partners_daily_naver': {},
        'partners_daily_cozymamang': {},
        'partners_daily_mediamixer': {},
        'partners_daily_aceplanet': {},
        'partners_daily_teads': {},
        'partners_daily_taboola': {},
        'partners_daily_coupang': {},  # 쿠팡 파트너스 수익 추가
        'stamply_daily_coupang': {},
        'stamply_daily_coupang_by_account': {},
    }
    
    for d in date_list:
        # 퍼블리셔 일일 수익 (main.py와 동일하게 int 변환)
        daily_data['publisher_daily_google'][d] = int(publisher_google_naver_data[d]['adsense'] + publisher_google_naver_data[d]['admanager'])
        
        # 파트너스 일일 수익 (main.py와 동일하게 int 변환)
        daily_data['partners_daily_google'][d] = int(partners_google_naver_data[d]['adsense'] + partners_google_naver_data[d]['admanager'])
        
        # 네이버 수익 - 네이버 세부 데이터의 결과값 사용 (main.py와 동일하게 int 변환)
        if naver_powerlink_detail and d in naver_powerlink_detail['daily']:
            daily_data['publisher_daily_naver'][d] = int(naver_powerlink_detail['daily'][d]['publisher_revenue'])
            daily_data['partners_daily_naver'][d] = int(naver_powerlink_detail['daily'][d]['partners_revenue'])
        else:
            # 네이버 세부 데이터가 없으면 기존 방식 사용 (main.py와 동일하게 int 변환)
            daily_data['publisher_daily_naver'][d] = int(publisher_google_naver_data[d]['naver'])
            daily_data['partners_daily_naver'][d] = int(partners_google_naver_data[d]['naver'])
        
        # 파트너스 개별 플랫폼 수익 - AdStats에서 직접 계산
        platform_revenues = {
            'cozymamang': Decimal('0'),
            'mediamixer': Decimal('0'),
            'aceplanet': Decimal('0'),
            'teads': Decimal('0'),
            'taboola': Decimal('0'),
            'coupang': Decimal('0')  # 쿠팡 파트너스 수익 추가
        }
        
        # AdStats에서 각 플랫폼별 수익 직접 조회
        from django.db.models import Sum
        from stats.models import AdStats
        
        # 기본 데이터 조회
        stats = AdStats.objects.filter(user=user, date=d)
        data = {}
        for row in stats.values('platform', 'alias').annotate(earnings=Sum('earnings')):
            key = f"{row['platform']}|{row['alias']}"
            data[key] = Decimal(str(row['earnings'] or 0))
        
        for platform in platform_revenues.keys():
            if platform == 'coupang':
                # 쿠팡은 PlatformCredential의 coupang_classification으로 판단
                from stats.models import PlatformCredential
                coupang_creds = PlatformCredential.objects.filter(
                    user=user,  # user는 함수 파라미터에 추가 필요
                    platform='coupang',
                    coupang_classification='partners'
                )
                for cred in coupang_creds:
                    key = f"coupang|{cred.alias}"
                    platform_revenues['coupang'] += data.get(key, Decimal('0'))
            else:
                # 다른 플랫폼들은 기본 데이터에서 가져오기
                for alias in [a for p, a in platform_list if p == platform]:
                    key = f"{platform}|{alias}"
                    platform_revenues[platform] += data.get(key, Decimal('0'))
        
        daily_data['partners_daily_cozymamang'][d] = platform_revenues['cozymamang']
        daily_data['partners_daily_mediamixer'][d] = platform_revenues['mediamixer']
        daily_data['partners_daily_aceplanet'][d] = platform_revenues['aceplanet']
        daily_data['partners_daily_teads'][d] = platform_revenues['teads']
        daily_data['partners_daily_taboola'][d] = platform_revenues['taboola']
        daily_data['partners_daily_coupang'][d] = platform_revenues['coupang']  # 쿠팡 파트너스 수익 추가
        
        # 스탬플리 쿠팡 수익 (계정별로 분리) - AdStats에서 직접 조회
        daily_data['stamply_daily_coupang_by_account'][d] = {}
        coupang_revenue = Decimal('0')
        
        # 스템플리로 분류된 쿠팡 계정들 조회
        from stats.models import PlatformCredential
        stamply_coupang_creds = PlatformCredential.objects.filter(
            user=user,
            platform='coupang',
            coupang_classification='stamply'
        )
        
        for cred in stamply_coupang_creds:
            key = f"coupang|{cred.alias}"
            account_revenue = data.get(key, Decimal('0'))
            daily_data['stamply_daily_coupang_by_account'][d][cred.alias] = account_revenue
            coupang_revenue += account_revenue
        
        daily_data['stamply_daily_coupang'][d] = coupang_revenue
    
    return daily_data

def calculate_coupang_account_totals(stamply_daily_coupang_by_account, date_list, stamply_platforms):
    """쿠팡 계정별 합계를 계산"""
    stamply_coupang_account_totals = {}
    for platform, alias in stamply_platforms:
        if platform == 'coupang':
            account_total = Decimal(str(sum(stamply_daily_coupang_by_account[d].get(alias, Decimal('0')) for d in date_list))).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
            stamply_coupang_account_totals[alias] = account_total
    return stamply_coupang_account_totals

def get_platform_headers(platforms, section_name=None):
    """플랫폼 헤더 정보를 생성"""
    headers = [
        (p, a, f"{get_platform_display_name(p)}{f'({a})' if a != 'default' else ''}", f"{p}|{a}")
        for p, a in platforms
    ]
    
    # 구글/네이버 헤더 추가 (스탬플리 섹션 제외)
    if section_name and section_name != 'stamply':
        headers.extend([
            ('google', section_name, f'Google({section_name})', f'google|{section_name}'),
            ('naver', section_name, f'Naver({section_name})', f'naver|{section_name}')
        ])
    
    return headers

def build_report_context(date_list, platform_headers, section_results, daily_data, 
                         stamply_coupang_account_totals, start_date, end_date,
                         publisher_google_naver_data, partners_google_naver_data, data, 
                         publisher_revenue, partners_revenue, stamply_revenue,
                         publisher_profit, partners_profit, stamply_profit,
                         total_revenue, total_profit, purchase_data, other_revenue_data):
    """리포트 컨텍스트를 구성하는 헬퍼 함수"""
    section_headers = {
        'publisher': get_platform_headers(section_results['publisher']['platforms'], 'publisher'),
        'partners': get_platform_headers(section_results['partners']['platforms'], 'partners'),
        'stamply': get_platform_headers(section_results['stamply']['platforms'], 'stamply')
    }
    
    context = {
        'date_list': date_list,
        'platform_headers': platform_headers,
        'publisher_platform_headers': section_headers['publisher'],
        'partners_platform_headers': section_headers['partners'],
        'stamply_platform_headers': section_headers['stamply'],
        'data': data,
        'publisher_data': section_results['publisher']['data'],
        'partners_data': section_results['partners']['data'],
        'stamply_data': section_results['stamply']['data'],
        'publisher_revenue': publisher_revenue,
        'publisher_daily_profit': publisher_profit,  # 매출 - 매입비용
        'publisher_daily_sales': publisher_revenue,  # 매출
        'partners_daily_profit': partners_profit,    # 매출 - 매입비용
        'partners_daily_sales': partners_revenue,    # 매출
        'stamply_daily_profit': stamply_profit,     # 매출 - 매입비용
        'stamply_daily_sales': stamply_revenue,     # 매출
        # 올바른 합계 계산 (일별 데이터의 합계 + 개별 플랫폼별 수익 + 매입비용)
        'publisher_totals': {
            'total_revenue': sum(publisher_revenue.values()),
            'publisher_revenue': sum(publisher_revenue.values()),
            'publisher_profit': sum(publisher_profit.values()),
            'publisher_sales': sum(publisher_revenue.values()),
            'publisher_cost': sum(purchase_data[d]['publisher'] for d in date_list),
            'other_revenue': sum(int(other_revenue_data[d].get('publisher', 0)) for d in date_list if other_revenue_data and d in other_revenue_data),
            # 구글/네이버 합계 추가
            'google_revenue': sum(daily_data.get('publisher_daily_google', {}).values()),
            'naver_revenue': sum(daily_data.get('publisher_daily_naver', {}).values()),
        },
        'partners_totals': {
            'total_revenue': sum(partners_revenue.values()),
            'partners_revenue': sum(partners_revenue.values()),
            'partners_profit': sum(partners_profit.values()),
            'partners_sales': sum(partners_revenue.values()),
            'partners_cost': sum(purchase_data[d]['partners'] for d in date_list),
            'other_revenue': sum(int(other_revenue_data[d].get('partners', 0)) for d in date_list if other_revenue_data and d in other_revenue_data),
            # 구글/네이버 합계 추가
            'google_revenue': sum(daily_data.get('partners_daily_google', {}).values()),
            'naver_revenue': sum(daily_data.get('partners_daily_naver', {}).values()),
            # 개별 플랫폼별 수익 (section_results에서 가져오기)
            'cozymamang_revenue': section_results['partners']['totals'].get('cozymamang_revenue', 0),
            'mediamixer_revenue': section_results['partners']['totals'].get('mediamixer_revenue', 0),
            'aceplanet_revenue': section_results['partners']['totals'].get('aceplanet_revenue', 0),
            'teads_revenue': section_results['partners']['totals'].get('teads_revenue', 0),
            'taboola_revenue': section_results['partners']['totals'].get('taboola_revenue', 0),
            'coupang_revenue': section_results['partners']['totals'].get('coupang_revenue', 0),
            'valid_pv': section_results['partners']['totals'].get('valid_pv', 0),
            'revenue_per_pv': section_results['partners']['totals'].get('revenue_per_pv', 0),
        },
        'stamply_totals': {
            'total_revenue': sum(stamply_revenue.values()),
            'stamply_revenue': sum(stamply_revenue.values()),
            'stamply_profit': sum(stamply_profit.values()),
            'stamply_sales': sum(stamply_revenue.values()),
            'stamply_cost': sum(purchase_data[d]['stamply'] for d in date_list),
            'other_revenue': sum(int(other_revenue_data[d].get('stamply', 0)) for d in date_list if other_revenue_data and d in other_revenue_data),
            'coupang_revenue': section_results['stamply']['totals'].get('coupang_revenue', 0),
        },
        'stamply_coupang_account_totals': stamply_coupang_account_totals,
        'total_revenue': total_revenue,           # 총 매출 (퍼블리셔 + 파트너스 + 스탬플리)
        'total_profit': total_profit,             # 총 순이익 (퍼블리셔 + 파트너스 + 스탬플리)
        'purchase_data': purchase_data,           # 매입 비용 데이터
        'start_date': start_date,
        'end_date': end_date,
        'publisher_google_naver_data': publisher_google_naver_data,
        'partners_google_naver_data': partners_google_naver_data,
    }
    
    # 일일 데이터 추가
    daily_fields = [
        'publisher_daily_google', 'partners_daily_google', 'publisher_daily_naver', 'partners_daily_naver',
        'partners_daily_cozymamang', 'partners_daily_mediamixer', 'partners_daily_aceplanet',
        'partners_daily_teads', 'partners_daily_taboola', 'partners_daily_coupang', 'stamply_daily_coupang', 'stamply_daily_coupang_by_account'
    ]
    
    for field in daily_fields:
        if field in daily_data:
            context[field] = daily_data[field]
    
    return context

def process_all_sections(user, platform_list, start_date, end_date, publisher_google_naver_data, partners_google_naver_data, other_revenue_data=None, daily_data=None):
    """모든 섹션을 한번에 처리하는 헬퍼 함수"""
    sections_config = {
        'publisher': {'google_data': publisher_google_naver_data},
        'partners': {'google_data': partners_google_naver_data},
        'stamply': {'google_data': None}
    }
    
    section_results = {}
    for section_name, config in sections_config.items():
        platforms = get_section_platforms(platform_list, section_name, user)
        section_data = process_section_data(
            user, platform_list, start_date, end_date, platforms, config['google_data'], section_name
        )
        
        if other_revenue_data:
            daily_profit, daily_sales, totals = calculate_section_totals_with_other_revenue(
                section_data, [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)], 
                section_name, config['google_data'], other_revenue_data, daily_data
            )
        else:
            daily_profit, totals = calculate_section_totals(
                section_data, [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)], 
                section_name, config['google_data'], daily_data
            )
            daily_sales = daily_profit  # 비용이 없으므로 매출=순익
        
        section_results[section_name] = {
            'data': section_data,
            'daily_profit': daily_profit,
            'daily_sales': daily_sales,
            'totals': totals,
            'platforms': platforms
        }
    
    return section_results

@login_required
def report_view(request):
    """
    광고 리포트 페이지: 선택한 기간의 날짜별, 플랫폼별 수익 테이블
    """
    user = request.user
    
    # 1. 기본 데이터 설정
    start_date, end_date = get_date_range_from_request(request)
    platform_list = get_platform_list(user)
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    # 2. 기본 수익 데이터 조회
    stats = AdStats.objects.filter(user=user, date__range=[start_date, end_date])
    data = {}
    for d in date_list:
        data[d] = {}
        for platform, alias in platform_list:
            key = f"{platform}|{alias}"
            data[d][key] = Decimal('0')

    for row in stats.values('date', 'platform', 'alias').annotate(earnings=Sum('earnings')):
        d = row['date']
        key = f"{row['platform']}|{row['alias']}"
        if d in data and key in data[d]:
            data[d][key] = Decimal(str(row['earnings'] or 0))

    # 3. 구글/네이버 수익을 Member level별로 분류
    exchange_rates = get_exchange_rates(user, start_date, end_date)
    ad_unit_member_map = get_ad_unit_member_mapping(user)
    
    publisher_google_naver_data, partners_google_naver_data = calculate_platform_revenue_by_member_level(
        user, start_date, end_date, ad_unit_member_map, exchange_rates
    )
    
    # 4. 네이버 파워링크 수익 계산
    publisher_google_naver_data, partners_google_naver_data = calculate_naver_powerlink_revenue(
        user, start_date, end_date, publisher_google_naver_data, partners_google_naver_data
    )
    
    # 5. 기타수익 데이터 조회
    other_revenue_data = get_other_revenue_data(user, start_date, end_date)
    
    # 7. 세부 데이터 표를 위한 데이터 추가 (naver_powerlink_detail을 먼저 생성)
    google_detail_adsense, google_detail_admanager = get_google_detail_data(
        user, start_date, end_date, publisher_google_naver_data, partners_google_naver_data
    )
    naver_powerlink_detail = get_naver_powerlink_detail_data(user, start_date, end_date)
    naver_performance_detail = get_naver_performance_report_data(user, start_date, end_date)
    cozymamang_detail, cozymamang_grand_totals, cozymamang_daily_totals = get_cozymamang_detail_data(user, start_date, end_date)
    partners_valid_pv_data = get_partners_valid_pv_data(user, start_date, end_date, other_revenue_data, partners_google_naver_data)
    
    # 8. 일일 개별 플랫폼 수익 계산 (naver_powerlink_detail 사용)
    daily_data = calculate_daily_platform_revenue(
        date_list, publisher_google_naver_data, partners_google_naver_data, 
        {}, naver_powerlink_detail, user, platform_list  # user와 platform_list 전달
    )
    
    # 9. 모든 섹션 처리 (daily_data 전달)
    section_results = process_all_sections(
        user, platform_list, start_date, end_date, publisher_google_naver_data, partners_google_naver_data, other_revenue_data, daily_data
    )
    
    # main.py와 동일한 방식으로 퍼블리셔 수익 계산
    publisher_revenue = {}
    for d in date_list:
        publisher_revenue[d] = 0  # int로 시작
        
        # 퍼블리셔 섹션의 개별 플랫폼 수익 (구글/네이버 제외)
        if d in section_results['publisher']['data']:
            for key, value in section_results['publisher']['data'][d].items():
                platform, alias = key.split('|', 1)
                # google|publisher, naver|publisher 키도 제외 (중복 방지)
                if platform not in ['google', 'naver'] and not key.startswith(('google|', 'naver|')):
                    publisher_revenue[d] += int(value)  # main.py와 동일하게 int 변환
        
        # 퍼블리셔의 구글/네이버 수익 추가 (daily_data에서 이미 int 변환됨)
        if d in daily_data['publisher_daily_google']:
            publisher_revenue[d] += daily_data['publisher_daily_google'][d]  # 이미 int이므로 변환 불필요
        if d in daily_data['publisher_daily_naver']:
            publisher_revenue[d] += daily_data['publisher_daily_naver'][d]  # 이미 int이므로 변환 불필요
        
        # 기타수익 추가 (main.py와 동일하게)
        if other_revenue_data and d in other_revenue_data:
            if 'publisher' in other_revenue_data[d]:
                publisher_revenue[d] += int(other_revenue_data[d]['publisher'])
    
    # main.py와 동일한 방식으로 파트너스 수익 계산
    partners_revenue = {}
    for d in date_list:
        partners_revenue[d] = 0  # int로 시작
        
        # 파트너스 섹션의 개별 플랫폼 수익 (구글/네이버 제외)
        if d in section_results['partners']['data']:
            for key, value in section_results['partners']['data'][d].items():
                platform, alias = key.split('|', 1)
                # google|partners, naver|partners 키도 제외 (중복 방지)
                if platform not in ['google', 'naver'] and not key.startswith(('google|', 'naver|')):
                    partners_revenue[d] += int(value)  # main.py와 동일하게 int 변환
        
        # 파트너스의 구글/네이버 수익 추가 (daily_data에서 이미 int 변환됨)
        if d in daily_data['partners_daily_google']:
            partners_revenue[d] += daily_data['partners_daily_google'][d]  # 이미 int이므로 변환 불필요
        if d in daily_data['partners_daily_naver']:
            partners_revenue[d] += daily_data['partners_daily_naver'][d]  # 이미 int이므로 변환 불필요
        
        # 기타수익 추가 (main.py와 동일하게)
        if other_revenue_data and d in other_revenue_data:
            if 'partners' in other_revenue_data[d]:
                partners_revenue[d] += int(other_revenue_data[d]['partners'])
    
    # 스탬플리 수익 계산 (main.py와 동일한 방식)
    stamply_revenue = {}
    for d in date_list:
        stamply_revenue[d] = 0  # int로 시작
        
        # 스탬플리 섹션의 개별 플랫폼 수익
        if d in section_results['stamply']['data']:
            for key, value in section_results['stamply']['data'][d].items():
                stamply_revenue[d] += int(value)
        
        # 기타수익 추가
        if other_revenue_data and d in other_revenue_data:
            if 'stamply' in other_revenue_data[d]:
                stamply_revenue[d] += int(other_revenue_data[d]['stamply'])
    
    # 매입 비용 계산 (main.py와 동일한 방식)
    purchase_data = {}
    for d in date_list:
        purchase_data[d] = {
            'publisher': 0,
            'partners': 0,
            'stamply': 0,
            'total': 0
        }
        
        # 기타수익에서 매입 비용 추출
        if other_revenue_data and d in other_revenue_data:
            for section, amount in other_revenue_data[d].items():
                if section.endswith('_cost'):
                    if section == 'publisher_cost':
                        purchase_data[d]['publisher'] += int(amount)
                    elif section == 'partners_cost':
                        purchase_data[d]['partners'] += int(amount)
                    elif section == 'stamply_cost':
                        purchase_data[d]['stamply'] += int(amount)
                    
                    purchase_data[d]['total'] += int(amount)
    
    # 순이익 계산 (매출 - 매입비용)
    publisher_profit = {d: publisher_revenue[d] - purchase_data[d]['publisher'] for d in date_list}
    partners_profit = {d: partners_revenue[d] - purchase_data[d]['partners'] for d in date_list}
    stamply_profit = {d: stamply_revenue[d] - purchase_data[d]['stamply'] for d in date_list}
    
    # 총합 계산 (퍼블리셔 + 파트너스 + 스탬플리)
    total_revenue = {d: publisher_revenue[d] + partners_revenue[d] + stamply_revenue[d] for d in date_list}
    total_profit = {d: publisher_profit[d] + partners_profit[d] + stamply_profit[d] for d in date_list}
    
    # 10. 쿠팡 계정별 합계 계산
    stamply_coupang_account_totals = calculate_coupang_account_totals(
        daily_data['stamply_daily_coupang_by_account'], date_list, section_results['stamply']['platforms']
    )
    
    # 11. 컨텍스트 구성 및 렌더링
    platform_headers = get_platform_headers(platform_list)
    
    context = build_report_context(
        date_list, platform_headers, section_results, daily_data, 
        stamply_coupang_account_totals, start_date, end_date,
        publisher_google_naver_data, partners_google_naver_data, data, 
        publisher_revenue, partners_revenue, stamply_revenue,
        publisher_profit, partners_profit, stamply_profit,
        total_revenue, total_profit, purchase_data, other_revenue_data
    )
    
    context.update({
        'google_detail_adsense': google_detail_adsense,
        'google_detail_admanager': google_detail_admanager,
        'naver_powerlink_detail': naver_powerlink_detail,
        'naver_performance_detail': naver_performance_detail,
        'cozymamang_detail': cozymamang_detail,
        'cozymamang_grand_totals': cozymamang_grand_totals,
        'cozymamang_daily_totals': cozymamang_daily_totals,
        'other_revenue_data': other_revenue_data,  # 기타수익 데이터 추가
        'partners_valid_pv_data': partners_valid_pv_data,  # 파트너스 유효PV 데이터 추가
    })
    
    return render(request, 'report.html', context)

def get_other_revenue_data(user, start_date, end_date):
    """기타수익 데이터를 조회하여 반환 (매입비용 포함)"""
    other_revenues = OtherRevenue.objects.filter(
        user=user,
        date__range=[start_date, end_date]
    ).values('date', 'section', 'amount')
    
    # 날짜별, 섹션별로 데이터 구성
    revenue_data = {}
    for revenue in other_revenues:
        date_key = revenue['date']
        section = revenue['section']
        amount = revenue['amount']
        
        if date_key not in revenue_data:
            revenue_data[date_key] = {}
        
        revenue_data[date_key][section] = amount
    
    # 매입비용 데이터 추가
    purchase_cost_data = calculate_purchase_cost_by_date_range(user, start_date, end_date)
    
    # 매입비용을 revenue_data에 추가
    for date_key in purchase_cost_data['publisher_cost']:
        if date_key not in revenue_data:
            revenue_data[date_key] = {}
        
        revenue_data[date_key]['publisher_cost'] = purchase_cost_data['publisher_cost'][date_key]
        revenue_data[date_key]['partners_cost'] = purchase_cost_data['partners_cost'][date_key]
    
    return revenue_data

@login_required
@require_POST
def save_other_revenue(request):
    """기타수익 저장/수정/삭제 API"""
    try:
        data = json.loads(request.body)
        date_str = data.get('date')
        section = data.get('section')
        amount = data.get('amount', 0)
        
        if not date_str or not section:
            return JsonResponse({'success': False, 'error': '날짜와 섹션은 필수입니다.'})
        
        # 날짜 파싱
        try:
            revenue_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': '올바른 날짜 형식이 아닙니다.'})
        
        # 금액 검증
        try:
            amount_decimal = Decimal(str(amount))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': '올바른 금액이 아닙니다.'})
        
        # 기존 데이터 조회
        other_revenue, created = OtherRevenue.objects.get_or_create(
            user=request.user,
            date=revenue_date,
            section=section,
            defaults={'amount': amount_decimal}
        )
        
        if not created:
            # 기존 데이터가 있는 경우
            if amount_decimal == 0:
                # 금액이 0이면 삭제
                other_revenue.delete()
                return JsonResponse({'success': True, 'action': 'deleted'})
            else:
                # 금액이 0이 아니면 수정
                other_revenue.amount = amount_decimal
                other_revenue.save()
                return JsonResponse({'success': True, 'action': 'updated'})
        else:
            # 새로 생성된 경우
            if amount_decimal == 0:
                # 금액이 0이면 삭제
                other_revenue.delete()
                return JsonResponse({'success': True, 'action': 'deleted'})
            else:
                return JsonResponse({'success': True, 'action': 'created'})
                
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '올바른 JSON 형식이 아닙니다.'})
    except Exception as e:
        logger.error(f"기타수익 저장 중 오류: {str(e)}")
        return JsonResponse({'success': False, 'error': '저장 중 오류가 발생했습니다.'})

# ===== 퍼블리셔 매출 지표 화면 =====
@login_required
def publisher_report_view(request):
    """
    퍼블리셔 매출 지표 화면: 주요 퍼블리셔 리스트 및 선택 퍼블리셔의 세부 데이터
    """
    user = request.user
    today = date.today()

    # 날짜 범위 파라미터 처리
    try:
        start_date = datetime.strptime(request.GET.get('start_date', ''), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.GET.get('end_date', ''), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        end_date = today
        start_date = end_date - timedelta(days=6)

    if end_date > today:
        end_date = today
    if start_date > end_date:
        start_date = end_date
    if (end_date - start_date).days > 31:
        start_date = end_date - timedelta(days=31)

    # 주요 퍼블리셔 리스트 조회
    important_groups = PurchaseGroup.objects.filter(
        user=request.user,
        is_active=True,
        is_important=True
    ).order_by('member_request_key')
    
    publisher_headers = []
    publisher_keys = []
    for group in important_groups:
        publisher_keys.append(group.member_request_key)
        try:
            member_name = group.member.uname if group.member else '미설정'
        except:
            member_name = '미설정'
        publisher_headers.append({
            'label': f"{group.company_name}",
            'key': group.member_request_key
        })

    # 날짜 리스트
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]

    # 성능 최적화: 한 번에 모든 데이터 조회
    all_publishers_detail_data = {}
    
    if publisher_keys:  # 퍼블리셔가 있을 때만 쿼리 실행
        # 1. Adpost 데이터 일괄 조회
        adpost_stats = AdStats.objects.filter(
            platform='adpost',
            ad_unit_id='모바일뉴스픽_컨텐츠',
            date__range=[start_date, end_date],
            user=request.user
        ).values('date').annotate(
            earnings=Sum('earnings'),
            clicks=Sum('clicks')
        )
        
        # 2. TotalStat powerlinkCount 일괄 조회
        total_powerlink_stats = TotalStat.newspic_objects().filter(
            sdate__range=[start_date, end_date]
        ).values('sdate').annotate(
            total_powerlink=Sum('powerlink_count')
        )
        
        # 3. MemberStat 데이터 일괄 조회
        member_stats = MemberStat.newspic_objects().filter(
            request_key__in=publisher_keys,
            sdate__range=[start_date.strftime('%Y%m%d'), end_date.strftime('%Y%m%d')]
        ).values('request_key', 'sdate').annotate(
            click_cnt=Sum('click_cnt'),
            point=Sum('point')
        )
        
        # 4. TotalStat 데이터 일괄 조회
        total_stats = TotalStat.newspic_objects().filter(
            request_key__in=publisher_keys,
            sdate__range=[start_date, end_date]
        ).values('request_key', 'sdate').annotate(
            visit_count=Sum('visit_count'),
            powerlink_count=Sum('powerlink_count')
        )
        
        # 5. 애드센스 데이터 일괄 조회 (매핑된 ad_unit_id들)
        adsense_ad_units = PurchaseGroupAdUnit.objects.filter(
            purchase_group__user=request.user,
            platform='adsense',
            is_active=True
        ).values_list('ad_unit_id', flat=True)
        
        adsense_stats = {}
        if adsense_ad_units:
            adsense_data = AdStats.objects.filter(
                user=request.user,
                platform='adsense',
                ad_unit_id__in=adsense_ad_units,
                date__range=[start_date, end_date]
            ).values('ad_unit_id', 'date').annotate(
                earnings_usd=Sum('earnings_usd')
            )
            
            # 환율 데이터 조회
            exchange_rates = ExchangeRate.objects.filter(
                user=request.user
            ).values('year_month', 'usd_to_krw')
            exchange_rate_map = {rate['year_month']: rate['usd_to_krw'] for rate in exchange_rates}
            
            for stat in adsense_data:
                key = (stat['ad_unit_id'], stat['date'])
                usd_amount = stat['earnings_usd'] or 0
                
                # 해당 월의 환율 조회, 없으면 기본값 1300 사용
                month_start = stat['date'].replace(day=1)
                exchange_rate = exchange_rate_map.get(month_start, Decimal('1300'))
                
                # float를 Decimal로 변환하여 연산
                usd_amount_decimal = Decimal(str(usd_amount))
                krw_amount = usd_amount_decimal * exchange_rate
                adsense_stats[key] = krw_amount
        
        # 6. ADX(애드매니저) 데이터 일괄 조회 (매핑된 ad_unit_id들)
        adx_ad_units = PurchaseGroupAdUnit.objects.filter(
            purchase_group__user=request.user,
            platform='admanager',
            is_active=True
        ).values_list('ad_unit_id', flat=True)
        
        adx_stats = {}
        if adx_ad_units:
            adx_data = AdStats.objects.filter(
                user=request.user,
                platform='admanager',
                ad_unit_id__in=adx_ad_units,
                date__range=[start_date, end_date]
            ).values('ad_unit_id', 'date').annotate(
                earnings=Sum('earnings')
            )
            
            for stat in adx_data:
                key = (stat['ad_unit_id'], stat['date'])
                earnings = stat['earnings'] or 0
                adx_stats[key] = earnings
        
        # 데이터를 딕셔너리로 변환하여 빠른 접근 가능하게 함
        adpost_data = {}
        for stat in adpost_stats:
            adpost_data[stat['date']] = {
                'earnings': stat['earnings'] or 0,
                'clicks': stat['clicks'] or 0
            }
        
        total_powerlink_data = {}
        for stat in total_powerlink_stats:
            total_powerlink_data[stat['sdate']] = stat['total_powerlink'] or 0
        
        member_stats_data = {}
        for stat in member_stats:
            key = (stat['request_key'], stat['sdate'])
            member_stats_data[key] = {
                'click_cnt': stat['click_cnt'] or 0,
                'point': stat['point'] or 0
            }
        
        total_stats_data = {}
        for stat in total_stats:
            key = (stat['request_key'], stat['sdate'])
            total_stats_data[key] = {
                'visit_count': stat['visit_count'] or 0,
                'powerlink_count': stat['powerlink_count'] or 0
            }
        
        # 각 퍼블리셔별 데이터 처리
        for pub in publisher_headers:
            publisher_key = pub['key']
            detail_data = {}
            detail_totals = {
                'pageview': 0,
                'valid_pageview': 0,
                'valid_pageview_rate': 0,
                'powerlink_click': 0,
                'powerlink_revenue': 0,
                'adsense_revenue': 0,
                'ab_revenue': 0,
                'adx_revenue': 0,
                'avg_revenue': 0,
            }
            
            # 해당 퍼블리셔의 PurchaseGroup 조회
            try:
                member = Member.newspic_objects().get(request_key=publisher_key)
            except Member.DoesNotExist:
                member = None
            
            purchase_group = PurchaseGroup.objects.filter(
                member_request_key=publisher_key,
                user=request.user,
                is_active=True
            ).first()
            
            # 해당 그룹의 매핑된 애드센스 ad_unit_id들 조회
            mapped_adsense_units = []
            if purchase_group:
                mapped_adsense_units = PurchaseGroupAdUnit.objects.filter(
                    purchase_group=purchase_group,
                    platform='adsense',
                    is_active=True
                ).values_list('ad_unit_id', flat=True)
            
            # 해당 그룹의 매핑된 ADX ad_unit_id들 조회
            mapped_adx_units = []
            if purchase_group:
                mapped_adx_units = PurchaseGroupAdUnit.objects.filter(
                    purchase_group=purchase_group,
                    platform='admanager',
                    is_active=True
                ).values_list('ad_unit_id', flat=True)
            
            for current_date in date_list:
                date_str = current_date.strftime('%Y%m%d')
                
                # 멤버 통계 데이터
                member_key = (publisher_key, date_str)
                member_data = member_stats_data.get(member_key, {'click_cnt': 0, 'point': 0})
                click_cnt = member_data['click_cnt']
                point = member_data['point']
                
                # 전체 통계 데이터
                total_key = (publisher_key, current_date)
                total_data = total_stats_data.get(total_key, {'visit_count': 0, 'powerlink_count': 0})
                visit_count = total_data['visit_count']
                powerlink_count = total_data['powerlink_count']
                
                # 유효페이지뷰율 계산
                valid_pageview_rate = 0
                if visit_count > 0:
                    valid_pageview_rate = round((click_cnt / visit_count) * 100, 2)
                
                # 파워링크 수익 계산
                powerlink_revenue = 0
                adpost_info = adpost_data.get(current_date, {'earnings': 0, 'clicks': 0})
                total_powerlink_count = total_powerlink_data.get(current_date, 0)
                
                adpost_earnings = adpost_info['earnings']
                adpost_clicks = adpost_info['clicks']
                
                if adpost_clicks > 0 and total_powerlink_count > 0 and powerlink_count > 0:
                    # 단가 = Adpost 매출 / Adpost 클릭수
                    unit_price = (Decimal(str(adpost_earnings)) / Decimal(str(adpost_clicks))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    # 파워링크 수익 = 단가 × 퍼블리셔 파워링크 클릭수 × 59.5% × (Adpost 클릭수 / 전체 powerlinkCount)
                    powerlink_revenue = (unit_price * Decimal(str(powerlink_count)) * Decimal('0.595') * (Decimal(str(adpost_clicks)) / Decimal(str(total_powerlink_count)))).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
                
                # 애드센스 수익 계산 (최적화된 버전)
                adsense_revenue = 0
                adsense_total_usd = Decimal('0')  # 그룹 전체 USD 합계 (Decimal로 초기화)
                
                # 해당 그룹의 모든 ad_unit_id에 대해 한 번에 데이터 조회
                if mapped_adsense_units:
                    adsense_usd_bulk = AdStats.objects.filter(
                        user=request.user,
                        platform='adsense',
                        ad_unit_id__in=mapped_adsense_units,
                        date=current_date
                    ).values('ad_unit_id').annotate(
                        total_earnings_usd=Sum('earnings_usd')
                    )
                    
                    # 벌크 결과를 딕셔너리로 변환
                    adsense_usd_dict = {item['ad_unit_id']: item['total_earnings_usd'] or 0 for item in adsense_usd_bulk}
                    
                    for ad_unit_id in mapped_adsense_units:
                        adsense_key = (ad_unit_id, current_date)
                        adsense_amount = adsense_stats.get(adsense_key, 0)
                        adsense_revenue += adsense_amount
                        
                        # USD 금액도 합계 계산 (딕셔너리에서 조회)
                        usd_amount = adsense_usd_dict.get(ad_unit_id, 0)
                        adsense_total_usd += Decimal(str(usd_amount))
                
                # 툴팁용 상세 정보 (그룹 전체 합계)
                adsense_details = None
                if adsense_revenue > 0 and adsense_total_usd > 0:
                    month_start = current_date.replace(day=1)
                    exchange_rate = exchange_rate_map.get(month_start, Decimal('1300'))
                    adsense_details = {
                        'total_usd': adsense_total_usd,
                        'exchange_rate': exchange_rate,
                        'total_krw': adsense_revenue
                    }
                
                # ADX 수익 계산
                adx_revenue = 0
                if mapped_adx_units:
                    for ad_unit_id in mapped_adx_units:
                        adx_key = (ad_unit_id, current_date)
                        adx_amount = adx_stats.get(adx_key, 0)
                        adx_revenue += adx_amount
                
                detail_data[current_date] = {
                    'pageview': visit_count,
                    'valid_pageview': click_cnt,
                    'valid_pageview_rate': f"{valid_pageview_rate}%" if valid_pageview_rate > 0 else '-',
                    'powerlink_click': powerlink_count,
                    'powerlink_revenue': powerlink_revenue,
                    'adsense_revenue': adsense_revenue,
                    'adsense_details': adsense_details,  # 툴팁용 상세 정보
                    'ab_revenue': float(powerlink_revenue) + float(adsense_revenue),
                    'adx_revenue': adx_revenue,
                    'avg_revenue': float(powerlink_revenue) + float(adsense_revenue) + float(adx_revenue),  # 파워링크 + 애드센스 + ADX 수익
                }
                
                # 합계 계산
                detail_totals['pageview'] += visit_count
                detail_totals['valid_pageview'] += click_cnt
                detail_totals['powerlink_click'] += powerlink_count
                detail_totals['powerlink_revenue'] += powerlink_revenue
                detail_totals['adsense_revenue'] += adsense_revenue
                detail_totals['ab_revenue'] += float(powerlink_revenue) + float(adsense_revenue)
                detail_totals['adx_revenue'] += adx_revenue
                detail_totals['avg_revenue'] += float(powerlink_revenue) + float(adsense_revenue) + float(adx_revenue)
            
            # 전체 유효페이지뷰율 계산
            if detail_totals['pageview'] > 0:
                detail_totals['valid_pageview_rate'] = f"{round((detail_totals['valid_pageview'] / detail_totals['pageview']) * 100, 2)}%"
            else:
                detail_totals['valid_pageview_rate'] = '-'
            
            all_publishers_detail_data[publisher_key] = {
                'detail_data': detail_data,
                'detail_totals': detail_totals
            }

    # 상단 매출 지표 표를 위한 데이터 생성
    revenue_summary_data = {}
    revenue_summary_totals = {
        'total_revenue': 0,
        'publisher_revenues': {}
    }
    
    # 각 퍼블리셔별 합계 초기화
    for pub in publisher_headers:
        revenue_summary_totals['publisher_revenues'][pub['key']] = 0
    
    # 날짜별 매출 데이터 생성
    for current_date in date_list:
        daily_total = 0
        daily_publisher_revenues = {}
        
        for pub in publisher_headers:
            publisher_key = pub['key']
            publisher_data = all_publishers_detail_data.get(publisher_key, {})
            detail_data = publisher_data.get('detail_data', {})
            
            # 해당 날짜의 평균 수익
            date_data = detail_data.get(current_date, {})
            avg_revenue = date_data.get('ab_revenue', 0)
            
            daily_publisher_revenues[publisher_key] = avg_revenue
            daily_total += avg_revenue
            revenue_summary_totals['publisher_revenues'][publisher_key] += avg_revenue
        
        revenue_summary_data[current_date] = {
            'total_revenue': daily_total,
            'publisher_revenues': daily_publisher_revenues
        }
        revenue_summary_totals['total_revenue'] += daily_total

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'publisher_headers': publisher_headers,
        'date_list': date_list,
        'all_publishers_detail_data': all_publishers_detail_data,
        'revenue_summary_data': revenue_summary_data,
        'revenue_summary_totals': revenue_summary_totals,
    }
    return render(request, 'publisher_report.html', context) 

def get_google_detail_data(user, start_date, end_date, publisher_google_naver_data, partners_google_naver_data):
    """구글(애드센스, 애드매니저) 세부 데이터 표에 필요한 데이터를 반환"""
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    # 1. 애드센스 데이터 (퍼블리셔/파트너스로 분류)
    adsense_data = {
        'publisher': {'daily': {}, 'total': Decimal('0')},
        'partners': {'daily': {}, 'total': Decimal('0')}
    }
    for d in date_list:
        adsense_data['publisher']['daily'][d] = publisher_google_naver_data[d]['adsense']
        adsense_data['partners']['daily'][d] = partners_google_naver_data[d]['adsense']
    
    adsense_data['publisher']['total'] = sum(adsense_data['publisher']['daily'].values())
    adsense_data['partners']['total'] = sum(adsense_data['partners']['daily'].values())

    # 2. 애드매니저(ADX) 데이터 (광고 단위별로 분류)
    admanager_stats = AdStats.objects.filter(
        user=user,
        platform='admanager',
        date__range=[start_date, end_date]
    ).values('ad_unit_name', 'date').annotate(
        daily_earnings=Sum('earnings')
    ).order_by('ad_unit_name', 'date')

    admanager_data = {}
    for stat in admanager_stats:
        ad_unit_name = stat['ad_unit_name'] or 'N/A'
        if ad_unit_name not in admanager_data:
            admanager_data[ad_unit_name] = {'daily': {d: Decimal('0') for d in date_list}, 'total': Decimal('0')}
        
        admanager_data[ad_unit_name]['daily'][stat['date']] = Decimal(str(stat['daily_earnings']))
    
    for ad_unit_name in admanager_data:
        admanager_data[ad_unit_name]['total'] = sum(admanager_data[ad_unit_name]['daily'].values())
        
    return adsense_data, admanager_data

def get_naver_powerlink_detail_data(user, start_date, end_date):
    """네이버 파워링크 세부 데이터 표에 필요한 데이터를 반환"""
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    # 데이터 초기화
    powerlink_data = {
        'daily': {d: {} for d in date_list},
        'totals': {}
    }

    # 1. Adpost 데이터 (단가 계산용)
    adpost_stats = AdStats.objects.filter(
        platform='adpost',
        ad_unit_id='모바일뉴스픽_컨텐츠',
        date__range=[start_date, end_date],
        user=user
    ).values('date').annotate(earnings=Sum('earnings'), clicks=Sum('clicks'))
    
    adpost_data = {stat['date']: {'earnings': stat['earnings'] or 0, 'clicks': stat['clicks'] or 0} for stat in adpost_stats}

    # 2. 전체 및 멤버별 파워링크 클릭수
    total_powerlink_stats = TotalStat.newspic_objects().filter(sdate__range=[start_date, end_date]).values('sdate').annotate(total_clicks=Sum('powerlink_count'))
    total_powerlink_data = {stat['sdate']: stat['total_clicks'] for stat in total_powerlink_stats}

    # tbTotalStat에서 해당 기간에 데이터가 있는 모든 퍼블리셔 조회
    totalstat_publishers = TotalStat.newspic_objects().filter(
        sdate__range=[start_date, end_date]
    ).values_list('request_key', flat=True).distinct()
    
    # Member 테이블에서 해당 퍼블리셔들의 level 정보 조회
    from stats.models import Member
    member_levels = {}
    for member in Member.newspic_objects().filter(request_key__in=totalstat_publishers):
        member_levels[member.request_key] = member.level
    
    # purchase_group에 있는 퍼블리셔들도 추가 (level 정보가 없는 경우)
    all_groups = PurchaseGroup.objects.filter(user=user, is_active=True)
    for group in all_groups:
        if group.member_request_key not in member_levels:
            member_levels[group.member_request_key] = group.member.level if group.member else 60
    
    # 모든 퍼블리셔 키 목록
    all_member_keys = list(member_levels.keys())
    
    member_powerlink_stats = TotalStat.newspic_objects().filter(
        request_key__in=all_member_keys, sdate__range=[start_date, end_date]
    ).values('request_key', 'sdate', 'powerlink_count')
    member_powerlink_data = {(stat['request_key'], stat['sdate']): stat['powerlink_count'] for stat in member_powerlink_stats}

    # 3. 일자별 데이터 계산
    for d in date_list:
        daily_values = {
            'total_revenue': Decimal('0'), 'publisher_revenue': Decimal('0'), 'partners_revenue': Decimal('0'),
            'total_clicks': 0, 'publisher_clicks': 0, 'partners_clicks': 0
        }
        
        # Adpost 정보 (모바일뉴스픽_컨텐츠)
        adpost_info = adpost_data.get(d, {'earnings': 0, 'clicks': 0})
        adpost_earnings = adpost_info['earnings']
        adpost_clicks = adpost_info['clicks']
        
        # 어드민 전체 파워링크 클릭수
        admin_total_clicks = total_powerlink_data.get(d, 0)
        
        # PPC 계산: 모바일뉴스픽_컨텐츠 매출 / 모바일뉴스픽_컨텐츠 클릭수
        ppc = (Decimal(str(adpost_earnings)) / Decimal(str(adpost_clicks))) if adpost_clicks > 0 else Decimal('0')
        
        # 인정비율 계산: 모바일뉴스픽_컨텐츠 클릭수 / 파워링크 전체 클릭수
        recognition_rate = (Decimal(str(adpost_clicks)) / Decimal(str(admin_total_clicks))) if admin_total_clicks > 0 else Decimal('0')

        daily_values['publisher_clicks'] = admin_total_clicks
        
        # 모든 퍼블리셔별 수익 및 클릭수 계산 (tbTotalStat에 있는 모든 퍼블리셔)
        for request_key in all_member_keys:
            clicks = member_powerlink_data.get((request_key, d), 0)
            revenue = Decimal('0')
            
            if ppc > 0 and clicks > 0 and recognition_rate > 0:
                # 수익 계산: PPC * 파워링크 클릭수 * 59.5% * 인정비율
                revenue = (ppc * Decimal(str(clicks)) * Decimal('0.595') * recognition_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            # level에 따라 퍼블리셔/파트너스 구분
            member_level = member_levels.get(request_key, 60)  # 기본값은 파트너스
            if member_level in [60, 61, 65]:  # 퍼블리셔 (level 50 또는 100)
                daily_values['partners_revenue'] += revenue
                daily_values['partners_clicks'] += clicks
                daily_values['publisher_clicks'] -= clicks
        
        daily_values['publisher_revenue'] = (ppc * Decimal(str(daily_values['publisher_clicks'])) * Decimal('0.595') * recognition_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        daily_values['total_revenue'] = daily_values['publisher_revenue'] + daily_values['partners_revenue']
        daily_values['total_clicks'] = daily_values['publisher_clicks'] + daily_values['partners_clicks']

        # Net CPC 계산: 인정비율 * PPC * 59.5%
        daily_values['net_cpc'] = (recognition_rate * ppc * Decimal('0.595')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        daily_values['ppc'] = ppc
        
        # 어드민 전체 클릭수 저장
        daily_values['admin_total_clicks'] = admin_total_clicks
        daily_values['recognition_rate'] = float(recognition_rate * 100)  # 퍼센트로 변환

        powerlink_data['daily'][d] = daily_values

    # 4. 합계 계산
    powerlink_data['totals'] = {
        'total_revenue': sum(v['total_revenue'] for v in powerlink_data['daily'].values()),
        'publisher_revenue': sum(v['publisher_revenue'] for v in powerlink_data['daily'].values()),
        'partners_revenue': sum(v['partners_revenue'] for v in powerlink_data['daily'].values()),
        'admin_total_clicks': sum(v['admin_total_clicks'] for v in powerlink_data['daily'].values()),
        'total_clicks': sum(v['total_clicks'] for v in powerlink_data['daily'].values()),
        'publisher_clicks': sum(v['publisher_clicks'] for v in powerlink_data['daily'].values()),
        'partners_clicks': sum(v['partners_clicks'] for v in powerlink_data['daily'].values()),
    }
    total_sum = powerlink_data['totals']
    total_sum['net_cpc'] = (total_sum['total_revenue'] / total_sum['total_clicks']) if total_sum['total_clicks'] > 0 else Decimal('0')
    total_sum['ppc'] = (total_sum['partners_revenue'] / total_sum['partners_clicks']) if total_sum['partners_clicks'] > 0 else Decimal('0')
    total_sum['recognition_rate'] = (total_sum['total_clicks'] / total_sum['admin_total_clicks'] * 100) if total_sum['admin_total_clicks'] > 0 else 0

    return powerlink_data

def get_naver_performance_report_data(user, start_date, end_date):
    """네이버 실적 보고서 표에 필요한 데이터를 반환"""
    stats = AdStats.objects.filter(
        user=user,
        platform='adpost',
        date__range=[start_date, end_date]
    ).values('date', 'ad_unit_name').annotate(
        impressions=Sum('impressions'),
        clicks=Sum('clicks'),
        earnings=Sum('earnings')
    ).order_by('date', 'ad_unit_name')

    report_data = {'TOTAL': {'daily': {}, 'totals': {}}}
    
    # 일별 데이터 집계
    for stat in stats:
        d = stat['date']
        ad_unit = stat['ad_unit_name'] or 'N/A'
        
        if ad_unit not in report_data:
            report_data[ad_unit] = {'daily': {}, 'totals': {}}
        
        # ad_unit별 데이터
        report_data[ad_unit]['daily'][d] = {
            'impressions': stat['impressions'], 'clicks': stat['clicks'], 'earnings': Decimal(str(stat['earnings']))
        }
        
        # TOTAL 데이터
        if d not in report_data['TOTAL']['daily']:
            report_data['TOTAL']['daily'][d] = {'impressions': 0, 'clicks': 0, 'earnings': Decimal('0')}
        
        report_data['TOTAL']['daily'][d]['impressions'] += stat['impressions']
        report_data['TOTAL']['daily'][d]['clicks'] += stat['clicks']
        report_data['TOTAL']['daily'][d]['earnings'] += Decimal(str(stat['earnings']))

    # CTR, PPC, 총매출 계산 및 합계
    for ad_unit, data in report_data.items():
        totals = {'impressions': 0, 'clicks': 0, 'earnings': Decimal('0'), 'total_revenue': Decimal('0')}
        for d, daily_data in data['daily'].items():
            daily_data['ctr'] = (daily_data['clicks'] / daily_data['impressions'] * 100) if daily_data['impressions'] > 0 else 0
            daily_data['ppc'] = (daily_data['earnings'] / daily_data['clicks']) if daily_data['clicks'] > 0 else Decimal('0')
            # '총 매출'은 수익에 0.595를 곱한 값으로 처리
            daily_data['total_revenue'] = daily_data['earnings'] * Decimal('0.595') 
            
            totals['impressions'] += daily_data['impressions']
            totals['clicks'] += daily_data['clicks']
            totals['earnings'] += daily_data['earnings']
            totals['total_revenue'] += daily_data['total_revenue']
        
        totals['ctr'] = (totals['clicks'] / totals['impressions'] * 100) if totals['impressions'] > 0 else 0
        totals['ppc'] = (totals['earnings'] / totals['clicks']) if totals['clicks'] > 0 else Decimal('0')
        data['totals'] = totals

    return report_data

def get_cozymamang_detail_data(user, start_date, end_date):
    """코지마망 세부 데이터 표에 필요한 데이터를 반환"""
    stats = AdStats.objects.filter(
        user=user,
        platform='cozymamang',
        ad_unit_name__in=['뉴스픽_템플릿스크립트', '뉴스픽_본문1_300x250', '뉴스픽_본문2_300x250', '뉴스픽_본문3_300x250'],
        date__range=[start_date, end_date]
    ).values('ad_unit_name', 'date').annotate(
        impressions=Sum('impressions'),
        clicks=Sum('clicks'),
        earnings=Sum('earnings'),
        final_purchase_amount=Sum('total_amount'),
        final_purchase_quantity=Sum('order_count')
    ).order_by('ad_unit_name', 'date')
    
    cozymamang_data = {}
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    for stat in stats:
        ad_unit_name = stat['ad_unit_name'] or 'N/A'
        if ad_unit_name not in cozymamang_data:
            cozymamang_data[ad_unit_name] = {'daily': {d: {} for d in date_list}, 'totals': {}}
        
        daily_stats = {
            'impressions': stat['impressions'], 
            'clicks': stat['clicks'], 
            'earnings': Decimal(str(stat['earnings'] or 0)),
            'final_purchase_amount': Decimal(str(stat['final_purchase_amount'] or 0)),
            'final_purchase_quantity': stat['final_purchase_quantity'] or 0
        }
        daily_stats['cpc'] = (daily_stats['earnings'] / daily_stats['clicks']) if daily_stats.get('clicks', 0) > 0 else Decimal('0')
        cozymamang_data[ad_unit_name]['daily'][stat['date']] = daily_stats

    # 합계 및 추가 필드 계산
    for ad_unit_name, data in cozymamang_data.items():
        totals = {
            'impressions': 0, 'clicks': 0, 'earnings': Decimal('0'),
            'final_purchase_amount': Decimal('0'), 'final_purchase_quantity': 0
        }
        for d, daily_data in data['daily'].items():
            if daily_data: # 데이터가 있는 날만 합산
                totals['impressions'] += daily_data.get('impressions', 0)
                totals['clicks'] += daily_data.get('clicks', 0)
                totals['earnings'] += daily_data.get('earnings', Decimal('0'))
                totals['final_purchase_amount'] += daily_data.get('final_purchase_amount', Decimal('0'))
                totals['final_purchase_quantity'] += daily_data.get('final_purchase_quantity', 0)
        
        totals['cpc'] = (totals['earnings'] / totals['clicks']) if totals['clicks'] > 0 else Decimal('0')
        data['totals'] = totals

    # 일별 총계 계산
    daily_totals = {}
    for d in date_list:
        day_sum = {'earnings': Decimal('0')}
        for ad_unit_data in cozymamang_data.values():
            if d in ad_unit_data['daily'] and ad_unit_data['daily'][d]:
                daily_data = ad_unit_data['daily'][d]
                day_sum['earnings'] += daily_data.get('earnings', Decimal('0'))
        daily_totals[d] = day_sum

    # 전체 ad_unit에 대한 grand_totals 계산
    grand_totals = {
        'impressions': 0, 'clicks': 0, 'earnings': Decimal('0'),
        'final_purchase_amount': Decimal('0'), 'final_purchase_quantity': 0
    }
    for ad_unit_name, data in cozymamang_data.items():
        grand_totals['impressions'] += data['totals']['impressions']
        grand_totals['clicks'] += data['totals']['clicks']
        grand_totals['earnings'] += data['totals']['earnings']
        grand_totals['final_purchase_amount'] += data['totals']['final_purchase_amount']
        grand_totals['final_purchase_quantity'] += data['totals']['final_purchase_quantity']
    
    grand_totals['cpc'] = (grand_totals['earnings'] / grand_totals['clicks']) if grand_totals['clicks'] > 0 else Decimal('0')

    return cozymamang_data, grand_totals, daily_totals 

def get_partners_valid_pv_data(user, start_date, end_date, other_revenue_data=None, partners_google_naver_data=None):
    """파트너스 유효PV와 유효PV당 매출 데이터를 계산하여 반환"""
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    # 파트너스 유효PV 데이터 조회 (tbMemberStat의 clickCnt를 해당 기간에 데이터가 있는 모든 대상에 대해서)
    from stats.models import MemberStat, Member
    
    # 날짜 범위를 문자열 형태로 변환 (YYYYMMDD 형식)
    start_date_str = start_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')
    
    # 해당 기간에 MemberStat에 데이터가 있는 모든 request_key 조회
    memberstat_publishers = MemberStat.newspic_objects().filter(
        sdate__range=[start_date_str, end_date_str]
    ).values_list('request_key', flat=True).distinct()
    
    # Member 테이블에서 해당 퍼블리셔들의 level 정보 조회
    member_levels = {}
    for member in Member.newspic_objects().filter(request_key__in=memberstat_publishers):
        member_levels[member.request_key] = member.level
    
    # level 50과 100을 제외한 퍼블리셔들만 필터링 (파트너스)
    partners_keys = [key for key, level in member_levels.items() if level != 50 and level != 100]
    
    # 해당 member들의 MemberStat 데이터 조회 (파트너스만)
    partners_stats = MemberStat.newspic_objects().filter(
        request_key__in=partners_keys,
        sdate__range=[start_date_str, end_date_str]
    ).values('sdate').annotate(
        valid_pageview=Sum('click_cnt')
    )
    
    # 파트너스 매출 데이터 조회 (AdStats에서 파트너스 플랫폼들)
    partners_revenue_stats = AdStats.objects.filter(
        user=user,
        platform__in=['cozymamang', 'mediamixer', 'aceplanet', 'teads', 'taboola'],
        date__range=[start_date, end_date]
    ).values('date').annotate(
        revenue=Sum('earnings')
    )
    
    # 데이터를 딕셔너리로 변환
    valid_pv_data = {stat['sdate']: stat['valid_pageview'] or 0 for stat in partners_stats}
    revenue_data = {stat['date']: Decimal(str(stat['revenue'] or 0)) for stat in partners_revenue_stats}
    
    # 일자별 데이터 계산
    daily_data = {}
    for d in date_list:
        # date 객체를 문자열로 변환하여 MemberStat 데이터와 매칭
        date_str = d.strftime('%Y%m%d')
        valid_pv = valid_pv_data.get(date_str, 0)
        base_revenue = revenue_data.get(d, Decimal('0'))
        
        # 구글/네이버 수익 추가 (파트너스용)
        google_naver_revenue = Decimal('0')
        if partners_google_naver_data and d in partners_google_naver_data:
            google_naver_revenue = partners_google_naver_data[d].get('adsense', Decimal('0')) + \
                                  partners_google_naver_data[d].get('admanager', Decimal('0')) + \
                                  partners_google_naver_data[d].get('naver', Decimal('0'))
        
        # 기타수익 추가
        other_revenue = Decimal('0')
        if other_revenue_data and d in other_revenue_data:
            if 'partners' in other_revenue_data[d]:
                other_revenue = other_revenue_data[d]['partners']
        
        # 총 매출 = 기본 매출 + 구글/네이버 수익 + 기타수익
        total_revenue = base_revenue + google_naver_revenue + other_revenue
        
        # 유효PV당 매출 계산
        revenue_per_pv = (total_revenue / valid_pv) if valid_pv > 0 else Decimal('0')
        
        daily_data[d] = {
            'valid_pageview': valid_pv,
            'revenue': total_revenue,
            'revenue_per_pv': revenue_per_pv.quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        }
    
    # 합계 계산
    total_valid_pv = sum(daily_data[d]['valid_pageview'] for d in date_list)
    total_revenue = sum(daily_data[d]['revenue'] for d in date_list)
    total_revenue_per_pv = (total_revenue / total_valid_pv) if total_valid_pv > 0 else Decimal('0')
    
    totals = {
        'valid_pageview': total_valid_pv,
        'revenue': total_revenue,
        'revenue_per_pv': total_revenue_per_pv.quantize(Decimal('0'), rounding=ROUND_HALF_UP)
    }
    
    return {
        'daily': daily_data,
        'totals': totals
    } 