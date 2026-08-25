import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
from datetime import datetime, timedelta
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. API 키 로드 (인코딩/디코딩 충돌 방지)
G2B_KEY = urllib.parse.unquote(os.getenv("G2B_API_KEY", "").strip())
IRIS_KEY = urllib.parse.unquote(os.getenv("IRIS_API_KEY", "").strip()) or G2B_KEY
NB_KEY = urllib.parse.unquote(os.getenv("NB_API_KEY", "").strip()) or G2B_KEY
SB_KEY = urllib.parse.unquote(os.getenv("SB_API_KEY", "").strip()) or G2B_KEY

# 2. 핵심 타깃 키워드
CATEGORY_RULES = {
    "AI": ["AI", "인공지능", "딥러닝", "머신러닝", "비전", "알고리즘", "데이터", "빅데이터", "플랫폼", "SW", "자율", "지능형"],
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

# [핵심 픽스] API 파라미터 수동 조립 함수 (requests 자동 인코딩 에러 원천 차단)
def fetch_api_safe(base_url, key, params_dict):
    if not key: return None
    # 키를 한 번 인코딩해서 URL에 직접 박아넣음
    encoded_key = urllib.parse.quote(key)
    query_string = "&".join([f"{k}={v}" for k, v in params_dict.items()])
    full_url = f"{base_url}?serviceKey={encoded_key}&{query_string}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(full_url, headers=headers, timeout=20, verify=False)
        if res.text.strip().startswith("<"): 
            return None # XML 에러 방어
        return res.json().get("response", {}).get("body", {}).get("items", [])
    except Exception as e:
        print(f"API 에러 ({base_url}): {e}")
        return None

# [수집 1] G2B 나라장터 API
def fetch_g2b():
    items = []
    today = datetime.today()
    start_str = (today - timedelta(days=14)).strftime("%Y%m%d0000")
    end_str = today.strftime("%Y%m%d2359")
    
    endpoints = [
        "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01",
        "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch01"
    ]
    
    for url in endpoints:
        params = {"numOfRows": "100", "pageNo": "1", "inqryDiv": "1", "inqryBgnDt": start_str, "inqryEndDt": end_str, "type": "json"}
        raw = fetch_api_safe(url, G2B_KEY, params)
        if not raw: continue
        if isinstance(raw, dict): raw = [raw]
        
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
                "budget": "조달청 기준",
                "close_date": str(item.get("bidClseDt", "-"))[:10],
                "dday_text": dday_label,
                "dday_class": dday_class,
                "url": direct_url
            })
    return items

# [수집 2] 다양한 사이트 웹 크롤링 확장 (한국기계연구원, 한국생산기술연구원, 한국전자통신연구원)
def scrape_research_institutes():
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    # 1. KIMM (한국기계연구원)
    try:
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
                close_dt = cols[6].get_text(strip=True)
                
                category, matched = classify_target(title)
                dday_label, dday_class = calculate_dday(close_dt.replace("-", ""))
                if dday_label != "마감":
                    items.append({
                        "org": "한국기계연구원",
                        "category": category,
                        "cat_class": "cat-cons",
                        "title": title,
                        "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#출연연",
                        "budget": "공고문 참조",
                        "close_date": close_dt,
                        "dday_text": dday_label,
                        "dday_class": dday_class,
                        "url": link
                    })
    except Exception as e:
        print(f"KIMM 크롤링 오류: {e}")

    # 2. ETRI (한국전자통신연구원) 모의 크롤링
    try:
        res = requests.get("https://www.etri.re.kr/kor/bbs/list.etri?b_board_id=ETRI08", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select(".board_list tbody tr"):
            title_elem = row.select_one(".subject a")
            if not title_elem: continue
            title = title_elem.get_text(strip=True)
            link = "https://www.etri.re.kr" + title_elem.get("href", "")
            date_text = row.select_one(".date").get_text(strip=True) if row.select_one(".date") else "-"
            
            category, matched = classify_target(title)
            items.append({
                "org": "한국전자통신연구원",
                "category": category,
                "cat_class": "cat-rd",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#ETRI",
                "budget": "공고문 참조",
                "close_date": date_text,
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"ETRI 크롤링 오류: {e}")

    return items

def update_html():
    # API 공고 + 확장된 웹 크롤링 공고 병합
    bids = fetch_g2b() + scrape_research_institutes()

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync"><strong>최근 동기화:</strong> {now_str} (통합 API/크롤러 연동)</div>', html)

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
    print(f"총 {len(bids)}건 통합 수집 완료!")

if __name__ == "__main__":
    update_html()
