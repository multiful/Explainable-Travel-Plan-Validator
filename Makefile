.PHONY: help install dev run test lint fmt docker-up docker-down clean

PY ?= python3.12
VENV = .venv
BIN = $(VENV)/bin

help:           ## 명령어 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:        ## venv 생성 + 런타임 의존성 설치
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt

dev:            ## 개발용 의존성(pytest, ruff)까지 설치
	$(BIN)/pip install -e ".[dev]"

run:            ## 개발 서버 실행 (http://localhost:8000)
	$(BIN)/uvicorn src.api.main:app --reload

test:           ## 전체 테스트
	$(BIN)/python -m pytest tests/ -q

lint:           ## ruff 린트
	$(BIN)/ruff check src/ tests/

fmt:            ## ruff 포맷
	$(BIN)/ruff format src/ tests/

docker-up:      ## 컨테이너 빌드 + 실행
	docker compose up --build

docker-down:    ## 컨테이너 중지
	docker compose down

clean:          ## 캐시 정리
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
