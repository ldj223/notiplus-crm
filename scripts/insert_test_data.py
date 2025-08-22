from datetime import datetime, timedelta
import random
from django.contrib.auth.models import User
from stats.models import AdStats, PlatformCredential

# 사용자 및 계정
user = User.objects.get(username="test")
cred = PlatformCredential.objects.get(user=user, platform="coupang", alias="default")

# 날짜 범위 설정
start_date = datetime(2025, 3, 1)
end_date = datetime.now()
date_list = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]

# 삽입
created = 0
for date in date_list:
    earnings = round(random.uniform(100, 3000), 2)
    clicks = random.randint(10, 300)
    impressions = random.randint(1000, 5000)
    ctr = round((clicks / impressions) * 100, 2) if impressions else 0
    ppc = round(earnings / clicks, 2) if clicks else 0

    AdStats.objects.update_or_create(
        user=user,
        platform="coupang",
        alias="default",
        credential=cred,
        date=date.date(),
        defaults={
            "earnings": earnings,
            "clicks": clicks,
            "impressions": impressions,
            "ctr": ctr,
            "ppc": ppc,
        }
    )
    created += 1

print(f"✅ {created}건 삽입 완료.")