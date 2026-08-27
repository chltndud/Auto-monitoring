import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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

# ----------------- [웹 크롤러 1] 한국기계연구원 (KIMM) -----------------
def scrape_kimm():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
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
                        "cat_class": "cat-cons" if category in ["소부장", "일반"] else "cat-rd",
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

# ----------------- [웹 크롤러 2] 한국생산기술연구원 (KITECH) -----------------
def scrape_kitech():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://www.kitech.re.kr/bbs/page1.php", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select("table tbody tr"):
            title_elem = row.find("a")
            if not title_elem: continue
            title = title_elem.get_text(strip=True)
            link = "https://www.kitech.re.kr/bbs/" + title_elem.get("href", "")
            
            # 생산기술연구원 특성상 마감일이 명확히 표기되지 않은 경우가 많아 안전하게 진행중으로 처리
            category, matched = classify_target(title)
            items.append({
                "org": "한국생산기술연구원",
                "category": category,
                "cat_class": "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#제조공정",
                "budget": "공고문 참조",
                "close_date": "사이트 확인",
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"KITECH 크롤링 오류: {e}")
    return items

# ----------------- [웹 크롤러 3] 한국로봇산업진흥원 (KIRIA) -----------------
def scrape_kiria():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://www.kiria.org/portal/bidding/portalBiddingList.do", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select("table tbody tr"):
            title_elem = row.find("a")
            if not title_elem: continue
            title = title_elem.get_text(strip=True)
            link = "https://www.kiria.org" + title_elem.get("href", "")
            
            category, matched = classify_target(title)
            items.append({
                "org": "한국로봇산업진흥원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-rd" if category == "AI" else "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#로봇자동화",
                "budget": "공고문 참조",
                "close_date": "사이트 확인",
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"KIRIA 크롤링 오류: {e}")
    return items

# ----------------- [웹 크롤러 4] 국방기술품질원 (DTaQ) -----------------
def scrape_dtaq():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://www.dtaq.re.kr/ko/notice/tender.jsp", headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select("table tbody tr"):
            title_elem = row.find("a")
            if not title_elem: continue
            title = title_elem.get_text(strip=True)
            link = "https://www.dtaq.re.kr/ko/notice/tender.jsp"
            
            category, matched = classify_target(title)
            items.append({
                "org": "국방기술품질원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#방위산업",
                "budget": "공고문 참조",
                "close_date": "사이트 확인",
                "dday_text": "진행중",
                "dday_class": "dday-safe",
                "url": link
            })
    except Exception as e:
        print(f"DTaQ 크롤링 오류: {e}")
    return items


def update_html():
    # 4개 기관 전면 크롤링 데이터 취합 (API 함수가 있다면 여기에 + fetch_g2b() 형태로 더함)
    bids = scrape_kimm() + scrape_kitech() + scrape_kiria() + scrape_dtaq()
    
    print(f"웹 크롤링 결과 -> 총 {len(bids)}건 확보 완료.")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync"><strong>최근 동기화:</strong> {now_str} (연구기관 다중 크롤러 작동)</div>', html)

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

if __name__ == "__main__":
    update_html()
