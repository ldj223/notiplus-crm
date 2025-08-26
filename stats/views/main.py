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
from decimal import Decimal
import logging
from rest_framework.decorators import api_view
from django.db.models import Q

from ..forms import CredentialForm, SignUpForm
from ..models import (
    AdStats, PlatformCredential, UserPreference, MonthlySales, 
    SettlementDepartment, ServiceGroup, PurchaseGroup, Member, 
    PurchasePrice, MemberStat, TotalStat, PurchaseGroupAdUnit, ExchangeRate, MonthlyAdjustment
)
from ..platforms import get_platform_display_name, PLATFORM_ORDER

logger = logging.getLogger(__name__)

@login_required
def main_view(request):
    # 시작일과 종료일 파라미터 처리
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if not start_date_str or not end_date_str:
        # 기본값: 이번 달 1일부터 오늘까지
        today = datetime.now().date()
        start_date = date(today.year, today.month, 1)
        end_date = today
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            # 파싱 실패 시 기본값 사용
            today = datetime.now().date()
            start_date = date(today.year, today.month, 1)
            end_date = today
    
    # 시작일이 종료일보다 늦으면 종료일을 시작일로 설정
    if start_date > end_date:
        end_date = start_date

    # 실제 매출 데이터 조회 (reports.py와 동일한 로직 사용)
    from stats.models import AdStats, OtherRevenue
    from .reports import (
        get_platform_list, get_exchange_rates, get_ad_unit_member_mapping,
        calculate_platform_revenue_by_member_level, calculate_naver_powerlink_revenue,
        process_all_sections, get_other_revenue_data
    )
    
    # 1. 플랫폼 리스트 및 기본 설정
    platform_list = get_platform_list(request.user)
    
    # 2. 환율 및 멤버 매핑 데이터
    exchange_rates = get_exchange_rates(request.user, start_date, end_date)
    ad_unit_member_map = get_ad_unit_member_mapping(request.user)
    
    # 날짜 리스트 생성
    date_list = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
    
    # 3. 구글/네이버 수익을 Member level별로 분류
    publisher_google_naver_data, partners_google_naver_data = calculate_platform_revenue_by_member_level(
        request.user, start_date, end_date, ad_unit_member_map, exchange_rates
    )
    
    # 4. 네이버 파워링크 수익 계산
    publisher_google_naver_data, partners_google_naver_data = calculate_naver_powerlink_revenue(
        request.user, start_date, end_date, publisher_google_naver_data, partners_google_naver_data
    )
    
    # 5. 기타수익 데이터 조회
    other_revenue_data = get_other_revenue_data(request.user, start_date, end_date)
    
    # 6. 일일 개별 플랫폼 수익 계산 (reports.py와 동일한 방식)
    from stats.views.reports import calculate_daily_platform_revenue, get_naver_powerlink_detail_data
    naver_powerlink_detail = get_naver_powerlink_detail_data(request.user, start_date, end_date)
    daily_data = calculate_daily_platform_revenue(
        date_list, publisher_google_naver_data, partners_google_naver_data, 
        {}, naver_powerlink_detail, request.user, platform_list
    )
    
    # 7. 모든 섹션 처리 (daily_data 전달)
    section_results = process_all_sections(
        request.user, platform_list, start_date, end_date, 
        publisher_google_naver_data, partners_google_naver_data, other_revenue_data, daily_data
    )
    
    # 8. 일별 매출 데이터 구성 (reports.py와 동일한 방식)
    sales_data = {}
    
    for current_date in date_list:
        sales_data[current_date] = {
            'publisher': 0,
            'partners': 0,
            'stamply': 0,
            'total': 0
        }
        
        # 퍼블리셔 수익 (개별 플랫폼 + 구글/네이버 + 기타수익)
        if current_date in section_results['publisher']['data']:
            # 개별 플랫폼 수익 (구글/네이버 제외)
            for key, value in section_results['publisher']['data'][current_date].items():
                platform, alias = key.split('|', 1)
                if platform not in ['google', 'naver']:
                    sales_data[current_date]['publisher'] += int(value)
            
            # 구글/네이버 수익 추가
            if current_date in daily_data['publisher_daily_google']:
                sales_data[current_date]['publisher'] += int(daily_data['publisher_daily_google'][current_date])
            if current_date in daily_data['publisher_daily_naver']:
                sales_data[current_date]['publisher'] += int(daily_data['publisher_daily_naver'][current_date])
        
        # 파트너스 수익 (개별 플랫폼 + 구글/네이버 + 기타수익)
        if current_date in section_results['partners']['data']:
            # 개별 플랫폼 수익 (구글/네이버 제외)
            for key, value in section_results['partners']['data'][current_date].items():
                platform, alias = key.split('|', 1)
                if platform not in ['google', 'naver']:
                    sales_data[current_date]['partners'] += int(value)
            
            # 구글/네이버 수익 추가
            if current_date in daily_data['partners_daily_google']:
                sales_data[current_date]['partners'] += int(daily_data['partners_daily_google'][current_date])
            if current_date in daily_data['partners_daily_naver']:
                sales_data[current_date]['partners'] += int(daily_data['partners_daily_naver'][current_date])
        
        # 스탬플리 수익 (section_results에서 가져오기)
        if current_date in section_results['stamply']['data']:
            sales_data[current_date]['stamply'] += int(sum(section_results['stamply']['data'][current_date].values()))
        
        # 기타수익 추가
        if current_date in other_revenue_data:
            for section, amount in other_revenue_data[current_date].items():
                if section == 'publisher':
                    sales_data[current_date]['publisher'] += int(amount)
                elif section == 'partners':
                    sales_data[current_date]['partners'] += int(amount)
                elif section == 'stamply':
                    sales_data[current_date]['stamply'] += int(amount)
        
        # 총합 계산
        sales_data[current_date]['total'] = (
            sales_data[current_date]['publisher'] + 
            sales_data[current_date]['partners'] + 
            sales_data[current_date]['stamply']
        )
    
    # 매입 비용 데이터 조회
    purchase_data = {}
    for current_date in date_list:
        purchase_data[current_date] = {
            'publisher': 0,
            'partners': 0,
            'stamply': 0,
            'total': 0
        }
        
        # 기타수익에서 매입 비용 추출
        if current_date in other_revenue_data:
            for section, amount in other_revenue_data[current_date].items():
                if section.endswith('_cost'):
                    if section == 'publisher_cost':
                        purchase_data[current_date]['publisher'] += int(amount)
                    elif section == 'partners_cost':
                        purchase_data[current_date]['partners'] += int(amount)
                    elif section == 'stamply_cost':
                        purchase_data[current_date]['stamply'] += int(amount)
                    
                    purchase_data[current_date]['total'] += int(amount)
    
    # 날짜별로 정렬된 매출 데이터 구성
    sales_rows = []
    for current_date in [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]:
        if current_date in sales_data:
            sales_rows.append({
                'date': current_date,
                'total': sales_data[current_date]['total'],
                'publisher': sales_data[current_date]['publisher'],
                'partners': sales_data[current_date]['partners'],
                'stamply': sales_data[current_date]['stamply']
            })
        else:
            sales_rows.append({
                'date': current_date,
                'total': 0,
                'publisher': 0,
                'partners': 0,
                'stamply': 0
            })
    
    # 날짜별로 정렬된 매입 데이터 구성
    purchase_rows = []
    for current_date in [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]:
        if current_date in purchase_data:
            purchase_rows.append({
                'date': current_date,
                'total': purchase_data[current_date]['total'],
                'publisher': purchase_data[current_date]['publisher'],
                'partners': purchase_data[current_date]['partners'],
                'stamply': purchase_data[current_date]['stamply'],
                'stamply_note': None
            })
        else:
            purchase_rows.append({
                'date': current_date,
                'total': 0,
                'publisher': 0,
                'partners': 0,
                'stamply': 0,
                'stamply_note': None
            })
    
    # 합계 계산
    sales_total = {
        'total': sum(r['total'] for r in sales_rows),
        'publisher': sum(r['publisher'] for r in sales_rows),
        'partners': sum(r['partners'] for r in sales_rows),
        'stamply': sum(r['stamply'] for r in sales_rows)
    }
    
    purchase_total = {
        'total': sum(r['total'] for r in purchase_rows),
        'publisher': sum(r['publisher'] for r in purchase_rows),
        'partners': sum(r['partners'] for r in purchase_rows),
        'stamply': sum(r['stamply'] for r in purchase_rows)
    }

    # 손익 계산 (매출 - 매입)
    profit_rows = []
    for s, p in zip(sales_rows, purchase_rows):
        profit_rows.append({
            'date': s['date'],
            'total': s['total'] - p['total'],
            'publisher': s['publisher'] - p['publisher'],
            'partners': s['partners'] - p['partners'],
            'stamply': s['stamply'] - p['stamply']
        })
    
    profit_total = {
        'total': sum(r['total'] for r in profit_rows),
        'publisher': sum(r['publisher'] for r in profit_rows),
        'partners': sum(r['partners'] for r in profit_rows),
        'stamply': sum(r['stamply'] for r in profit_rows)
    }

    # 전월대비 계산 (현재 조회 기간과 동일한 길이의 전월 기간)
    period_days = (end_date - start_date).days + 1
    
    # 전월 시작일 계산
    if start_date.month == 1:
        prev_start_date = date(start_date.year - 1, 12, start_date.day)
    else:
        prev_start_date = date(start_date.year, start_date.month - 1, start_date.day)
    
    # 전월 종료일 계산
    prev_end_date = prev_start_date + timedelta(days=period_days - 1)
    
    # 전월 데이터 조회 (reports.py와 동일한 로직 사용)
    prev_exchange_rates = get_exchange_rates(request.user, prev_start_date, prev_end_date)
    prev_ad_unit_member_map = get_ad_unit_member_mapping(request.user)
    
    # 전월 구글/네이버 수익을 Member level별로 분류
    prev_publisher_google_naver_data, prev_partners_google_naver_data = calculate_platform_revenue_by_member_level(
        request.user, prev_start_date, prev_end_date, prev_ad_unit_member_map, prev_exchange_rates
    )
    
    # 전월 네이버 파워링크 수익 계산
    prev_publisher_google_naver_data, prev_partners_google_naver_data = calculate_naver_powerlink_revenue(
        request.user, prev_start_date, prev_end_date, prev_publisher_google_naver_data, prev_partners_google_naver_data
    )
    
    # 전월 기타수익 데이터 조회
    prev_other_revenue_data = get_other_revenue_data(request.user, prev_start_date, prev_end_date)
    
    # 전월 일일 개별 플랫폼 수익 계산
    prev_naver_powerlink_detail = get_naver_powerlink_detail_data(request.user, prev_start_date, prev_end_date)
    prev_daily_data = calculate_daily_platform_revenue(
        [prev_start_date + timedelta(days=i) for i in range(period_days)], 
        prev_publisher_google_naver_data, prev_partners_google_naver_data, 
        {}, prev_naver_powerlink_detail, request.user, platform_list
    )
    
    # 전월 모든 섹션 처리
    prev_section_results = process_all_sections(
        request.user, platform_list, prev_start_date, prev_end_date, 
        prev_publisher_google_naver_data, prev_partners_google_naver_data, prev_other_revenue_data, prev_daily_data
    )
    
    # 전월 네이버 파워링크 수익 계산
    prev_publisher_google_naver_data, prev_partners_google_naver_data = calculate_naver_powerlink_revenue(
        request.user, prev_start_date, prev_end_date, prev_publisher_google_naver_data, prev_partners_google_naver_data
    )
    
    # 전월 기타수익 데이터 조회
    prev_other_revenue_data = get_other_revenue_data(request.user, prev_start_date, prev_end_date)
    
    # 전월 모든 섹션 처리
    prev_section_results = process_all_sections(
        request.user, platform_list, prev_start_date, prev_end_date, 
        prev_publisher_google_naver_data, prev_partners_google_naver_data, prev_other_revenue_data
    )
    
    # 전월 매출 합계 계산 (reports.py와 동일한 방식)
    prev_sales_total = {'publisher': 0, 'partners': 0, 'stamply': 0, 'total': 0}
    
    # 전월 일별 매출 데이터 계산
    prev_date_list = [prev_start_date + timedelta(days=i) for i in range(period_days)]
    for current_date in prev_date_list:
        # 퍼블리셔 수익 (개별 플랫폼 + 구글/네이버 + 기타수익)
        if current_date in prev_section_results['publisher']['data']:
            # 개별 플랫폼 수익 (구글/네이버 제외)
            for key, value in prev_section_results['publisher']['data'][current_date].items():
                platform, alias = key.split('|', 1)
                if platform not in ['google', 'naver']:
                    prev_sales_total['publisher'] += int(value)
            
            # 구글/네이버 수익 추가
            if current_date in prev_daily_data['publisher_daily_google']:
                prev_sales_total['publisher'] += int(prev_daily_data['publisher_daily_google'][current_date])
            if current_date in prev_daily_data['publisher_daily_naver']:
                prev_sales_total['publisher'] += int(prev_daily_data['publisher_daily_naver'][current_date])
        
        # 파트너스 수익 (개별 플랫폼 + 구글/네이버 + 기타수익)
        if current_date in prev_section_results['partners']['data']:
            # 개별 플랫폼 수익 (구글/네이버 제외)
            for key, value in prev_section_results['partners']['data'][current_date].items():
                platform, alias = key.split('|', 1)
                if platform not in ['google', 'naver']:
                    prev_sales_total['partners'] += int(value)
            
            # 구글/네이버 수익 추가
            if current_date in prev_daily_data['partners_daily_google']:
                prev_sales_total['partners'] += int(prev_daily_data['partners_daily_google'][current_date])
            if current_date in prev_daily_data['partners_daily_naver']:
                prev_sales_total['partners'] += int(prev_daily_data['partners_daily_naver'][current_date])
        
        # 스탬플리 수익
        if current_date in prev_section_results['stamply']['data']:
            prev_sales_total['stamply'] += int(sum(prev_section_results['stamply']['data'][current_date].values()))
        
        # 기타수익 추가
        if current_date in prev_other_revenue_data:
            for section, amount in prev_other_revenue_data[current_date].items():
                if section == 'publisher':
                    prev_sales_total['publisher'] += int(amount)
                elif section == 'partners':
                    prev_sales_total['partners'] += int(amount)
                elif section == 'stamply':
                    prev_sales_total['stamply'] += int(amount)
    
    # 전월 총합 계산
    prev_sales_total['total'] = (
        prev_sales_total['publisher'] + 
        prev_sales_total['partners'] + 
        prev_sales_total['stamply']
    )
    
    # 전월 매입 합계 계산
    prev_purchase_total = {'publisher': 0, 'partners': 0, 'stamply': 0, 'total': 0}
    for date_data in prev_other_revenue_data.values():
        for section, amount in date_data.items():
            if section.endswith('_cost'):
                if section == 'publisher_cost':
                    prev_purchase_total['publisher'] += int(amount)
                elif section == 'partners_cost':
                    prev_purchase_total['partners'] += int(amount)
                elif section == 'stamply_cost':
                    prev_purchase_total['stamply'] += int(amount)
                
                prev_purchase_total['total'] += int(amount)
    
    # 전월대비 증감 계산
    sales_mom = {
        'total': sales_total['total'] - prev_sales_total['total'],
        'publisher': sales_total['publisher'] - prev_sales_total['publisher'],
        'partners': sales_total['partners'] - prev_sales_total['partners'],
        'stamply': sales_total['stamply'] - prev_sales_total['stamply']
    }
    
    purchase_mom = {
        'total': purchase_total['total'] - prev_purchase_total['total'],
        'publisher': purchase_total['publisher'] - prev_purchase_total['publisher'],
        'partners': purchase_total['partners'] - prev_purchase_total['partners'],
        'stamply': purchase_total['stamply'] - prev_purchase_total['stamply']
    }
    
    profit_mom = {
        'total': profit_total['total'] - (prev_sales_total['total'] - prev_purchase_total['total']),
        'publisher': profit_total['publisher'] - (prev_sales_total['publisher'] - prev_purchase_total['publisher']),
        'partners': profit_total['partners'] - (prev_sales_total['partners'] - prev_purchase_total['partners']),
        'stamply': profit_total['stamply'] - (prev_sales_total['stamply'] - prev_purchase_total['stamply'])
    }

    context = {
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'sales_rows': sales_rows,
        'sales_total': sales_total,
        'purchase_rows': purchase_rows,
        'purchase_total': purchase_total,
        'profit_rows': profit_rows,
        'profit_total': profit_total,
        'sales_mom': sales_mom,
        'purchase_mom': purchase_mom,
        'profit_mom': profit_mom,
    }
    return render(request, 'home.html', context)

@login_required
@require_POST
def save_monthly_adjustment(request):
    """월별 매출/매입 조정 저장 API"""
    try:
        data = json.loads(request.body)
        year_month_str = data.get('year_month')
        adjustment_type = data.get('adjustment_type')
        sales_type = data.get('sales_type')
        adjustment_amount = data.get('adjustment_amount')
        adjustment_note = data.get('adjustment_note')
        tax_deadline = data.get('tax_deadline')
        
        if not year_month_str or not adjustment_type or not sales_type:
            return JsonResponse({'success': False, 'error': '필수 필드가 누락되었습니다.'})
        
        # 날짜 파싱
        try:
            year_month = datetime.strptime(year_month_str, '%Y-%m').date()
            year_month = year_month.replace(day=1)  # 월의 첫날로 설정
        except ValueError:
            return JsonResponse({'success': False, 'error': '올바른 날짜 형식이 아닙니다.'})
        
        # 기존 데이터 조회
        adjustment, created = MonthlyAdjustment.objects.get_or_create(
            user=request.user,
            year_month=year_month,
            adjustment_type=adjustment_type,
            sales_type=sales_type,
            defaults={
                'adjustment_amount': Decimal('0'),
                'adjustment_note': '',
                'tax_deadline': None
            }
        )
        
        # 업데이트할 필드들만 처리
        if adjustment_amount is not None:
            try:
                amount_decimal = Decimal(str(adjustment_amount))
                adjustment.adjustment_amount = amount_decimal
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': '올바른 금액이 아닙니다.'})
        
        if adjustment_note is not None:
            adjustment.adjustment_note = adjustment_note
        
        if adjustment_type == 'purchase' and tax_deadline is not None:
            try:
                tax_deadline_date = datetime.strptime(tax_deadline, '%Y-%m-%d').date()
                adjustment.tax_deadline = tax_deadline_date
            except ValueError:
                return JsonResponse({'success': False, 'error': '올바른 세금계산서 수취기한 형식이 아닙니다.'})
        
        adjustment.save()
        
        if created:
            return JsonResponse({'success': True, 'action': 'created'})
        else:
            return JsonResponse({'success': True, 'action': 'updated'})
                
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '올바른 JSON 형식이 아닙니다.'})
    except Exception as e:
        import traceback
        print(f"월별 조정 저장 중 오류: {str(e)}")
        print(f"상세 오류: {traceback.format_exc()}")
        return JsonResponse({'success': False, 'error': f'저장 중 오류가 발생했습니다: {str(e)}'}) 