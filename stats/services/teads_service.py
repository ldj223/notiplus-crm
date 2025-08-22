import json
import time
import logging
import os
import pandas as pd
import requests
from datetime import datetime
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from stats.models import AdStats, PlatformCredential
from django.conf import settings
from selenium.webdriver.support.ui import Select

logger = logging.getLogger(__name__)

def save_screenshot(driver, step_name):
    """스크린샷 저장 함수"""
    try:
        # 스크린샷 디렉토리 생성
        screenshot_dir = os.path.join(settings.BASE_DIR, 'screenshots', 'teads')
        os.makedirs(screenshot_dir, exist_ok=True)
        
        # 파일명 생성 (타임스탬프 포함)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{step_name}_{timestamp}.png"
        filepath = os.path.join(screenshot_dir, filename)
        
        # 스크린샷 저장
        driver.save_screenshot(filepath)
        # logger.info(f"[teads] 스크린샷 저장됨: {filepath}")
        
    except Exception as e:
        logger.error(f"[teads] 스크린샷 저장 실패: {str(e)}")

def login_to_teads(driver, username, password):
    """
    teads에 로그인하는 함수
    """
    try:
        # teads 로그인 페이지로 이동
        driver.get("https://login.teads.tv/login")
        time.sleep(1)  # 페이지 로딩 대기
        # save_screenshot(driver, "1. login_page")
        
        # 로그인 폼이 로드될 때까지 대기
        WebDriverWait(driver, 1).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[ng-model='ctrl.user.username']"))
        )
        
        # 아이디 입력
        username_field = driver.find_element(By.CSS_SELECTOR, "[ng-model='ctrl.user.username']")
        username_field.clear()
        username_field.send_keys(username)
        # save_screenshot(driver, "2. username_entered")

        # 아이디 입력 및 버튼 클릭 후 비밀번호 입력 화면 대기
        login_button = driver.find_element(By.ID, "login-btn")
        login_button.click()
        time.sleep(2)  # 로그인 처리 대기

        # 비밀번호 입력 로드 대기
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='password']"))
        )
        
        # 비밀번호 입력
        password_field = driver.find_element(By.CSS_SELECTOR, "input[name='password']")
        password_field.clear()
        password_field.send_keys(password)
        # save_screenshot(driver, "3. password_entered")
        
        # 로그인 버튼 클릭
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        time.sleep(2)  # 로그인 처리 대기
        # save_screenshot(driver, "login_clicked")
        
        # 로그인 성공 확인
        WebDriverWait(driver, 30).until(
            lambda driver: "login.teads.tv/portal" in driver.current_url
        )
        # save_screenshot(driver, "4. login_success")
        
        return True
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        # save_screenshot(driver, "login_error")
        return False

def fetch_teads_stats_by_credential(cred, start_date, end_date):
    """
    teads 통계 데이터를 가져오는 함수
    """
    try:
        # 날짜 문자열을 datetime 객체로 변환
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d")
        
        logger.info(f"[teads] '{cred.alias}' 계정에 대해 {start_date} ~ {end_date} 데이터 수집 시작")
        
        # 자격증명에서 이메일과 비밀번호 가져오기
        credentials = cred.get_credentials()
        email = credentials.get("email")
        password = credentials.get("password")
        
        # Selenium 옵션 설정
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--lang=ko-KR,ko')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        
        # 다운로드 디렉토리 설정
        download_dir = os.path.join(settings.BASE_DIR, 'temp', 'teads')
        os.makedirs(download_dir, exist_ok=True)
        
        prefs = {
            'intl.accept_languages': 'ko-KR,ko',
            'profile.default_content_setting_values.images': 2,
            'profile.managed_default_content_settings.images': 2,
            'download.default_directory': download_dir,
            'download.prompt_for_download': False,
            'download.directory_upgrade': True,
            'safebrowsing.enabled': False
        }
        options.add_experimental_option('prefs', prefs)
        
        # ChromeDriver 서비스 설정
        service = webdriver.ChromeService(executable_path='/usr/local/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=options)
        
        try:
            # 로그인 시도
            if not login_to_teads(driver, email, password):
                logger.error(f"[teads] '{cred.alias}' 계정 로그인 실패")
                return None
                
            logger.info(f"[teads] '{cred.alias}' 계정 로그인 성공")

            # 웹페이지 URL을 통해 데이터 직접 수집
            if fetch_teads_data_via_url(driver, cred, start_date, end_date):
                logger.info(f"[teads] 데이터 수집 완료")
            else:
                logger.error(f"[teads] 데이터 수집 실패")
                return None
            
            logger.info(f"[teads] '{cred.alias}' 계정 데이터 수집 완료")
            cred.last_fetched_at = timezone.now()
            cred.save()
            return True
            
        finally:            
            driver.quit()
            
    except Exception as e:
        logger.error(f"[teads] '{cred.alias}' 계정 데이터 수집 중 오류 발생: {str(e)}")
        return None 

def fetch_teads_data_via_url(driver, cred, start_date, end_date):
    """
    웹페이지 URL을 통해 teads 데이터를 직접 가져오는 함수
    """
    try:
        logger.info(f"[teads] fetch_teads_data_via_url 함수 시작")
        logger.info(f"[teads] 계정: {cred.alias}, 시작일: {start_date}, 종료일: {end_date}")
        
        # 로그인 후 쿠키 가져오기
        cookies = driver.get_cookies()
        session = requests.Session()
        
        # 쿠키를 requests 세션에 추가
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
            # logger.info(f"[teads] 쿠키 설정: {cookie['name']} = {cookie['value'][:20]}...")  # 쿠키 값이 길어질 수 있음
        
        # 웹페이지 URL 구성 (AJAX 요청 URL)
        data_url = "https://publishers.teads.tv/reportV2/api/finance"
        
        # 파라미터 구성 (대괄호로 감싸야 함)
        params = {
            'startDate': start_date.strftime('%Y-%m-%dT00:00:00Z'),
            'endDate': end_date.strftime('%Y-%m-%dT23:59:59Z'),
            'sm': '[metricTotalEarnings,metricSoldImpressions]',
            'sd': '[dimensionDateAndTime,dimensionWebsite,dimensionPlacement]'
        }
        
        # 헤더 설정 (브라우저처럼 보이게)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            'Referer': 'https://publishers.teads.tv/report/finance',
            'Origin': 'https://publishers.teads.tv',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        # URL 호출 전 로깅
        logger.info(f"[teads] 데이터 URL 호출 시작: {data_url}")
        logger.info(f"[teads] 파라미터: {params}")
        logger.info(f"[teads] 쿠키 개수: {len(cookies)}")
        # logger.info(f"[teads] 세션 쿠키: {dict(session.cookies)}")  # 쿠키 값이 길어질 수 있음
        
        # 웹페이지 URL 호출
        response = session.get(data_url, params=params, headers=headers)
        
        # 응답 상태 로깅
        logger.info(f"[teads] 응답 상태: {response.status_code}")
        # logger.info(f"[teads] 응답 헤더: {dict(response.headers)}")  # 헤더 정보가 길어질 수 있음
        
        if response.status_code != 200:
            logger.error(f"[teads] URL 호출 실패: {response.status_code}")
            logger.error(f"[teads] 응답 내용: {response.text}")
            raise Exception(f"URL 호출 실패: {response.status_code} - {response.text}")
        
        # JSON 응답 파싱
        try:
            data = response.json()
            logger.info(f"[teads] JSON 파싱 성공")
        except Exception as e:
            logger.error(f"[teads] JSON 파싱 실패: {str(e)}")
            # logger.error(f"[teads] 응답 내용: {response.text}")  # 응답 내용이 길어질 수 있음
            raise Exception(f"JSON 파싱 실패: {str(e)}")
        
        # 데이터 처리 및 저장
        if process_teads_data(data, cred):
            logger.info(f"[teads] 데이터 처리 완료")
            return True
        else:
            logger.error(f"[teads] 데이터 처리 실패")
            return False
            
    except Exception as e:
        logger.error(f"[teads] 데이터 수집 중 오류 발생: {str(e)}")
        logger.error(f"[teads] 오류 상세: {type(e).__name__}: {str(e)}")
        return False
    finally:
        logger.info(f"[teads] fetch_teads_data_via_url 함수 종료")

def process_teads_data(data, cred):
    """
    Teads 웹페이지 응답 데이터를 처리하고 저장하는 함수
    """
    try:
        # logger.info(f"[teads] API 응답 데이터 구조: {json.dumps(data, indent=2)}")  # 응답 데이터가 길어질 수 있음
        
        # Teads 웹페이지 응답 구조에 따라 데이터 추출
        # Teads 응답 구조: {"data": {"stats": [...], "columns": [...], ...}}
        data_items = []
        
        if 'data' in data and 'stats' in data['data']:
            data_items = data['data']['stats']
            # 통화 정보 로깅
            currency = data['data'].get('currency', 'Unknown')
            time_group = data['data'].get('timeGroupBy', 'Unknown')
            logger.info(f"[teads] 통화: {currency}, 시간 그룹: {time_group}")
        elif 'data' in data:
            data_items = data['data']
        elif 'rows' in data:
            data_items = data['rows']
        elif 'results' in data:
            data_items = data['results']
        else:
            # 최상위 레벨에 데이터가 있는 경우
            if isinstance(data, list):
                data_items = data
            else:
                # logger.error(f"[teads] 웹페이지 응답에서 데이터를 찾을 수 없음: {data}")  # 응답 데이터가 길어질 수 있음
                logger.error(f"[teads] 웹페이지 응답에서 데이터를 찾을 수 없음")
                return False
        
        if not data_items:
            logger.warning(f"[teads] API 응답에 데이터 항목이 없음")
            return True
        
        processed_count = 0
        
        # 데이터 처리
        for item in data_items:
            try:
                # 날짜 파싱 - Teads 웹페이지는 Unix timestamp (밀리초) 사용
                if 'time' in item:
                    # Unix timestamp를 datetime으로 변환
                    timestamp_ms = item['time']
                    date = pd.to_datetime(timestamp_ms, unit='ms').date()
                else:
                    # 기존 방식 지원
                    date_str = None
                    for date_field in ['date', 'day', 'dateTime', 'dimensionDateAndTime']:
                        if date_field in item:
                            date_str = item[date_field]
                            break
                    
                    if not date_str:
                        logger.warning(f"[teads] 날짜 필드를 찾을 수 없음: {item}")
                        continue
                        
                    date = pd.to_datetime(date_str).date()
                
                # content_id 생성 - Teads 웹페이지는 websiteName 사용
                content_id = str(item.get('websiteName', ''))
                
                # ad_unit_id 생성 - Teads 웹페이지는 placementName 사용
                ad_unit_id = str(item.get('placementName', ''))
                
                # 수익 및 노출수 - Teads 웹페이지 필드명 사용
                earnings = float(item.get('earnings', 0))
                impressions = int(item.get('soldImpressions', 0))
                
                # 데이터 업데이트 또는 생성
                AdStats.objects.update_or_create(
                    user=cred.user,
                    platform="teads",
                    alias=cred.alias,
                    date=date,
                    content_id=content_id,
                    ad_unit_id=ad_unit_id,
                    defaults={
                        'content_id': content_id,
                        'ad_unit_name': ad_unit_id,
                        'earnings': earnings,
                        'impressions': impressions,
                        'credential': cred
                    }
                )
                
                processed_count += 1
                
                # 상세 로깅 (디버깅용)
                # logger.info(f"[teads] 데이터 처리: {date} | {content_id} | {ad_unit_id} | 수익: {earnings:,.0f}원 | 노출수: {impressions:,}")  # 각 항목마다 로그가 길어질 수 있음
                
            except Exception as e:
                # logger.error(f"[teads] 데이터 항목 처리 중 오류 발생: {str(e)} - 항목: {item}")  # 항목 데이터가 길어질 수 있음
                logger.error(f"[teads] 데이터 항목 처리 중 오류 발생: {str(e)}")
                continue
        
        logger.info(f"[teads] 총 {processed_count}개 데이터 항목 처리 완료")
        return True
        
    except Exception as e:
        logger.error(f"[teads] 웹페이지 데이터 처리 중 오류 발생: {str(e)}")
        return False 