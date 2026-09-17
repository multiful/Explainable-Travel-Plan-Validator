<!-- updated: 2026-09-16 | hash: 49262617 | summary: PRD↔PLAN↔코드 3대 충돌 해소 점수체계 교체 명문화·누락 Warning 2건 결정·Neo4j 제거 기록 -->
# Design Reconciliation — PRD ↔ ENHANCEMENT_PLAN ↔ 실제 코드

> ENHANCEMENT_PLAN(2026-04-26) 검토 중 발견된 **3대 정합성 이슈**를 해소하기 위한 결정 기록. 이 문서가 원본 문서들의 **상위 권위**를 가진다 (이후 충돌 시 본 문서 기준).

---

## 0. 문제 요약

비판적 검토에서 발견된 충돌:

| # | 이슈 | 원본 문서 | ENHANCEMENT_PLAN | 실제 코드 |
|---|---|---|---|---|
| A | **점수 공식**이 다름 | 5개 가중 평균 (Eff/Feas/Pf/Flow/AreaInt) | 100 - 패널티 누적 (VRPTW + 3 scoring) | PLAN과 일치 |
| B | **Soft Warning 5개 중 2개 누락** | DENSE/INEFF/STRAIN/PURPOSE/REVISIT | DENSE·INEFF·PURPOSE만 매핑 | STRAIN·REVISIT 미구현 |
| C | **Neo4j 위치** | 시스템 핵심 의존성 | 한 번도 언급 없음 | `src/graph/` 폴더 자체 없음 |

ENHANCEMENT_PLAN이 자체 일관성은 양호하나 **원본 문서를 폐기·교체하는 의도를 명시하지 않아** 신규 합류자가 혼란을 겪을 수 있다. 본 문서로 결정을 명문화한다.

---

## 1. 결정 ① — 점수 공식 교체 (PRD §점수체계 → PLAN §10)

### 변경 사항
- PRD의 **5개 가중 평균** 공식을 **deprecate**한다.
- ENHANCEMENT_PLAN의 **패널티 누적** 공식을 채택한다.

### 매핑 — 5개 지표 vs 신규 6개 패널티

| PRD 지표 (deprecated) | 신규 패널티 모듈 | 상태 |
|---|---|---|
| `Efficiency` (NN heuristic 거리) | `scoring/travel_ratio.py` (이동/관광 시간 비율) | **재정의** — 정의 변경 (거리→시간) |
| `Feasibility` (3 sub-score) | VRPTW Engine `time_window_infeasibility` + `safety_margin` | **흡수** |
| `PurposeFit` (코사인 유사도) | `scoring/theme_alignment.py` (LLM 판정) | **방법론 교체** — rule → LLM |
| `Flow` (backtracking) | `scoring/cluster_dispersion.py` (per-day) | **개념 확장** — 시간 순서 → 공간 응집도 |
| `AreaIntensity` (카테고리 분산) | **신규 모듈 필요** (§3 결정 참조) | **누락** → 본 문서에서 처리 |

### 최종 공식 (코드 기준)

```
final_risk_score = 100
    - VRPTW_CRITICAL_count × 15      (영업시간/안전마진/depot 제약)
    - VRPTW_WARNING_count × 5        (fatigue, efficiency_gap)
    - travel_ratio_penalty           (0/-5/-10/-20)
    - cluster_dispersion_penalty     (0~-20, 합산 캡)
    - theme_alignment_penalty        (0/-5/-10/-20, LLM)
    - category_revisit_penalty       (0/-5/-10, 신규 — §3 결정)
    - physical_strain_penalty        (0/-5/-10, 신규 — §3 결정)

if VRPTW에 CRITICAL ≥ 1 → final_risk_score = min(final, 59)
PASS_THRESHOLD = 60
```

### 영향 받는 문서 항목

- `docs/PRD.md` § 점수 체계 (line 30~40 부근) → **deprecated** 표기 필요
- `docs/ARCHITECTURE.md` § 점수 계산 공식 → **deprecated** 표기 필요
- `docs/ENHANCEMENT_PLAN.md` §10 → **본 문서의 최종 공식으로 교체**

---

## 2. 결정 ② — 누락된 PRD Warning 2건 처리

PRD의 5개 Soft Warning 중 ENHANCEMENT_PLAN에 매핑되지 않은 2건을 어떻게 처리할지 결정한다.

### 2-1. `PHYSICAL_STRAIN` (체력 부담 — 총 이동거리 30km 초과)

**결정**: `cluster_dispersion.py`에 **메트릭 3 추가** (별도 모듈 X).

**이유**:
- 거리 계산 인프라가 이미 `cluster_dispersion`에 있음 (Haversine)
- 메트릭 1·2(시군구 점프, max_pairwise_km)와 자연스럽게 연계 — 모두 *공간 차원* 검증
- 메트릭 1·2가 "최대 거리"라면, 메트릭 3은 "총 누적 거리"

**메트릭 3 명세**:
```
total_travel_km = sum(haversine(places[i], places[i+1]) for i in 0..n-1)  per-day
```

| 거리 | 패널티 | risk |
|---|---|---|
| < 30km | 0 | OK |
| 30 ~ 50km | -5 | WARNING |
| ≥ 50km | -10 | WARNING |

**중복 방지**: 메트릭 1·2·3 합산 캡 -25 (기존 -20에서 +5).

**구현 위치**: `src/scoring/cluster_dispersion.py`의 `evaluate_cluster_dispersion()` 함수 안에서 동시 산출.

### 2-2. `AREA_REVISIT` (구역 재방문 — 동일 카테고리 연속 방문)

**결정**: **신규 모듈** `src/scoring/category_revisit.py` 생성.

**이유**:
- 공간(distance)·시간(travel_ratio)과는 **다른 차원** — *카테고리* 측면
- "박물관 → 박물관 → 박물관" 패턴은 거리·시간으로는 잡히지 않음
- 이미 `theme_alignment`가 LLM 기반 판정이므로 rule 기반은 별도 분리하는 게 합리적

**모듈 명세**:

```python
# src/scoring/category_revisit.py
def evaluate_category_revisit(days: list[VRPTWDay], lcls_codes_per_day) -> Report:
    """동일 카테고리(lclsSystm1 또는 lclsSystm2) 연속 방문 횟수 산출.

    예: [VE0101, VE0102, VE0301, FD02] → 박물관/기념관/전시관(VE) 3연속 → AREA_REVISIT
    """
```

| 동일 lclsSystm1 연속 방문 | 패널티 | risk |
|---|---|---|
| ≤ 2회 (2개 같은 카테고리는 OK) | 0 | OK |
| 3회 | -5 | WARNING |
| 4회 이상 | -10 | WARNING |

**입력 데이터**: `pois.csv`의 `lclsSystm1` 컬럼 활용 — 이미 수집됨.

### 2-3. 영향 받는 코드 변경

| 파일 | 변경 | 우선순위 |
|---|---|---|
| `src/scoring/cluster_dispersion.py` | 메트릭 3 (`total_travel_km`) 추가 | P1 |
| `src/scoring/category_revisit.py` | 신규 작성 | P1 |
| `tests/test_cluster_dispersion.py` | 메트릭 3 테스트 케이스 추가 | P1 |
| `tests/test_category_revisit.py` | 신규 작성 | P1 |
| `gun/docs/DESIGN_RECONCILIATION.md` | (본 문서) — 결정 기록 완료 | P0 ✓ |

---

## 3. 과거 결정 — Neo4j MVP 제외

### 결정
- **MVP 범위에서 Neo4j 제외**.
- 이 문서는 당시의 범위 결정 기록이다. 현재 ADR-005에서는 Neo4j를 제품 런타임과 의존성에서 제거하고, 로컬 근거 카탈로그로 대체했다.
- VRPTW 검증 로직은 in-memory Pydantic 객체로 충분히 작동 (이미 검증됨).

### 이유
1. **현재 in-memory 검증으로 모든 Hard Fail/Warning을 산출 가능** — Neo4j Cypher 쿼리 없이도 `_simulate_day()` 함수가 정확히 같은 결과를 낸다.
2. **그래프 DB의 가치는 분석·시각화 단계에서 발생** — "어떤 POI가 가장 많은 일정에 등장하는가" 같은 통계는 검증 로직이 아닌 BI 영역.
3. **MVP 범위 줄이는 게 출시 우선순위에 부합** — 공모전 마감 전 검증 엔진 + UI 완성이 최우선.
4. **Docker/Neo4j 운영 비용** — 단일 서비스 의존성이 늘면 배포 복잡도 ↑.

### Phase 7 시점 (제안)

다음 조건이 모두 충족되면 Neo4j 도입 재검토:

| 조건 | 충족 시점 |
|---|---|
| 검증 일정 데이터 1만 건 이상 누적 | 사용자 100명 × 100건 |
| 통계 보고서 요구 ("월별 가장 인기 있는 코스" 등) | 운영 3개월 후 |
| 그래프 시각화 UI 추가 (D3.js + Cypher 쿼리) | 차기 메이저 버전 |

### 영향 받는 문서 항목

- `docs/ARCHITECTURE.md` §시스템 흐름 → "Graph layer는 phase 7 연기" 주석 필요
- `docs/ARCHITECTURE.md` §디렉토리 구조 → `src/graph/` 항목 제거 또는 *(deferred)* 표기
- `docs/ADR.md` ADR-005 → "**연기**: MVP 외 phase 7+로 연기" 추가
- `phases/3-graph/index.json` → status `pending` → `deferred`

---

## 4. ENHANCEMENT_PLAN 자체 수정사항

검토에서 발견된 작은 이슈들 — ENHANCEMENT_PLAN을 다음 회차에 갱신할 때 반영.

| 위치 | 이슈 | 수정안 |
|---|---|---|
| 맨 위 | PRD/ARCH 폐기 의도 미명시 | "본 문서는 PRD §점수체계와 ARCHITECTURE §scoring을 대체합니다" 한 줄 추가 |
| §1 매트릭스 | PRD Warning 2건 누락 | PHYSICAL_STRAIN, AREA_REVISIT 행 추가 (본 문서 §2 결정 참조) |
| §7 LLM 평가 기준 | 5단계(0.7/0.4) vs 코드 6단계(0.8/0.6/0.4) 불일치 | 코드 기준 6단계로 통일 |
| §10 점수 공식 | "WARNING × 5" — 실제 코드는 `CRITICAL × 15, WARNING × 5` 가중치 | 본 문서 §1 최종 공식으로 교체 |
| §11 검증 체크리스트 | 모두 미체크 | 완료된 6개 항목에 `[x]` 표기 |
| 임계값 인용 | 출처 파일 링크 없음 | `phases/0-setup/statistical_report.json` 링크 추가 |
| 테마-lclsSystm 매핑 | 코드는 휴리스틱 추정 | 실측 데이터로 검증 후 수정 (TODO 주석 보강) |

---

## 5. 다음 단계 — 갱신된 통합 순서

ENHANCEMENT_PLAN §9의 P0~P4를 본 문서 결정사항을 반영하여 재정렬:

| 우선순위 | 작업 | 대상 파일 |
|---|---|---|
| **P0** ✓ | 본 문서 작성 | `gun/docs/DESIGN_RECONCILIATION.md` |
| **P0** | ENHANCEMENT_PLAN 맨 위에 본 문서 참조 + supersession 명시 | `gun/docs/ENHANCEMENT_PLAN_v3.md`(보강판)? 또는 원본 `docs/ENHANCEMENT_PLAN.md` 헤더 갱신 |
| **P1** | `cluster_dispersion.py`에 메트릭 3 (`total_travel_km`) 추가 | `src/scoring/cluster_dispersion.py` + 테스트 |
| **P1** | `category_revisit.py` 신규 작성 | `src/scoring/category_revisit.py` + 테스트 |
| **P1** | VRPTWEngine에 dwell_db 통합 (PLAN §3 약속의 미반영분) | `src/validation/vrptw_engine.py` + 테스트 |
| **P2** | Scoring orchestrator (5개 모듈 일괄 호출) | `src/scoring/orchestrator.py` |
| **P2** | Final risk_score 통합 함수 — 본 문서 §1 공식 | `src/scoring/orchestrator.py` |
| **P3** | Kakao Mobility 실시간 어댑터 (이미 다른 폴더에 있음 — 이전) | `src/validation/kakao_matrix.py` |
| **P4** | (deferred) Neo4j — phase 7+로 연기 | `docs/ARCHITECTURE.md`, `docs/ADR.md` 갱신만 |

---

## 6. 결론

본 문서가 결정한 사항을 한 표로 요약:

| 영역 | 결정 |
|---|---|
| **점수 공식** | PRD 5지표 deprecate → ENHANCEMENT_PLAN 패널티 누적 채택 + 본 문서 §1의 최종식 |
| **PHYSICAL_STRAIN** | `cluster_dispersion`의 메트릭 3으로 흡수 |
| **AREA_REVISIT** | `category_revisit.py` 신규 모듈로 분리 |
| **Neo4j** | MVP 제외, phase 7+로 연기 |
| **PLAN 7개 자체 결함** | 다음 갱신 회차에 일괄 반영 (§4) |

이 결정은 **2026-04-29 시점에서 유효**하며, 추후 본 문서의 어떤 결정이라도 변경 시 새 ADR 또는 개정판으로 명시한다.

---

## 7. 검증 체크리스트

- [x] PRD ↔ PLAN 점수 공식 충돌 명시
- [x] 누락된 Warning 2건의 처리 결정 (PHYSICAL_STRAIN → cluster_dispersion 메트릭 3, AREA_REVISIT → 신규 모듈)
- [x] Neo4j 제거 결정과 로컬 근거 카탈로그 대체를 현재 ADR에 반영
- [x] ENHANCEMENT_PLAN 자체 보완 사항 7건 정리
- [x] 갱신된 P0~P4 통합 순서 제시
- [ ] (다음 단계) 본 문서 결정사항을 코드에 반영 — P1 작업들
