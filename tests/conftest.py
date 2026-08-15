"""테스트 전역 fixture.

src.api.main은 import 시점에 .env를 읽어 os.environ에 ANTHROPIC_API_KEY를 주입한다.
그 모듈을 import하는 테스트가 먼저 수집되면 이후 테스트의 "키 없음" 케이스가
실행 순서에 따라 랜덤하게 깨진다 — 매 테스트마다 강제로 지워 격리한다.
"""
import pytest


@pytest.fixture(autouse=True)
def _clean_anthropic_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
