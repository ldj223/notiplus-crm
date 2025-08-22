from django.apps import AppConfig
import os

class StatsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stats'

    def ready(self):
        # 개발 서버의 autoreloader가 두 번 실행하는 것을 방지
        if os.environ.get('RUN_MAIN', None) != 'true':
            from . import scheduler
            scheduler.start()
