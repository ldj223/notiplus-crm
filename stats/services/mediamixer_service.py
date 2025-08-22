import json
import time
import logging
import os
import pandas as pd
import subprocess
import shutil
import signal
from datetime import datetime
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, SessionNotCreatedException
from stats.models import AdStats, PlatformCredential
from django.conf import settings

logger = logging.getLogger(__name__)

def setup_environment():
    """스케줄러 환경에서 필요한 환경 변수 설정"""
    os.environ.setdefault('DISPLAY', ':99')
    os.environ.setdefault('LANG', 'ko_KR.UTF-8')
    os.environ.setdefault('LC_ALL', 'ko_KR.UTF-8')
    os.environ.setdefault('LANGUAGE', 'ko_KR')
    
    # Chrome 관련 환경 변수
    os.environ.setdefault('CHROME_BIN', '/usr/bin/google-chrome')
    os.environ.setdefault('CHROME_DRIVER', '/usr/local/bin/chromedriver')

def find_chromedriver():
    """ChromeDriver 경로를 자동으로 찾는 함수"""
    possible_paths = [
        '/usr/local/bin/chromedriver',
        '/usr/bin/chromedriver',
        '/opt/homebrew/bin/chromedriver',
        shutil.which('chromedriver'),
    ]
    
    for path in possible_paths:
        if path and os.path.exists(path):
            logger.info(f"[mediamixer] ChromeDriver found at: {path}")
            return path
    
    # 시스템 PATH에서 찾기
    try:
        result = subprocess.run(['which', 'chromedriver'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            path = result.stdout.strip()
            if os.path.exists(path):
                logger.info(f"[mediamixer] ChromeDriver found in PATH: {path}")
                return path
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.warning(f"[mediamixer] ChromeDriver PATH 검색 실패: {str(e)}")
    
    logger.error("[mediamixer] ChromeDriver not found in any expected location")
    return None

def cleanup_chrome_processes():
    """Chrome 프로세스 정리"""
    try:
        subprocess.run(['pkill', '-f', 'chrome'], capture_output=True, timeout=10)
        subprocess.run(['pkill', '-f', 'chromedriver'], capture_output=True, timeout=10)
        time.sleep(2)
    except Exception as e:
        logger.warning(f"[mediamixer] Chrome 프로세스 정리 실패: {str(e)}")

def save_screenshot(driver, step_name):
    """스크린샷 저장 함수"""
    try:
        # 스크린샷 디렉토리 생성
        screenshot_dir = os.path.join(settings.BASE_DIR, 'screenshots', 'mediamixer')
        os.makedirs(screenshot_dir, exist_ok=True)
        
        # 파일명 생성 (타임스탬프 포함)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{step_name}_{timestamp}.png"
        filepath = os.path.join(screenshot_dir, filename)
        
        # 스크린샷 저장
        driver.save_screenshot(filepath)
        logger.info(f"[mediamixer] 스크린샷 저장됨: {filepath}")
        
    except Exception as e:
        logger.error(f"[mediamixer] 스크린샷 저장 실패: {str(e)}")

def process_excel_file(file_path, cred):
    """엑셀 파일을 처리하고 데이터를 저장하는 함수"""
    try:
        # 엑셀 파일 읽기
        df = pd.read_excel(file_path, header=0)  # 첫 번째 행을 헤더로 사용
        
        # 데이터 처리
        for index, row in df.iterrows():
            try:
                # 날짜 가져오기
                date = pd.to_datetime(row['날짜']).date()
                
                # ad_unit_id 생성 (SUB_ID + SUBPARAM)
                ad_unit_id = str(row['SUB_ID'])
                if 'SUBPARAM' in row and not pd.isna(row['SUBPARAM']):
                    ad_unit_id += str(row['SUBPARAM'])
                
                # 데이터 업데이트 또는 생성
                AdStats.objects.update_or_create(
                    user=cred.user,
                    platform="mediamixer",
                    alias=cred.alias,
                    date=date,
                    ad_unit_id=ad_unit_id,
                    defaults={
                        'ad_unit_name': row['지면명'],
                        'earnings': float(row['최종수익금']) if not pd.isna(row['최종수익금']) else 0,
                        'clicks': int(row['클릭수']) if not pd.isna(row['클릭수']) else 0,
                        'impressions': int(row['노출수']) if not pd.isna(row['노출수']) else 0,
                        'order_count': int(row['최종구매수량']) if not pd.isna(row['최종구매수량']) else 0,
                        'total_amount': float(row['최종구매금액']) if not pd.isna(row['최종구매금액']) else 0,
                        'credential': cred
                    }
                )
                
                # logger.info(f"[mediamixer] 데이터 저장 완료: {ad_unit_id} ({date})")
                
            except Exception as e:
                # logger.error(f"[mediamixer] 행 {index+2} 처리 중 오류 발생: {str(e)}")
                continue
        
        # 임시 엑셀 파일 삭제
        try:
            os.remove(file_path)
            # logger.info(f"[mediamixer] 임시 엑셀 파일 삭제 완료: {file_path}")
        except Exception as e:
            logger.error(f"[mediamixer] 임시 엑셀 파일 삭제 실패: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"[mediamixer] 엑셀 파일 처리 중 오류 발생: {str(e)}")
        return False

def login_to_mediamixer(driver, username, password, max_retries=3):
    """
    mediamixer에 로그인하는 함수 (재시도 메커니즘 포함)
    """
    for attempt in range(max_retries):
        try:
            logger.info(f"[mediamixer] 로그인 시도 {attempt + 1}/{max_retries}")
            
            # mediamixer 로그인 페이지로 이동
            driver.get("http://mediamixer.co.kr/#/report/tag/0")
            time.sleep(3)  # 페이지 로딩 대기 증가
            # save_screenshot(driver, f"login_page_attempt_{attempt + 1}")
            
            # 로그인 폼이 로드될 때까지 대기
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[ng-model='frm.id']"))
            )
            
            # 아이디 입력
            username_field = driver.find_element(By.CSS_SELECTOR, "[ng-model='frm.id']")
            username_field.clear()
            time.sleep(0.5)
            username_field.send_keys(username)
            # save_screenshot(driver, f"username_entered_attempt_{attempt + 1}")
            
            # 비밀번호 입력
            password_field = driver.find_element(By.CSS_SELECTOR, "[ng-model='frm.pw']")
            password_field.clear()
            time.sleep(0.5)
            password_field.send_keys(password)
            # save_screenshot(driver, f"password_entered_attempt_{attempt + 1}")
            
            # 로그인 버튼 클릭
            login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            login_button.click()
            time.sleep(3)  # 로그인 처리 대기 증가
            # save_screenshot(driver, f"login_clicked_attempt_{attempt + 1}")
            
            # 로그인 성공 확인 (여러 URL 패턴 확인)
            success_urls = [
                "www.mediamixer.co.kr/#/report/date/0",
                "mediamixer.co.kr/#/report/date/0",
                "www.mediamixer.co.kr/#/report/tag/0",
                "mediamixer.co.kr/#/report/tag/0"
            ]
            
            current_url = driver.current_url
            if any(success_url in current_url for success_url in success_urls):
                logger.info(f"[mediamixer] 로그인 성공 (시도 {attempt + 1})")
                # save_screenshot(driver, f"login_success_attempt_{attempt + 1}")
                return True
            else:
                logger.warning(f"[mediamixer] 로그인 실패 (시도 {attempt + 1}), 현재 URL: {current_url}")
                if attempt < max_retries - 1:
                    time.sleep(3)  # 재시도 전 대기
                    continue
                
        except Exception as e:
            logger.error(f"[mediamixer] 로그인 시도 {attempt + 1} 중 오류: {str(e)}")
            # save_screenshot(driver, f"login_error_attempt_{attempt + 1}")
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
    
    logger.error(f"[mediamixer] 모든 로그인 시도 실패 ({max_retries}회)")
    return False

def fetch_mediamixer_stats_by_credential(cred, start_date, end_date, max_retries=3):
    """
    mediamixer 통계 데이터를 가져오는 함수 (재시도 메커니즘 포함)
    """
    # 환경 설정
    setup_environment()
    
    for attempt in range(max_retries):
        driver = None
        try:
            # 날짜 문자열을 datetime 객체로 변환 (이미 datetime인 경우 처리)
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, "%Y-%m-%d")
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, "%Y-%m-%d")
            
            logger.info(f"[mediamixer] '{cred.alias}' 계정에 대해 {start_date} ~ {end_date} 데이터 수집 시작 (시도 {attempt + 1}/{max_retries})")
            
            # 자격증명에서 이메일과 비밀번호 가져오기
            credentials = cred.get_credentials()
            email = credentials.get("email")
            password = credentials.get("password")
            
            if not email or not password:
                logger.error(f"[mediamixer] '{cred.alias}' 계정의 자격증명이 누락되었습니다.")
                return None
            
            # Chrome 프로세스 정리
            if attempt > 0:
                cleanup_chrome_processes()
            
            # ChromeDriver 경로 찾기
            chromedriver_path = find_chromedriver()
            if not chromedriver_path:
                logger.error("[mediamixer] ChromeDriver를 찾을 수 없습니다.")
                return None
            
            # Selenium 옵션 설정 (스케줄러 환경 최적화)
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--lang=ko-KR,ko')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-web-security')
            options.add_argument('--allow-running-insecure-content')
            options.add_argument('--disable-features=VizDisplayCompositor')
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-plugins')
            options.add_argument('--disable-images')
            options.add_argument('--disable-background-timer-throttling')
            options.add_argument('--disable-backgrounding-occluded-windows')
            options.add_argument('--disable-renderer-backgrounding')
            options.add_argument('--disable-field-trial-config')
            options.add_argument('--disable-ipc-flooding-protection')
            options.add_argument('--disable-default-apps')
            options.add_argument('--disable-sync')
            options.add_argument('--no-first-run')
            options.add_argument('--no-default-browser-check')
            options.add_argument('--disable-translate')
            options.add_argument('--disable-background-networking')
            options.add_argument('--disable-component-update')
            options.add_argument('--disable-client-side-phishing-detection')
            options.add_argument('--disable-hang-monitor')
            options.add_argument('--disable-prompt-on-repost')
            options.add_argument('--disable-domain-reliability')
            options.add_argument('--disable-features=TranslateUI')
            
            # 다운로드 디렉토리 설정
            download_dir = os.path.join(settings.BASE_DIR, 'temp', 'mediamixer')
            os.makedirs(download_dir, exist_ok=True)
            
            prefs = {
                'intl.accept_languages': 'ko-KR,ko',
                'profile.default_content_setting_values.images': 2,
                'profile.managed_default_content_settings.images': 2,
                'download.default_directory': download_dir,
                'download.prompt_for_download': False,
                'download.directory_upgrade': True,
                'safebrowsing.enabled': False,
                'profile.default_content_settings.popups': 0,
                'profile.managed_default_content_settings.media_stream': 2,
                'profile.default_content_setting_values.notifications': 2,
                'profile.managed_default_content_settings.notifications': 2,
            }
            options.add_experimental_option('prefs', prefs)
            
            # ChromeDriver 서비스 설정
            service = webdriver.ChromeService(executable_path=chromedriver_path)
            driver = webdriver.Chrome(service=service, options=options)
            
            # 페이지 로드 타임아웃 설정
            driver.set_page_load_timeout(90)
            driver.implicitly_wait(15)
            
            # 로그인 시도
            if not login_to_mediamixer(driver, email, password):
                logger.error(f"[mediamixer] '{cred.alias}' 계정 로그인 실패 (시도 {attempt + 1})")
                if attempt < max_retries - 1:
                    continue
                return None
                
            logger.info(f"[mediamixer] '{cred.alias}' 계정 로그인 성공 (시도 {attempt + 1})")
            
            # 리포트 페이지로 이동 (날짜 파라미터 포함)
            report_url = f"https://www.mediamixer.co.kr/#/report/date/0?limit=500&startDate={start_date.strftime('%Y-%m-%d')}&endDate={end_date.strftime('%Y-%m-%d')}"
            driver.get(report_url)
            time.sleep(3)  # 페이지 로딩 대기 증가
            # save_screenshot(driver, f"report_page_attempt_{attempt + 1}")
            
            # 페이지 새로고침
            driver.refresh() 
            time.sleep(3)  # 새로고침 후 로딩 대기 증가
            # save_screenshot(driver, f"report_page_refreshed_attempt_{attempt + 1}")
            
            # 동적 테이블 로딩 완료 대기 (더 강한 대기)
            try:
                # 테이블이 로드될 때까지 대기 (최대 90초)
                WebDriverWait(driver, 90).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.ng-scope:not(.bg-grey) tr[ng-repeat='row in srch.rows']"))
                )
                logger.info(f"[mediamixer] 동적 테이블 로딩 완료 (시도 {attempt + 1})")
                
                # 추가 대기 시간 (데이터가 완전히 렌더링되도록)
                time.sleep(8)
                
            except TimeoutException:
                logger.error(f"[mediamixer] 테이블 로딩 시간 초과 (시도 {attempt + 1})")
                # save_screenshot(driver, f"table_timeout_attempt_{attempt + 1}")
                if attempt < max_retries - 1:
                    continue
                return None
            
            # 테이블 데이터 추출
            # 두 번째 tbody에서 ng-repeat이 있는 tr만 선택
            rows = driver.find_elements(By.CSS_SELECTOR, "tbody.ng-scope:not(.bg-grey) tr[ng-repeat='row in srch.rows']")
            logger.info(f"[mediamixer] 총 {len(rows)}개의 데이터 행 발견 (시도 {attempt + 1})")
            
            if not rows:
                logger.error(f"[mediamixer] 데이터 행을 찾을 수 없습니다 (시도 {attempt + 1})")
                # save_screenshot(driver, f"no_data_attempt_{attempt + 1}")
                if attempt < max_retries - 1:
                    continue
                return None
            
            # 데이터 처리 성공 여부 확인
            success_count = 0
            for index, row in enumerate(rows, 1):
                try:
                    # 각 열의 데이터 추출
                    columns = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(columns) < 7:
                        logger.warning(f"[mediamixer] {index}번째 행의 열 수가 부족합니다: {len(columns)}개")
                        continue
                    
                    # 날짜 (첫 번째 열)
                    date_str = columns[0].text.strip()
                    if not date_str:
                        logger.warning(f"[mediamixer] {index}번째 행의 날짜가 비어있습니다")
                        continue
                    
                    date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    
                    # 노출수 (두 번째 열) - 쉼표 제거 후 정수로 변환
                    impressions_str = columns[1].text.replace(",", "")
                    impressions = int(impressions_str) if impressions_str.isdigit() else 0
                    
                    # 클릭수 (세 번째 열) - 쉼표 제거 후 정수로 변환
                    clicks_str = columns[2].text.replace(",", "")
                    clicks = int(clicks_str) if clicks_str.isdigit() else 0
                    
                    # 매출 (일곱 번째 열) - 쉼표 제거 후 정수로 변환
                    earnings_str = columns[6].text.replace(",", "")
                    earnings = int(earnings_str) if earnings_str.isdigit() else 0
                    
                    # CTR 계산 (클릭수 / 노출수 * 100)
                    ctr = (clicks / impressions * 100) if impressions > 0 else 0
                    
                    # 데이터 저장
                    stats, created = AdStats.objects.update_or_create(
                        user=cred.user,
                        platform="mediamixer",
                        alias=cred.alias,
                        date=date,
                        defaults={
                            'impressions': impressions,
                            'clicks': clicks,
                            'earnings': earnings,
                            'ctr': ctr,
                            'credential': cred
                        }
                    )
                    success_count += 1
                    
                except Exception as e:
                    logger.error(f"[mediamixer] {index}번째 행 처리 중 오류 발생: {str(e)}")
                    continue
            
            if success_count > 0:
                logger.info(f"[mediamixer] '{cred.alias}' 계정 데이터 수집 완료: {success_count}개 행 처리 (시도 {attempt + 1})")
                cred.last_fetched_at = timezone.now()
                cred.save()
                return True
            else:
                logger.error(f"[mediamixer] '{cred.alias}' 계정 데이터 처리 실패: 모든 행 처리 실패 (시도 {attempt + 1})")
                if attempt < max_retries - 1:
                    continue
                return None
            
        except SessionNotCreatedException as e:
            logger.error(f"[mediamixer] Chrome 세션 생성 실패 (시도 {attempt + 1}): {str(e)}")
            cleanup_chrome_processes()
            if attempt < max_retries - 1:
                time.sleep(10)  # 재시도 전 대기
                continue
        except WebDriverException as e:
            logger.error(f"[mediamixer] WebDriver 오류 (시도 {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(10)  # 재시도 전 대기
                continue
        except Exception as e:
            logger.error(f"[mediamixer] '{cred.alias}' 계정 데이터 수집 중 오류 발생 (시도 {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.error(f"[mediamixer] 드라이버 종료 중 오류: {str(e)}")
    
    logger.error(f"[mediamixer] '{cred.alias}' 계정 모든 시도 실패 ({max_retries}회)")
    return None 