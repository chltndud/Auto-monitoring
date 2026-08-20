import os
import requests
import urllib.parse
from datetime import datetime, timedelta
import re

SERVICE_KEY = os.getenv("G2B_API_KEY", "").strip()
if "%" in SERVICE_KEY:
    SERVICE_KEY = urllib.parse.unquote(SERVICE_KEY)

CATEGORY_RULES = {
    "선행개발/AI": ["AI", "인공지능", "LLM", "딥러닝", "머신러닝", "비전", "자동화"],
    "소부장/공정": ["소부장", "스마트", "공정", "반도체", "이차전지", "제조", "컨베이어", "검사장비"],
    "국방/로봇": ["국방", "방산", "로봇", "무인", "다관절"],
    "용역입찰": ["용역", "ISP", "구축", "플랫폼", "데이터", "시스템", "개발"]
}

ALL_KEYWORDS = [kw for kws in CATEGORY_RULES.values() for kw in kws]

def classify_category(title):
    for cat, kws in CATEGORY_RULES.items():
        if any(k.lower() in title.lower() for k in kws):
            return cat
    return "기타"

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

def fetch_g2b_bids():
    """나라장터(G2B) API 수집 및 실제 공고 URL 매핑"""
    today = datetime.today()
    start_date = (today - timedelta(days=7)).strftime("%Y%m%d0000")
    end_date = today.strftime("%Y%m%d2359")
    
    url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01"
    params = {
        "serviceKey": SERVICE_KEY,
        "numOfRows": "100",
        "pageNo": "1",
        "inqryDiv": "1",
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
        "type": "json"
    }
    
    items = []
    if not SERVICE_KEY: return items

    try:
        res = requests.get(url, params=params, timeout=15)
        raw_items = res.json().get("response", {}).get("body", {}).get("items", [])
        if isinstance(raw_items, dict): raw_items = [raw_items]

        for item in raw_items:
            bid_name = item.get("bidNtceNm", "")
            matched = [k for k in ALL_KEYWORDS if k.lower() in bid_name.lower()]
            
            if matched:
                category = classify_category(bid_name)
                bid_no = item.get("bidNtceNo", "")
                bid_ord = item.get("bidNtceOrd", "00")
                
                # [수정 1] 실제 공고 상세페이지로 이동하는 정확한 다이렉트 URL 적용
                direct_url = f"https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={bid_no}&bidseq={bid_ord}&releaseYn=Y&taskClCd=5"

                price_val = float(item.get("presmptPrce", 0))
                budget_str = f"{price_val / 100000000:.1f} 억원" if price_val >= 100000000 else f"{int(price_val / 10000):,} 만원" if price_val > 0 else "규격서 참조"

                close_dt = item.get("bidClseDt", "-")
                dday_label, dday_class = calculate_dday(close_dt)

                items.append({
                    "org": item.get("dminsttNm") or item.get("orderInsttNm") or "조달청",
                    "category": category,
                    "cat_class": "cat-rd" if "AI" in category or "소부장" in category else "cat-bid",
                    "title": bid_name,
                    "tags": " ".join([f"#{k}" for k in matched[:4]]),
                    "budget": budget_str,
                    "close_date": close_dt,
                    "dday_text": dday_label,
                    "dday_class": dday_class,
                    "url": direct_url
                })
    except Exception as e:
        print(f"G2B Error: {e}")
    return items

def fetch_extra_bids():
    """
    [수정 2] 추가 사이트(IRIS, D2B 등) 모니터링 확장을 위한 빈 함수
    여기에 공공데이터포털 API 호출 로직을 추가하여 리스트 반환
    """
    return []

def update_html():
    # 데이터 병합
    bids = fetch_g2b_bids() + fetch_extra_bids()
    print(f"총 수집된 공고: {len(bids)}건")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")

    if bids:
        total_cnt = len(bids)
        urgent_cnt = sum(1 for b in bids if "urgent" in b["dday_class"])
        ai_cnt = sum(1 for b in bids if b["category"] in ["선행개발/AI", "소부장/공정"])

        html = re.sub(r'class="value text-blue">.*?<span', f'class="value text-blue">{total_cnt} <span', html)
        html = re.sub(r'class="value text-red">.*?<span', f'class="value text-red">{urgent_cnt} <span', html)
        html = re.sub(r'color:var\(--accent-purple\);">(.*?)<span', f'color:var(--accent-purple);">{ai_cnt} <span', html)
        html = re.sub(r'최근 동기화:.*?</div>', f'최근 동기화:</strong> {now_str} (매일 자동 갱신)</div>', html)

        rows_html = ""
        for b in bids:
            rows_html += f"""
        <tr data-category="{b['category']}">
          <td>
            <span class="badge-org">{b['org'][:12]}</span>
            <span class="badge-category {b['cat_class']}">{b['category']}</span>
          </td>
          <td class="title-cell">
            <!-- [수정 1] 클릭 시 실제 공고로 이동하도록 b['url'] 삽입 -->
            <a href="{b['url']}" target="_blank" class="title-link">{b['title']}</a>
            <div class="tags-list">{b['tags']}</div>
          </td>
          <td><strong>{b['budget']}</strong></td>
          <td>
            <span class="dday-tag {b['dday_class']}">{b['dday_text']}</span>
            <div style="font-size:12px; color:#64748b; margin-top:2px;">{b['close_date']}</div>
          </td>
          <td>
            <a href="{b['url']}" target="_blank" class="btn-action">공고문 ↗</a>
          </td>
        </tr>"""
        
        # HTML의 tbody 영역을 실제 데이터로 치환
        html = re.sub(r'<tbody>.*?</tbody>', f'<tbody>\n{rows_html}\n      </tbody>', html, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("index.html 갱신 완료")

if __name__ == "__main__":
    update_html()
