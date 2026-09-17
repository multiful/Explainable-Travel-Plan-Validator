<!-- updated: 2026-09-16 | hash: f101e72a | summary: 제거된 그래프 DB 단계와 현재 로컬 근거 리트리버 안내 -->
# Step 0: graph-db (removed)

이 단계는 과거 Neo4j 스키마를 정의하던 기록이다. 외부 그래프 DB는 현재 제품 런타임과 의존성에서 제거되었다.

현재 장소 근거 검색은 `src/data/evidence_retriever.py`의 `LocalEvidenceRetriever`가
프로젝트 데이터 CSV를 로컬에서 읽어 처리한다. 외부 네트워크 없이 테스트할 수 있으며,
지역·근접 대안 정보도 동일한 Pydantic 모델로 반환한다.
