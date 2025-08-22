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

def has_auth_changed(old_data, new_client_id, new_secret):
    """인증값 변경 여부 확인"""
    return old_data.get("client_id") != new_client_id or old_data.get("secret") != new_secret

def is_duplicate_platform_alias(user, platform, alias, exclude_pk=None):
    """플랫폼과 별칭의 중복 체크"""
    qs = PlatformCredential.objects.filter(
        user=user,
        platform=platform,
        alias=alias
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()

def render_with_error(request, form, instance, error_message):
    """에러 메시지와 함께 폼을 렌더링"""
    messages.error(request, error_message)
    return render_credential_form(request, form, instance)

def redirect_with_error(request, instance, error_message):
    """에러 메시지와 함께 리다이렉트"""
    messages.error(request, error_message)
    return redirect("edit_credential", pk=instance.pk) if instance else redirect("credential_list")

def render_credential_form(request, form, instance):
    """자격증명 폼 렌더링"""
    user_credentials = PlatformCredential.objects.filter(user=request.user)
    is_authenticated = instance and instance.platform == "adsense" and bool(instance.token)
    
    return render(request, "credential_form.html", {
        "form": form,
        "user_credentials": user_credentials,
        "edit_mode": instance is not None,
        "is_authenticated": instance and (instance.platform in ["adsense", "admanager"]) and bool(instance.token),
        "cred_pk": instance.pk if instance else None,
    })

# ===== 자격증명 관련 함수 =====
def handle_credential_update(request, instance, platform, client_id, secret, email, password):
    """자격증명 수정 처리"""
    if instance.token and has_auth_changed(instance.get_credentials(), client_id, secret):
        instance.token = None
        messages.info(request, "⚠️ API 정보가 변경되어 인증 정보가 초기화되었습니다.")
    
    if not password or password == "********":
        existing_creds = instance.get_credentials()
        password = existing_creds.get("password", "")
    
    instance.set_credentials(
        client_id=client_id,
        secret=secret,
        email=email,
        password=password
    )
    instance.save()
    messages.success(request, "✅ 계정 정보가 수정되었습니다.")
    return redirect("edit_credential", pk=instance.pk)

def handle_credential_create(request, user, platform, alias, client_id, secret, email, password):
    """자격증명 생성 처리"""
    obj = PlatformCredential.objects.create(user=user, platform=platform, alias=alias)
    obj.set_credentials(
        client_id=client_id,
        secret=secret,
        email=email,
        password=password
    )
    obj.save()
    messages.success(request, "✅ 계정이 등록되었습니다.")
    return redirect("edit_credential", pk=obj.pk)

@login_required
def credential_list_view(request):
    """자격증명 목록 뷰"""
    user_credentials = PlatformCredential.objects.filter(user=request.user)
    return render(request, "credential_list.html", {
        "user_credentials": user_credentials,
    })

def is_duplicate_adsense(user, client_id, secret, exclude_pk=None):
    """AdSense 중복 체크"""
    qs = PlatformCredential.objects.filter(user=user, platform="adsense")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    for cred in qs:
        data = cred.get_credentials()
        if data.get("client_id") == client_id and data.get("secret") == secret:
            return True
    return False

def is_duplicate_admanager(user, client_id, secret, exclude_pk=None):
    """AdManager 중복 체크"""
    qs = PlatformCredential.objects.filter(user=user, platform="admanager")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    for cred in qs:
        data = cred.get_credentials()
        if data.get("client_id") == client_id and data.get("secret") == secret:
            return True
    return False

@login_required
def credential_view(request, pk=None):
    """자격증명 관리 뷰"""
    user = request.user
    instance = PlatformCredential.objects.filter(pk=pk, user=user).first() if pk else None
    
    initial = {}
    if instance:
        credentials = instance.get_credentials()
        initial = {
            "platform": instance.platform, 
            "alias": instance.alias,
            "client_id": credentials.get("client_id", ""),
            "secret": credentials.get("secret", ""),
            "email": credentials.get("email", ""),
            "password": "********" if credentials.get("password") else "",
            "pk": instance.pk
        }

    if request.method == "POST":
        form = CredentialForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            platform = data["platform"]
            alias = data["alias"]
            new_client_id = data["client_id"]
            new_secret = data["secret"]
            email = data["email"]
            password = data["password"]

            if not alias:
                return render_with_error(request, form, instance, "별칭을 입력해주세요.")

            if platform == "adsense" and is_duplicate_adsense(user, new_client_id, new_secret, exclude_pk=instance.pk if instance else None):
                return redirect_with_error(request, instance, "⚠️ 동일한 AdSense client_id와 secret이 이미 등록되어 있습니다.")

            if is_duplicate_platform_alias(user, platform, alias, exclude_pk=instance.pk if instance else None):
                return render_with_error(request, form, instance, f"⚠️ {platform} 플랫폼의 '{alias}' 별칭이 이미 존재합니다.")

            if instance:
                return handle_credential_update(request, instance, platform, new_client_id, new_secret, email, password)
            else:
                return handle_credential_create(request, user, platform, alias, new_client_id, new_secret, email, password)
    else:
        form = CredentialForm(initial=initial)

    return render(request, "credential_form.html", {
        "form": form,
        "edit_mode": instance is not None,
        "is_authenticated": instance and (instance.platform in ["adsense", "admanager"]) and bool(instance.token),
        "cred_pk": instance.pk if instance else None,
    })

@login_required
def delete_credential(request, pk):
    """자격증명 삭제"""
    cred = get_object_or_404(PlatformCredential, pk=pk, user=request.user)
    linked_stats_count = cred.adstats.count()
    cred.delete()
    messages.success(request, f"{linked_stats_count}개의 수익 데이터와 함께 계정이 삭제되었습니다.")
    return redirect("credential_list")

# ===== 사용자 설정 관련 함수 =====
@login_required
def get_auto_fetch_setting(request):
    """자동 수집 설정 조회"""
    pref = UserPreference.objects.filter(user=request.user).first()
    return JsonResponse({"days": pref.auto_fetch_days if pref else 0})

@login_required
@require_POST
def save_auto_fetch_setting(request):
    """자동 수집 설정 저장"""
    days = request.POST.get("days", 0)
    pref, created = UserPreference.objects.get_or_create(user=request.user)
    pref.auto_fetch_days = days
    pref.save()
    return JsonResponse({"success": True})

def signup_view(request):
    """회원가입 뷰"""
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("main")
    else:
        form = SignUpForm()
    return render(request, "signup.html", {"form": form})

def logout_view(request):
    """로그아웃 뷰"""
    logout(request)
    return redirect("login")

def check_main_account(request):
    """메인 계정 체크"""
    username = request.GET.get("username", "")
    if User.objects.filter(username=username).exists():
        return JsonResponse({"exists": True})
    return JsonResponse({"exists": False})

def check_username(request):
    """사용자명 중복 체크"""
    username = request.GET.get("username", "")
    if User.objects.filter(username=username).exists():
        return JsonResponse({"exists": True})
    return JsonResponse({"exists": False})

def check_email(request):
    """이메일 중복 체크"""
    email = request.GET.get("email", "")
    if User.objects.filter(email=email).exists():
        return JsonResponse({"exists": True})
    return JsonResponse({"exists": False})

def login_view(request):
    """로그인 뷰"""
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("main")
        else:
            messages.error(request, "아이디 또는 비밀번호가 올바르지 않습니다.")
    return render(request, "login.html") 