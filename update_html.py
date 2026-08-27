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

def check_deadline_from_text(row_text):
    dates = re.findall(r'(202\d|2\d)[-/.년\s]+([01]?\d)[-/.월\s]+([0-3]?\d)', row_text)
    if dates:
        if len(dates) == 1:
            y, m, d = dates[0]
            if len(y) == 2: y = "20" + y
            return f"{y}-{m.zfill(2)}-{d.zfill(2)} (등록)", "진행중", "dday-safe"
        else: 
            y, m, d = dates[-1]
            if len(y) == 2: y = "20" + y
            close_dt_str = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            try:
                close_date = datetime.strptime(close_dt_str, "%Y-%m-%d").date()
                KST = timezone(timedelta(hours=9))
                today = datetime.now(KST).date()
                diff = (close_date - today).days
                
                if diff < 0: return close_dt_str, "마감", "dday-urgent"
                elif diff == 0: return close_dt_str, "D-Day", "dday-urgent"
                elif diff <= 7: return close_dt_str, f"D-{diff}", "dday-urgent"
                elif diff <= 14: return close_dt_str, f"D-{diff}", "dday-normal"
                else: return close_dt_str, f"D-{diff}", "dday-safe"
            except:
                pass
    return "상세 확인", "진행중", "dday-safe"

# =====================================================================
# 1. 한국기계연구원 (KIMM) 맞춤형 크롤러 (과거 성공했던 안정적인 방식 복구)
# =====================================================================
def scrape_kimm():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = "https://www.kimm.re.kr/bidding"
        res = requests.get(url, headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 기계연 특유의 정확한 7칸(td) 표기법 활용 (잡동사니 완벽 차단)
        for row in soup.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) >= 7:
                title_elem = cols[2].find("a")
                if not title_elem: continue
                
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                if link.startswith("/"): link = "https://www.kimm.re.kr" + link
                
                close_dt, dday_label, dday_class = check_deadline_from_text(row.get_text(separator=" "))
                if dday_label == "마감": continue
                    
                category, matched = classify_target(title)
                items.append({
                    "org": "한국기계연구원",
                    "category": category,
                    "cat_class": "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid" if category == "용역" else "cat-general",
                    "title": title,
                    "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#출연연공고",
                    "budget": "공고문 참조",
                    "close_date": cols[6].get_text(strip=True), # 확실한 기계연 날짜 위치
                    "dday_text": dday_label,
                    "dday_class": dday_class,
                    "url": link
                })
    except Exception as e:
        print(f"[한국기계연구원 오류]: {e}")
    return items

# =====================================================================
# 2. 한국생산기술연구원 (KITECH) 맞춤형 크롤러
# =====================================================================
def scrape_kitech():
    items = []
    try:
        url = "https://www.kitech.re.kr/bbs/page1.php"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, verify=False, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # th(머리글)가 없는 순수 데이터 행(tr)만 수집
        for tr in soup.find_all("tr"):
            if tr.find("th"): continue 
            
            a_tags = tr.find_all("a")
            if not a_tags: continue
            
            # 해당 행에서 가장 긴 텍스트를 가진 a태그를 공고 제목으로 인식
            a_tag = max(a_tags, key=lambda x: len(x.get_text(strip=True)))
            title = a_tag.get_text(strip=True)
            if len(title) < 6: continue
            
            href = a_tag.get("href", "")
            link = url # 자바스크립트로 숨겨진 경우를 대비해 기본 게시판 URL 셋팅
            if href and href.startswith("http"): link = href
            elif href and not href.startswith("#") and not href.startswith("javascript"):
                link = "https://www.kitech.re.kr/bbs/" + href.lstrip("/")

            close_dt, dday_label, dday_class = check_deadline_from_text(tr.get_text(separator=" "))
            if dday_label == "마감": continue
            
            category, matched = classify_target(title)
            items.append({
                "org": "한국생산기술연구원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#제조공정",
                "budget": "공고문 참조",
                "close_date": close_dt,
                "dday_text": dday_label,
                "dday_class": dday_class,
                "url": link
            })
    except Exception as e:
        print(f"[한국생산기술연구원 오류]: {e}")
    return items

# =====================================================================
# 3. 한국로봇산업진흥원 (KIRIA) 맞춤형 크롤러
# =====================================================================
def scrape_kiria():
    items = []
    try:
        url = "https://www.kiria.org/portal/bidding/portalBiddingList.do"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, verify=False, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for tr in soup.find_all("tr"):
            if tr.find("th"): continue 
            
            a_tags = tr.find_all("a")
            if not a_tags: continue
            
            a_tag = max(a_tags, key=lambda x: len(x.get_text(strip=True)))
            title = a_tag.get_text(strip=True)
            if len(title) < 6: continue
            
            href = a_tag.get("href", "")
            link = url
            if href and href.startswith("http"): link = href
            elif href and not href.startswith("#") and not href.startswith("javascript"):
                link = "https://www.kiria.org" + href if href.startswith("/") else url.split("?")[0] + "/" + href

            close_dt, dday_label, dday_class = check_deadline_from_text(tr.get_text(separator=" "))
            if dday_label == "마감": continue
            
            category, matched = classify_target(title)
            items.append({
                "org": "한국로봇산업진흥원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#로봇자동화",
                "budget": "공고문 참조",
                "close_date": close_dt,
                "dday_text": dday_label,
                "dday_class": dday_class,
                "url": link
            })
    except Exception as e:
        print(f"[한국로봇산업진흥원 오류]: {e}")
    return items

# =====================================================================
# 4. 국방기술품질원 (DTaQ) 맞춤형 크롤러
# =====================================================================
def scrape_dtaq():
    items = []
    try:
        url = "https://www.dtaq.re.kr/ko/notice/tender.jsp"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, verify=False, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for tr in soup.find_all("tr"):
            if tr.find("th"): continue 
            
            a_tags = tr.find_all("a")
            if not a_tags: continue
            
            a_tag = max(a_tags, key=lambda x: len(x.get_text(strip=True)))
            title = a_tag.get_text(strip=True)
            if len(title) < 6: continue
            
            href = a_tag.get("href", "")
            link = url
            if href and href.startswith("http"): link = href
            elif href and not href.startswith("#") and not href.startswith("javascript"):
                link = "https://www.dtaq.re.kr" + href if href.startswith("/") else url.split("?")[0] + "/" + href

            close_dt, dday_label, dday_class = check_deadline_from_text(tr.get_text(separator=" "))
            if dday_label == "마감": continue
            
            category, matched = classify_target(title)
            items.append({
                "org": "국방기술품질원",
                "category": category if category != "일반" else "소부장",
                "cat_class": "cat-cons",
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else "#방위산업",
                "budget": "공고문 참조",
                "close_date": close_dt,
                "dday_text": dday_label,
                "dday_class": dday_class,
                "url": link
            })
    except Exception as e:
        print(f"[국방기술품질원 오류]: {e}")
    return items

def update_html():
    bids = []
    
    # 4개 기관의 독립 맞춤형 크롤러를 순차적으로 실행
    bids += scrape_kimm()
    bids += scrape_kitech()
    bids += scrape_kiria()
    bids += scrape_dtaq()
    
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    
    github_actions_url = "#" 
    sync_btn_html = f'<a href="{github_actions_url}" target="_blank" style="display:inline-block; background-color:#10b981; color:white; padding:3px 8px; border-radius:6px; text-decoration:none; font-size:11px; font-weight:bold; margin-right:8px; box-shadow:0 1px 2px rgba(0,0,0,0.1);">🔄 수동 동기화</a>'
    
    html = re.sub(r'id="metaSync">.*?</div>', f'id="metaSync">{sync_btn_html}<strong>최근 동기화:</strong> {now_str}</div>', html)

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
    print(f"동기화 완료: 총 {total_cnt}건")

if __name__ == "__main__":
    update_html()
