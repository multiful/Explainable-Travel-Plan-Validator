<!-- updated: 2026-09-12 | hash: 06799987 | summary: API test and integration notes -->
# API 테스트 스니펫

API 키는 `.env`에서 읽는다. 실행 전 `pip install python-dotenv requests` 필요.

---

## Kakao Mobility — 경로 탐색

```python
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# 핵심: 'KakaoAK ' 접두어가 반드시 포함되어야 인증에 성공합니다.
headers = {
    "Authorization": f"KakaoAK {os.environ.get('KAKAO_REST_API_KEY')}"
}

# 1. Kakao Mobility (자동차 경로/소요 시간)
def get_directions():
    url = "https://apis-navi.kakaomobility.com/v1/directions"
    params = {
        "origin": "127.1086228,37.4012191",
        "destination": "127.1058342,37.359708"
    }
    res = requests.get(url, headers=headers, params=params)
    return res.json()

# 2. Kakao Local (주소 -> 좌표 변환)
def get_coords(address):
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    params = {"query": address}
    res = requests.get(url, headers=headers, params=params)
    return res.json()

# 테스트 실행
print("--- Mobility Result ---")
print(get_directions())

print("\n--- Local Result ---")
print(get_coords("경기도 성남시 분당구 판교역로 166"))
```

---

## TourAPI — 지역 기반 관광지 목록

```python
import os, requests
from dotenv import load_dotenv

load_dotenv()

url = "http://apis.data.go.kr/B551011/KorService2/areaBasedList2"

params = {
    "serviceKey": os.environ["TOUR_API_SERVICE_KEY"],
    "numOfRows": 10,
    "pageNo": 1,
    "MobileOS": "ETC",
    "MobileApp": "AppTest",
    "arrange": "A",
    "contentTypeId": 12,  # 관광지
    "areaCode": 1,        # 서울
    "_type": "json"
}

response = requests.get(url, params=params)
data = response.json()

print(data)
```
