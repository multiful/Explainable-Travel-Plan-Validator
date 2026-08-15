"""PlanExtractor 테스트 (실제 Claude API 호출 X — 모두 mock)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.explain.plan_extractor import PlanExtractionError, PlanExtractor


def _client_returning(text: str) -> MagicMock:
    client = MagicMock()
    block = MagicMock()
    block.text = text
    client.messages.create.return_value = MagicMock(content=[block])
    return client


def test_extract_from_text_parses_llm_response() -> None:
    client = _client_returning(
        '{"days":[{"places":[{"name":"다려도","address":"제주 조천읍","category":"12"}]}]}'
    )
    extractor = PlanExtractor(client=client)

    resp = extractor.extract_from_text("1 다려도 여행지")

    assert len(resp.days) == 1
    assert resp.days[0].places[0].name == "다려도"
    client.messages.create.assert_called_once()


def test_extract_from_text_strips_code_fence() -> None:
    client = _client_returning('```json\n{"days":[{"places":[{"name":"월정리해변"}]}]}\n```')
    extractor = PlanExtractor(client=client)

    resp = extractor.extract_from_text("월정리해변 다녀왔어요")

    assert resp.days[0].places[0].name == "월정리해변"


def test_extract_from_text_empty_raises() -> None:
    extractor = PlanExtractor(client=_client_returning("{}"))
    with pytest.raises(PlanExtractionError):
        extractor.extract_from_text("   ")


def test_extract_from_text_without_client_falls_back_to_heuristic() -> None:
    extractor = PlanExtractor(client=None, api_key="")

    resp = extractor.extract_from_text("Day 1\n1 다려도 여행지\n2 바람벽에흰당나귀 카페\n\nDay 2\n월정리해변")

    assert [p.name for d in resp.days for p in d.places] == [
        "다려도", "바람벽에흰당나귀", "월정리해변",
    ]
    assert len(resp.days) == 2


def test_extract_from_document_without_client_raises() -> None:
    extractor = PlanExtractor(client=None, api_key="")
    with pytest.raises(PlanExtractionError):
        extractor.extract_from_document(b"fake-pdf-bytes", "application/pdf")


def test_extract_from_document_empty_bytes_raises() -> None:
    extractor = PlanExtractor(client=_client_returning("{}"))
    with pytest.raises(PlanExtractionError):
        extractor.extract_from_document(b"", "application/pdf")


def test_extract_from_document_sends_document_block_for_pdf() -> None:
    client = _client_returning('{"days":[{"places":[{"name":"소노벨 제주"}]}]}')
    extractor = PlanExtractor(client=client)

    resp = extractor.extract_from_document(b"%PDF-1.4...", "application/pdf")

    assert resp.days[0].places[0].name == "소노벨 제주"
    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "document"


def test_extract_from_document_sends_image_block_for_png() -> None:
    client = _client_returning('{"days":[]}')
    extractor = PlanExtractor(client=client)

    extractor.extract_from_document(b"\x89PNG...", "image/png")

    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"


def test_invalid_json_response_raises() -> None:
    extractor = PlanExtractor(client=_client_returning("이건 JSON이 아닙니다"))
    with pytest.raises(PlanExtractionError):
        extractor.extract_from_text("아무 텍스트")


def test_api_call_failure_raises_extraction_error() -> None:
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("network down")
    extractor = PlanExtractor(client=client)

    with pytest.raises(PlanExtractionError):
        extractor.extract_from_text("아무 텍스트")
