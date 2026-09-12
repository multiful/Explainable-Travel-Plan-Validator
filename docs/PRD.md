<!-- updated: 2026-09-12 | hash: 0863df04 | summary: Neo4j 제거, 실시간 혼잡도 MVP 포함, 기술 제약 갱신 -->
# PRD: Explainable Travel Plan Validator

## 목표
사용자가 직접 만든 여행 일정을 입력하면,
**실행 가능성 · 동선 품질 · 체력 부담 · 경험 편향 · 실패 위험**을
설명 가능한 방식으로 검증하는 AI QA 레이어를 구축한다.

> "우리는 여행을 추천하지 않는다. 그 일정이 실패할지, 성공할지를 증명한다."

## 사용자
- **여행 계획자**: 자신이 만든 일정의 현실적 실행 가능성을 미리 검증하고 싶은 일반인
- **여행사/플랫폼 (B2B)**: AI 일정 생성 후 품질 검증 레이어가 필요한 서비스

## 핵심 기능

1. **일정 검증** (`POST /api/validate`): 여행 일정 입력 → Hard Fail/Warning 탐지 → 점수 + 설명 보고서
2. **수정 제안**: 검증 응답의 `repair_suggestions` 필드로 즉시 반환
3. **REST API**: FastAPI `/api/validate`, `/api/places`, `/health` 엔드포인트

## 검증 프레임워크

### Hard Fail (Critical)
- 운영시간 충돌: 도착 예상 시간이 POI 운영시간 외
- 이동 불가능: 이동시간이 이동 가능 창(time window)을 초과
- 시간적 수행 불가: 전체 일정이 시간 내 수행 불가능

※ Hard Fail 존재 시: `Final Score Cap = 59`

### Soft Warning
- 동선 비효율 (backtracking, zigzag)
- 일정 과밀 (장소 수 대비 시간 부족)
- 체력 부담 (이동 누적 거리/시간 과다)
- 경험 편향 (여행 타입 vs 실제 활동 분포 불일치)
- 구역 재방문

## 점수 체계

```
Final Score (0~100) =
    0.30 × Efficiency      (이동 효율)
  + 0.25 × Feasibility     (실행 가능성)
  + 0.20 × PurposeFit      (목적 적합성)
  + 0.15 × Flow            (동선 흐름)
  + 0.10 × AreaIntensity   (지역 강도)

Hard Fail 존재 시: Final Score = min(계산값, 59)
```

점수는 "요약"일 뿐. 핵심은 **Fail/Warning + Evidence-based Explanation**.

## MVP 입출력

### 입력
- 장소 4~8개 + 이동수단 + 여행 타입 + 날짜

```json
{
  "places": [
    {"name": "경복궁", "stay_minutes": 120, "visit_order": 1},
    {"name": "인사동", "stay_minutes": 60,  "visit_order": 2},
    {"name": "남산서울타워", "stay_minutes": 90, "visit_order": 3}
  ],
  "transport": "transit",
  "travel_type": "cultural",
  "date": "2024-07-20"
}
```

### 출력
```json
{
  "plan_id": "abc123def456",
  "final_score": 68,
  "hard_fails": [],
  "warnings": [
    {
      "type": "DENSE_SCHEDULE",
      "message": "3개 장소에 총 270분 체류 + 이동시간 약 90분 = 360분. 하루 일정 기준 과밀.",
      "confidence": "Medium"
    }
  ],
  "scores": {
    "efficiency": 0.82,
    "feasibility": 0.90,
    "purpose_fit": 0.75,
    "flow": 0.70,
    "area_intensity": 0.65
  },
  "explanation": "경복궁(09:00~18:00)은 도착 예상 09:10으로 운영시간 내 방문 가능합니다...",
  "repair_suggestions": []
}
```

## MVP 제외 사항
- 멀티데이 일정 (per-day 검증은 포함, 다일 간 연계는 제외)
- 개인 체력 모델
- 프론트엔드 UI (Swagger UI로 테스트)
- 사용자 인증/권한

## 디자인 원칙
- **Explainability 우선**: 모든 판정에 증거(사실 → 규칙 → 판정 → 제안) 4단 구조 명시
- **Constraint-based Repair**: 최적화가 아닌 제약 기반 수정 제안 (Hard Fail 제거 우선)
- **Confidence 명시**: 데이터 한계를 Confidence Level (High / Medium / Medium-Low)로 반영
- **Mock-first**: 외부 의존성(TourAPI, Kakao, Seoul API, Claude API)이 없어도 테스트 가능

---

## 사용자 스토리

### Story 1 — 여행 계획자
> "서울 당일 여행 일정을 만들었는데, 실제로 실행 가능한지 확인하고 싶다."

- `POST /validate` 로 일정 제출
- Hard Fail 없음, Warning 2개 (일정 과밀, 동선 비효율) 확인
- 설명을 읽고 방문 순서 변경

### Story 2 — 수정 제안 요청자
> "검증 결과에서 비효율적인 동선이 있었다. 자동 수정 제안을 받고 싶다."

- `POST /api/validate` 응답의 `repair_suggestions`로 Repair 제안 수신
- 우선순위: Hard Fail 제거 → 재방문 제거 → 일정 과밀 완화 → 효율 개선

### Story 3 — B2B 여행 플랫폼
> "AI가 생성한 여행 일정의 품질을 자동으로 검증하고 싶다."

- 일정 생성 후 `POST /validate` 자동 호출
- `final_score < 60` (Hard Fail 존재) → 일정 재생성 트리거

---

## 성공 지표

| 지표 | 목표 | 측정 방법 |
|------|------|---------|
| Hard Fail 탐지 정확도 | ≥ 90% | Synthetic test (의도적 Hard Fail 주입) |
| API 응답 시간 | < 10초 (warm) | `time curl` 측정 |
| Warning 탐지 정확도 | ≥ 75% | 수동 라벨링 20개 일정 기준 |
| 테스트 커버리지 | ≥ 80% (src/ 기준) | `pytest --cov=src` |
| 전체 파이프라인 성공률 | ≥ 95% | 10개 일정 반복 실행 |

---

## 기술적 제약

| 제약 | 내용 | 대응 방안 |
|------|------|---------|
| Kakao Mobility API | B2B 신청 필요 | MVP 폴백: 직선거리 × 속도계수로 이동시간 추정 |
| TourAPI 일일 한도 | 10,000 쿼리/키 | 검증 1회당 POI당 최대 2 API 호출 계획 |
| 서울 도시데이터 API | 서울 115개소 한정 | 미커버 POI는 한국문화관광연구원 5개년 CSV 통계로 폴백 |
| sklearn (DBSCAN M4) | 미설치 시 M4 자동 스킵 | graceful fallback, M1-M3로 대체 |
| Claude API 의존성 | 오프라인 환경에서 설명 생성 불가 | Validation/Scoring 결과는 오프라인 동작; LLM은 설명에만 사용 |
