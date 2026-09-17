<!-- updated: 2026-09-16 | hash: 677fbbec | summary: 제거된 그래프 적재 단계와 로컬 데이터 로딩 방식 안내 -->
# Step 1: graph-load (removed)

과거 그래프 적재 작업은 폐기했다. `scripts/`의 과거 적재 파일은 운영 경로에서 호출되지 않으며,
새 환경은 `data/jeju_places.csv`를 애플리케이션 시작 시 로컬 인덱스로 읽는다.

검증·설명·대안 추천은 모두 외부 그래프 연결 없이 동작해야 한다.
