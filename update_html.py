import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. GitHub Secrets를 쓰지 않고 키를 직접 코드에 박아버립니다 (가장 확실한 방법)
TEST_KEY = "yqd2J707PpMlQORvHoa0ZsjNNDqQM3Of%2BOmqs3p9kJXpkcwC2lc%2FzOR6R9MqPf6QyYyp0B0HnmjluOJh%2FBkzHA%3D%3D"

# 2. 파이썬이 특수문자를 건드리지 못하도록 URL 전체를 통째로 조립합니다.
# (최근 공고를 확인하기 위해 2026년 8월 데이터를 검색합니다)
url = f"http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch01?serviceKey={TEST_KEY}&numOfRows=10&pageNo=1&inqryDiv=1&inqryBgnDt=202608010000&inqryEndDt=202608272359&type=json"

print("================ G2B API 다이렉트 테스트 ================")
try:
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, verify=False, timeout=15)
    
    print(f"HTTP 상태 코드: {res.status_code}")
    
    if res.status_code == 200:
        if res.text.strip().startswith("<"):
            print("❌ 에러: XML 응답이 왔습니다. (키가 틀렸거나 트래픽 초과)")
            print(res.text[:300])
        else:
            data = res.json()
            items = data.get("response", {}).get("body", {}).get("items", [])
            print(f"✅ 성공! 데이터를 {len(items)}건 가져왔습니다.")
            if items:
                print(f"첫 번째 공고명: {items[0].get('bidNtceNm')}")
    else:
        print(f"❌ 실패 (상태코드 {res.status_code}): {res.text[:300]}")

except Exception as e:
    print(f"통신 중 치명적 에러 발생: {e}")
print("=========================================================")
