import json
import time
import logging
import os
import pandas as pd
from datetime import datetime
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from stats.models import AdStats, PlatformCredential
from django.conf import settings

logger = logging.getLogger(__name__)

def save_screenshot(driver, step_name):
    """스크린샷 저장 함수"""
    try:
        # 스크린샷 디렉토리 생성
        screenshot_dir = os.path.join(settings.BASE_DIR, 'screenshots', 'cozymamang')
        os.makedirs(screenshot_dir, exist_ok=True)
        
        # 파일명 생성 (타임스탬프 포함)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{step_name}_{timestamp}.png"
        filepath = os.path.join(screenshot_dir, filename)
        
        # 스크린샷 저장
        driver.save_screenshot(filepath)
        
    except Exception as e:
        logger.error(f"[Cozymamang] 스크린샷 저장 실패: {str(e)}")

def process_excel_file(file_path, cred):
    """엑셀 파일을 처리하고 데이터를 저장하는 함수"""
    try:
        df = pd.read_excel(file_path, header=0)
        
        for index, row in df.iterrows():
            try:
                date = pd.to_datetime(row['날짜']).date()
                
                ad_unit_id = str(row['SUB_ID'])
                if 'SUBPARAM' in row and not pd.isna(row['SUBPARAM']):
                    ad_unit_id += str(row['SUBPARAM'])
                
                AdStats.objects.update_or_create(
                    user=cred.user,
                    platform="cozymamang",
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
                
            except Exception as e:
                logger.error(f"[Cozymamang] 행 {index+2} 처리 중 오류 발생: {str(e)}")
                continue
        
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error(f"[Cozymamang] 임시 엑셀 파일 삭제 실패: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"[Cozymamang] 엑셀 파일 처리 중 오류 발생: {str(e)}")
        return False

def login_to_cozymamang(driver, username, password):
    """Cozymamang에 로그인하는 함수"""
    try:
        driver.get("https://media.cozymamang.com/login/")
        time.sleep(1)
        
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "IPA_ID"))
        )
        
        username_field = driver.find_element(By.ID, "IPA_ID")
        username_field.clear()
        username_field.send_keys(username)
        
        password_field = driver.find_element(By.ID, "IPA_PW")
        password_field.clear()
        password_field.send_keys(password)
        
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        time.sleep(2)
        
        WebDriverWait(driver, 10).until(
            lambda drv: "media.cozymamang.com/report" in drv.current_url
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return False

def fetch_cozymamang_stats_by_credential(cred, start_date, end_date):
    """Cozymamang 통계 데이터를 가져오는 함수"""
    try:
        start_date_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        credentials = cred.get_credentials()
        email = credentials.get("email")
        password = credentials.get("password")
        
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--lang=ko-KR,ko')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        
        download_dir = os.path.join(settings.BASE_DIR, 'temp', 'cozymamang')
        os.makedirs(download_dir, exist_ok=True)
        
        prefs = {
            'intl.accept_languages': 'ko-KR,ko',
            'download.default_directory': download_dir,
            'download.prompt_for_download': False,
            'download.directory_upgrade': True,
            'safebrowsing.enabled': False
        }
        options.add_experimental_option('prefs', prefs)
        
        service = webdriver.ChromeService(executable_path='/usr/local/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=options)
        
        try:
            if not login_to_cozymamang(driver, email, password):
                logger.error(f"[Cozymamang] '{cred.alias}' 계정 로그인 실패")
                return None
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "sdate"))
            )
            
            driver.execute_script(f"""
                document.getElementById('sdate').value = '{start_date_dt.strftime("%Y-%m-%d")}';
                document.getElementById('edate').value = '{end_date_dt.strftime("%Y-%m-%d")}';
            """)
            
            excel_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "excelFileExport"))
            )
            excel_button.click()
            time.sleep(3)
            
            downloaded_files = os.listdir(download_dir)
            if downloaded_files:
                latest_file = max(
                    [os.path.join(download_dir, f) for f in downloaded_files],
                    key=os.path.getctime
                )
                
                if process_excel_file(latest_file, cred):
                    logger.info(f"[Cozymamang] 엑셀 데이터 처리 완료")
                else:
                    logger.error(f"[Cozymamang] 엑셀 데이터 처리 실패")
            
            cred.last_fetched_at = timezone.now()
            cred.save()
            return True
            
        finally:            
            driver.quit()
            
    except Exception as e:
        logger.error(f"[Cozymamang] '{cred.alias}' 계정 데이터 수집 중 오류 발생: {str(e)}", exc_info=True)
        return None 