import logging
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
from stats.jobs import scheduled_auto_fetch

logger = logging.getLogger(__name__)

def start():
    """
    APScheduler를 시작하고 작업을 등록합니다.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), "default")

    job_id = "scheduled_auto_fetch_job"

    # 기존 작업이 있다면 제거 (개발 중 재시작 시 중복 방지)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Existing job '{job_id}' removed.")

    scheduler.add_job(
        scheduled_auto_fetch,
        trigger="interval",  # 간격 기반 트리거
        hours=1,             # 1시간마다 실행
        id=job_id,
        max_instances=1,
        replace_existing=True,
    )
    logger.info("✅ 'scheduled_auto_fetch' 작업이 1시간 주기로 등록되었습니다.")

    try:
        logger.info("🚀 스케줄러를 시작합니다...")
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("스케줄러를 종료합니다.")
        scheduler.shutdown()
    except Exception as e:
        logger.error(f"스케줄러 실행 중 오류 발생: {e}", exc_info=True) 