"""혼잡도 판정 엔진 — 결정론적 규칙 기반 (LLM 의존 없음).

데이터 소스 우선순위:
    0. 서울 도시데이터 API (실시간) — SeoulCityDataClient 주입 시 서울 소재 POI 우선 적용
    1. POI 정확 이름 매칭 (data/congestion_stats.csv)
    2. POI 명칭 부분 문자열 매칭 (longest match)
    3. 카테고리 평균 (poi_name에 지역/유형 접두어 기반 클러스터링)
    4. 전체 평균
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from pathlib import Path

import pandas as pd

from src.data.models import Settings
from src.data.seoul_citydata_client import SeoulCityDataClient

_DEFAULT_CSV = Path(__file__).parent.parent.parent / "data" / "congestion_stats.csv"


class CongestionLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


@dataclass(frozen=True)
class CongestionResult:
    poi_name: str
    month: int
    congestion_score: float  # 0.0 ~ 1.0
    level: CongestionLevel
    avg_visitors: float
    matched_poi: str  # 실제 매칭된 POI명
    fallback_used: str  # "exact" | "partial" | "category" | "global"


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip()


def _score_to_level(score: float) -> CongestionLevel:
    if score < 0.4:
        return CongestionLevel.LOW
    if score < 0.65:
        return CongestionLevel.MEDIUM
    if score < 0.85:
        return CongestionLevel.HIGH
    return CongestionLevel.VERY_HIGH


class CongestionEngine:
    """POI × month → congestion_score 판정기.

    Args:
        csv_path: congestion_stats.csv 경로 (기본값: data/congestion_stats.csv)
        category_prefix_len: 카테고리 클러스터링에 사용할 POI명 앞 글자 수
        seoul_client: SeoulCityDataClient 인스턴스 (주입 시 서울 POI 실시간 우선 적용)
    """

    def __init__(
        self,
        csv_path: Path = _DEFAULT_CSV,
        category_prefix_len: int = 2,
        seoul_client: SeoulCityDataClient | None = None,
    ) -> None:
        self._csv_path = csv_path
        self._prefix_len = category_prefix_len
        self._seoul: SeoulCityDataClient | None = seoul_client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> CongestionEngine:
        settings = settings or Settings()
        seoul_client = (
            SeoulCityDataClient(api_key=settings.seoul_data_api_key)
            if settings.seoul_data_api_key.strip()
            else None
        )
        return cls(seoul_client=seoul_client)

    @cached_property
    def _df(self) -> pd.DataFrame:
        if not self._csv_path.exists():
            raise FileNotFoundError(
                f"혼잡도 데이터 없음: {self._csv_path}\n"
                "먼저 `python scripts/extract_visitor_stats.py` 를 실행하세요."
            )
        df = pd.read_csv(self._csv_path, encoding="utf-8-sig")
        df["poi_name"] = df["poi_name"].apply(_normalize)
        return df

    @cached_property
    def _poi_names(self) -> list[str]:
        return self._df["poi_name"].unique().tolist()

    @cached_property
    def _global_avg_by_month(self) -> dict[int, tuple[float, float]]:
        """month → (avg_visitors, congestion_score) 전체 평균."""
        agg = self._df.groupby("month")[["avg_visitors", "congestion_score"]].mean()
        return {int(m): (row["avg_visitors"], row["congestion_score"]) for m, row in agg.iterrows()}

    @cached_property
    def _category_avg_by_month(self) -> dict[str, dict[int, tuple[float, float]]]:
        """prefix → month → (avg_visitors, congestion_score)."""
        df = self._df.copy()
        df["prefix"] = df["poi_name"].str[: self._prefix_len]
        result: dict[str, dict[int, tuple[float, float]]] = {}
        for prefix, group in df.groupby("prefix"):
            agg = group.groupby("month")[["avg_visitors", "congestion_score"]].mean()
            result[prefix] = {
                int(m): (row["avg_visitors"], row["congestion_score"]) for m, row in agg.iterrows()
            }
        return result

    def _lookup_exact(self, poi_name: str, month: int) -> pd.Series | None:
        rows = self._df[(self._df["poi_name"] == poi_name) & (self._df["month"] == month)]
        if rows.empty:
            return None
        return rows.iloc[0]

    def _lookup_partial(self, poi_name: str, month: int) -> tuple[pd.Series, str] | None:
        """가장 긴 부분 문자열 매칭."""
        candidates = [n for n in self._poi_names if poi_name in n or n in poi_name]
        if not candidates:
            return None
        best = max(candidates, key=len)
        rows = self._df[(self._df["poi_name"] == best) & (self._df["month"] == month)]
        if rows.empty:
            return None
        return rows.iloc[0], best

    def score(self, poi_name: str, month: int) -> CongestionResult:
        """POI와 방문 월로 혼잡도를 판정한다.

        서울 POI에 SeoulCityDataClient가 주입된 경우 실시간 데이터를 우선 사용한다.

        Args:
            poi_name: 관광지명
            month: 1~12 (방문 월)

        Returns:
            CongestionResult
        """
        if not 1 <= month <= 12:
            raise ValueError(f"month must be 1-12, got {month}")

        norm_name = _normalize(poi_name)

        # 0. 서울 도시데이터 API (실시간) — 주입된 경우만
        if self._seoul is not None:
            try:
                realtime = self._seoul.get(poi_name)
                if realtime is not None:
                    return CongestionResult(
                        poi_name=poi_name,
                        month=month,
                        congestion_score=realtime.score,
                        level=_score_to_level(realtime.score),
                        avg_visitors=float((realtime.ppltn_min + realtime.ppltn_max) // 2),
                        matched_poi=realtime.area_name,
                        fallback_used="seoul_realtime",
                    )
            except Exception:
                pass  # API 실패 시 CSV 폴백으로 진행

        # 1. Exact match
        row = self._lookup_exact(norm_name, month)
        if row is not None:
            return CongestionResult(
                poi_name=poi_name,
                month=month,
                congestion_score=float(row["congestion_score"]),
                level=_score_to_level(float(row["congestion_score"])),
                avg_visitors=float(row["avg_visitors"]),
                matched_poi=row["poi_name"],
                fallback_used="exact",
            )

        # 2. Partial match
        partial = self._lookup_partial(norm_name, month)
        if partial is not None:
            row, matched = partial
            return CongestionResult(
                poi_name=poi_name,
                month=month,
                congestion_score=float(row["congestion_score"]),
                level=_score_to_level(float(row["congestion_score"])),
                avg_visitors=float(row["avg_visitors"]),
                matched_poi=matched,
                fallback_used="partial",
            )

        # 3. Category average (prefix-based)
        prefix = norm_name[: self._prefix_len]
        cat_data = self._category_avg_by_month.get(prefix, {})
        if month in cat_data:
            avg_v, score = cat_data[month]
            return CongestionResult(
                poi_name=poi_name,
                month=month,
                congestion_score=round(score, 4),
                level=_score_to_level(score),
                avg_visitors=round(avg_v, 1),
                matched_poi=f"[카테고리:{prefix}*]",
                fallback_used="category",
            )

        # 4. Global average
        avg_v, score = self._global_avg_by_month.get(month, (0.0, 0.5))
        return CongestionResult(
            poi_name=poi_name,
            month=month,
            congestion_score=round(score, 4),
            level=_score_to_level(score),
            avg_visitors=round(avg_v, 1),
            matched_poi="[전체평균]",
            fallback_used="global",
        )

    def is_crowded(self, poi_name: str, month: int, threshold: float = 0.7) -> bool:
        """congestion_score >= threshold 이면 True."""
        return self.score(poi_name, month).congestion_score >= threshold

    def score_itinerary(self, pois: list[str], month: int) -> list[CongestionResult]:
        """여행 일정의 모든 POI 혼잡도를 일괄 반환한다."""
        return [self.score(poi, month) for poi in pois]
