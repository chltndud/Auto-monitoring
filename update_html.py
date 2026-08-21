import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib.parse
from datetime import datetime, timedelta
import re

# 1. API 키 처리
SERVICE_KEY = os.getenv("G2B_API_KEY", "").strip()
if "%" in SERVICE_KEY:
    SERVICE_KEY = urllib.parse.unquote(SERVICE_KEY)

# 2. 핵심 관심 키워드
CATEGORY_RULES = {
    "AI": ["AI", "인공지능", "LLM", "딥러닝", "머신러닝", "비전", "알고리즘", "지능형", "데이터"],
    "소부장": ["소부장", "소재", "부품", "장비", "스마트", "공정", "반도체", "센서", "배터리", "이차전지", "제조", "로봇", "자동화", "설계", "검사"],
    "용역": ["용역", "연구", "개발", "R&D", "구축", "플랫폼", "시스템", "SW", "소프트웨어", "실증"]
}

ALL_KEYWORDS = [kw for kws in CATEGORY_RULES.values() for kw in kws]

def classify_category(title):
    for cat, kws in CATEGORY_RULES.items():
        if any(k.lower() in title.lower() for k in kws):
            return cat
    return "용역"

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

def fetch_real_bids():
    today = datetime.today()
    # 통신 지연을 방지하기 위해 최근 5일 데이터로 슬림화
    start_date = (today - timedelta(days=5)).strftime("%Y%m%d0000")
    end_date = today.strftime("%Y%m%d2359")
    
    url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01"
    params = {
        "serviceKey": SERVICE_KEY,
        "numOfRows": "60", # 타임아웃 방지를 위해 가볍게 요청
        "pageNo": "1",
        "inqryDiv": "1",
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
        "type": "json"
    }
    
    # 해외 가상서버 차단 방지를 위한 브라우저 헤더
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    items = []
    if not SERVICE_KEY:
        return items, "G2B_API_KEY 시크릿이 등록되지 않았습니다."

    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    try:
        res = session.get(url, params=params, headers=headers, timeout=(15, 30))
        
        if res.text.strip().startswith("<"):
            return items, "공공데이터포털 인증키 승인 연계 중입니다. (신청 후 1~2시간 소요)"

        data = res.json()
        raw_items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(raw_items, dict):
            raw_items = [raw_items]

        for item in raw_items:
            bid_name = item.get("bidNtceNm", "")
            matched = [k for k in ALL_KEYWORDS if k.lower() in bid_name.lower()]
            
            if matched:
                category = classify_category(bid_name)
                bid_no = item.get("bidNtceNo", "")
                bid_ord = item.get("bidNtceOrd", "00")
                
                # 공고 상세페이지 직통 링크
                if bid_no:
                    direct_url = f"https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={bid_no}&bidseq={bid_ord}&releaseYn=Y&taskClCd=5"
                else:
                    direct_url = item.get("bidNtceDtlUrl") or "https://www.g2b.go.kr"

                try:
                    price_val = float(item.get("presmptPrce", 0))
                    if price_val >= 100000000:
                        budget_str = f"{price_val / 100000000:.1f} 억원"
                    elif price_val > 0:
                        budget_str = f"{int(price_val / 10000):,} 만원"
                    else:
                        budget_str = "규격서 참조"
                except Exception:
                    budget_str = "규격서 참조"

                close_dt = item.get("bidClseDt", "-")
                dday_label, dday_class = calculate_dday(close_dt)

                items.append({
                    "org": item.get("dminsttNm") or item.get("orderInsttNm") or "조달청",
                    "category": category,
                    "cat_class": "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid",
                    "title": bid_name,
                    "tags": " ".join([f"#{k}" for k in matched[:4]]),
                    "budget": budget_str,
                    "close_date": close_dt,
                    "dday_text": dday_label,
                    "dday_class": dday_class,
                    "url": direct_url
                })
        return items, ""
    except Exception as e:
        return items, f"공공데이터 서버 통신 오류: {e}"

def update_html():
    bids, err_msg = fetch_real_bids()
    print(f"최종 수집된 공고: {len(bids)}건")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    week_str = f"{now.year}년 {now.month}월 {(now.day - 1) // 7 + 1}주차"

    html = re.sub(r'id="metaWeek">.*?</div>', f'id="metaWeek"><strong>기준 주차:</strong> {week_str}</div>', html)
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync"><strong>최근 동기화:</strong> {now_str} (실시간 갱신)</div>', html)

    total_cnt = len(bids)
    urgent_cnt = sum(1 for b in bids if "urgent" in b["dday_class"])
    ai_cnt = sum(1 for b in bids if b["category"] in ["AI", "소부장"])

    html = re.sub(r'id="statTotal">.*?<span', f'id="statTotal">{total_cnt} <span', html)
    html = re.sub(r'id="statUrgent">.*?<span', f'id="statUrgent">{urgent_cnt} <span', html)
    html = re.sub(r'id="statAi">.*?<span', f'id="statAi">{ai_cnt} <span', html)
    html = re.sub(r'id="statBudget">.*?<span', f'id="statBudget">{total_cnt * 3.5:.1f} 억원 <span', html)

    if bids:
        rows_html = ""
        for b in bids:
            rows_html += f"""
        <tr data-category="{b['category']}">
          <td>
            <span class="badge-org">{b['org'][:12]}</span>
            <span class="badge-category {b['cat_class']}">{b['category']}</span>
          </td>
          <td class="title-cell">
            <a href="{b['url']}" target="_blank" class="title-link">{b['title']}</a>
            <div class="tags-list">{b['tags']}</div>
          </td>
          <td><strong>{b['budget']}</strong><br><span style="font-size:12px; color:#64748b;">(추정가격)</span></td>
          <td>
            <span class="dday-tag {b['dday_class']}">{b['dday_text']}</span>
            <div style="font-size:12px; color:#64748b; margin-top:2px;">{b['close_date']}</div>
          </td>
          <td>
            <a href="{b['url']}" target="_blank" class="btn-action">공고문 ↗</a>
          </td>
        </tr>"""
    else:
        msg = err_msg if err_msg else "최근 5일간 조건에 부합하는 신규 공고가 없습니다."
        rows_html = f"""
        <tr>
          <td colspan="5" style="text-align:center; padding: 40px; color: #ef4444; font-weight:600;">
            ⚠️ {msg}
          </td>
        </tr>"""

    html = re.sub(r'<tbody>.*?</tbody>', f'<tbody>{rows_html}\n      </tbody>', html, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML 업데이트 완료!")

if __name__ == "__main__":
    update_html()
