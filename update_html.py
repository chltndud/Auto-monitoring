import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CATEGORY_RULES = {
    "AI": ["AI", "인공지능", "딥러닝", "머신러닝", "비전", "알고리즘", "데이터", "빅데이터", "플랫폼", "SW", "자율", "지능형", "제어"],
    "소부장": ["장비", "공정", "반도체", "센서", "배터리", "이차전지", "로봇", "자동화", "검사", "카메라", "모듈", "기구", "설계", "컨베이어", "시제품", "가공", "동력", "프레임", "무인", "방산", "기계", "핸들러"],
    "용역": ["연구", "개발", "R&D", "구축", "실증", "기획", "분석", "표준화", "시험", "용역"]
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

def extract_safe_text(element):
    return element.get_text(strip=True) if element else "-"

# ----------------- [웹 크롤러 1] 한국기계연구원 (KIMM) -----------------
def scrape_kimm():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://www.kimm.re.kr/bidding", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 탐색 조건 완화: table 안의 tr 또는 모든 tr 검색
        rows = soup.select("table tbody tr") or soup.find_all("tr")
        for row in rows:
            a_tag = row.find("a")
            if not a_tag: continue
            
            title = extract_safe_text(a_tag)
            if len(title) < 5: continue # 너무 짧은 메뉴 텍스트 방어
            
            link = a_tag.get("href", "")
            if link.startswith("/"): link = "https://www.kimm.re.kr" + link
            
            # 날짜 형식 파싱 시도 (기계연구원은 7번째 td에 날짜가 있음)
            cols = row.find_all("td")
            close_dt = extract_safe_text(cols[6]) if len(cols) >= 7 else "확인 필요"
            
            category, matched = classify_target(title)
            items.append({
                "org": "한국기계연구원",
                "category": category,
                "cat_class": "cat-cons" if category in ["소부장", "일반"] else "cat-rd",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#출연연",
                "budget": "공고문 참조",
                "close_date": close_dt,
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"KIMM 오류: {e}")
    return items

# ----------------- [웹 크롤러 2] 한국생산기술연구원 (KITECH) -----------------
def scrape_kitech():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        # 생기원 입찰공고 URL (실제 URL에 맞게 수정 필요 시 대비)
        res = requests.get("https://www.kitech.re.kr/bbs/page1.php", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 조건 대폭 완화: a 태그 중 href가 있는 것들 추출
        rows = soup.find_all("tr")
        for row in rows:
            a_tag = row.find("a")
            if not a_tag: continue
            
            title = extract_safe_text(a_tag)
            if len(title) < 5: continue
            
            link = a_tag.get("href", "")
            if not link.startswith("http"):
                link = "https://www.kitech.re.kr/bbs/" + link.lstrip("/")
                
            category, matched = classify_target(title)
            items.append({
                "org": "한국생산기술연구원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#제조공정",
                "budget": "공고문 참조",
                "close_date": "진행중",
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"KITECH 오류: {e}")
    return items

# ----------------- [웹 크롤러 3] 한국로봇산업진흥원 (KIRIA) -----------------
def scrape_kiria():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://www.kiria.org/portal/bidding/portalBiddingList.do", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        rows = soup.find_all("tr")
        for row in rows:
            a_tag = row.find("a")
            if not a_tag: continue
            
            title = extract_safe_text(a_tag)
            if len(title) < 5: continue
            
            link = a_tag.get("href", "")
            if link.startswith("/"): link = "https://www.kiria.org" + link
            
            category, matched = classify_target(title)
            items.append({
                "org": "한국로봇산업진흥원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-rd" if category == "AI" else "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#로봇자동화",
                "budget": "공고문 참조",
                "close_date": "진행중",
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"KIRIA 오류: {e}")
    return items

# ----------------- [웹 크롤러 4] 국방기술품질원 (DTaQ) -----------------
def scrape_dtaq():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://www.dtaq.re.kr/ko/notice/tender.jsp", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        rows = soup.find_all("tr")
        for row in rows:
            a_tag = row.find("a")
            if not a_tag: continue
            
            title = extract_safe_text(a_tag)
            if len(title) < 5: continue
            
            link = "https://www.dtaq.re.kr/ko/notice/tender.jsp" # 상세 링크 파싱이 어려울 경우 메인으로 우회
            
            category, matched = classify_target(title)
            items.append({
                "org": "국방기술품질원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#방위산업",
                "budget": "공고문 참조",
                "close_date": "진행중",
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"DTaQ 오류: {e}")
    return items


def update_html():
    bids = scrape_kimm() + scrape_kitech() + scrape_kiria() + scrape_dtaq()
    
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # KST (한국 표준시, UTC+9) 적용
    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    
    # 1. 최근 동기화 시간 업데이트 (KST 반영)
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync"><strong>최근 동기화:</strong> {now_str} (연구기관 다중 크롤러 작동)</div>', html)

    # 2. 기준 주차 업데이트 (복구 완료)
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
    print(f"업데이트 완료: 총 {total_cnt}건 반영")

if __name__ == "__main__":
    update_html()
