import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
from datetime import datetime, timedelta
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def clean_key(key_str):
    if not key_str: return ""
    return urllib.parse.unquote(urllib.parse.unquote(key_str.strip()))

G2B_KEY = clean_key(os.getenv("G2B_API_KEY", ""))

def get_api_diagnostic(url, params):
    """API 통신 상태를 정밀 진단하여 콘솔에 출력하는 함수"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    print(f"\n[테스트 중...] {url[:60]}...")
    
    try:
        res = requests.get(url, params=params, headers=headers, verify=False, timeout=15)
        print(f" -> HTTP 상태 코드: {res.status_code}")
        
        # 1. 정상 통신이나 XML(에러) 폼이 날아온 경우
        if res.text.strip().startswith("<"):
            print(f" -> ❌ [API 키/권한 에러 발생] 서버 응답 내용: {res.text[:300]}")
            return []
            
        # 2. JSON 정상 수신
        data = res.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        if not items:
            print(f" -> ⚠️ [데이터 0건] 통신과 인증은 성공했으나 조건에 맞는 데이터가 없음.")
            return []
            
        if isinstance(items, dict): items = [items]
        print(f" -> ✅ [수집 성공] 데이터 {len(items)}건 확보!")
        return items
        
    except requests.exceptions.Timeout:
        print(" -> ❌ [시간 초과 에러] 공공데이터포털이 GitHub(해외 IP) 접속을 강제 차단했습니다.")
        return []
    except Exception as e:
        print(f" -> ❌ [기타 통신 에러]: {e}")
        return []

def run_diagnostics():
    if not G2B_KEY:
        print("❌ G2B_API_KEY 시크릿이 설정되지 않았습니다.")
        return

    today = datetime.today()
    start_str = (today - timedelta(days=5)).strftime("%Y%m%d0000")
    end_str = today.strftime("%Y%m%d2359")
    
    url = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01"
    params = {"serviceKey": G2B_KEY, "numOfRows": "10", "pageNo": "1", "inqryDiv": "1", "inqryBgnDt": start_str, "inqryEndDt": end_str, "type": "json"}
    
    print("================ API 통신 진단 시작 ================")
    get_api_diagnostic(url, params)
    print("====================================================")

if __name__ == "__main__":
    run_diagnostics()
