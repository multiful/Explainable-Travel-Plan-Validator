<!-- updated: 2026-09-12 | hash: 8fe359a5 | summary: 현재 API 입력·응답 스키마와 검증 경계 기록 -->
# Step 0: API schemas

현재 API는 Pydantic v2로 입력을 검증한다.

- `POST /api/validate`: 1~30일, 하루 1~8장소, ISO 날짜, `HH:MM` 시작 시각
- 빈 일정·공백 장소명·잘못된 날짜/시각은 FastAPI 422로 반환한다.
- 검증 응답은 점수, Hard Fail/Warning, 설명, `repair_suggestions`를 함께 포함한다.

