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
    "용역": ["연구", "개발", "R&D", "구축", "실증", "기획", "분석", "표준화", "시험", "용역", "폐기물", "공사", "구매", "용역"]
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
    return "진행중(확인)", "진행중", "dday-safe"

def generic_scrape(url, org_name, default_category, base_url):
    """
    특정 태그(table, tr)에 의존하지 않고 페이지 내의 모든 하이퍼링크(a)를 탐색해
    '공고글'의 패턴을 가진 요소만 똑똑하게 뽑아내는 만능 크롤러
    """
    items = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 페이지 내 모든 링크 요소 탐색
        a_tags = soup.find_all("a")
        
        for a in a_tags:
            title = a.get_text(strip=True)
            
            # 너무 짧은 단어(메뉴 버튼)나 숫자로만 된 텍스트(페이지 번호)는 패스
            if len(title) < 10 or title.isdigit() or title in ["새글", "첨부파일", "자세히보기", "개인정보처리방침"]:
                continue
            
            href = a.get("href", "")
            # 실제 이동하지 않는 자바스크립트 더미 링크 제외
            if not href or href.startswith("#") or "javascript:void(0)" in href:
                continue
                
            # 휴리스틱: 링크에 뷰어 파라미터나 고유 ID가 없는데 텍스트가 짧으면 일반 메뉴일 확률이 높음
            if not any(kw in href.lower() for kw in ["?", "id=", "idx=", "seq=", "num=", "view", "read", "bbs", "page", "bidding", "tender"]):
                if len(title) < 15:
                    continue

            # 링크 URL 조합 (상대 경로인 경우 절대 경로로 변환)
            link = href
            if not link.startswith("http"):
                if link.startswith("/"): 
                    link = base_url + link
                else: 
                    link = url.split('?')[0] + "/" + link if '?' not in link else base_url + "/" + link
            
            # 날짜를 찾기 위해 해당 링크가 속한 가장 가까운 행(tr)이나 리스트(li)의 전체 텍스트를 추출
            parent = a.find_parent("tr") or a.find_parent("li")
            row_text = parent.get_text(separator=" ") if parent else title
            
            close_dt, dday_label, dday_class = check_deadline_from_text(row_text)
            
            # 기한이 지난 공고 원천 배제
            if dday_label == "마감": 
                continue
                
            # 동일한 공고글 중복 수집 방지
            if any(item['title'] == title for item in items):
                continue
                
            category, matched = classify_target(title)
            if category == "일반": category = default_category
            cat_class = "cat-rd" if category == "AI" else "cat-cons" if category == "소부장" else "cat-bid"
            
            items.append({
                "org": org_name,
                "category": category,
                "cat_class": cat_class,
                "title": title,
                "tags": " ".join([f"#{k}" for k in matched[:3]]) if matched else f"#{org_name[:2]}공고",
                "budget": "공고문 참조",
                "close_date": close_dt,
                "dday_text": dday_label,
                "dday_class": dday_class,
                "url": link
            })
            
            # 화면이 한 기관의 데이터로 덮이는 것을 막기 위해 최신순 10건만 수집
            if len(items) >= 10: 
                break
                
    except Exception as e:
        print(f"[{org_name} 크롤링 오류]: {e}")
        
    return items

def update_html():
    bids = []
    # 각 기관별 최신 입찰공고 보드 URL 업데이트
    bids += generic_scrape("https://www.kimm.re.kr/bidding", "한국기계연구원", "소부장", "https://www.kimm.re.kr")
    bids += generic_scrape("https://www.kitech.re.kr/pages/25", "한국생산기술연구원", "소부장", "https://www.kitech.re.kr")
    bids += generic_scrape("https://www.kiria.org/portal/bidding/portalBiddingList.do", "한국로봇산업진흥원", "소부장", "https://www.kiria.org")
    bids += generic_scrape("https://www.dtaq.re.kr/ko/notice/tender.jsp", "국방기술품질원", "소부장", "https://www.dtaq.re.kr")
    
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    
    # 깃허브 액션 링크 단축 버튼 (본인 저장소 주소로 변경하여 사용 가능)
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
