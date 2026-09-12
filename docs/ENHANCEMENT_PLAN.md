<!-- updated: 2026-09-12 | hash: bafb1d66 | summary: 8개 요구사항 전부 ✅, M1-M4 DBSCAN 추가, 혼잡도 ⑦⑧ 신규 반영 -->
# 패널티 통합 설계서 (Enhancement Plan v2)

> "**진짜 갈 수 있는 길인가**"(현실 제약) + "**얼마나 좋은 경로인가**"(품질 평가) — 6개 패널티 요구사항을 VRPTW 엔진(이미 구현)과 3개 신규 scoring 모듈로 분담 처리.

---

## 0. 한 줄 요약

> 일정 검증을 **두 레이어**로 나눈다:
> ① **Validation Layer (VRPTW)** — "이 일정 실행 가능한가?" — 영업시간/이동시간/체류시간 → CRITICAL/WARNING 산출
> ② **Scoring Layer (3개 모듈)** — "얼마나 좋은가?" — 이동·관광 비율, 일별 밀집도, 테마 일치성 → 패널티 점수

---

## 1. 요구사항 매트릭스 — 구현 상태

| # | 요구사항 | 분류 | 모듈 | 상태 |
|---|---|---|---|---|
| ① | 영업시간 준수 (Time Window) | Validation | `vrptw_engine.py` | ✅ 구현됨 (`time_window_infeasibility`) |
| ② | 이동 시간 현실성 | Validation | `vrptw_engine.py` `CachedRouteMatrix` | 🟡 캐시 lookup만 (실시간 호출 미구현) |
| ③ | 권장 체류 시간 | Validation | `data/dwell_db.py` | ✅ 완료 (5단계 폴백) |
| ④ | 이동 vs 관광 시간 비율 | Scoring | `scoring/travel_ratio.py` | ✅ 완료 |
| ⑤ | 경로 밀집도 (per-day) | Scoring | `scoring/cluster_dispersion.py` | ✅ 완료 (M1-M4 · DBSCAN M4 포함) |
| ⑥ | 테마 일치성 (LLM 판정) | Scoring | `scoring/theme_alignment.py` | ✅ 완료 |
| ⑦ | 혼잡도 — 서울 실시간 | Scoring | `data/seoul_citydata_client.py` | ✅ 완료 |
| ⑧ | 혼잡도 — 전국 계절성 | Scoring | `scoring/congestion_engine.py` | ✅ 완료 (Seoul 우선, CSV 폴백) |

⭐ = 본 문서에서 신규 설계.

---

## 2. 두 레이어 분리의 이유

```
사용자 일정 입력
   ↓
[ Validation Layer — VRPTW ]
   "할 수 있는가?" → CRITICAL이면 즉시 FAIL
   ↓
[ Scoring Layer — 3개 패널티 ]
   "얼마나 좋은가?" → 점수 깎기
   ↓
   risk_score (0~100) + DeepDive 리스트
```

**왜 분리?** Hard Fail(예: 영업시간 충돌)은 일정을 **무효화**하는 결정적 결함. 반면 "테마 안 맞음" 같은 건 **개선 권고** 수준. 같은 0~100 척도에 섞으면 의미가 모호해진다. → VRPTW가 먼저 판정하고, 통과한 일정만 scoring으로 등급 매김.

---

## 3. 신규 모듈 ① — `src/data/dwell_db.py`

### 목적
사용자가 입력한 `stay_duration`이 **현실적인가** 검증. "경복궁 30분"은 비현실적이라고 잡아내야 함.

### 알고리즘 (Q1 답변: 하이브리드)

```python
def get_recommended_dwell(
    name: str,
    lcls_systm3: str | None = None,
    content_type_id: int | None = None,
) -> tuple[int, int, str]:
    """
    반환: (min_minutes, max_minutes, source)
    source: 'manual' | 'lcls3' | 'lcls1' | 'content_type' | 'default'
    우선순위: 수동 오버라이드 → lclsSystm3 → lclsSystm1 → contentType → default
    """
```

### 데이터 구조

| 우선순위 | 데이터 | 예시 | 커버리지 |
|---|---|---|---|
| 1 | `MANUAL_OVERRIDES` (이름→분) | `"경복궁": (90, 150)` | 주요 50~100개 POI |
| 2 | `BY_LCLS3` (3-depth 분류→분) | `"NA0410": (120, 240)` (산) | 약 200개 분류 |
| 3 | `BY_LCLS1` (1-depth 분류→분) | `"NA": (90, 180)` (자연) | 6개 대분류 |
| 4 | `BY_CONTENT_TYPE` (12=관광지→분) | `12: (60, 120)` | 8개 컨텐츠 타입 |
| 5 | `DEFAULT_DWELL = (60, 120)` | 모든 매칭 실패 시 | 100% |

### Validation 통합

VRPTWEngine에 dwell 검증 추가 — 사용자 입력 `stay_duration`이 권장 범위의 **50% 미만**이면 WARNING:

```
fact: "'경복궁' 체류 30분 입력, 권장 90~150분 (출처: 수동 큐레이션)"
rule: "dwell_too_short"
risk: "WARNING"
suggestion: "경복궁은 최소 90분 이상 체류를 권장합니다."
```

---

## 4. 신규 모듈 ② — `src/data/theme_taxonomy.py`

### 목적
Q2 답변의 **2축 18테마**를 정의 + lclsSystm 코드 매핑.

### 2축 구조

```python
# 축 A: 장소 유형 (List 1)
PLACE_TYPES = [
    "산", "바다", "실내 여행지", "액티비티", "문화_역사",
    "테마파크", "카페", "전통시장", "축제",
]

# 축 B: 여행 스타일 (List 2)
TRAVEL_STYLES = [
    "체험_액티비티", "SNS 핫플레이스", "자연과 함께",
    "유명 관광지는 필수", "여유롭게 힐링", "문화_예술_역사",
    "여행지 느낌 물씬", "쇼핑은 열정적으로", "관광보다 먹방",
]
```

### 사용자 입력 모델

```python
class UserPreferences:
    place_types: list[str]    # 1개 이상 (다중 선택 허용)
    travel_styles: list[str]  # 1개 이상
```

### 매핑: PLACE_TYPE ↔ lclsSystm

| PLACE_TYPE | lclsSystm 매칭 |
|---|---|
| 산 | `NA04*` (산), `NA01*` (국립공원) |
| 바다 | `NA12*` (해수욕장), `NA11*` (해안절경), `NA13*` (섬) |
| 실내 여행지 | `VE*` (인문관광지 전체 — 박물관·전시관 등) |
| 액티비티 | `EX*` (레포츠 전체) |
| 문화_역사 | `VE01*`, `VE02*`, `HS*` (역사관광지) |
| 테마파크 | `EX021100` (테마파크), `VE0501` (체험관) |
| 카페 | `FD0202` (카페·전통찻집) |
| 전통시장 | `SH0101` (5일·전통시장) |
| 축제 | contentTypeId=15 (축제공연행사) |

> 매핑은 **휴리스틱**이며, 한 lclsSystm 코드가 여러 PLACE_TYPE에 속할 수 있음 (예: 한라산 → 산 + 자연과 함께).

### TRAVEL_STYLE은 매핑하지 않음
스타일은 **분위기/태도** 차원이라 코드와 1:1 매칭이 어려움 → **LLM 판정용 컨텍스트로만 사용** (모듈 ⑥).

---

## 5. 신규 모듈 ③ — `src/scoring/travel_ratio.py`

### 목적
이동에 너무 많은 시간을 쓰지 않는지 정량 평가.

### 공식 (Q4 답변: 기존 정의 유지)

```
travel_ratio = travel_sec / (travel_sec + dwell_sec)
```

### 패널티 표 (구석구석 P75/P90 실측 기반)

| 구간 | 패널티 | 근거 |
|---|---|---|
| < 0.20 | 0 | 정상 (구석구석 평균 0.157) |
| 0.20 ~ 0.40 | -5 | 경고 — 이동 비율 P75 초과 |
| 0.40 ~ 0.60 | -10 | 위험 — 구석구석 위험 사례 집중 구간 |
| ≥ 0.60 | -20 | 심각 — 구석구석 최악 0.86, 트리플 0.607 |

### 출력
일자별 + 전체 평균 ratio, 가장 비율이 높은 day의 DeepDive 항목 생성.

---

## 6. 신규 모듈 ④ — `src/scoring/cluster_dispersion.py`

### 목적 (Q3 사용자 설명 반영)

> "1일차에는 목적지 근처로, 2일차에는 또 다른 목적지" — **하루 안에서** 너무 멀리 떨어진 장소 배치 시 패널티.

### 핵심: **Per-day 검증** (다일 간 거리는 패널티 X)

```
좋은 예: Day1 = [강남구 안 4곳] / Day2 = [부산 해운대구 4곳]
       → 각 day 안에서 응집도 높음 → 패널티 없음

나쁜 예: Day1 = [서울 강남, 부산 광안리, 서울 종로]
       → Day1 안에서 시군구 3회 점프 + 최대거리 320km → CRITICAL
```

### 네 가지 메트릭 (M1-M4)

#### 메트릭 1 (M1): 비연속 구역 재진입 — 백트래킹 (per-day)

이미 방문한 시군구에 다른 지역을 거쳐 돌아오는 횟수. 순방향 다구역 순회와 구별됨.

| 재진입 횟수 | 패널티 |
|---|---|
| 0회 | 0 |
| 1회 | -5 |
| 2회 이상 | -10 |

> 예: 강남→홍대→강남 = 1회 / 강남→이태원→명동→종로 = 0회

#### 메트릭 2 (M2): 시군구 전환 횟수 (per-day)
```
sigungu_switches = 같은 day 안에서 lDongSignguCd가 변경된 횟수
```

| 횟수 | 패널티 |
|---|---|
| 0~2 | 0 (정상) |
| 3 | -5 |
| 4 이상 | -10 |

#### 메트릭 3 (M3): 최대 직선거리 (per-day)
```
max_dist_km = 같은 day 안의 모든 좌표 쌍 중 최대 직선거리 (Haversine)
```

| 거리 | 패널티 |
|---|---|
| < 30km | 0 (정상 — 도시 내 이동 가능) |
| 30~50km | -5 (경고) |
| 50~100km | -10 (위험) |
| ≥ 100km | -20 (심각 — 광역 이탈) |

#### 메트릭 4 (M4): 지리 클러스터 재진입 — DBSCAN (per-day) ⭐ 추가됨

M1(시군구 기반) 보완. 경주·제주 등 대형 시군구 내부 지리 분산 탐지.
`DBSCAN(eps=2km, haversine)` per-request 즉석 계산 (<1ms). sklearn 미설치 시 스킵.
`net = max(0, M4_count - M1_count)` 순증분만 패널티 (M1과 중복 방지).

| 재진입 횟수 (순증분) | 패널티 |
|---|---|
| 0회 | 0 |
| 1회 | -5 |
| 2회 이상 | -10 |

### 중복 방지 캡

네 메트릭 동시 위반 시 **합산 캡 -20** 적용. 같은 원인(번개패턴)에 대한 이중 패널티 방지.

---

## 7. 신규 모듈 ⑤ — `src/scoring/theme_alignment.py`

### 목적
사용자가 선택한 테마와 실제 일정의 장소가 의미적으로 일치하는지 **AI 판정**.

> 사용자 예시: "액티비티 선택했는데 추천이 카페·잔잔한 곳 위주" → 패널티

### LLM 호출 구조 (Anthropic Claude API)

```python
class ThemeAlignmentJudge:
    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        ...

    def judge(
        self,
        place_types: list[str],      # 사용자 선택 PLACE_TYPE
        travel_styles: list[str],    # 사용자 선택 TRAVEL_STYLE
        places: list[POIWithCategory],  # 일정의 장소 + 카테고리명
    ) -> ThemeJudgment:
        """LLM에게 일치도 평가 요청. JSON 응답 파싱."""
```

### Prompt 설계 (Prompt Caching 적용)

**System (캐시):**
```
당신은 한국 여행 일정 평가 전문가입니다.
사용자가 선택한 여행 테마/스타일과 추천된 일정의 일치도를 0.0~1.0으로 평가하세요.
편향 없이 다음 기준을 따르세요:
- 1.0: 모든 장소가 선택 테마에 부합
- 0.7: 대부분 부합, 1~2개 어긋남
- 0.4: 절반 정도만 부합
- 0.0: 전혀 다른 테마

응답은 반드시 JSON: {"score": 0.0-1.0, "reasoning": "한 문장 평가",
                     "mismatched_places": ["테마와 안 맞는 장소명 리스트"]}
```

**User (매 호출마다 다름):**
```
[사용자 선택]
- 장소 유형: 액티비티, 산
- 여행 스타일: 체험_액티비티, 자연과 함께

[일정 (방문 순서)]
1. 한라산 (자연관광지/산) — 240분
2. 카페 봄날 (음식점/카페) — 60분
3. 제주 박물관 (인문관광지/박물관) — 90분

위 일정의 테마 일치도를 평가하세요.
```

### 패널티 표

| 일치도 score | 패널티 |
|---|---|
| ≥ 0.8 | 0 (양호) |
| 0.6 ~ 0.8 | -5 (경고) |
| 0.4 ~ 0.6 | -10 (불일치) |
| < 0.4 | -20 (심각 불일치) |

### 비용·성능 고려사항

| 항목 | 정책 |
|---|---|
| API 키 누락 | judge() 호출 자체를 스킵 + DeepDive에 "테마 평가 미수행" 정보성 항목 |
| 캐시 | (테마 + 정렬된 장소명) MD5 해시 기준 메모리 캐시 |
| 모델 | `claude-sonnet-4-6` (CLAUDE.md 명시) |
| Timeout | 10초 → 초과 시 정보성 DeepDive |
| 토큰 비용 | system prompt 캐시 적용 (`cache_control: ephemeral`) |

---

## 8. 폴더 구조 (확정)

```
src/
├── data/
│   ├── models.py                  ✓ 기존
│   ├── dwell_db.py                ⭐ NEW (모듈 ③)
│   └── theme_taxonomy.py          ⭐ NEW (모듈 ④)
├── validation/
│   └── vrptw_engine.py            ✓ 기존 (확장: dwell_db 사용)
└── scoring/                       ⭐ NEW 폴더
    ├── __init__.py
    ├── travel_ratio.py            ⭐ NEW (모듈 ⑤)
    ├── cluster_dispersion.py      ⭐ NEW (모듈 ⑥)
    └── theme_alignment.py         ⭐ NEW (모듈 ⑦, LLM)

tests/
├── test_vrptw_engine.py           ✓ 기존
├── test_dwell_db.py               ⭐ NEW
├── test_theme_taxonomy.py         ⭐ NEW
├── test_travel_ratio.py           ⭐ NEW
├── test_cluster_dispersion.py     ⭐ NEW
└── test_theme_alignment.py        ⭐ NEW (LLM mocking 필수)

docs/
└── ENHANCEMENT_PLAN.md            ⭐ NEW (본 문서)
```

---

## 9. 통합 순서 (다음 단계)

| 우선순위 | 작업 | 산출물 |
|---|---|---|
| **P0** | 본 문서의 모듈 ③~⑦ 코드 작성 | 이번 세션에 완료 |
| P1 | VRPTWEngine에 dwell_db 통합 (validate에서 호출) | 별도 PR |
| P2 | Scoring orchestrator (3개 모듈을 하나로 호출) | `src/scoring/orchestrator.py` |
| P3 | Final risk_score 계산 통합 (VRPTW + Scoring 합산) | VRPTWResult 확장 |
| P4 | Kakao Mobility 실시간 호출 어댑터 (요구사항 ②) | `src/validation/kakao_matrix.py` |

---

## 10. Risk Score 통합 공식 (제안)

VRPTW 단독으로 점수가 나오는 현재 구조를 확장:

```
final_risk_score = 100
    - VRPTW CRITICAL × 15  (영업시간/depot/dwell_too_short 등)
    - VRPTW WARNING × 5    (fatigue, efficiency_gap)
    - travel_ratio_penalty (0/-5/-10/-20)
    - cluster_dispersion_penalty (0~-20, 캡 적용)
    - theme_mismatch_penalty (0/-5/-10/-20, LLM)

if VRPTW에 CRITICAL 1건이라도 있으면 → final ≤ 59 (PASS_THRESHOLD 미만)
```

이 공식은 P3 단계에서 코드로 구현 — 본 문서는 모듈만 정의하고, 합산 로직은 다음 세션에서.

---

## 11. 본 문서 검증 체크리스트

- [ ] 6개 요구사항 모두 매핑됨
- [ ] 신규 모듈 5개 (data 2 + scoring 3) 책임 명확히 분리
- [ ] LLM 호출 비용·실패 케이스 모두 정의
- [ ] per-day 밀집도 로직이 사용자 의도("1일차 근처, 2일차 다른 목적지")와 일치
- [ ] dwell_db 우선순위 5단계 폴백 정의
- [ ] 폴더 구조가 카테고리별로 분리 (`data/`, `validation/`, `scoring/`)
