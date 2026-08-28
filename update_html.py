import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import re
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =====================================================================
API_KEY_G2B = "여기에_조달청_인코딩_키를_넣어주세요"
# =====================================================================

CATEGORY_RULES = {
    "AI": ["AI", "인공지능", "딥러닝", "머신러닝", "비전", "알고리즘", "데이터", "빅데이터", "플랫폼", "SW", "자율", "지능형", "제어"],
    "소부장": ["장비", "공정", "반도체", "센서", "배터리", "이차전지", "로봇", "자동화", "검사", "카메라", "모듈", "기구", "설계", "컨베이어", "시제품", "가공", "동력", "프레임", "무인", "방산", "기계", "핸들러"],
    "용역": ["연구", "개발", "R&D", "구축", "실증", "기획", "분석", "표준화", "시험", "용역", "폐기물", "공사", "구매"]
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

# ----------------- [크롤러] 한국기계연구원 (KIMM) -----------------
def scrape_kimm():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://www.kimm.re.kr/bidding", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) >= 7:
                title_elem = cols[2].find("a")
                if not title_elem: continue
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                if link.startswith("/"): link = "https://www.kimm.re.kr" + link
                
                close_dt = cols[6].get_text(strip=True)
                category, matched = classify_target(title)
                items.append({
                    "org": "한국기계연구원", "category": category,
                    "cat_class": "cat-cons", "title": title,
                    "tags": "#출연연공고", "budget": "공고문 참조",
                    "close_date": close_dt, "dday_text": "진행중",
                    "dday_class": "dday-safe", "url": link
                })
    except Exception as e:
        pass
    return items

# ----------------- [API] 조달청(G2B) -----------------
def fetch_g2b_api():
    items = []
    try:
        KST = timezone(timedelta(hours=9))
        now = datetime.now(KST)
        bgn_dt = (now - timedelta(days=7)).strftime("%Y%m%d0000")
        end_dt = now.strftime("%Y%m%d2359")
        
        # 탐색 범위를 999건으로 대폭 확대
        url = f"http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01?serviceKey={API_KEY_G2B}&numOfRows=999&pageNo=1&inqryDiv=1&inqryBgnDt={bgn_dt}&inqryEndDt={end_dt}&type=json"
        
        res = requests.get(url, verify=False, timeout=20)
        if res.status_code == 200 and not res.text.startswith("<"):
            data = res.json()
            bids = data.get("response", {}).get("body", {}).get("items", [])
            
            target_orgs = ["생산기술연구원", "로봇산업진흥원", "국방기술품질원", "과학기술"]
            target_kws = ["컨베이어", "모듈", "검사", "자동화", "장비", "제어"]
            
            for bid in bids:
                org_name = bid.get('dminsttNm', '조달청')
                title = bid.get('bidNtceNm', '')
                
                is_target_org = any(org in org_name for org in target_orgs)
                is_target_kw = any(kw in title for kw in target_kws)
                
                if is_target_org or is_target_kw:
                    category, matched = classify_target(title)
                    items.append({
                        "org": org_name[:12], "category": category if category != "일반" else "소부장",
                        "cat_class": "cat-rd", "title": title,
                        "tags": "#조달청(매칭)", "budget": "공고문 참조",
                        "close_date": bid.get('bidClseDt', '미정')[:8],
                        "dday_text": "진행중", "dday_class": "dday-safe",
                        "url": bid.get('ntceInsttDturl', 'https://www.g2b.go.kr')
                    })
            
            # [안전장치] 만약 필터링 후 조건에 맞는 게 0건이라면, 무조건 최신 2건을 집어넣어 API 통신 증명
            if len(items) == 0 and len(bids) > 0:
                for i in range(min(2, len(bids))):
                    items.append({
                        "org": bids[i].get('dminsttNm', '조달청')[:12],
                        "category": "일반", "cat_class": "cat-general",
                        "title": bids[i].get('bidNtceNm', ''),
                        "tags": "#API통신_테스트_성공", "budget": "-",
                        "close_date": bids[i].get('bidClseDt', '미정')[:8],
                        "dday_text": "테스트", "dday_class": "dday-safe",
                        "url": bids[i].get('ntceInsttDturl', 'https://www.g2b.go.kr')
                    })
    except Exception as e:
        print(f"API 에러: {e}")
    return items

def update_html():
    bids = scrape_kimm() + fetch_g2b_api()
    
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    KST = timezone(timedelta(hours=9))
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    
    # 시간 강제 치환 (형식이 깨져있어도 무조건 덮어쓰도록 정규식 완화)
    html = re.sub(r'(<div[^>]*id="metaSync"[^>]*>).*?(</div>)', rf'\1<strong>최근 동기화:</strong> {now_str} (전면 재정비 가동)\2', html, flags=re.DOTALL)

    if bids:
        rows_html = ""
        for b in bids:
            rows_html += f"""
        <tr>
          <td><span class="badge-org">{b['org']}</span></td>
          <td class="title-cell"><a href="{b['url']}" target="_blank">{b['title']}</a><br><small>{b['tags']}</small></td>
          <td><strong>{b['budget']}</strong></td>
          <td><span class="{b['dday_class']}">{b['dday_text']}</span></td>
          <td><a href="{b['url']}" target="_blank">공고문 ↗</a></td>
        </tr>"""
        
        # <tbody> 치환
        html = re.sub(r'<tbody>.*?</tbody>', f'<tbody>\n{rows_html}\n      </tbody>', html, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    update_html()
