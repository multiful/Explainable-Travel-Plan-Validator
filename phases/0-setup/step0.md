<!-- updated: 2026-09-12 | hash: 95af287a | summary: pyproject.toml, .env.example, src/__init__.py 환경 설정 -->
# Step 0: python-env

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 기획·아키텍처·설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`

## 작업

프로젝트 루트에 Python 환경 설정 파일들을 생성하라. 소스 코드는 이 step에서 작성하지 않는다.

### 1. `pyproject.toml` 생성

```toml
[build-system]
requires = ["setuptools>=72"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "travel-plan-validator"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "neo4j>=5.24.0",
    "httpx>=0.27.0",
    "anthropic>=0.40.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.8.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["src*"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests", "scripts"]
```

### 2. `.env.example` 생성

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
CLAUDE_MODEL=claude-sonnet-4-6
TOUR_API_KEY=your_tour_api_key_here
KAKAO_REST_API_KEY=your_kakao_rest_api_key_here
KAKAO_MOBILITY_KEY=
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password_here
```

### 3. `src/__init__.py` 생성 (빈 파일)

### 4. `tests/__init__.py` 생성 (빈 파일)

## Acceptance Criteria

```bash
pip install -e ".[dev]"
python -c "import fastapi; import neo4j; import httpx; import anthropic; import pydantic; print('All dependencies OK')"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `pyproject.toml`이 CLAUDE.md 기술 스택과 일치하는지 확인한다 (ChromaDB, sentence-transformers, kiwipiepy, KeyBERT 없음).
3. 결과에 따라 `phases/0-setup/index.json`의 step 0 status를 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "pyproject.toml, .env.example, src/__init__.py, tests/__init__.py 생성 완료"`
   - 설치 실패 → `"status": "blocked"`, `"blocked_reason": "구체적 에러 메시지"`

## 금지사항

- `src/` 하위에 실제 로직 코드를 작성하지 마라. 이 step은 환경 설정 파일만 만든다.
- API 키 실제값을 어떤 파일에도 하드코딩하지 마라.
- `requirements.txt`를 별도로 만들지 마라. `pyproject.toml`만 사용한다.
- ChromaDB, sentence-transformers, kiwipiepy, KeyBERT는 의존성에 추가하지 마라.
