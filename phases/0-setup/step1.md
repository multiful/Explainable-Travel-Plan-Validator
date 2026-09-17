<!-- updated: 2026-09-16 | hash: 23d1bca8 | summary: 현재 설정 모델과 외부 클라이언트 구성 규칙을 설명한다 -->

# Step 1. 설정 모델과 외부 클라이언트

## 설정의 단일 진입점

`src/config.py`의 `Settings`가 환경변수를 읽는다. `.env` 경로는 프로젝트 루트를 기준으로 해 실행 위치가 달라도 같은 설정을 사용한다.

주요 설정은 다음과 같다.

- `ANTHROPIC_API_KEY`: 설명 생성과 문서 파싱
- `TOUR_API_KEY`: 한국관광공사 TourAPI
- `KAKAO_REST_API_KEY`: 장소 검색·주소 지오코딩
- `SEOUL_API_KEY`: 서울 실시간 도시데이터
- `ENVIRONMENT`, `API_AUTH_TOKEN`, `CORS_ALLOWED_ORIGINS`: 운영 보호

키는 코드나 테스트 fixture에 하드코딩하지 않는다. 테스트는 각 외부 클라이언트를 mock/stub으로 대체한다.

## 레이어 규칙

외부 I/O는 `src/data/`의 클라이언트에서만 실행한다. API 라우터는 클라이언트를 조합하고, 계산 레이어에는 `src/data/models.py`의 Pydantic 모델만 전달한다.

현재 실행 흐름은 다음과 같다.

```text
api → explain → validation/scoring → data clients
```

검증 요청은 장소를 해석한 뒤 Kakao 이동시간 행렬을 준비하고, 필요한 경우 TourAPI·서울 도시데이터를 조회한다. 외부 조회 실패는 데이터 신뢰도를 낮추되 서버 오류로 위장하지 않는다.

## 테스트와 실행

```bash
python -m pytest tests/ -q
ruff check src tests
uvicorn src.api.main:app --reload
```

Neo4j 기반 설정과 클라이언트는 현재 제품에서 제거되었다. 과거 설계가 필요한 경우 `docs/ADR.md`의 ADR-005를 참고하되, 새 코드나 운영 문서에서 해당 서비스를 요구하지 않는다.
