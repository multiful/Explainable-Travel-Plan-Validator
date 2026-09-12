<!-- updated: 2026-09-12 | hash: 2b231d35 | summary: Neo4j 제거 반영 (503·health 엔드포인트 갱신) -->
# API 설계 가이드

## 설계 원칙
1. **API-first**: UI 없음. Swagger UI(`/docs`)로 인터랙티브 테스트.
2. **에러는 명확하게**: 422 Validation Error + 상세 메시지. "unknown error" 금지.
3. **응답은 Pydantic 모델로**: dict 직접 반환 금지.

---

## 엔드포인트

### POST /validate
여행 일정 검증 실행.

**Request**
```json
{
  "places": [
    {"name": "경복궁",      "stay_minutes": 120, "visit_order": 1},
    {"name": "인사동",      "stay_minutes": 60,  "visit_order": 2},
    {"name": "남산서울타워", "stay_minutes": 90,  "visit_order": 3}
  ],
  "transport": "transit",
  "travel_type": "cultural",
  "date": "2024-07-20",
  "start_time": "09:00"
}
```

**필드 설명**
| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| places | list[PlaceInput] | Y | 방문 장소 목록 (4~8개) |
| transport | str | Y | "transit" / "car" / "walk" |
| travel_type | str | Y | "cultural" / "nature" / "shopping" / "food" / "adventure" |
| date | str | Y | YYYY-MM-DD |
| start_time | str | N | HH:MM (기본값: "09:00") |

**Response** (200)
```json
{
  "plan_id": "abc123def456",
  "final_score": 68,
  "hard_fails": [],
  "warnings": [
    {
      "type": "DENSE_SCHEDULE",
      "message": "3개 장소 체류 270분 + 이동 약 90분 = 360분. 기준(300분)을 초과합니다.",
      "affected_places": ["경복궁", "인사동", "남산서울타워"],
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
  "explanation": "경복궁(09:00 도착, 운영 09:00~18:00) → 인사동(11:20 도착, 운영 상시) → 남산서울타워(12:40 도착, 운영 10:00~23:00). 운영시간 충돌 없음. 동선: 종로구→종로구→중구로 이동 효율 양호. 다만 하루 일정으로 3개 장소 270분 체류 + 이동 약 90분은 여유 있게 계획하면 좋습니다.",
  "repair_suggestions": []
}
```

**Hard Fail 포함 예시**
```json
{
  "plan_id": "xyz789",
  "final_score": 42,
  "hard_fails": [
    {
      "type": "OPERATING_HOURS_CONFLICT",
      "message": "경복궁 도착 예상 08:30 / 운영 시작 09:00 → 30분 충돌",
      "affected_places": ["경복궁"],
      "confidence": "High",
      "evidence": {
        "fact": "도착 예상 08:30, 운영 시작 09:00",
        "rule": "도착 시간 < 운영 시작 → Hard Fail",
        "verdict": "운영시간 충돌",
        "suggestion": "출발 시간을 09:30 이후로 조정하거나 경복궁 방문 순서를 변경하세요"
      }
    }
  ],
  "warnings": [],
  "scores": {"efficiency": 0.80, "feasibility": 0.0, ...},
  "explanation": "...",
  "repair_suggestions": [
    {"priority": 1, "action": "CHANGE_START_TIME", "detail": "전체 출발 시간을 09:30으로 변경"}
  ]
}
```

**에러**
- `400`: 장소 수 범위 초과 (4개 미만 또는 8개 초과)
- `404`: TourAPI에서 장소를 찾을 수 없음
- `503`: Claude API 또는 외부 API 연결 실패

---

### Repair 제안
검증된 일정의 Repair 제안 반환.

**Response** (200)
```json
{
  "plan_id": "abc123def456",
  "repair_suggestions": [
    {
      "priority": 1,
      "action": "REORDER_PLACES",
      "affected_places": ["경복궁", "인사동"],
      "detail": "인사동을 1번째, 경복궁을 2번째로 순서 변경 시 이동시간 15분 단축"
    },
    {
      "priority": 2,
      "action": "REDUCE_STAY",
      "affected_places": ["경복궁"],
      "detail": "경복궁 체류시간을 120분 → 90분으로 줄이면 일정 과밀 Warning 해소"
    }
  ]
}
```

**에러**
- `404`: `plan_id`에 해당하는 검증 결과 없음

---

### GET /health
서버 상태 확인.

**Response** (200)
```json
{
  "status": "ok",
  "claude": "available",
  "seoul_api": "available"
}
```

---

## Fail/Warning 타입 목록

### Hard Fail 타입
| 타입 | 설명 |
|------|------|
| `OPERATING_HOURS_CONFLICT` | 도착 예상 시간이 POI 운영시간 외 |
| `TRAVEL_TIME_IMPOSSIBLE` | 이동시간 > 이용 가능한 시간 창 |
| `SCHEDULE_INFEASIBLE` | 전체 일정이 시간 내 수행 불가능 |

### Warning 타입
| 타입 | 설명 | Confidence |
|------|------|------------|
| `DENSE_SCHEDULE` | 장소 수 대비 시간 부족 | Medium |
| `INEFFICIENT_ROUTE` | 동선 비효율 (backtracking) | Medium |
| `PHYSICAL_STRAIN` | 이동 누적 거리/시간 과다 | Medium |
| `PURPOSE_MISMATCH` | 여행 타입 vs 실제 활동 불일치 | Medium-Low |
| `AREA_REVISIT` | 동일 구역 재방문 | Medium |

---

## AI 슬롭 안티패턴 — 하지 마라
| 금지 사항 | 이유 |
|-----------|------|
| `return {"status": "ok"}` dict 직접 반환 | 타입 안전성 없음. Pydantic Response 모델 사용 |
| 에러를 500으로 퉁치기 | 클라이언트가 원인 알 수 없음. 구체적 4xx/5xx 사용 |
| `time.sleep()` in async 함수 | `asyncio.sleep()` 사용 |
| 전역 변수에 연결 객체 저장 | FastAPI lifespan + dependency injection 사용 |
| 수정 제안 반환 | POST /api/validate 응답의 repair_suggestions에서 반환한다. 별도 /repair 호출은 제공하지 않는다. |
