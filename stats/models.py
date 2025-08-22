from django.utils import timezone
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver
from cryptography.fernet import Fernet
from encrypted_model_fields.fields import EncryptedTextField
from django.conf import settings
from datetime import date
import os
import base64

# settings에서 키를 가져와서 Fernet 키로 변환
key = settings.FIELD_ENCRYPTION_KEY.encode()
fernet = Fernet(key)

# ============================================================================
# Encrypted Models
# ============================================================================

class PlatformCredential(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    platform = models.CharField(max_length=20)
    alias = models.CharField(max_length=100, blank=True)

    encrypted_client_id = models.BinaryField(blank=True, null=True)
    encrypted_secret = models.BinaryField(blank=True, null=True)
    encrypted_email = models.BinaryField(blank=True, null=True)
    encrypted_password = models.BinaryField(blank=True, null=True)
    token = EncryptedTextField(blank=True, null=True)
    login_pw = EncryptedTextField(blank=True, null=True)
    report_resource_name = EncryptedTextField(blank=True, null=True)  # AdManager 보고서 리소스 이름
    report_id = EncryptedTextField(blank=True, null=True)  # AdManager 보고서 ID
    network_code = EncryptedTextField(blank=True, null=True)  # AdManager 네트워크 코드
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)

    color = models.CharField(max_length=20, blank=True, default="")  # ✅ 색상 필드 추가

    class Meta:
        unique_together = ('user', 'platform', 'alias')

    def save(self, *args, **kwargs):
        # ✅ 새로 생성될 때 또는 색상이 비어 있을 때 랜덤 색상 부여
        if not self.color:
            import random
            r = random.randint(50, 200)
            g = random.randint(50, 200)
            b = random.randint(50, 200)
            self.color = f"rgb({r},{g},{b})"
        super().save(*args, **kwargs)

    def set_credentials(self, client_id='', secret='', email='', password='', report_id='', report_resource_name='', network_code=''):
        self.encrypted_client_id = fernet.encrypt(client_id.encode()) if client_id else None
        self.encrypted_secret = fernet.encrypt(secret.encode()) if secret else None
        self.encrypted_email = fernet.encrypt(email.encode()) if email else None
        self.encrypted_password = fernet.encrypt(password.encode()) if password else None
        self.report_id = report_id if report_id else None
        self.report_resource_name = report_resource_name if report_resource_name else None
        self.network_code = network_code if network_code else None

    def get_credentials(self):
        try:
            return {
                'client_id': fernet.decrypt(bytes(self.encrypted_client_id)).decode() if self.encrypted_client_id else '',
                'secret': fernet.decrypt(bytes(self.encrypted_secret)).decode() if self.encrypted_secret else '',
                'email': fernet.decrypt(bytes(self.encrypted_email)).decode() if self.encrypted_email else '',
                'password': fernet.decrypt(bytes(self.encrypted_password)).decode() if self.encrypted_password else '',
            }
        except Exception as e:
            return {'client_id': '', 'secret': '', 'email': '', 'password': ''}

    def get_admanager_info(self):
        """AdManager 전용 정보를 반환합니다."""
        return {
            'report_id': self.report_id,
            'report_resource_name': self.report_resource_name,
            'network_code': self.network_code,
        }

    def __str__(self):
        return f"{self.platform} - {self.alias or 'default'}"

# ============================================================================
# Basic Models
# ============================================================================

class AdStats(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    platform = models.CharField(max_length=20)
    alias = models.CharField(max_length=100, default="default")
    date = models.DateField()
    content_id = models.CharField(max_length=100, null=True, blank=True)
    content_name = models.CharField(max_length=200, null=True, blank=True)
    ad_unit_id = models.CharField(max_length=100, null=True, blank=True)
    ad_unit_name = models.CharField(max_length=200, null=True, blank=True)

    credential = models.ForeignKey(
        PlatformCredential,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="adstats"
    )

    earnings = models.FloatField(default=0.0)
    earnings_usd = models.FloatField(default=0.0)
    impressions = models.IntegerField(default=0)  # 광고 요청 수
    view_count = models.IntegerField(default=0)  # 조회수
    clicks = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)  # 클릭률 (%)
    ppc = models.FloatField(default=0.0)  # 클릭당 단가 (원)

    # 쿠팡 파트너스 전용 필드
    order_count = models.IntegerField(default=0)  # 주문건수
    total_amount = models.FloatField(default=0.0)  # 합산금액

    class Meta:
        unique_together = ('user', 'platform', 'alias', 'date', 'content_id', 'ad_unit_id')
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'platform', 'date']),
            models.Index(fields=['user', 'ad_unit_id', 'date']),
            models.Index(fields=['user', 'platform', 'ad_unit_id', 'date']),
            models.Index(fields=['date', 'platform']),
            models.Index(fields=['ad_unit_id', 'platform']),
        ]

    def __str__(self):
        if self.ad_unit_name:
            return f"{self.platform}:{self.alias}:{self.content_name}:{self.ad_unit_name} | {self.date} | {self.earnings}"
        return f"{self.platform}:{self.alias}:{self.content_name} | {self.date} | {self.earnings}"

class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    auto_fetch_days = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} 설정"

class UserProfile(models.Model):
    ACCOUNT_TYPES = (
        ('main', '메인 계정'),
        ('sub', '서브 계정'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPES, default='main')
    main_account = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sub_accounts')
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_account_type_display()})"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()

# ============================================================================
# Stat Models
# ============================================================================

class SettlementDepartment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="설정 소유 사용자")
    name = models.CharField(max_length=100, help_text="정산주관부서명")

    class Meta:
        unique_together = ['user', 'name']  # 한 사용자 내에서 부서명은 유일해야 함
        verbose_name = '정산주관부서'
        verbose_name_plural = '정산주관부서'

    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Member(models.Model):
    no = models.AutoField(primary_key=True)
    uid = models.CharField(max_length=50, null=True, blank=True)
    uname = models.CharField(max_length=100, null=True, blank=True)
    level = models.SmallIntegerField(default=1)
    request_key = models.CharField(max_length=8, unique=True, null=True, blank=True, db_column='requestKey')

    class Meta:
        db_table = 'member'
        managed = False  # Django가 테이블을 생성/수정하지 않음
        indexes = [
            models.Index(fields=['request_key']),
            models.Index(fields=['uid']),
        ]

    def __str__(self):
        return f"{self.uname} ({self.request_key})"

    # newspic 데이터베이스에서 조회하기 위한 매니저
    objects = models.Manager()
    
    @classmethod
    def newspic_objects(cls):
        """newspic 데이터베이스에서 조회하는 매니저"""
        return cls.objects.using('newspic')

class PurchaseGroup(models.Model):
    """매입 그룹 메타데이터 - 그룹당 하나만 저장"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="설정 소유 사용자")
    member_request_key = models.CharField(max_length=8, verbose_name='퍼블리셔 코드', db_column='member_request_key', default='')
    group_name = models.CharField(max_length=100, verbose_name='그룹명')
    company_name = models.CharField(max_length=100, verbose_name='거래처명')
    service_name = models.CharField(max_length=100, verbose_name='서비스명')
    default_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='기본 단가',
        null=True, blank=True
    )
    default_unit_type = models.CharField(
        max_length=10,
        choices=[
            ('percent', '퍼센트 (%)'),
            ('rate', '요율'),
        ],
        default='percent',
        verbose_name='기본 단가 유형'
    )
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    is_important = models.BooleanField(default=False, verbose_name='주요 퍼블리셔')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    class Meta:
        db_table = 'purchase_group'
        verbose_name = '매입 그룹'
        verbose_name_plural = '매입 그룹'
        unique_together = ['user', 'member_request_key', 'is_active']  # 한 사용자당 한 멤버의 활성 그룹만

    def __str__(self):
        return f"{self.group_name} ({self.member_request_key}) - {self.user.username}"

    def clean(self):
        super().clean()
        # 활성 그룹이 중복되지 않도록 검증
        if self.is_active:
            existing_active = PurchaseGroup.objects.filter(
                user=self.user,
                member_request_key=self.member_request_key,
                is_active=True
            ).exclude(pk=self.pk)
            if existing_active.exists():
                raise ValidationError('이 퍼블리셔에 대한 활성 그룹이 이미 존재합니다.')
    
    @property
    def member(self):
        """Member 객체를 반환하는 프로퍼티 (newspic 데이터베이스에서 조회)"""
        try:
            return Member.newspic_objects().get(request_key=self.member_request_key)
        except Member.DoesNotExist:
            return None

class PurchasePrice(models.Model):
    """월별 매입 단가 설정"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="설정 소유 사용자")
    request_key = models.CharField(max_length=50, verbose_name='퍼블리셔 코드')
    year_month = models.DateField(verbose_name='적용년월')  # YYYY-MM-01 형식으로 저장
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='단가')
    unit_type = models.CharField(
        max_length=10,
        choices=[
            ('percent', '퍼센트 (%)'),
            ('rate', '요율'),
        ],
        default='percent',
        verbose_name='단가 유형'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    class Meta:
        db_table = 'purchase_price'
        verbose_name = '매입 단가'
        verbose_name_plural = '매입 단가'
        unique_together = ['user', 'request_key', 'year_month']  # 사용자별 퍼블리셔별 월별 유일

    def __str__(self):
        return f"{self.user.username} - {self.request_key} - {self.year_month.strftime('%Y-%m')} ({self.unit_price}{'%' if self.unit_type == 'percent' else ''})"

    def clean(self):
        super().clean()
        # year_month는 항상 월의 첫날로 저장
        if self.year_month:
            self.year_month = self.year_month.replace(day=1)

class PurchaseGroupAdUnit(models.Model):
    """퍼블리셔 그룹과 광고 단위 매핑 (애드센스, 애드매니저)"""
    purchase_group = models.ForeignKey(
        PurchaseGroup, 
        on_delete=models.CASCADE, 
        related_name='ad_units',
        verbose_name='퍼블리셔 그룹'
    )
    platform = models.CharField(
        max_length=20,
        choices=[
            ('adsense', '구글 애드센스'),
            ('admanager', '구글 애드매니저'),
        ],
        verbose_name='플랫폼'
    )
    ad_unit_id = models.CharField(max_length=100, verbose_name='광고 단위 ID')
    ad_unit_name = models.CharField(max_length=200, verbose_name='광고 단위명', blank=True)
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    class Meta:
        db_table = 'purchase_group_ad_unit'
        verbose_name = '퍼블리셔 그룹 광고 단위'
        verbose_name_plural = '퍼블리셔 그룹 광고 단위'
        unique_together = ['purchase_group', 'platform', 'ad_unit_id']  # 그룹별 플랫폼별 ad_unit_id 유일

    def __str__(self):
        return f"{self.purchase_group.company_name} - {self.platform} - {self.ad_unit_name or self.ad_unit_id}"

    def clean(self):
        super().clean()
        # ad_unit_name이 없으면 ad_unit_id로 설정
        if not self.ad_unit_name:
            self.ad_unit_name = self.ad_unit_id

class ExchangeRate(models.Model):
    """월별 USD/KRW 환율 관리"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="설정 소유 사용자")
    year_month = models.DateField(verbose_name='적용년월')  # YYYY-MM-01 형식으로 저장
    usd_to_krw = models.DecimalField(
        max_digits=10, decimal_places=2, 
        verbose_name='USD/KRW 환율',
        help_text='1 USD = ? KRW'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    class Meta:
        db_table = 'exchange_rate'
        verbose_name = '환율'
        verbose_name_plural = '환율'
        unique_together = ['user', 'year_month']  # 사용자별 월별 유일

    def __str__(self):
        return f"{self.user.username} - {self.year_month.strftime('%Y-%m')} ({self.usd_to_krw} KRW/USD)"

    def clean(self):
        super().clean()
        # year_month는 항상 월의 첫날로 저장
        if self.year_month:
            self.year_month = self.year_month.replace(day=1)

class ServiceGroup(models.Model):
    """서비스 그룹 관리 모델"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, help_text="데이터 소유 사용자")
    group_code = models.CharField(max_length=100, unique=True, help_text="그룹 고유 코드")
    group_name = models.CharField(max_length=200, help_text="그룹명")
    company_name = models.CharField(max_length=100, help_text="업체명")
    service_name = models.CharField(max_length=100, help_text="서비스명")
    issue_type = models.CharField(max_length=50, default='정발행', choices=[
        ('정발행', '정발행'),
        ('역발행', '역발행'),
        ('영세율', '영세율'),
    ], help_text="발행유형")
    settlement_timing = models.CharField(max_length=50, blank=True, help_text="정산시기")
    settlement_department = models.ForeignKey(
        SettlementDepartment, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        help_text="정산주관부서"
    )
    is_active = models.BooleanField(default=True, help_text="활성 여부")
    created_at = models.DateTimeField(auto_now_add=True, help_text="생성일시")

    def __str__(self):
        return f"{self.group_name} ({self.group_code})"

class MonthlySales(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, help_text="데이터 소유 사용자")
    # 기본 매출 정보
    transaction_date = models.DateField(help_text="거래일 (엑셀: 작성시기)", db_index=True)
    year_month = models.DateField(help_text="매출 년월 (매월 1일로 저장)", editable=False, db_index=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="금액 (엑셀: 품목단가)")
    
    # 서비스 정보 (엑셀에서 직접 업로드)
    service_code = models.CharField(max_length=100, help_text="서비스 고유 코드 (승인번호)", db_index=True, default="")
    company_name = models.CharField(max_length=100, help_text="업체명 (엑셀: 상호)", default="")
    service_name = models.CharField(max_length=100, help_text="서비스명 (엑셀: 품목명)", default="")
    business_number = models.CharField(max_length=12, help_text="사업자번호 (XXX-XX-XXXXX)", blank=True, default="")
    
    # 그룹화 관련
    group = models.ForeignKey(
        ServiceGroup, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        help_text="서비스 그룹 (자동 매칭)"
    )

    class Meta:
        unique_together = ('user', 'service_code', 'year_month')

    def save(self, *args, **kwargs):
        # year_month를 매월 1일로 설정
        if self.transaction_date:
            self.year_month = self.transaction_date.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.company_name} - {self.service_name} ({self.transaction_date})"

class MemberStat(models.Model):
    sdate = models.CharField(max_length=8, help_text='일자')
    request_key = models.CharField(max_length=8, help_text='cp 코드', db_column='requestKey')
    click_cnt = models.IntegerField(default=0, help_text='유효 페이지뷰', db_column='clickCnt')
    point = models.FloatField(default=0, help_text='파트너스 포인트')

    class Meta:
        db_table = 'tbMemberStat'
        managed = False  # Django가 테이블을 생성/수정하지 않음
        unique_together = ('sdate', 'request_key')
        verbose_name = '제휴사 통계'
        verbose_name_plural = '제휴사 통계'

    def __str__(self):
        return f"{self.request_key} - {self.sdate} (클릭: {self.click_cnt}, 포인트: {self.point})"

    # newspic 데이터베이스에서 조회하기 위한 매니저
    objects = models.Manager()
    
    @classmethod
    def newspic_objects(cls):
        """newspic 데이터베이스에서 조회하는 매니저"""
        return cls.objects.using('newspic')

class TotalStat(models.Model):
    sdate = models.DateField()
    request_key = models.CharField(max_length=8, db_column='requestKey')
    visit_count = models.BigIntegerField(default=0, help_text='페이지뷰', db_column='visitCount')
    powerlink_count = models.BigIntegerField(default=0, help_text='파워링크 클릭', db_column='powerlinkCount')

    class Meta:
        db_table = 'tbTotalStat'
        managed = False  # Django가 테이블을 생성/수정하지 않음
        unique_together = ('sdate', 'request_key')
        verbose_name = '전체 통계'
        verbose_name_plural = '전체 통계'

    def __str__(self):
        return f"{self.request_key} - {self.sdate} (방문: {self.visit_count}, 파워링크: {self.powerlink_count})"

    # newspic 데이터베이스에서 조회하기 위한 매니저
    objects = models.Manager()
    
    @classmethod
    def newspic_objects(cls):
        """newspic 데이터베이스에서 조회하는 매니저"""
        return cls.objects.using('newspic')

# ============================================================================
# Manual Input Models for Reports
# ============================================================================

class OtherRevenue(models.Model):
    """report.html의 기타수익 수기 입력을 위한 모델"""
    SECTION_CHOICES = [
        ('publisher', '퍼블리셔'),
        ('partners', '파트너스'),
        ('stamply', '스탬플리'),
        ('publisher_cost', '퍼블리셔 매입비용'),
        ('partners_cost', '파트너스 매입비용'),
        ('stamply_cost', '스탬플리 매입비용'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="데이터 소유 사용자")
    date = models.DateField(help_text="수익 날짜")
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, help_text="수익 구분 (퍼블리셔, 파트너스, 스탬플리, 매입비용)")
    amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="기타 수익 금액")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '일별 기타수익'
        verbose_name_plural = '일별 기타수익'
        unique_together = ('user', 'date', 'section')
        ordering = ['-date', 'section']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.get_section_display()}: {self.amount}"


class MonthlyAdjustment(models.Model):
    """home.html의 월별 매출/매입 조정 수기 입력을 위한 모델"""
    ADJUSTMENT_TYPE_CHOICES = [
        ('sales', '매출 조정'),
        ('purchase', '매입 조정'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="데이터 소유 사용자")
    year_month = models.DateField(help_text="조정 대상 년월 (매월 1일로 저장)")
    adjustment_type = models.CharField(max_length=20, choices=ADJUSTMENT_TYPE_CHOICES, help_text="조정 유형")
    sales_type = models.CharField(max_length=100, help_text="매출/매입 구분 (예: 퍼블리셔, 파트너스)")
    adjustment_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="조정 금액")
    adjustment_note = models.TextField(blank=True, help_text="조정 내역")
    tax_deadline = models.DateField(null=True, blank=True, help_text="세금계산서 수취기한 (매입 조정시만 사용)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '월별 매출/매입 조정'
        verbose_name_plural = '월별 매출/매입 조정'
        unique_together = ('user', 'year_month', 'adjustment_type', 'sales_type')
        ordering = ['-year_month', 'adjustment_type', 'sales_type']

    def __str__(self):
        return f"{self.user.username} - {self.year_month.strftime('%Y-%m')} - {self.get_adjustment_type_display()}: {self.sales_type} - {self.adjustment_amount}" 