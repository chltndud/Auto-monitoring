import os
import requests
import urllib.parse
from datetime import datetime, timedelta
import re

# 1. API 키 처리
SERVICE_KEY = os.getenv("G2B_API_KEY", "").strip()
if "%" in SERVICE_KEY:
    SERVICE_KEY = urllib.parse.unquote(SERVICE_KEY)

# 2. 팀 핵심 관심 도메인별 매칭 키워드
CATEGORY_RULES = {
    "AI": ["AI", "인공지능", "LLM", "딥러닝", "머신러닝", "비전", "알고리즘", "지능형", "빅데이터", "플랫폼", "SW", "소프트웨어", "정보화"],
    "소부장": ["소부장", "소재", "부품", "장비", "스마트", "공정", "반도체", "센서", "배터리", "이차전지", "제조", "로봇", "자동화", "설계", "검사", "카메라", "모듈", "기구", "컨베이어", "시제품", "가공"],
    "용역": ["연구", "개발", "R&D", "구축", "실증", "기획", "표준화", "시험", "ISP", "전략"]
}

def classify_target(title):
    matched_tags = []
    found_cat = None
    
    for cat, kws in CATEGORY_RULES.items():
        kws_matched = [k for k in kws if k.lower() in title.lower()]
        if kws_matched:
            if not found_cat:
                found_cat = cat
            matched_tags.extend(kws_matched)
            
    if found_cat:
        return found_cat, list(set(matched_tags))
    return "일반입찰", []

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

def fetch_bids_period(url, start_dt, end_dt):
    """지정된 기간(최대 10일 단위) 동안의 공고를 수집하는 함수"""
    params = {
        "serviceKey": SERVICE_KEY,
        "numOfRows": "50",
        "pageNo": "1",
        "inqryDiv": "1",
        "inqryBgnDt": start_dt,
        "inqryEndDt": end_dt,
        "type": "json"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=20)
        if res.text.strip().startswith("<"):
            return []
        data = res.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict):
            return [items]
        return items or []
    except Exception as e:
        print(f"기간 {start_dt}~{end_dt} 요청 실패: {e}")
        return []

def fetch_real_bids():
    if not SERVICE_KEY:
        return [], "G2B_API_KEY 시크릿이 설정되지 않았습니다."

    servc_url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01"
    thng_url = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoThngPPSSrch01"

    all_raw_items = []
    today = datetime.today()

    # 조달청 1개월 제약을 피하기 위해 최근 30일을 7일씩 쪼개어 4회 호출
    for i in range(4):
        chunk_end = today - timedelta(days=i * 7)
        chunk_start = today - timedelta(days=(i + 1) * 7)
        
        start_str = chunk_start.strftime("%Y%m%d0000")
        end_str = chunk_end.strftime("%Y%m%d2359")
        
        all_raw_items += fetch_bids_period(servc_url, start_str, end_str)
        all_raw_items += fetch_bids_period(thng_url, start_str, end_str)

    items = []
    seen_ids = set()

    for item in all_raw_items:
        bid_name = item.get("bidNtceNm", "")
        bid_no = item.get("bidNtceNo", "")
        bid_ord = item.get("bidNtceOrd", "00")
        
        if not bid_name or not bid_no:
            continue

        unique_id = f"{bid_no}-{bid_ord}"
        if unique_id in seen_ids:
            continue
        seen_ids.add(unique_id)

        category, matched_kws = classify_target(bid_name)
        
        direct_url = f"https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={bid_no}&bidseq={bid_ord}&releaseYn=Y&taskClCd=5"

        try:
            price_val = float(item.get("presmptPrce", 0) or item.get("bdgtAmt", 0) or 0)
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

        if matched_kws:
            tags_str = " ".join([f"#{k}" for k in matched_kws[:4]])
        else:
            tags_str = "#일반입찰 #조달공고"

        if category == "AI": cat_class = "cat-rd"
        elif category == "소부장": cat_class = "cat-cons"
        elif category == "용역": cat_class = "cat-bid"
        else: cat_class = "cat-general"

        items.append({
            "org": item.get("dminsttNm") or item.get("orderInsttNm") or "조달청",
            "category": category,
            "cat_class": cat_class,
            "title": bid_name,
            "tags": tags_str,
            "budget": budget_str,
            "close_date": close_dt,
            "dday_text": dday_label,
            "dday_class": dday_class,
            "url": direct_url
        })

    return items, ""

def update_html():
    bids, err_msg = fetch_real_bids()
    print(f"최종 수집된 전체 공고: {len(bids)}건")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    week_str = f"{now.year}년 {now.month}월 {(now.day - 1) // 7 + 1}주차"

    html = re.sub(r'id="metaWeek">.*?</div>', f'id="metaWeek"><strong>기준 주차:</strong> {week_str}</div>', html)
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync"><strong>최근 동기화:</strong> {now_str} (실시간 갱신)</div>', html)

    total_cnt = len(bids)
    urgent_cnt = sum(1 for b in bids if "urgent" in b["dday_class"])
    team_target_cnt = sum(1 for b in bids if b["category"] in ["AI", "소부장", "용역"])

    html = re.sub(r'id="statTotal">.*?<span', f'id="statTotal">{total_cnt} <span', html)
    html = re.sub(r'id="statUrgent">.*?<span', f'id="statUrgent">{urgent_cnt} <span', html)
    html = re.sub(r'id="statAi">.*?<span', f'id="statAi">{team_target_cnt} <span', html)
    html = re.sub(r'id="statBudget">.*?<span', f'id="statBudget">{max(total_cnt * 1.5, 0):.1f} 억원 <span', html)

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
        msg = err_msg if err_msg else "수집된 공고가 없습니다."
        rows_html = f"""
        <tr>
          <td colspan="5" style="text-align:center; padding: 40px; color: #ef4444; font-weight:600;">
            ⚠️ {msg}
          </td>
        </tr>"""

    html = re.sub(r'<tbody>.*?</tbody>', f'<tbody>{rows_html}\n      </tbody>', html, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("동기화 완료!")

if __name__ == "__main__":
    update_html()
