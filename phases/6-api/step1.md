<!-- updated: 2026-09-17 | hash: 2d07eca5 | summary: 웹 배포용 API 보호와 readiness 상태 확인 방식을 기록 -->
# Step 1: API runtime

라우터는 외부 I/O를 직접 수행하지 않고 data/scoring 계층의 클라이언트를 호출한다.

- `POST /api/validate`: Kakao 경로 행렬(키가 없으면 Haversine 명시적 폴백), 시작 시각, 실시간 서울 혼잡도, Repair 제안을 한 응답에 반영한다.
- `POST /api/parse/text`, `POST /api/parse/document`: 파싱 실패는 구체적인 4xx로 반환하고 문서 업로드는 15MB로 제한한다.
- `GET /health`: API 키 설정 여부와 필수 데이터 로딩 여부를 반환하며, 필수 데이터가 없으면 HTTP 503을 반환한다. 외부 API 연결성 자체를 보장하는 probe는 아니다.
- `ENVIRONMENT=production`에서는 비용이 큰 엔드포인트에 `Authorization: Bearer` 토큰이 필요하며, 모든 API 요청은 IP별 sliding-window 레이트리밋을 적용한다.
- 별도 `/repair/{plan_id}` 조회 API는 제공하지 않는다. Repair 제안은 검증 응답의 `repair_suggestions` 필드에 포함한다.
