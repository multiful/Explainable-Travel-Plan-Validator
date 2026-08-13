"""PlanExtractor — Claude API 기반 여행 일정표 파싱 엔진.

'대한민국구석구석'(AI콕콕플래너 등)에서 나온 여행 코스 추천 결과물 — PDF·스크린샷(PNG/JPG)·
복사한 텍스트 — 을 입력받아 day/place 구조(ParsedPlanResponse)로 정규화한다.
텍스트는 쿼리 리라이팅으로, 이미지·PDF는 Claude Vision으로 동일한 JSON 스키마를 뽑아낸다.

추출된 장소명은 이후 src.api.router._resolve_poi()가 지식그래프(GraphRetriever)·
jeju_places.csv 등 기존 데이터 레이어를 그대로 통해 좌표·운영시간을 재조회하므로,
이 모듈은 "이름·주소·카테고리 추출"에만 집중한다.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from src.api.schemas import ParsedDay, ParsedPlace, ParsedPlanResponse

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

DEFAULT_MODEL: str = "claude-sonnet-4-6"
DEFAULT_TIMEOUT_SEC: float = 45.0
DEFAULT_MAX_TOKENS: int = 4000

_SYSTEM_PROMPT = """너는 여행 일정표 파싱 엔진이다. 입력(텍스트·이미지·PDF)에서 여행 코스를 읽고
반드시 JSON 객체 하나만 출력하라. 설명, 인사말, 마크다운 코드블록 등 다른 텍스트는 절대 포함하지 마라.

출력 스키마:
{"days": [{"places": [{"name": "장소명", "address": "도로명주소(모르면 빈 문자열)", "category": "12"}]}]}

category 코드 (아래 중 하나만 사용):
  12=관광지/명소/여행지, 14=문화시설(공연장·박물관·미술관), 28=레저스포츠/체험,
  32=숙박(호텔·리조트·펜션), 38=쇼핑(시장·매장), 39=음식점/카페

규칙:
- "Day 1"/"1일차"/"둘째 날" 등으로 날짜가 구분되어 있으면 그 순서를 유지해 days 배열을 나눠라.
- 날짜 구분이 없으면 days 배열 하나에 전체 장소를 등장 순서대로 담아라.
- 장소명에서 번호("1", "①"), 이모지, "여행지"/"카페"/"음식점"/"숙소" 같은 태그 라벨은 제거하고
  실제 상호명만 남겨라 (예: "1 다려도 여행지" → "다려도").
- 주소가 함께 보이면 address에 그대로 담아라. 없으면 빈 문자열로 둬라.
- 장소가 아닌 광고 문구, 총 이동거리, 해시태그, 안내 문구는 무시하라.
- 장소를 하나도 찾지 못하면 {"days": []} 를 반환하라.
"""

_USER_PREFIX_TEXT = "다음은 여행 플래너에서 추천받은 일정을 복사한 텍스트다. 스키마에 맞게 파싱하라:\n\n"
_USER_PREFIX_DOC = "첨부된 여행 일정 캡처(이미지 또는 PDF)를 스키마에 맞게 파싱하라."

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_DAY_MARKER_RE = re.compile(r"(\d+)\s*일\s*차|day\s*\d+", re.IGNORECASE)
_TAG_RE = re.compile(r"^[\s\d①-⑳·\-\.\)]*")
_NOISE_TAGS = ("여행지", "카페", "음식점", "숙소", "관광지")


class PlanExtractionError(Exception):
    """추출 실패 — API 미설정, 호출 실패, 응답 파싱 실패 등."""


def _strip_fence(raw: str) -> str:
    return _FENCE_RE.sub("", raw.strip()).strip()


def _parse_response(raw: str) -> ParsedPlanResponse:
    text = _strip_fence(raw)
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlanExtractionError(f"LLM 응답이 JSON이 아닙니다: {e}") from e
    try:
        return ParsedPlanResponse.model_validate(data)
    except Exception as e:  # pydantic ValidationError
        raise PlanExtractionError(f"응답 스키마가 올바르지 않습니다: {e}") from e


def _fallback_text_parse(text: str) -> ParsedPlanResponse:
    """ANTHROPIC_API_KEY 미설정 시 최소한의 줄 단위 휴리스틱 파싱.
    ponytail: day/카테고리 태그 인식 없는 단순 라인 스플리터. 정확한 파싱은 LLM 키 설정 시 사용."""
    days: list[list[str]] = [[]]
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _DAY_MARKER_RE.search(line) and len(line) < 20:
            if days[-1]:
                days.append([])
            continue
        name = _TAG_RE.sub("", line).strip()
        for tag in _NOISE_TAGS:
            name = name.removesuffix(tag).strip()
        if 1 < len(name) <= 40 and "http" not in name:
            days[-1].append(name)
    days = [d for d in days if d]
    return ParsedPlanResponse(
        days=[ParsedDay(places=[ParsedPlace(name=n) for n in d]) for d in days]
    )


class PlanExtractor:
    """LLM 기반 일정표 추출기. External I/O = Claude API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
    ) -> None:
        self._model = model
        self._timeout = timeout_sec
        self._max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = client
        if self._client is None and _ANTHROPIC_AVAILABLE and self._api_key:
            self._client = anthropic.Anthropic(api_key=self._api_key)

    @classmethod
    def from_env(cls) -> PlanExtractor:
        return cls()

    def is_available(self) -> bool:
        return self._client is not None

    def extract_from_text(self, text: str) -> ParsedPlanResponse:
        """붙여넣은 텍스트를 쿼리 리라이팅으로 정렬된 day/place 구조로 변환."""
        text = (text or "").strip()
        if not text:
            raise PlanExtractionError("빈 텍스트입니다.")
        if not self.is_available():
            return _fallback_text_parse(text)
        return self._call([{"type": "text", "text": _USER_PREFIX_TEXT + text}])

    def extract_from_document(self, data: bytes, media_type: str) -> ParsedPlanResponse:
        """PDF·PNG·JPG 캡처를 Claude Vision으로 읽어 day/place 구조로 변환."""
        if not data:
            raise PlanExtractionError("빈 파일입니다.")
        if not self.is_available():
            raise PlanExtractionError("이미지·PDF 분석에는 ANTHROPIC_API_KEY 설정이 필요합니다.")
        block_type = "document" if media_type == "application/pdf" else "image"
        b64 = base64.b64encode(data).decode("ascii")
        content = [
            {
                "type": block_type,
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            },
            {"type": "text", "text": _USER_PREFIX_DOC},
        ]
        return self._call(content)

    def _call(self, content: list[dict]) -> ParsedPlanResponse:
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                timeout=self._timeout,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
        except Exception as e:
            raise PlanExtractionError(f"Claude API 호출 실패: {e}") from e
        text_blocks = [b.text for b in message.content if hasattr(b, "text")]
        return _parse_response("".join(text_blocks))


def _demo() -> None:
    resp = _parse_response(
        '```json\n{"days":[{"places":[{"name":"성산일출봉","address":"","category":"12"}]}]}\n```'
    )
    assert resp.days[0].places[0].name == "성산일출봉"

    fb = _fallback_text_parse("Day 1\n1 다려도 여행지\n2 바람벽에흰당나귀 카페\n\nDay 2\n월정리해변")
    assert [p.name for d in fb.days for p in d.places] == [
        "다려도", "바람벽에흰당나귀", "월정리해변",
    ]
    assert len(fb.days) == 2
    print("plan_extractor self-check OK")


if __name__ == "__main__":
    _demo()
