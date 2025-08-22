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
    PurchasePrice, MemberStat, TotalStat, PurchaseGroupAdUnit, ExchangeRate
)
from ..platforms import get_platform_display_name, PLATFORM_ORDER
from .sales import generate_sales_context

logger = logging.getLogger(__name__)

@login_required
def settlement_department_list(request):
    """정산주관부서 목록"""
    departments = SettlementDepartment.objects.filter(user=request.user).order_by('name')
    return render(request, 'settlement_department_list.html', {'departments': departments})

@login_required
def settlement_department_create(request):
    """정산주관부서 생성"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            # 현재 사용자 내에서 중복 체크
            if SettlementDepartment.objects.filter(user=request.user, name=name).exists():
                return JsonResponse({'success': False, 'message': '이미 존재하는 부서명입니다.'})
            else:
                department = SettlementDepartment.objects.create(user=request.user, name=name)
                return JsonResponse({
                    'success': True, 
                    'message': f'부서 "{name}"이(가) 생성되었습니다.',
                    'department': {
                        'id': department.id,
                        'name': department.name
                    }
                })
        else:
            return JsonResponse({'success': False, 'message': '부서명을 입력해주세요.'})
    
    return render(request, 'settlement_department_form.html')

@login_required
def settlement_department_edit(request, pk):
    """정산주관부서 수정"""
    try:
        department = SettlementDepartment.objects.get(pk=pk, user=request.user)
    except SettlementDepartment.DoesNotExist:
        return JsonResponse({'success': False, 'message': '부서를 찾을 수 없습니다.'})
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            # 현재 사용자 내에서 중복 체크 (자신 제외)
            if SettlementDepartment.objects.filter(user=request.user, name=name).exclude(pk=pk).exists():
                return JsonResponse({'success': False, 'message': '이미 존재하는 부서명입니다.'})
            else:
                department.name = name
                department.save()
                return JsonResponse({
                    'success': True, 
                    'message': f'부서명이 "{name}"으로 수정되었습니다.',
                    'department': {
                        'id': department.id,
                        'name': department.name
                    }
                })
        else:
            return JsonResponse({'success': False, 'message': '부서명을 입력해주세요.'})
    
    return render(request, 'settlement_department_form.html', {'department': department})

@login_required
def settlement_department_delete(request, pk):
    """정산주관부서 삭제"""
    try:
        department = SettlementDepartment.objects.get(pk=pk, user=request.user)
        department_name = department.name
        department.delete()
        return JsonResponse({'success': True, 'message': f'부서 "{department_name}"이(가) 삭제되었습니다.'})
    except SettlementDepartment.DoesNotExist:
        return JsonResponse({'success': False, 'message': '부서를 찾을 수 없습니다.'})

@login_required
def sales_excel_download_view(request):
    """매출 현황 데이터를 엑셀 파일로 다운로드"""
    year = request.GET.get('year', datetime.now().year)
    try:
        year = int(year)
    except (ValueError, TypeError):
        year = datetime.now().year

    # 원본 MonthlySales 데이터 조회
    from stats.models import MonthlySales, ServiceGroup, SettlementDepartment
    from django.db.models import Sum
    from datetime import date
    
    monthly_data = MonthlySales.objects.filter(
        user=request.user,
        year_month__year=year
    ).order_by('year_month', 'company_name', 'service_name')
    
    # 부서 정보 조회
    departments = SettlementDepartment.objects.filter(user=request.user)
    departments_map = {d.id: d.name for d in departments}
    
    # 그룹 정보 조회
    groups = ServiceGroup.objects.filter(user=request.user)
    groups_map = {g.group_code: g for g in groups}

    # 엑셀 워크북 생성
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = f"{year}년 매출 현황"

    # --- 헤더 생성 ---
    header = [
        '구분', '유형', '담당부서', '정산기간', '업체명', '서비스명', '서비스코드'
    ]
    months = list(range(1, 13))
    for month in months:
        header.extend([f'{month}월', '증감'])
    header.append('총합')
    sheet.append(header)

    # --- 그룹별 데이터 추가 ---
    for group in groups:
        group_sales = monthly_data.filter(group=group)
        if not group_sales.exists():
            continue
            
        # 그룹의 월별 데이터 계산
        monthly_sales = {}
        monthly_changes = {}
        total_amount = 0
        
        for month in months:
            month_start = date(year, month, 1)
            month_amount = group_sales.filter(year_month=month_start).aggregate(
                total=Sum('amount')
            )['total'] or 0
            monthly_sales[month] = month_amount
            total_amount += month_amount
            
            # 증감 계산
            if month == 1:
                monthly_changes[month] = month_amount
            else:
                prev_month_amount = monthly_sales.get(month - 1, 0)
                monthly_changes[month] = month_amount - prev_month_amount
        
        # 그룹 행 추가
        department_name = departments_map.get(group.settlement_department.id if group.settlement_department else None, '')
        row = [
            '그룹',
            group.issue_type or '',
            department_name,
            group.settlement_timing or '',
            group.company_name,
            group.service_name,
            group.group_code,
        ]
        for month in months:
            row.append(monthly_sales.get(month, 0))
            row.append(monthly_changes.get(month, 0))
        row.append(total_amount)
        sheet.append(row)

    # --- 개별 데이터 추가 (그룹에 속하지 않은 항목들) ---
    ungrouped_sales = monthly_data.filter(group__isnull=True)
    service_groups = {}
    for sale in ungrouped_sales:
        service_code = sale.service_code
        if service_code not in service_groups:
            service_groups[service_code] = []
        service_groups[service_code].append(sale)
    
    for service_code, sales_list in service_groups.items():
        # 개별 항목의 월별 데이터 계산
        monthly_sales = {}
        monthly_changes = {}
        total_amount = 0
        
        for month in months:
            month_start = date(year, month, 1)
            month_amount = sum(sale.amount for sale in sales_list if sale.year_month == month_start)
            monthly_sales[month] = month_amount
            total_amount += month_amount
            
            # 증감 계산
            if month == 1:
                monthly_changes[month] = month_amount
            else:
                prev_month_amount = monthly_sales.get(month - 1, 0)
                monthly_changes[month] = month_amount - prev_month_amount
        
        # 개별 항목 행 추가
        first_sale = sales_list[0]
        row = [
            '개별',
            '',  # 개별 항목은 발행유형 없음
            '',  # 개별 항목은 담당부서 없음
            '',  # 개별 항목은 정산기간 없음
            first_sale.company_name,
            first_sale.service_name,
            service_code,
        ]
        for month in months:
            row.append(monthly_sales.get(month, 0))
            row.append(monthly_changes.get(month, 0))
        row.append(total_amount)
        sheet.append(row)

    # --- 요약 행 추가 ---
    sheet.append([]) # Spacer
    
    # 월별 매출/매입 계산
    revenue_monthly = {m: 0 for m in months}
    purchase_monthly = {m: 0 for m in months}
    
    for month in months:
        month_start = date(year, month, 1)
        
        # 매출 데이터 (양수)
        revenue = monthly_data.filter(
            year_month=month_start,
            amount__gt=0
        ).aggregate(
            total_amount=Sum('amount')
        )['total_amount'] or 0
        
        # 매입 데이터 (음수 절대값)
        purchase = monthly_data.filter(
            year_month=month_start,
            amount__lt=0
        ).aggregate(
            total_amount=Sum('amount')
        )['total_amount'] or 0
        
        revenue_monthly[month] = revenue
        purchase_monthly[month] = abs(purchase)
    
    # 총합 계산
    total_revenue = sum(revenue_monthly.values())
    total_purchase = sum(purchase_monthly.values())
    total_gross_profit = total_revenue - total_purchase
    
    # 월별 손익
    sheet.append(['--- 월별 손익 ---'])
    
    # 매출
    row = ['매출', '', '', '', '', '', '']
    for month in months:
        row.append(revenue_monthly.get(month, 0))
        row.append('')  # 증감 없음
    row.append(total_revenue)
    sheet.append(row)
    
    # 매입
    row = ['매입', '', '', '', '', '', '']
    for month in months:
        row.append(purchase_monthly.get(month, 0))
        row.append('')  # 증감 없음
    row.append(total_purchase)
    sheet.append(row)
    
    # 매출총이익
    row = ['매출총이익', '', '', '', '', '', '']
    for month in months:
        gross_profit = revenue_monthly.get(month, 0) - purchase_monthly.get(month, 0)
        row.append(gross_profit)
        row.append('')  # 증감 없음
    row.append(total_gross_profit)
    sheet.append(row)

    # 이익율
    total_profit_rate = (total_gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    row = ['이익율(%)', '', '', '', '', '', '']
    for month in months:
        revenue = revenue_monthly.get(month, 0)
        if revenue > 0:
            profit_rate = ((revenue_monthly.get(month, 0) - purchase_monthly.get(month, 0)) / revenue) * 100
        else:
            profit_rate = 0
        row.append(profit_rate)
        row.append('')  # 증감 없음
    row.append(total_profit_rate)
    sheet.append(row)

    # --- HttpResponse로 반환 ---
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{year}년_매출_현황.xlsx"'
    workbook.save(response)

    return response

# ===== 매입 그룹 관리 =====
@login_required
def purchase_group_detail_api(request, request_key):
    """
    PurchaseGroup 정보를 JSON으로 반환하는 API
    """
    logger.info(f"API: Attempting to find Member with request_key: '{request_key}'")
    try:
        member = Member.objects.get(request_key=request_key.strip())
        group = PurchaseGroup.objects.filter(member=member, is_active=True).first()
        
        if group:
            data = {
                'id': group.id,
                'group_name': group.group_name,
                'company_name': group.company_name,
                'service_name': group.service_name,
                'unit_price': group.default_unit_price,
                'unit_type': group.default_unit_type,
            }
        else:
            data = {'error': '해당 퍼블리셔에 대한 활성 매입 그룹을 찾을 수 없습니다.'}
        
        return JsonResponse(data)
    except Member.DoesNotExist:
        logger.error(f"API: Member not found with request_key: '{request_key}'")
        return JsonResponse({'error': f"API: Member not found with request_key: '{request_key}'"}, status=404)
    except Exception as e:
        logger.error(f"API: An exception occurred: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def purchase_group_batch_update(request):
    logger.info("Batch update requested.")
    try:
        data = json.loads(request.body)
        updates = data.get('updates', [])
        year = data.get('year')

        if not year:
            logger.error("Batch update failed: Year is required.")
            return JsonResponse({'error': 'Year is required.'}, status=400)

        for item in updates:
            request_key = item.get('request_key')
            logger.info(f"Batch update processing item with request_key: '{request_key}'")
            
            if not request_key:
                logger.warning("Batch update: skipping item with no request_key.")
                continue

            try:
                member = Member.objects.get(request_key=request_key.strip())
            except Member.DoesNotExist:
                logger.error(f"Batch update: Member not found with request_key: '{request_key}'")
                return JsonResponse({'error': f"'{request_key}'에 해당하는 Member를 찾을 수 없습니다."}, status=400)
            
            has_group = item.get('has_group')
            service_name = item.get('service_name')
            company_name = item.get('company_name')
            unit_price = Decimal(item.get('unit_price', '0'))
            unit_type = item.get('unit_type', 'percent')

            if has_group:
                group = PurchaseGroup.objects.filter(member=member, is_active=True).first()
                if group:
                    group.service_name = service_name
                    group.company_name = company_name
                    group.default_unit_price = unit_price
                    group.default_unit_type = unit_type
                    group.group_name = service_name 
                    group.save()
                    logger.info(f"Updated group for request_key: '{request_key}'")
            else:
                new_group = PurchaseGroup(
                    member=member,
                    group_name=service_name,
                    company_name=company_name,
                    service_name=service_name,
                    default_unit_price=unit_price,
                    default_unit_type=unit_type,
                    is_active=True
                )
                new_group.full_clean()
                new_group.save()
                logger.info(f"Created new group for request_key: '{request_key}'")
                
        return JsonResponse({'success': True})
    except json.JSONDecodeError:
        logger.error("Batch update failed: Invalid JSON.")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValidationError as e:
        logger.error(f"Batch update failed: Validation failed: {e}")
        return JsonResponse({'error': f'Validation failed: {e}'}, status=400)
    except Exception as e:
        logger.error(f"Batch update failed: An exception occurred: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def purchase_group_delete_api(request, request_key):
    """
    request_key로 매입 그룹 삭제 API
    """
    try:
        member = Member.objects.get(request_key=request_key.strip())
        group = PurchaseGroup.objects.filter(member=member, is_active=True).first()
        
        if group:
            group_name = group.group_name
            group.delete()
            return JsonResponse({'success': True, 'message': f'그룹 "{group_name}"이 삭제되었습니다.'})
        else:
            return JsonResponse({'success': False, 'error': '삭제할 그룹을 찾을 수 없습니다.'})
            
    except Member.DoesNotExist:
        return JsonResponse({'success': False, 'error': f"'{request_key}'에 해당하는 Member를 찾을 수 없습니다."})
    except Exception as e:
        logger.error(f"Delete API error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def ad_units_management_view(request):
    """광고 단위 매핑 관리 메인 페이지 - 플랫폼 선택 및 매핑"""
    # 사용자의 PurchaseGroup 조회
    purchase_groups = PurchaseGroup.objects.filter(
        user=request.user,
        is_active=True
    ).order_by('company_name')
    
    # 각 PurchaseGroup의 현재 매핑된 ad_unit_id 조회 (플랫폼별)
    group_mappings = {}
    for group in purchase_groups:
        # 여기서는 기본적으로 빈 리스트를 제공하고,
        # API 호출을 통해 플랫폼별 데이터를 가져와 클라이언트에서 처리
        group_mappings[group.id] = []
    
    context = {
        'purchase_groups': purchase_groups,
        'group_mappings': group_mappings,
    }
    return render(request, 'ad_units_management.html', context)

@login_required
def exchange_rate_list(request):
    """환율 목록 뷰"""
    exchange_rates = ExchangeRate.objects.filter(
        user=request.user
    ).order_by('-year_month')
    
    context = {
        'exchange_rates': exchange_rates,
    }
    return render(request, 'exchange_rate_list.html', context)

@login_required
def exchange_rate_create(request):
    """환율 생성 뷰"""
    if request.method == 'POST':
        year_month = request.POST.get('year_month')
        usd_to_krw = request.POST.get('usd_to_krw')
        
        if year_month and usd_to_krw:
            try:
                # YYYY-MM 형식을 YYYY-MM-01로 변환
                year_month_date = datetime.strptime(year_month + '-01', '%Y-%m-%d').date()
                usd_to_krw_decimal = Decimal(usd_to_krw)
                
                # 중복 체크
                existing = ExchangeRate.objects.filter(
                    user=request.user,
                    year_month=year_month_date
                ).first()
                
                if existing:
                    messages.error(request, '해당 월의 환율이 이미 존재합니다.')
                else:
                    ExchangeRate.objects.create(
                        user=request.user,
                        year_month=year_month_date,
                        usd_to_krw=usd_to_krw_decimal
                    )
                    messages.success(request, '환율이 성공적으로 등록되었습니다.')
                    return redirect('exchange_rate_list')
                    
            except (ValueError, TypeError):
                messages.error(request, '올바른 값을 입력해주세요.')
        else:
            messages.error(request, '모든 필드를 입력해주세요.')
    
    context = {
        'edit_mode': False,
    }
    return render(request, 'exchange_rate_form.html', context)

@login_required
def exchange_rate_edit(request, pk):
    """환율 수정 뷰"""
    exchange_rate = get_object_or_404(ExchangeRate, pk=pk, user=request.user)
    
    if request.method == 'POST':
        year_month = request.POST.get('year_month')
        usd_to_krw = request.POST.get('usd_to_krw')
        
        if year_month and usd_to_krw:
            try:
                year_month_date = datetime.strptime(year_month + '-01', '%Y-%m-%d').date()
                usd_to_krw_decimal = Decimal(usd_to_krw)
                
                # 중복 체크 (자신 제외)
                existing = ExchangeRate.objects.filter(
                    user=request.user,
                    year_month=year_month_date
                ).exclude(pk=pk).first()
                
                if existing:
                    messages.error(request, '해당 월의 환율이 이미 존재합니다.')
                else:
                    exchange_rate.year_month = year_month_date
                    exchange_rate.usd_to_krw = usd_to_krw_decimal
                    exchange_rate.save()
                    messages.success(request, '환율이 성공적으로 수정되었습니다.')
                    return redirect('exchange_rate_list')
                    
            except (ValueError, TypeError):
                messages.error(request, '올바른 값을 입력해주세요.')
        else:
            messages.error(request, '모든 필드를 입력해주세요.')
    
    context = {
        'exchange_rate': exchange_rate,
        'edit_mode': True,
    }
    return render(request, 'exchange_rate_form.html', context)

@login_required
def exchange_rate_delete(request, pk):
    """환율 삭제 뷰"""
    exchange_rate = get_object_or_404(ExchangeRate, pk=pk, user=request.user)
    
    if request.method == 'POST':
        exchange_rate.delete()
        messages.success(request, '환율이 성공적으로 삭제되었습니다.')
        return redirect('exchange_rate_list')
    
    context = {
        'exchange_rate': exchange_rate,
    }
    return render(request, 'exchange_rate_confirm_delete.html', context)

@login_required
def ad_units_data_api(request, platform):
    """광고 단위 데이터를 JSON으로 반환하는 API"""
    try:
        # 사용 가능한 광고 단위 목록 조회
        available_ad_units = AdStats.objects.filter(
            user=request.user,
            platform=platform
        ).values('ad_unit_id', 'ad_unit_name', 'alias').distinct().order_by('ad_unit_name')
        
        # 사용자의 PurchaseGroup 조회
        purchase_groups = PurchaseGroup.objects.filter(
            user=request.user,
            is_active=True
        ).order_by('company_name')
        
        # 각 PurchaseGroup의 현재 매핑된 ad_unit_id 조회
        group_mappings = {}
        for group in purchase_groups:
            mappings = PurchaseGroupAdUnit.objects.filter(
                purchase_group=group,
                platform=platform,
                is_active=True
            ).values_list('ad_unit_id', flat=True)
            group_mappings[group.id] = list(mappings)
        
        data = {
            'ad_units': list(available_ad_units),
            'group_mappings': group_mappings,
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_POST
def adsense_ad_units_api(request):
    """애드센스 광고 단위 매핑 API"""
    return _handle_ad_units_api(request, 'adsense')

@login_required
@require_POST
def admanager_ad_units_api(request):
    """애드매니저 광고 단위 매핑 API"""
    return _handle_ad_units_api(request, 'admanager')

def _handle_ad_units_api(request, platform):
    """광고 단위 매핑 공통 처리 함수"""
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        ad_unit_ids = data.get('ad_unit_ids', [])
        
        if not group_id:
            return JsonResponse({'error': 'group_id is required'}, status=400)
        
        # PurchaseGroup 조회
        try:
            group = PurchaseGroup.objects.get(id=group_id, user=request.user)
        except PurchaseGroup.DoesNotExist:
            return JsonResponse({'error': 'PurchaseGroup not found'}, status=404)
        
        # 기존 매핑 비활성화
        PurchaseGroupAdUnit.objects.filter(
            purchase_group=group,
            platform=platform
        ).update(is_active=False)
        
        # 새로운 매핑 생성
        for ad_unit_id in ad_unit_ids:
            if ad_unit_id:
                # ad_unit_name 조회
                ad_unit = AdStats.objects.filter(
                    user=request.user,
                    platform=platform,
                    ad_unit_id=ad_unit_id
                ).values('ad_unit_name').first()
                
                ad_unit_name = ad_unit['ad_unit_name'] if ad_unit else ad_unit_id
                
                PurchaseGroupAdUnit.objects.update_or_create(
                    purchase_group=group,
                    platform=platform,
                    ad_unit_id=ad_unit_id,
                    defaults={
                        'ad_unit_name': ad_unit_name,
                        'is_active': True
                    }
                )
        
        return JsonResponse({'success': True})
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500) 