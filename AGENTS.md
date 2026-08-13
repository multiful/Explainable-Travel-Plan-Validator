<!-- updated: 2026-04-30 | hash: 22ccaf16 | summary: Neo4j 제거, Seoul API 추가, 기술 스택·아키텍처 규칙·선결 조건 업데이트 -->
# 프로젝트: Explainable Travel Plan Validator

## 기술 스택
- Python 3.11+
- FastAPI 0.115+ (HTTP API 서버)
- httpx 0.27+ (async HTTP — TourAPI + Kakao API + 서울 도시데이터 API 클라이언트)
- Anthropic Codex API / Codex-sonnet-4-6 (Evidence-based 설명 + Repair 제안)
- pydantic 2.9+ + pydantic-settings 2.6+ (데이터 모델 + 환경변수 관리)
- pytest 8.3+ (테스트), ruff 0.8+ (린터/포매터)

## 프로젝트 구조
```
src/
├── data/           # Pydantic 모델, TourAPI 클라이언트, Kakao API 클라이언트, 서울 도시데이터 API
├── matrix/         # Pairwise 이동시간·거리 행렬 (Kakao Mobility)
├── scoring/        # travel_ratio, cluster_dispersion (M3 백트래킹 포함), theme_alignment, congestion_engine
├── validation/     # Hard Fail 탐지, Warning 탐지, 점수 계산 (VRPTW)
├── explain/        # 설명 엔진(LLM), Repair 제안, 파이프라인 오케스트레이터
└── api/            # FastAPI 앱, 라우터, Request/Response 스키마
tests/              # pytest 단위 테스트
```

## 아키텍처 규칙
- CRITICAL: 모든 외부 I/O(TourAPI, Kakao API, 서울 도시데이터 API, Codex API)는 각 레이어 모듈에서만 처리한다. `api/` 레이어가 직접 외부 API를 호출하지 않는다.
- CRITICAL: Codex API 키, TourAPI 키, Kakao API 키, Seoul API 키는 반드시 환경변수(`.env`)로 관리한다. 코드에 하드코딩 절대 금지.
- CRITICAL: 모듈 간 데이터는 `src/data/models.py`의 Pydantic 모델로만 주고받는다. 원시 `dict` 전달 금지.
- 의존 방향: `api → explain → validation/scoring → data` (역방향 의존 금지)
- 각 외부 의존성(TourAPI, Kakao API, Codex API, Seoul API)은 테스트에서 mock/stub으로 대체해야 한다.

## 개발 프로세스
- CRITICAL: 새 기능 구현 시 반드시 테스트를 먼저 작성하고, 테스트가 통과하는 구현을 작성할 것 (TDD)
- 커밋 메시지는 conventional commits 형식을 따를 것 (feat:, fix:, docs:, refactor:)
- 환경변수는 `.env.example`에 키 이름만 문서화하고 `.env`는 git에서 제외

## 명령어
```bash
python -m pytest tests/ -q           # 전체 테스트
python -m pytest tests/test_X.py -v  # 특정 테스트
python -m pytest scripts/ -q         # 하네스 테스트
ruff check src/ tests/               # 린트
ruff format src/ tests/              # 포맷
uvicorn src.api.main:app --reload    # 개발 서버 (port 8000)
python scripts/execute.py {phase}   # 하네스 실행
```

## 문서 관리 규칙

**모든 `.md` 파일 최상단 첫 번째 줄**에 아래 메타 헤더를 유지하라:

```
<!-- updated: YYYY-MM-DD | hash: {8hex} | summary: {한 줄 요약} -->
```

- `updated`: 파일을 마지막으로 수정한 날짜 (KST)
- `hash`: 헤더 행(첫 줄)을 **제외한** 나머지 본문 전체의 MD5 앞 8자
- `summary`: 문서 핵심 내용을 한 문장으로 요약

**해시 계산 커맨드** (파일에 헤더가 이미 있을 때):
```bash
python -c "
import hashlib, sys
lines = open(sys.argv[1], encoding='utf-8').readlines()
body = ''.join(lines[1:])
print(hashlib.md5(body.encode()).hexdigest()[:8])
" <파일경로>
```

**적용 범위**: 프로젝트 내 모든 `.md` 파일 (`phases/` 하위 step 파일 포함)  
**갱신 타이밍**: 파일 내용을 수정할 때마다 updated 날짜와 hash를 함께 업데이트한다  
**단,** 헤더 자체만 수정(updated 날짜/hash 업데이트)할 때는 hash를 재계산하지 않는다

---

## ⚠ harness 실행 전 필수 선결 조건
```bash
# 1. git 초기화 (최초 1회)
git init && git add -A && git commit -m "chore: initial project structure"

# 2. .env 생성
cp .env.example .env  # 그 후 실제 키 입력
```
