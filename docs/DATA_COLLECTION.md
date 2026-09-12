<!-- updated: 2026-09-12 | hash: d0cb7ba4 | summary: 서울 도시데이터 API 섹션 추가, SEOUL_DATA_API_KEY 환경변수 반영 -->
# 데이터 파이프라인 가이드

본 시스템은 두 개의 외부 API를 데이터 소스로 사용한다:
1. **TourAPI (한국관광공사)** — POI 메타데이터 (운영시간, 위치, 카테고리)
2. **Kakao API** — POI 좌표 정규화 (Local) + 이동시간 행렬 (Mobility)

리뷰 데이터는 검증 파이프라인에 **직접 사용하지 않는다** (결과 설명의 보조 사례로만 활용 가능).

---

## 1. TourAPI (한국관광공사)

### 인증
- 신청: https://www.data.go.kr → "한국관광공사_국문 관광정보 서비스_GW" 검색
- 인증 방식: URL Query Parameter `serviceKey` (URL-encoded)
- Base URL: `http://apis.data.go.kr/B551011/KorService1/`
- 공통 파라미터: `MobileOS=ETC`, `MobileApp=travel-validator`, `_type=json`

### 수집 엔드포인트 (2종)

#### 1-A. searchKeyword1 — 키워드 검색
```
GET /searchKeyword1?serviceKey=...&keyword=경복궁&numOfRows=5&pageNo=1
    &MobileOS=ETC&MobileApp=travel-validator&_type=json
```

**응답 핵심 필드**
| 필드명 | 설명 |
|--------|------|
| contentid | 관광지 고유 ID |
| contenttypeid | 콘텐츠 타입 (12=관광지, 14=문화시설) |
| title | 관광지명 |
| mapx / mapy | 경도 / 위도 |
| addr1 | 주소 |

#### 1-B. detailIntro1 — 운영시간·요금 상세
```
GET /detailIntro1?serviceKey=...&contentId=126508&contentTypeId=14
    &MobileOS=ETC&MobileApp=travel-validator&_type=json
```

**응답 핵심 필드**
| 필드명 | 설명 |
|--------|------|
| usetime | 이용 시간 (예: "09:00~18:00(입장마감 17:00)") |
| usefee | 이용 요금 |
| parking | 주차 안내 |

**운영시간 파싱 전략**: `usetime` 문자열에서 정규식으로 `HH:MM~HH:MM` 추출.  
파싱 실패 시: `open_start = "00:00"`, `open_end = "23:59"` (폴백), Confidence Medium-Low.

### Rate Limiting
| 항목 | 값 |
|------|----|
| 일일 허용 쿼리 | 10,000건 / 인증키 |
| 권장 요청 간격 | 순차 호출 시 0.5초 이상, 병렬 호출 시 5개 이하 |
| POI 1개 수집 API 호출 수 | 2회 (searchKeyword1 + detailIntro1) |

---

## 2. Kakao Local API

### 인증
- Kakao Developers 앱 등록 → REST API 키 발급
- Header: `Authorization: KakaoAK {REST_API_KEY}`
- Base URL: `https://dapi.kakao.com/v2/local/`

### 엔드포인트: 키워드 장소 검색
```
GET /search/keyword.json?query=경복궁&size=1
Authorization: KakaoAK {KAKAO_REST_API_KEY}
```

**응답 핵심 필드**
| 필드명 | 설명 |
|--------|------|
| documents[0].x | 경도 (더 정밀) |
| documents[0].y | 위도 (더 정밀) |
| documents[0].address_name | 정규화된 주소 |
| documents[0].category_group_code | 카테고리 코드 |

**폴백**: Kakao Local 검색 실패 시 TourAPI 좌표(mapx, mapy) 그대로 사용.

---

## 3. Kakao Mobility API

### 인증
- B2B 신청 필요 (https://developers.kakao.com/product/mobility)
- Header: `Authorization: KakaoAK {KAKAO_MOBILITY_KEY}`
- Base URL: `https://apis-navi.kakaomobility.com/v1/`

### 엔드포인트: 경로 탐색 (대중교통)
```
GET /directions?origin={lng},{lat}&destination={lng},{lat}&priority=RECOMMEND
Authorization: KakaoAK {KAKAO_MOBILITY_KEY}
```

**응답 핵심 필드**
| 필드명 | 설명 |
|--------|------|
| routes[0].summary.duration | 이동시간 (초) |
| routes[0].summary.distance | 이동거리 (미터) |

### 직선거리 폴백 공식
`KAKAO_MOBILITY_KEY`가 없거나 API 호출 실패 시:

```python
import math

def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

SPEED_KMH = {"transit": 20, "car": 40, "walk": 4}
ROUTE_FACTOR = {"transit": 1.3, "car": 1.1, "walk": 1.0}

def estimate_travel_min(lat1, lng1, lat2, lng2, mode: str) -> float:
    dist_km = haversine_km(lat1, lng1, lat2, lng2) * ROUTE_FACTOR[mode]
    return (dist_km / SPEED_KMH[mode]) * 60
```

---

## 4. Travel Matrix 구조

N개 POI의 Pairwise 이동시간 행렬:

```python
# TravelMatrix: (N × N) dict
# matrix[i][j] = {"travel_min": float, "distance_km": float, "mode": str, "is_fallback": bool}
# i → j 이동, i == j → travel_min = 0

matrix = {
    0: {0: {"travel_min": 0, ...}, 1: {"travel_min": 35.2, ...}},
    1: {0: {"travel_min": 35.2, ...}, 1: {"travel_min": 0, ...}},
}
```

`is_fallback = True`이면 Confidence Level 자동 하향 (High → Medium-Low).

---

## 5. 서울 도시데이터 API (실시간 혼잡도)

### 인증
- 신청: https://data.seoul.go.kr → "서울 실시간 도시데이터" 검색
- 엔드포인트: `http://openapi.seoul.go.kr:8088/{KEY}/json/citydata/1/1/{AREA_NM}`
- 커버리지: 서울시 주요 115개소 (경복궁·인사동·명동 관광특구·홍대 관광특구 등)
- 갱신주기: 10~15분

### 응답 핵심 필드
| 필드 | 설명 |
|------|------|
| `AREA_CONGEST_LVL` | 현재 혼잡도 ("여유"/"보통"/"약간 붐빔"/"붐빔") |
| `AREA_PPLTN_MIN/MAX` | 실시간 인구 추정 범위 |
| `PPLTN_TIME` | 측정 시각 |
| `FCST_PPLTN` | 12시간 예측 슬롯 배열 |

### 혼잡도 점수 변환
| 레벨 | congestion_score |
|------|-----------------|
| 여유 | 0.1 |
| 보통 | 0.4 |
| 약간 붐빔 | 0.7 |
| 붐빔 | 1.0 |

### CongestionEngine 연동
서울 소재 POI는 `SeoulCityDataClient.get(poi_name)` 성공 시 실시간 데이터 우선 사용.
API 실패 또는 커버리지 밖이면 `data/congestion_stats.csv` (한국문화관광연구원 2020~2024) 폴백.

---

## 6. 환경변수 설정

```
TOUR_API_KEY=your_tour_api_key
KAKAO_REST_API_KEY=your_kakao_rest_api_key
KAKAO_MOBILITY_KEY=          # 없으면 직선거리 폴백
SEOUL_DATA_API_KEY=          # 없으면 CSV 통계 폴백
```
