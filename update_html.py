import os
import requests
import urllib.parse
from datetime import datetime, timedelta
import re

# 1. API 키 처리 (공백 및 인코딩 정리)
SERVICE_KEY = os.getenv("G2B_API_KEY", "").strip()
if "%" in SERVICE_KEY:
    SERVICE_KEY = urllib.parse.unquote(SERVICE_KEY)

# 2. 키워드 및 카테고리 설정 (검색 범위를 넓혀 공고가 누락되지 않도록 구성)
CATEGORY_RULES = {
    "선행개발/AI": ["AI", "인공지능", "LLM", "딥러닝", "머신러닝", "비전", "알고리즘", "지능형", "빅데이터"],
    "소부장/공정": ["소부장", "소재", "부품", "장비", "스마트", "공정", "반도체", "센서", "배터리", "이차전지", "제조", "로봇", "자동화", "설계"],
    "용역/R&D": ["용역", "연구", "개발", "R&D", "구축", "플랫폼", "시스템", "SW", "소프트웨어", "실증"]
}

ALL_KEYWORDS = [kw for kws in CATEGORY_RULES.values() for kw in kws]

def classify_category(title):
    for cat, kws in CATEGORY_RULES.items():
        if any(k.lower() in title.lower() for k in kws):
            return cat
    return "용역/R&D"

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
    # 최근 14일간의 공고를 넓게 조회
    start_date = (today - timedelta(days=14)).strftime("%Y%m%d0000")
    end_date = today.strftime("%Y%m%d2359")
    
    url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01"
    params = {
        "serviceKey": SERVICE_KEY,
        "numOfRows": "200",
        "pageNo": "1",
        "inqryDiv": "1",
        "inqryBgnDt": start_date,
        "inqryEndDt": end_date,
        "type": "json"
    }
    
    items = []
    if not SERVICE_KEY:
        print("[경고] G2B_API_KEY가 등록되지 않았습니다.")
        return items, "API 키가 등록되지 않았습니다. GitHub Secrets(G2B_API_KEY)를 확인하세요."

    try:
        res = requests.get(url, params=params, timeout=20)
        
        # XML 형식 에러 메시지(인증키 오류 등)가 돌아온 경우 처리
        if res.text.startswith("<"):
            print(f"[API 응답 오류]: {res.text[:200]}")
            return items, "공공데이터포털 인증키 오류 또는 시스템 동기화 중입니다. (1~2시간 후 재시도)"

        data = res.json()
        body = data.get("response", {}).get("body", {})
        raw_items = body.get("items", [])
        
        if isinstance(raw_items, dict):
            raw_items = [raw_items]

        for item in raw_items:
            bid_name = item.get("bidNtceNm", "")
            matched = [k for k in ALL_KEYWORDS if k.lower() in bid_name.lower()]
            
            # 관심 키워드가 포함된 공고만 필터링
            if matched:
                category = classify_category(bid_name)
                bid_no = item.get("bidNtceNo", "")
                bid_ord = item.get("bidNtceOrd", "00")
                
                # 나라장터 상세페이지 통합 직통 링크
                if bid_no:
                    direct_url = f"https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={bid_no}&bidPbancOrd={bid_ord}"
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
                    "cat_class": "cat-rd" if "AI" in category or "소부장" in category else "cat-bid",
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
        print(f"[수집 예외 발생]: {e}")
        return items, f"데이터 수집 중 오류가 발생했습니다: {e}"

def update_html():
    bids, error_msg = fetch_real_bids()
    print(f"수집된 실제 공고: {len(bids)}건")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    week_str = f"{now.year}년 {now.month}월 {(now.day - 1) // 7 + 1}주차"

    # 통계 및 시간 업데이트
    total_cnt = len(bids)
    urgent_cnt = sum(1 for b in bids if "urgent" in b["dday_class"])
    ai_cnt = sum(1 for b in bids if b["category"] in ["선행개발/AI", "소부장/공정"])

    html = re.sub(r'class="value text-blue">.*?<span', f'class="value text-blue">{total_cnt} <span', html)
    html = re.sub(r'class="value text-red">.*?<span', f'class="value text-red">{urgent_cnt} <span', html)
    html = re.sub(r'color:var\(--accent-purple\);">(.*?)<span', f'color:var(--accent-purple);">{ai_cnt} <span', html)
    html = re.sub(r'기준 주차:.*?</div>', f'기준 주차:</strong> {week_str}</div>', html)
    html = re.sub(r'최근 동기화:.*?</div>', f'최근 동기화:</strong> {now_str} (실시간 동기화)</div>', html)

    # 본문 테이블 교체 (예시 데이터 완전 삭제)
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
          <td><strong>{b['budget']}</strong></td>
          <td>
            <span class="dday-tag {b['dday_class']}">{b['dday_text']}</span>
            <div style="font-size:12px; color:#64748b; margin-top:2px;">{b['close_date']}</div>
          </td>
          <td>
            <a href="{b['url']}" target="_blank" class="btn-action">나라장터 공고문 ↗</a>
          </td>
        </tr>"""
    else:
        # 데이터가 없을 때 가짜 데이터 대신 안내 메시지 출력
        msg = error_msg if error_msg else "최근 14일간 매칭되는 신규 공고가 없습니다."
        rows_html = f"""
        <tr>
          <td colspan="5" style="text-align:center; padding: 40px; color: #64748b;">
            ⚠️ {msg}
          </td>
        </tr>"""

    html = re.sub(r'<tbody>.*?</tbody>', f'<tbody>{rows_html}\n      </tbody>', html, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("index.html 갱신 완료")

if __name__ == "__main__":
    update_html()
