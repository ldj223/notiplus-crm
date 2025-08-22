from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from stats.models import PlatformCredential, UserPreference
from stats.services.adsense_service import fetch_adsense_stats_by_credential
from stats.services.admanager_service import fetch_admanager_stats_by_credential
from stats.services.coupang_service import fetch_coupang_stats_by_credential
from stats.services.cozymamang_service import fetch_cozymamang_stats_by_credential
from stats.services.mediamixer_service import fetch_mediamixer_stats_by_credential
from stats.services.aceplanet_service import fetch_aceplanet_stats_by_credential
from stats.services.teads_service import fetch_teads_stats_by_credential

class Command(BaseCommand):
    help = "설정된 주기에 따라 모든 플랫폼의 수익 데이터를 자동 수집합니다."

    PLATFORM_FETCHERS = {
        "adsense": fetch_adsense_stats_by_credential,
        "admanager": fetch_admanager_stats_by_credential,
        "coupang": fetch_coupang_stats_by_credential,
        "cozymamang": fetch_cozymamang_stats_by_credential,
        "mediamixer": fetch_mediamixer_stats_by_credential,
        "aceplanet": fetch_aceplanet_stats_by_credential,
        "teads": fetch_teads_stats_by_credential,
    }

    def handle(self, *args, **options):
        now = timezone.now()
        preferences = UserPreference.objects.filter(auto_fetch_days__gt=0)

        for pref in preferences:
            user = pref.user
            days = pref.auto_fetch_days
            creds = PlatformCredential.objects.filter(user=user).exclude(
                encrypted_email__isnull=True, encrypted_client_id__isnull=True
            )

            for cred in creds:
                platform = cred.platform
                if platform not in self.PLATFORM_FETCHERS:
                    continue

                last = cred.last_fetched_at
                should_fetch = not last or (now - last).days >= days
                if not should_fetch:
                    continue

                # days가 1일이면 3일 전부터, 그렇지 않으면 원래 days 값 사용
                fetch_days = 3 if days == 1 else days
                start_date = (now - timedelta(days=fetch_days)).date().isoformat()
                end_date = now.date().isoformat()

                try:
                    self.stdout.write(f"🔄 [{user.username}] {platform}:{cred.alias or 'default'} → 수집 시작")
                    self.PLATFORM_FETCHERS[platform](cred, start_date, end_date)
                    self.stdout.write(f"✅ [{user.username}] {platform}:{cred.alias or 'default'} → 완료")
                except Exception as e:
                    self.stderr.write(f"❌ [{user.username}] {platform}:{cred.alias or 'default'} 오류: {str(e)}")