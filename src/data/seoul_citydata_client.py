"""서울 도시데이터 API 클라이언트 — 실시간 인구 혼잡도.

API: 서울 열린데이터광장 citydata (도시데이터 API)
엔드포인트: http://openapi.seoul.go.kr:8088/{KEY}/json/citydata/1/1/{AREA_NM}

커버리지: 서울시 주요 115개 장소 (POI/상권/관광지)
갱신주기: 10~15분

지원 혼잡도 레벨:
    여유 → 0.1  |  보통 → 0.4  |  약간 붐빔 → 0.7  |  붐빔 → 1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import httpx

BASE_URL = "http://openapi.seoul.go.kr:8088"

# 서울 도시데이터 API 등록 장소명 (115개소 중 주요 관광지)
# 정확한 문자열 일치가 필요 — 오타 시 404 반환
KNOWN_AREAS: set[str] = {
    "경복궁",
    "창덕궁",
    "창경궁",
    "덕수궁",
    "경희궁",
    "인사동",
    "북촌한옥마을",
    "서촌",
    "남산공원",
    "명동 관광특구",
    "동대문 관광특구",
    "이태원 관광특구",
    "강남 MICE 관광특구",
    "홍대 관광특구",
    "여의도한강공원",
    "반포한강공원",
    "뚝섬한강공원",
    "잠실한강공원",
    "망원한강공원",
    "이촌한강공원",
    "롯데월드",
    "코엑스",
    "국립중앙박물관",
    "서울숲",
    "올림픽공원",
    "북한산",
    "관악산",
    "강남역",
    "신촌·이대",
    "건대입구역",
    "왕십리역",
}

# 사용자 입력 → API 장소명 별칭 매핑
AREA_ALIASES: dict[str, str] = {
    "명동": "명동 관광특구",
    "홍대": "홍대 관광특구",
    "홍대입구": "홍대 관광특구",
    "이태원": "이태원 관광특구",
    "동대문": "동대문 관광특구",
    "동대문디자인플라자": "동대문 관광특구",
    "ddp": "동대문 관광특구",
    "강남": "강남 MICE 관광특구",
    "코엑스": "코엑스",
    "한강공원": "여의도한강공원",
    "여의도": "여의도한강공원",
    "반포": "반포한강공원",
    "뚝섬": "뚝섬한강공원",
}

CONGEST_SCORE_MAP: dict[str, float] = {
    "여유": 0.1,
    "보통": 0.4,
    "약간 붐빔": 0.7,
    "붐빔": 1.0,
}


@dataclass(frozen=True)
class ForecastSlot:
    time: str  # "YYYY-MM-DD HH:MM"
    level: str  # "여유" | "보통" | "약간 붐빔" | "붐빔"
    score: float  # 0.0~1.0
    ppltn_min: int
    ppltn_max: int


@dataclass(frozen=True)
class SeoulRealtimeCongestion:
    area_name: str
    area_code: str
    level: str  # 현재 혼잡도 텍스트
    score: float  # 0.0~1.0
    ppltn_min: int
    ppltn_max: int
    measured_at: str  # "YYYY-MM-DD HH:MM"
    forecast: list[ForecastSlot] = field(default_factory=list)
    is_replaced: bool = False  # REPLACE_YN == 'Y' 이면 추정치


class SeoulCityDataClient:
    """서울 도시데이터 실시간 혼잡도 클라이언트 (동기).

    Args:
        api_key: SEOUL_DATA_API_KEY (기본값: 환경변수에서 로드)
        timeout: HTTP 타임아웃 (초)
    """

    def __init__(self, api_key: str | None = None, timeout: float = 10.0) -> None:
        if api_key:
            self._key = api_key
        else:
            from src.data.models import Settings

            self._key = Settings().seoul_data_api_key
        if not self._key:
            raise ValueError("SEOUL_DATA_API_KEY가 설정되지 않았습니다.")
        self._timeout = timeout

    def _url(self, area_name: str) -> str:
        return f"{BASE_URL}/{self._key}/json/citydata/1/1/{area_name}"

    def _parse_forecast(self, raw: list[dict]) -> list[ForecastSlot]:
        slots: list[ForecastSlot] = []
        for item in raw:
            lvl = item.get("FCST_CONGEST_LVL", "")
            slots.append(
                ForecastSlot(
                    time=item.get("FCST_TIME", ""),
                    level=lvl,
                    score=CONGEST_SCORE_MAP.get(lvl, 0.5),
                    ppltn_min=int(item.get("FCST_PPLTN_MIN", 0)),
                    ppltn_max=int(item.get("FCST_PPLTN_MAX", 0)),
                )
            )
        return slots

    def _resolve_name(self, area_name: str) -> str:
        """별칭 및 대소문자 정규화 처리."""
        key = area_name.strip().lower()
        for alias, canonical in AREA_ALIASES.items():
            if alias.lower() == key:
                return canonical
        return area_name.strip()

    def get(self, area_name: str) -> SeoulRealtimeCongestion | None:
        """장소명으로 실시간 혼잡도를 조회한다.

        Args:
            area_name: 장소명 (별칭 자동 해석 — AREA_ALIASES 참조)
                       예: '경복궁', '인사동', '명동', '홍대', '여의도'

        Returns:
            SeoulRealtimeCongestion, 또는 API 커버리지 밖/오류 시 None
        """
        area_name = self._resolve_name(area_name)
        try:
            resp = httpx.get(self._url(area_name), timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            return None

        result_code = data.get("RESULT", {}).get("RESULT.CODE", "")
        if result_code not in ("INFO-000", ""):
            return None

        citydata = data.get("CITYDATA", {})
        live_list = citydata.get("LIVE_PPLTN_STTS", [])
        if not live_list:
            return None

        live = live_list[0]
        lvl = live.get("AREA_CONGEST_LVL", "보통")
        return SeoulRealtimeCongestion(
            area_name=live.get("AREA_NM", area_name),
            area_code=live.get("AREA_CD", ""),
            level=lvl,
            score=CONGEST_SCORE_MAP.get(lvl, 0.5),
            ppltn_min=int(live.get("AREA_PPLTN_MIN", 0)),
            ppltn_max=int(live.get("AREA_PPLTN_MAX", 0)),
            measured_at=live.get("PPLTN_TIME", ""),
            forecast=self._parse_forecast(live.get("FCST_PPLTN", [])),
            is_replaced=live.get("REPLACE_YN", "N") == "Y",
        )

    def get_at(self, area_name: str, target_time: str) -> ForecastSlot | None:
        """특정 시각(HH:MM)의 예측 혼잡도를 반환한다.

        target_time이 현재라면 실시간, 미래라면 예측값을 사용한다.
        Args:
            area_name: 장소명
            target_time: "HH:MM" 형식 (예: "15:00")
        Returns:
            ForecastSlot, 없으면 None
        """
        data = self.get(area_name)
        if data is None:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        target_dt = f"{today} {target_time}"

        # 현재 시간과 가장 가까운 예측 슬롯 반환
        for slot in data.forecast:
            if slot.time >= target_dt:
                return slot

        # 현재 상태를 슬롯으로 래핑해 반환
        return ForecastSlot(
            time=data.measured_at,
            level=data.level,
            score=data.score,
            ppltn_min=data.ppltn_min,
            ppltn_max=data.ppltn_max,
        )
