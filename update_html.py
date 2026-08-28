import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import re
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =====================================================================
# 🔑 방금 테스트에 성공하신 '일반 인증키(Encoding)'를 아래에 꼭 넣어주세요!
API_KEY_G2B = "yqd2J707PpMlQORvHoa0ZsjNNDqQM3Of%2BOmqs3p9kJXpkcwC2lc%2FzOR6R9MqPf6QyYyp0B0HnmjluOJh%2FBkzHA%3D%3D"
API_KEY_IRIS = "yqd2J707PpMlQORvHoa0ZsjNNDqQM3Of%2BOmqs3p9kJXpkcwC2lc%2FzOR6R9MqPf6QyYyp0B0HnmjluOJh%2FBkzHA%3D%3D"
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
                clean_str = re.sub(r'[^0-9]', '', close_dt)[:8]
                dday_label, dday_class = "진행중", "dday-safe"
                
                if len(clean_str) == 8:
                    close_date = datetime.strptime(clean_str, "%Y%m%d").date()
                    today = datetime.now(timezone(timedelta(hours=9))).date()
                    diff = (close_date - today).days
                    if diff < 0: continue
                    elif diff == 0: dday_label, dday_class = "D-Day", "dday-urgent"
                    elif diff <= 7: dday_label, dday_class = f"D-{diff}", "dday-urgent"
                    else: dday_label, dday_class = f"D-{diff}", "dday-normal"
                    
                category, matched = classify_target(title)
                items.append({
                    "org": "한국기계연구원",
                    "category": category,
                    "cat_class": "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid",
                    "title": title,
                    "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#출연연공고",
                    "budget": "공고문 참조",
                    "close_date": close_dt,
                    "dday_text": dday_label,
                    "dday_class": dday_class,
                    "url": link
                })
    except Exception as e:
        print(f"KIMM 오류: {e}")
    return items

# ----------------- [API] 조달청(G2B) 타깃 검색 -----------------
def fetch_g2b_api():
    items = []
    try:
        KST = timezone(timedelta(hours=9))
        now = datetime.now(KST)
        # 검색 기간: 한 달 전 ~ 오늘
        bgn_dt = (now - timedelta(days=30)).strftime("%Y%m%d0000")
        end_dt = now.strftime("%Y%m%d2359")
        
        url = f"http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01?serviceKey={API_KEY}&numOfRows=50&pageNo=1&inqryDiv=1&inqryBgnDt={bgn_dt}&inqryEndDt={end_dt}&type=json"
        
        res = requests.get(url, verify=False, timeout=15)
        if res.status_code == 200 and not res.text.startswith("<"):
            data = res.json()
            bids = data.get("response", {}).get("body", {}).get("items", [])
            
            # 발주기관명(dminsttNm) 또는 공고명(bidNtceNm) 필터링
            target_orgs = ["생산기술연구원", "로봇산업진흥원", "국방기술품질원"]
            target_kws = ["컨베이어", "모듈", "검사장비", "자동화"]
            
            for bid in bids:
                org_name = bid.get('dminsttNm', '조달청')
                title = bid.get('bidNtceNm', '')
                
                # 핵심 타깃 기관이거나 핵심 키워드가 포함된 공고만 선별
                is_target_org = any(org in org_name for org in target_orgs)
                is_target_kw = any(kw in title for kw in target_kws)
                
                if not (is_target_org or is_target_kw):
                    continue
                    
                close_dt_str = bid.get('bidClseDt', '')
                dday_label, dday_class = "진행중", "dday-safe"
                close_date_disp = "마감일 미정"
                
                if close_dt_str:
                    try:
                        close_date = datetime.strptime(close_dt_str[:8], "%Y%m%d").date()
                        close_date_disp = close_date.strftime("%Y-%m-%d")
                        diff = (close_date - now.date()).days
                        
                        if diff < 0: continue
                        elif diff == 0: dday_label, dday_class = "D-Day", "dday-urgent"
                        elif diff <= 7: dday_label, dday_class = f"D-{diff}", "dday-urgent"
                        else: dday_label, dday_class = f"D-{diff}", "dday-normal"
                    except:
                        pass
                
                category, matched = classify_target(title)
                items.append({
                    "org": org_name[:12], # 기관명이 너무 길면 UI가 깨지므로 자름
                    "category": category if category != "일반" else "소부장",
                    "cat_class": "cat-cons" if category == "소부장" else "cat-rd",
                    "title": title,
                    "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#조달청API",
                    "budget": "공고문 참조",
                    "close_date": close_date_disp,
                    "dday_text": dday_label,
                    "dday_class": dday_class,
                    "url": bid.get('ntceInsttDturl', 'https://www.g2b.go.kr')
                })
    except Exception as e:
        print(f"G2B API 연동 오류: {e}")
    
    return items

def update_html():
    bids = scrape_kimm() + fetch_g2b_api()
    
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    
    github_actions_url = "#" 
    sync_btn_html = f'<a href="{github_actions_url}" target="_blank" style="display:inline-block; background-color:#10b981; color:white; padding:3px 8px; border-radius:6px; text-decoration:none; font-size:11px; font-weight:bold; margin-right:8px; box-shadow:0 1px 2px rgba(0,0,0,0.1);">🔄 수동 동기화</a>'
    
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync">{sync_btn_html}<strong>최근 동기화:</strong> {now_str} (API+웹크롤링 하이브리드)</div>', html)

    week_num = (now.day - 1) // 7 + 1
    week_str = f"{now.year}년 {now.month}월 {week_num}주차"
    html = re.sub(r'id="metaWeek">.*?</div>', f'id="metaWeek"><strong>기준 주차:</strong> {week_str}</div>', html)

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
    print(f"하이브리드 동기화 완료: 총 {total_cnt}건")

if __name__ == "__main__":
    update_html()
