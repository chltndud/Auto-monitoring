import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
from datetime import datetime, timedelta
import re
import urllib3

# 웹 크롤링 시 SSL 경고 무시
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVICE_KEY = os.getenv("G2B_API_KEY", "").strip()
if "%" in SERVICE_KEY:
    SERVICE_KEY = urllib.parse.unquote(SERVICE_KEY)

# 융합된 전문 도메인 키워드 분류 (연구소 핵심 매칭)
CATEGORY_RULES = {
    "AI": ["AI", "인공지능", "딥러닝", "머신러닝", "비전", "알고리즘", "데이터", "플랫폼", "SW", "자율"],
    "소부장": ["장비", "공정", "반도체", "센서", "배터리", "이차전지", "로봇", "자동화", "검사", "카메라", "모듈", "기구설계", "컨베이어", "시제품", "가공", "동력", "프레임", "무인", "방산"],
    "용역": ["연구", "개발", "R&D", "구축", "실증", "기획", "분석", "설계 용역"]
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
    # 키워드가 매칭되지 않은 수많은 공고들은 '일반' 카테고리로 밀어넣어 전체보기에만 표출
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

def scrape_kimm_bids():
    """한국기계연구원 입찰공고 게시판 라이브 웹 크롤링"""
    items = []
    url = "https://www.kimm.re.kr/bidding"
    try:
        # 봇 차단을 우회하기 위한 브라우저 헤더 설정
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"}
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        rows = soup.select("table tbody tr")
        if not rows:
            rows = soup.find_all("tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 7:
                title_elem = cols[2].find("a")
                if not title_elem:
                    continue
                    
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                if link.startswith("/"):
                    link = "https://www.kimm.re.kr" + link
                    
                close_dt = cols[6].get_text(strip=True)
                
                category, matched_kws = classify_target(title)
                tags_str = " ".join([f"#{k}" for k in matched_kws[:3]]) if matched_kws else "#출연연공고"
                cat_class = "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid" if category == "용역" else "cat-general"
                
                dday_label, dday_class = calculate_dday(close_dt.replace("-", ""))
                
                # 이미 마감된 공고는 필터링
                if dday_label == "마감":
                    continue

                items.append({
                    "org": "한국기계연구원",
                    "category": category,
                    "cat_class": cat_class,
                    "title": title,
                    "tags": tags_str,
                    "budget": "공고문 참조",
                    "close_date": close_dt,
                    "dday_text": dday_label,
                    "dday_class": dday_class,
                    "url": link
                })
    except Exception as e:
        print(f"한국기계연구원 크롤링 에러: {e}")
    return items

def fetch_g2b_period(url, start_dt, end_dt):
    """나라장터 조달 데이터를 조각 단위로 수집"""
    params = {
        "serviceKey": SERVICE_KEY,
        "numOfRows": "200", # 한 번에 최대한 많은 일반 공고 확보
        "pageNo": "1",
        "inqryDiv": "1",
        "inqryBgnDt": start_dt,
        "inqryEndDt": end_dt,
        "type": "json"
    }
    try:
        res = requests.get(url, params=params, timeout=20)
        if res.text.strip().startswith("<"): return []
        data = res.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict): return [items]
        return items or []
    except Exception as e:
        print(f"G2B API 에러: {e}")
        return []

def fetch_all_g2b_bids():
    """조건 필터 없이 나라장터의 모든 용역/물품 입찰을 쓸어 담는 함수"""
    if not SERVICE_KEY: return []
    
    servc_url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01"
    thng_url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch01"
    
    today = datetime.today()
    all_raw_items = []
    
    # 조달청 30일 제약을 피해 최근 14일치를 7일씩 안전하게 나눠서 대량 호출
    for i in range(2):
        chunk_end = today - timedelta(days=i * 7)
        chunk_start = today - timedelta(days=(i + 1) * 7)
        start_str = chunk_start.strftime("%Y%m%d0000")
        end_str = chunk_end.strftime("%Y%m%d2359")
        
        all_raw_items += fetch_g2b_period(servc_url, start_str, end_str)
        all_raw_items += fetch_g2b_period(thng_url, start_str, end_str)
        
    items = []
    seen_ids = set()

    for item in all_raw_items:
        bid_name = item.get("bidNtceNm", "")
        bid_no = item.get("bidNtceNo", "")
        bid_ord = item.get("bidNtceOrd", "00")
        
        if not bid_name or not bid_no: continue

        # 중복 공고문 배제
        unique_id = f"{bid_no}-{bid_ord}"
        if unique_id in seen_ids: continue
        seen_ids.add(unique_id)

        # 여기서 타깃 카테고리가 아니면 '일반'으로 분류됨
        category, matched_kws = classify_target(bid_name)
        
        # 새 창 이동 오류를 방지하기 위해 생성하는 완벽한 직통 URL
        direct_url = f"https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={bid_no}&bidseq={bid_ord}&releaseYn=Y&taskClCd=5"

        tags_str = " ".join([f"#{k}" for k in matched_kws[:3]]) if matched_kws else "#일반공고"
        
        if category == "AI": cat_class = "cat-rd"
        elif category == "소부장": cat_class = "cat-cons"
        elif category == "용역": cat_class = "cat-bid"
        else: cat_class = "cat-general"

        try:
            price_val = float(item.get("presmptPrce", 0) or item.get("bdgtAmt", 0) or 0)
            if price_val >= 100000000:
                budget_str = f"{price_val / 100000000:.1f} 억원"
            elif price_val > 0:
                budget_str = f"{int(price_val / 10000):,} 만원"
            else:
                budget_str = "조달청 기준 참조"
        except Exception:
            budget_str = "조달청 기준 참조"

        close_dt = item.get("bidClseDt", "-")
        dday_label, dday_class = calculate_dday(close_dt)

        items.append({
            "org": (item.get("dminsttNm") or item.get("orderInsttNm") or "조달청")[:12],
            "category": category,
            "cat_class": cat_class,
            "title": bid_name,
            "tags": tags_str,
            "budget": budget_str,
            "close_date": close_dt[:10],
            "dday_text": dday_label,
            "dday_class": dday_class,
            "url": direct_url
        })
    return items

def update_html():
    # 1. 크롤링(웹 직접 탐색) 데이터와 2. G2B 공공데이터 API 데이터를 하나로 융합
    bids = scrape_kimm_bids() + fetch_all_g2b_bids()

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync"><strong>최근 동기화:</strong> {now_str} (통합 크롤링/API 연동)</div>', html)

    # 4대 지표 카드 업데이트
    total_cnt = len(bids)
    urgent_cnt = sum(1 for b in bids if "urgent" in b["dday_class"])
    team_target_cnt = sum(1 for b in bids if b["category"] in ["AI", "소부장", "용역"])
    
    html = re.sub(r'id="statTotal">.*?<span', f'id="statTotal">{total_cnt} <span', html)
    html = re.sub(r'id="statUrgent">.*?<span', f'id="statUrgent">{urgent_cnt} <span', html)
    html = re.sub(r'id="statAi">.*?<span', f'id="statAi">{team_target_cnt} <span', html)

    if bids:
        rows_html = ""
        for b in bids:
            # target="_blank" rel="noopener noreferrer" 속성을 통해 보안 및 링킹 에러 방지
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
    print("업데이트 완료")

if __name__ == "__main__":
    update_html()
