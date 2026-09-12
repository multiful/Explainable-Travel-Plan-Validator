<!-- updated: 2026-09-12 | hash: 9b1cb461 | summary: ADR-005 Neo4j 제거 확정(Python M3/M4 대체), 제거 기술 표 갱신 -->
# Architecture Decision Records

## 철학
MVP 속도 최우선. 로컬 실행 가능하고 별도 인프라를 최소화하는 도구 우선.  
외부 API 의존성은 명확히 격리하고, 테스트에서 mock으로 대체 가능한 구조를 선택한다.

---

### ADR-001: POI 정규화 — Kakao Local API 선택
**결정**: Kakao Local API (`/v2/local/search/keyword.json`)  
**이유**: 장소명 → 정규화 좌표 변환에 가장 정확한 국내 서비스. TourAPI의 위치 데이터보다 정밀하고, 주소 기반 POI 검색 지원.  
**트레이드오프**: Google Places 대비 영어 지원 약함. MVP는 한국어 전용이므로 문제없음.

---

### ADR-002: 이동시간 계산 — Kakao Mobility API + 직선거리 폴백
**결정**: Kakao Mobility API (B2B) 우선, 키 없을 시 직선거리 × 속도계수 폴백  
**이유**: Kakao Mobility는 실제 도로 경로/대중교통 시간을 제공하는 국내 최고 정확도 서비스. 단, B2B 신청 필요.  
**폴백 공식**: `travel_min = (직선거리_km / 속도_kmh) × 60 × 경로계수`
- transit: 속도 20km/h, 경로계수 1.3
- car: 속도 40km/h, 경로계수 1.1  
- walk: 속도 4km/h, 경로계수 1.0  
**트레이드오프**: 폴백 사용 시 이동시간 정확도↓ → Confidence Level을 Medium-Low로 하향.

---

### ADR-003: 검증 방식 — 제약 기반 규칙 엔진 (vs ML 기반)
**결정**: 규칙 기반 Hard Fail/Warning 탐지  
**이유**: 운영시간 충돌·이동 불가 같은 명확한 제약은 규칙으로 표현이 완전하다. ML 모델은 레이블 데이터가 없고, "왜 실패하는지" 설명이 불가능하다. Explainability가 핵심 가치이므로 규칙 기반이 필수.  
**트레이드오프**: 복잡한 맥락적 판단(예: "이 일정은 여행자에게 피로할 것인가")은 규칙보다 LLM에게 위임.

---

### ADR-004: LLM — Claude claude-sonnet-4-6 선택 (Explanation 전용)
**결정**: Anthropic `claude-sonnet-4-6`, prompt caching 적용  
**이유**: 4단계 Evidence-based 설명 생성과 Repair 제안 문장화에 최적. 200K 토큰 컨텍스트로 전체 일정 맥락 제공 가능. `cache_control`로 시스템 프롬프트 캐싱.  
**트레이드오프**: API 의존성. Validation 자체(Hard Fail/Warning/Score)는 LLM 없이 동작하므로 LLM 실패 시 부분 응답 가능.

---

### ADR-005: Graph DB — Neo4j 제거, Python 순수 구현으로 대체 (2026-04-30)
**결정**: Neo4j 제거 확정. 백트래킹·구역 재진입 탐지를 Python 규칙 기반 M3/M4 메트릭으로 완전 대체.  
**이유**: `scripts/neo4j_coverage_analysis.py` 커버리지 검증 결과, Neo4j가 담당하던 7개 역할을 Python 로직이 100% 대체함을 확인.  
- M3 `count_area_backtracks()`: 시군구 코드 기반 비연속 재진입, O(n) — Cypher 쿼리 완전 대체  
- M4 `count_geo_cluster_backtracks()`: DBSCAN(eps=2km), Neo4j가 잡지 못하던 대형 시군구 내부 분산까지 추가 탐지  
- 이동 행렬·시간 슬롯 저장 역할은 VRPTW 엔진 내부 Python 자료구조로 처리  
**트레이드오프**: 그래프 시각화·복잡 관계 쿼리는 불가하나, MVP 검증 범위 내에서는 불필요.

---

### ADR-006: API 프레임워크 — FastAPI 선택
**결정**: `FastAPI` + `uvicorn`  
**이유**: async 지원 (TourAPI/Kakao API 병렬 호출 필수). Pydantic 통합. Swagger UI 자동 생성. 타입 안전성.  
**트레이드오프**: Flask 대비 복잡도 높지만 async + 자동 문서화가 더 중요.

---

### ADR-007: HTTP 클라이언트 — httpx 선택
**결정**: `httpx` (async)  
**이유**: TourAPI + Kakao API를 `asyncio.gather`로 병렬 호출. FastAPI lifespan에서 클라이언트 재사용. `httpx.AsyncClient`는 연결 풀 자동 관리.  
**트레이드오프**: requests 대비 학습 곡선 있음. async I/O 이점이 압도적으로 크므로 선택.

---

### ADR-008: 의존성 관리 — pyproject.toml
**결정**: `pyproject.toml` + `setuptools` (editable install `pip install -e ".[dev]"`)  
**이유**: 표준 Python 패키지 구조. `src/` 레이아웃으로 import 충돌 방지.  
**트레이드오프**: Poetry/uv 대비 설정 약간 번거롭지만 추가 도구 설치 없이 동작.

---

## 제거된 기술 (구 설계 대비)

| 제거 항목 | 이유 |
|----------|------|
| Neo4j | Python M3/M4 메트릭으로 100% 대체 확인 (ADR-005 참조). Docker 의존성 제거. |
| ChromaDB (Vector Store) | 검증 시스템은 RAG 불필요. 제약 기반 규칙 + LLM으로 충분. |
| sentence-transformers | 임베딩 불필요. 검색 대신 규칙 엔진 사용. |
| kiwipiepy (한국어 형태소 분석) | NLP 파이프라인 제거. 여행 일정은 구조화 데이터. |
| KeyBERT (키워드 추출) | 리뷰 텍스트 분석 제거. 리뷰는 분석에 직접 사용 안 함. |
| scikit-learn (TF-IDF) | NLP 용도 불필요. ※ DBSCAN(sklearn.cluster)은 M4 지리 클러스터링에 선택적 사용 중. |
