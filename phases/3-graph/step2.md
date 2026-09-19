<!-- updated: 2026-09-16 | hash: a6213e79 | summary: 그래프 쿼리를 Python 검증 엔진으로 대체한 결정 기록 -->
# Step 2: graph-query (removed)

그래프 쿼리 단계는 제거했다. 이동시간은 `KakaoMobilityMatrix` 또는 명시적인 Haversine
폴백이 담당하고, 운영시간·구역 재방문·클러스터 분산은 `validation/`과 `scoring/`의
결정론적 Python 로직이 담당한다.
