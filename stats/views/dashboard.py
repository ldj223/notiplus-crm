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

logger = logging.getLogger(__name__)

@login_required
def dashboard_view(request):
    """대시보드"""
    credentials = PlatformCredential.objects.filter(user=request.user)

    platform_aliases_grouped = {}
    credential_colors = {}
    last_fetched_times = {}

    for cred in credentials:
        key = f"{cred.platform}:{cred.alias or 'default'}"
        label = cred.alias or "(기본)"
        platform_aliases_grouped.setdefault(cred.platform, []).append(label)
        credential_colors[key] = cred.color or "#999999"

        # 마지막 저장 시간 설정
        if cred.platform == "adpost":
            last_fetched_times[cred.alias] = cred.last_fetched_at
        else:
            if cred.platform not in last_fetched_times:
                last_fetched_times[cred.platform] = cred.last_fetched_at
            else:
                current = last_fetched_times[cred.platform]
                if cred.last_fetched_at and (not current or cred.last_fetched_at > current):
                    last_fetched_times[cred.platform] = cred.last_fetched_at

    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    
    stats = AdStats.objects.filter(
        user=request.user,
        date__range=[start_date, end_date]
    ).values("date", "platform", "alias").annotate(
        earnings=Sum("earnings"),
        clicks=Sum("clicks"),
        impressions=Sum("impressions"),
        order_count=Sum("order_count"),
        total_amount=Sum("total_amount")
    ).order_by("date")

    dates = []
    earnings_data = []
    clicks_data = []
    order_count_data = []
    total_amount_data = []

    for stat in stats:
        dates.append(stat["date"].strftime("%Y-%m-%d"))
        earnings_data.append(float(stat["earnings"] or 0))
        clicks_data.append(int(stat["clicks"] or 0))
        order_count_data.append(int(stat["order_count"] or 0))
        total_amount_data.append(float(stat["total_amount"] or 0))

    return render(request, "chart_template.html", {
        "platform_aliases_grouped": platform_aliases_grouped,
        "credential_colors": credential_colors,
        "last_fetched_times": last_fetched_times,
        "dates": dates,
        "earnings_data": earnings_data,
        "clicks_data": clicks_data,
        "order_count_data": order_count_data,
        "total_amount_data": total_amount_data,
        "daily_stats": stats
    }) 