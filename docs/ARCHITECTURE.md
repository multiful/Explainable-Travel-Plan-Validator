<!-- updated: 2026-09-12 | hash: 22d55ea2 | summary: Neo4j 제거, M1-M4 cluster_dispersion, 서울 도시데이터 API, 혼잡도 하이브리드 구조 반영 -->
# 아키텍처

## 시스템 흐름

```
사용자 입력 (places + transport + travel_type + date)
    ↓
[API Layer] POST /validate
    ↓
[Explain Layer] ValidationOrchestrator.run(plan)
    ├── [Data]       TourAPIClient.get_poi(name)          → POI 메타데이터 (운영시간, 위치, 카테고리)
    ├── [Data]       KakaoClient.normalize_poi(name)      → 정규화된 POI 좌표 (Kakao Local API)
    ├── [Matrix]     TravelMatrixBuilder.build(pois)      → Pairwise 이동시간 행렬 (Kakao Mobility)
    ├── [Validation] HardFailDetector.detect(plan)        → Hard Fail 목록
    ├── [Validation] WarningDetector.detect(plan)         → Warning 목록
    ├── [Scoring]    VRPTWEngine.compute(plan, matrix)    → Efficiency Gap (OR-Tools 최적 경로 대비)
    ├── [Scoring]    evaluate_cluster_dispersion(days)    → M1-M4 밀집도 패널티
    ├── [Scoring]    CongestionEngine.score(poi, month)   → 혼잡도 계수 (실시간 + 통계 하이브리드)
    ├── [Scoring]    ThemeAlignmentJudge.judge(plan)      → 테마 일치도 (LLM 판정 유일 예외)
    └── [Explain]    ExplainEngine.explain(result)        → LLM 설명 + Repair 제안
    ↓
ValidationResult (Pydantic 모델)
```

## 디렉토리 구조

```
src/
├── data/
│   ├── models.py                # POI, ItineraryPlan, ValidationResult, VRPTWDay, Settings
│   ├── tour_api.py              # TourAPI v2 클라이언트 (async httpx)
│   ├── kakao_client.py          # Kakao Local + Mobility API 클라이언트 (async httpx)
│   ├── seoul_citydata_client.py # 서울 도시데이터 API — 실시간 인구 혼잡도 (115개소)
│   ├── dwell_db.py              # 권장 체류시간 DB (5단계 폴백)
│   └── theme_taxonomy.py        # 여행 테마 × POI 카테고리 매핑 테이블
├── scoring/
│   ├── cluster_dispersion.py    # M1-M4 하루 밀집도 패널티 (DBSCAN M4 포함)
│   ├── congestion_engine.py     # POI × month → 혼잡 계수 (Seoul API 우선, CSV 폴백)
│   ├── theme_alignment.py       # 테마-POI 의미적 일치도 (LLM 판정)
│   └── travel_ratio.py          # 이동시간 비율 → Efficiency Gap
├── validation/
│   ├── hard_fail.py             # Hard Fail 탐지 (운영시간 충돌, 이동 불가 등)
│   ├── warning.py               # Warning 탐지 (동선 비효율, 일정 과밀 등)
│   └── vrptw_engine.py          # OR-Tools VRPTW 최적화 엔진
├── explain/
│   ├── prompts.py               # LLM 프롬프트 템플릿 (prompt caching 적용)
│   ├── explain_engine.py        # Claude API 호출 → Evidence-based 설명
│   └── orchestrator.py          # 전체 파이프라인 오케스트레이터
└── api/
    ├── main.py                  # FastAPI app + lifespan
    ├── router.py                # /api/validate, /api/places, /health
    └── schemas.py               # ValidateRequest, ValidateResponse Pydantic 스키마
tests/
├── test_cluster_dispersion.py   # M1-M4 밀집도 7개 테스트
├── test_congestion_engine.py    # 혼잡도 엔진 20개 테스트
├── test_dwell_db.py
├── test_theme_alignment.py
├── test_theme_taxonomy.py
├── test_travel_ratio.py
└── test_vrptw_engine.py
```

## cluster_dispersion — M1-M4 메트릭

| 메트릭 | 측정 대상 | 임계값 | 패널티 |
|--------|-----------|--------|--------|
| M1. sigungu_switches | 같은 day 안 시군구 전환 횟수 | ≥3 WARNING / ≥4 CRITICAL | -5 / -10 |
| M2. max_pairwise_km | Haversine 최대 직선거리 | ≥30 / ≥50 / ≥100km | -5 / -10 / -20 |
| M3. area_backtrack_count | 시군구 비연속 재진입 (O(n)) | ≥1 WARNING / ≥2 CRITICAL | -5 / -10 |
| M4. geo_cluster_backtrack | DBSCAN(eps=2km) 지리 클러스터 재진입 | ≥1 WARNING / ≥2 CRITICAL | -5 / -10 |

- M3 보완: M4는 경주·제주 등 대형 시군구 내부 분산 탐지
- 이중 패널티 방지: `net = max(0, M4_count - M3_count)` — M3가 이미 탐지한 이벤트는 M4 패널티 제외
- 합산 캡: 한 day 최대 -20 (COMBINED_PENALTY_CAP)

## 혼잡도 판정 — 하이브리드 데이터 소스

```
CongestionEngine.score(poi_name, month)
    ├── 0순위: SeoulCityDataClient.get(poi_name)  → 서울 115개소 실시간 혼잡도
    │          (주입된 경우만; API 실패 시 자동 폴백)
    ├── 1순위: CSV 정확 매칭 (data/congestion_stats.csv — 한국문화관광연구원 2020~2024)
    ├── 2순위: 부분 문자열 매칭 (longest match)
    ├── 3순위: POI명 2글자 접두어 카테고리 평균
    └── 4순위: 전체 월평균
```

| fallback_used | 설명 |
|---------------|------|
| `seoul_realtime` | 서울 도시데이터 API 실시간 성공 |
| `exact` | CSV 정확 매칭 |
| `partial` | CSV 부분 문자열 매칭 |
| `category` | POI명 접두어 카테고리 평균 |
| `global` | 전체 평균 (최후 폴백) |

## 데이터 흐름 (검증 파이프라인 상세)

```
1. TourAPI     → POI(name, lat, lng, category, open_start, open_end, usetime)
2. Kakao Local → 정규화된 좌표 (폴백: TourAPI 좌표 그대로 사용)
3. Kakao Mobility → TravelMatrix[i][j] = (travel_min, distance_km, mode)
   ※ 키 없음 → Haversine × 속도계수(transit:1.3, car:1.1, walk:1.0) 폴백
4. Validation (순수 Python, I/O 없음):
   hard_fails = HardFailDetector.detect(plan, matrix)
   warnings   = WarningDetector.detect(plan, matrix)
5. Scoring:
   vrptw_gap    = VRPTWEngine.compute(plan, matrix)          # Efficiency Gap
   dispersion   = evaluate_cluster_dispersion(days, codes)   # M1-M4
   congestion   = CongestionEngine.score_itinerary(pois, month)
   theme_score  = ThemeAlignmentJudge.judge(plan)            # LLM 판정
6. Explain: ExplainEngine.explain(plan, hard_fails, warnings, scores)
   → ValidationResult(plan_id, final_score, hard_fails, warnings, scores, explanation, repair_suggestions)
```

## 점수 계산 공식

```
cluster_dispersion_penalty = sum(per_day_penalty)   # M1+M2+M3+M4 합산, day별 캡 -20
vrptw_efficiency_gap       = actual_time / optimal_time - 1.0   (>0.20 → WARNING)
congestion_coefficient     = POI별 congestion_score 평균 (0.0~1.0)
theme_alignment_score      = ThemeAlignmentJudge 판정 (0.0~1.0)

Final Score (0~100) =
    round(100
        - cluster_dispersion_penalty × weight_cd
        - vrptw_efficiency_gap       × weight_ef
        - congestion_coefficient     × weight_cg
        + theme_alignment_score      × weight_th)

Hard Fail 존재 시: Final Score = min(Final Score, 59)
```

## 데이터 신뢰도

| 수준 | 조건 | 결과 표시 |
|------|------|-----------|
| High | Kakao 실시간 API 성공 + TourAPI 운영시간 정상 | (표시 없음) |
| Medium | 캐시 경로 또는 dwell_db 추정값 사용 | "(추정)" 표시 |
| Low | Haversine 폴백 또는 지오코딩 실패 | 경고 메시지 |

## 설정 관리

**Settings 주요 필드** (`src/data/models.py` — pydantic-settings, `.env` 자동 로드)

| 필드 | 기본값 | 설명 |
|------|--------|------|
| ANTHROPIC_API_KEY | (필수) | Claude API 인증 |
| CLAUDE_MODEL | "claude-sonnet-4-6" | LLM 모델명 |
| TOUR_API_KEY | (필수) | 한국관광공사 API 인증 |
| KAKAO_REST_API_KEY | (필수) | Kakao Local API 인증 |
| KAKAO_MOBILITY_KEY | "" | Kakao Mobility API (없으면 Haversine 폴백) |
| SEOUL_DATA_API_KEY | "" | 서울 도시데이터 API (없으면 CSV 폴백) |

## 설명 엔진 출력 구조 (4단계)

모든 판정은 아래 4단 구조로 LLM에게 생성하도록 지시한다:

1. **발견된 사실**: 경복궁 종료 18:00 / 체류 계획 90분 / 혼잡도 HIGH (5월 실시간)
2. **적용된 규칙**: 혼잡도 ≥0.7 → 대기 시간 추가 소요 가능성
3. **위험 판정**: 체류 시간이 대기 포함 시 부족할 수 있음 (Medium confidence)
4. **개선 제안**: 체류 시간 30분 추가 또는 오전 일찍 방문으로 혼잡 회피

## Repair 제안 우선순위

```
1순위: Hard Fail 제거 (운영시간 조정, 방문 순서 변경)
2순위: 구역 재방문/백트래킹 제거 (M3/M4 감지 기반)
3순위: 일정 과밀 완화 (장소 축소 또는 체류시간 조정)
4순위: 목적 적합성 개선
5순위: 이동 효율 개선
```

## 오류 처리 전략

| 컴포넌트 | 실패 조건 | 처리 방식 | 결과 |
|---------|-----------|-----------|------|
| TourAPI | 관광지 없음 | `raise ValueError` | API 404 반환 |
| TourAPI | HTTP 5xx / 타임아웃 | 3회 재시도 후 `raise` | API 503 반환 |
| Kakao Local | POI 정규화 실패 | TourAPI 좌표 사용 (폴백) | Warning 추가 |
| Kakao Mobility | 키 없음 / 실패 | Haversine × 속도계수 폴백 | Confidence↓ |
| Seoul 도시데이터 | 키 없음 / API 실패 | CSV 폴백 자동 전환 | `fallback_used` 기록 |
| Claude API | 타임아웃 | 3회 재시도 후 `raise` | API 503 반환 |
| Validation | 파싱 오류 | `raise` (즉시 노출) | API 500 반환 |

## 성능 고려사항

| 항목 | 예상 시간 | 최적화 방법 |
|------|-----------|-------------|
| TourAPI (POI당) | ~0.5-1s | asyncio.gather로 병렬 호출 |
| Kakao Mobility 행렬 | ~1-3s (N≤8) | 순차 호출로 충분 (최대 56 쌍) |
| Seoul 도시데이터 API | ~0.2-0.5s | POI당 1 호출, 실패 시 즉시 폴백 |
| DBSCAN M4 (4-8 POI) | <1ms | per-request 즉석 계산, DB 불필요 |
| VRPTW (OR-Tools) | <10ms (N≤8) | 평균 4.3개 POI 기준 밀리초 내 수렴 |
| Claude API 호출 | ~3-8s | SYSTEM_PROMPT caching으로 토큰 ~60% 절감 |
| 전체 /validate | ~8-15s (cold) / ~5-8s (warm) | TourAPI 응답 인메모리 캐시 |
