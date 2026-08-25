import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
from datetime import datetime, timedelta
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. API 키 완전 해독 (더블 인코딩 에러 방지)
def clean_key(key_str):
    if not key_str: return ""
    return urllib.parse.unquote(urllib.parse.unquote(key_str.strip()))

G2B_KEY = clean_key(os.getenv("G2B_API_KEY", ""))
IRIS_KEY = clean_key(os.getenv("IRIS_API_KEY", "")) or G2B_KEY
NB_KEY = clean_key(os.getenv("NB_API_KEY", "")) or G2B_KEY
SB_KEY = clean_key(os.getenv("SB_API_KEY", "")) or G2B_KEY

# 2. 팀 타깃 키워드 분류
CATEGORY_RULES = {
    "AI": ["AI", "인공지능", "딥러닝", "머신러닝", "비전", "알고리즘", "데이터", "빅데이터", "플랫폼", "SW", "자율", "지능형", "예지보전", "디지털트윈"],
    "소부장": ["장비", "공정", "반도체", "센서", "배터리", "이차전지", "로봇", "자동화", "검사", "카메라", "모듈", "기구", "설계", "컨베이어", "시제품", "가공", "동력", "프레임", "무인", "방산", "기계"],
    "용역": ["연구", "개발", "R&D", "구축", "실증", "기획", "분석", "표준화", "시험", "ISP", "용역"]
}

def classify_target(title):
    matched_tags = []
    found_cat = None
    for cat, kws in CATEGORY_RULES.items():
        matched = [k for k in kws if k.lower() in title.lower()]
        if matched:
            if not found_cat: found_cat = cat
            matched_tags.extend(matched)
            
    if found_cat:
        return found_cat, list(set(matched_tags))
    return "일반", []

def calculate_dday(close_dt_str):
    try:
        clean_str = re.sub(r'[^0-9]', '', str(close_dt_str))[:8]
        if len(clean_str) == 8:
            close_date = datetime.strptime(clean_str, "%Y%m%d").date()
            today = datetime.now().date()
            diff = (close_date - today).days
            if diff < 0: return "마감", "dday-urgent"
            elif diff == 0: return "D-Day", "dday-urgent"
            elif diff <= 7: return f"D-{diff}", "dday-urgent"
            elif diff <= 14: return f"D-{diff}", "dday-normal"
            else: return f"D-{diff}", "dday-safe"
    except Exception:
        pass
    return "진행중", "dday-safe"

def get_api_data(url, params):
    """해외 가상서버(GitHub) 차단 우회를 위해 http 통신 및 헤더 위장 적용"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"}
    try:
        res = requests.get(url, params=params, headers=headers, verify=False, timeout=25)
        if res.text.strip().startswith("<"): 
            print(f"[XML 에러 응답] {url[:50]}... 키 오류 또는 트래픽 초과")
            return []
        data = res.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict): items = [items]
        return items or []
    except Exception as e:
        print(f"[통신 에러] {url[:50]}... : {e}")
        return []

# [수집 1] G2B 나라장터 (http 로 변경)
def fetch_g2b():
    if not G2B_KEY: return []
    items = []
    today = datetime.today()
    start_str = (today - timedelta(days=14)).strftime("%Y%m%d0000")
    end_str = today.strftime("%Y%m%d2359")
    
    endpoints = [
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01",
        "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch01"
    ]
    
    for url in endpoints:
        params = {"serviceKey": G2B_KEY, "numOfRows": "100", "pageNo": "1", "inqryDiv": "1", "inqryBgnDt": start_str, "inqryEndDt": end_str, "type": "json"}
        raw = get_api_data(url, params)
        for item in raw:
            title = item.get("bidNtceNm", "")
            bid_no = item.get("bidNtceNo", "")
            bid_ord = item.get("bidNtceOrd", "00")
            if not title or not bid_no: continue
            
            category, matched = classify_target(title)
            direct_url = f"https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={bid_no}&bidseq={bid_ord}&releaseYn=Y&taskClCd=5"
            dday_label, dday_class = calculate_dday(item.get("bidClseDt", "-"))
            
            items.append({
                "org": (item.get("dminsttNm") or item.get("orderInsttNm") or "조달청")[:12],
                "category": category,
                "cat_class": "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid" if category == "용역" else "cat-general",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#일반공고",
                "budget": "조달청 참조",
                "close_date": str(item.get("bidClseDt", "-"))[:10],
                "dday_text": dday_label,
                "dday_class": dday_class,
                "url": direct_url
            })
    return items

# [수집 2] IRIS 범부처 국가 R&D
def fetch_iris():
    if not IRIS_KEY: return []
    items = []
    url = "http://apis.data.go.kr/1741000/NationalRnDNoticeInfoService/getRnDNoticeList"
    params = {"serviceKey": IRIS_KEY, "numOfRows": "50", "pageNo": "1", "type": "json"}
    raw = get_api_data(url, params)
    for item in raw:
        title = item.get("pblancNm") or item.get("title", "")
        if not title: continue
        category, matched = classify_target(title)
        items.append({
            "org": "IRIS(범부처)",
            "category": category if category != "일반" else "용역",
            "cat_class": "cat-rd" if category == "AI" else "cat-bid",
            "title": f"[국책R&D] {title}",
            "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#국가R&D",
            "budget": "과제 제안요청서",
            "close_date": str(item.get("receiptClseDt", "-"))[:10],
            "dday_text": "접수중",
            "dday_class": "dday-normal",
            "url": item.get("dtlUrl") or "https://www.iris.go.kr"
        })
    return items

# [수집 3] NB 남부발전
def fetch_nb():
    if not NB_KEY: return []
    items = []
    url = "http://apis.data.go.kr/B551893/BidInfoService/getBidList"
    params = {"serviceKey": NB_KEY, "numOfRows": "50", "pageNo": "1", "type": "json"}
    raw = get_api_data(url, params)
    for item in raw:
        title = item.get("bidNtceNm") or item.get("title", "")
        if not title: continue
        category, matched = classify_target(title)
        items.append({
            "org": "한국남부발전",
            "category": category,
            "cat_class": "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid" if category == "용역" else "cat-general",
            "title": f"[남부발전] {title}",
            "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#발전사",
            "budget": "공고문 참조",
            "close_date": str(item.get("bidClseDt", "-"))[:10],
            "dday_text": "진행중",
            "dday_class": "dday-safe",
            "url": "https://www.kospo.co.kr"
        })
    return items

# [수집 4] SB 중소벤처기업부
def fetch_sb():
    if not SB_KEY: return []
    items = []
    url = "http://apis.data.go.kr/B552735/kisedPblancService/getPblancList"
    params = {"serviceKey": SB_KEY, "numOfRows": "50", "pageNo": "1", "type": "json"}
    raw = get_api_data(url, params)
    for item in raw:
        title = item.get("pblancNm") or item.get("bizNm", "")
        if not title: continue
        category, matched = classify_target(title)
        items.append({
            "org": "중기부(SMTECH)",
            "category": category if category != "일반" else "용역",
            "cat_class": "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid",
            "title": f"[중기부지원] {title}",
            "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#정부지원사업",
            "budget": "사업안내서",
            "close_date": str(item.get("reqstEndDe", "-"))[:10],
            "dday_text": "접수중",
            "dday_class": "dday-safe",
            "url": item.get("detlUrl") or "https://www.smtech.go.kr"
        })
    return items

# [웹 크롤러] 한국기계연구원
def scrape_kimm():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get("https://www.kimm.re.kr/bidding", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select("table tbody tr") or soup.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) >= 7:
                title_elem = cols[2].find("a")
                if not title_elem: continue
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                if link.startswith("/"): link = "https://www.kimm.re.kr" + link
                
                category, matched = classify_target(title)
                dday_label, dday_class = calculate_dday(cols[6].get_text(strip=True).replace("-", ""))
                if dday_label != "마감":
                    items.append({
                        "org": "한국기계연구원",
                        "category": category,
                        "cat_class": "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid" if category == "용역" else "cat-general",
                        "title": title,
                        "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#출연연공고",
                        "budget": "공고문 참조",
                        "close_date": cols[6].get_text(strip=True),
                        "dday_text": dday_label,
                        "dday_class": dday_class,
                        "url": link
                    })
    except Exception as e:
        print(f"KIMM 크롤링 오류: {e}")
    return items

def update_html():
    bids = fetch_g2b() + fetch_iris() + fetch_nb() + fetch_sb() + scrape_kimm()
    
    # 디버깅 출력: 어떤 소스에서 몇 건이 수집되었는지 Actions 로그에서 확인 가능
    print(f"수집 결과 -> 총 {len(bids)}건 확보 완료.")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync"><strong>최근 동기화:</strong> {now_str} (통합 시스템 가동중)</div>', html)

    total_cnt = len(bids)
    urgent_cnt = sum(1 for b in bids if "urgent" in b["dday_class"])
    team_target_cnt = sum(1 for b in bids if b["category"] in ["AI", "소부장", "용역"])
    
    html = re.sub(r'id="statTotal">.*?<span', f'id="statTotal">{total_cnt} <span', html)
    html = re.sub(r'id="statUrgent">.*?<span', f'id="statUrgent">{urgent_cnt} <span', html)
    html = re.sub(r'id="statAi">.*?<span', f'id="statAi">{team_target_cnt} <span', html)

    if bids:
        rows_html = ""
        for b in bids:
            rows_html += f"""
        <tr data-category="{b['category']}">
          <td>
            <span class="badge-org">{b['org']}</span>
            <span class="badge-category {b['cat_class']}">{b['category']}</span>
          </td>
          <td class="title-cell">
            <a href="{b['url']}" target="_blank" rel="noopener noreferrer" class="title-link">{b['title']}</a>
            <div class="tags-list">{b['tags']}</div>
          </td>
          <td><strong>{b['budget']}</strong></td>
          <td>
            <span class="dday-tag {b['dday_class']}">{b['dday_text']}</span>
            <div style="font-size:12px; color:#64748b; margin-top:2px;">{b['close_date']}</div>
          </td>
          <td>
            <a href="{b['url']}" target="_blank" rel="noopener noreferrer" class="btn-action">공고문 ↗</a>
          </td>
        </tr>"""
        html = re.sub(r'<tbody>.*?</tbody>', f'<tbody>\n{rows_html}\n      </tbody>', html, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML 적용 완료")

if __name__ == "__main__":
    update_html()
