import logging
from django.core.management import call_command

logger = logging.getLogger(__name__)

def scheduled_auto_fetch():
    """
    APScheduler에 의해 주기적으로 실행될 작업 함수.
    'auto_fetch_all' 관리자 명령을 직접 호출합니다.
    """
    logger.info("🚀 스케줄된 자동 수집 작업을 시작합니다...")
    try:
        call_command('auto_fetch_all')
        logger.info("✅ 스케줄된 자동 수집 작업이 성공적으로 완료되었습니다.")
    except Exception as e:
        logger.error(f"❌ 스케줄된 자동 수집 작업 중 오류 발생: {e}", exc_info=True) 