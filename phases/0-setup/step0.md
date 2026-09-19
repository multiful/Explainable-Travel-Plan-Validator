<!-- updated: 2026-09-16 | hash: 19d1b2b3 | summary: 현재 프로젝트의 설치와 환경변수 설정 기준을 정리한다 -->

# Step 0. 설치와 환경 설정

## 목적

Python 3.11 이상에서 API와 검증 파이프라인을 실행할 수 있는 개발 환경을 만든다.

## 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Windows에서는 `.venv\\Scripts\\activate`를 사용한다.

## 환경변수

```bash
cp .env.example .env
```

`.env`에는 실제 키를 넣고 저장소에는 커밋하지 않는다. 외부 연동 키는 TourAPI, Kakao, 서울 도시데이터, Anthropic만 사용한다. 키가 없는 개발 환경에서는 각 클라이언트가 안전한 폴백을 사용하며, 검증 결과에는 데이터 신뢰도가 표시된다.

## 확인

```bash
python -m pytest tests/ -q
ruff check src tests
uvicorn src.api.main:app --reload
```

운영 환경에서는 `ENVIRONMENT=production`과 `API_AUTH_TOKEN`을 설정한다.
