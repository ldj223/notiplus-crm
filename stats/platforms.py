PLATFORM_DISPLAY_NAMES = {
    'adsense': '구글 애드센스',
    'admanager': '구글 애드매니저',
    'adpost': '네이버 애드포스트',
    'coupang': '쿠팡 파트너스',
    'cozymamang': '코지마망',
    'mediamixer': '디온미디어',
    'teads': '티즈',
    'aceplanet': '에이스플래닛',
    'taboola': '타불라'
}

def get_platform_display_name(platform):
    return PLATFORM_DISPLAY_NAMES.get(platform, platform)

PLATFORM_CHOICES = [(k, v) for k, v in PLATFORM_DISPLAY_NAMES.items()]

# 플랫폼 정렬 기준 (필요시 import해서 사용)
PLATFORM_ORDER = {
    'coupang': 1,
    'adsense': 2,
    'admanager': 3,
    'adpost': 4,
    'cozymamang': 5,
    'mediamixer': 6,
    'aceplanet': 7,
    'taboola': 8,
    'teads': 9
} 