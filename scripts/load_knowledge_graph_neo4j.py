#!/usr/bin/env python3
"""data/graph/*.csv → Neo4j Aura 적재.

scripts/build_knowledge_graph.py가 만든 neo4j-admin-import 포맷 CSV를 읽어
Bolt 드라이버로 배치 UNWIND+MERGE 적재한다 (Aura는 관리형이라 neo4j-admin CLI
오프라인 임포트를 못 쓰기 때문). 멱등적 — 재실행해도 중복 생성되지 않는다.

용량이 큰 NEAR_BY(약 42만건)는 맨 마지막에 적재한다. Aura Free는 노드/관계
쿼터가 있어 중간에 실패할 수 있는데, 그 앞의 핵심 그래프(Place/Region/Category
+ IS_LOCATED_IN/PART_OF/HAS_CATEGORY)는 이미 다 적재된 상태로 남는다.

Usage:
    python scripts/load_knowledge_graph_neo4j.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

ROOT = Path(__file__).parent.parent
GRAPH_DIR = ROOT / "data" / "graph"
BATCH_SIZE = 2000

CONSTRAINTS = [
    "CREATE CONSTRAINT place_id IF NOT EXISTS FOR (p:Place) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT region_id IF NOT EXISTS FOR (r:Region) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT category_code IF NOT EXISTS FOR (c:Category) REQUIRE c.code IS UNIQUE",
]


def _strip_type_suffix(col: str) -> str:
    # neo4j-admin import 헤더: "id:ID"/"lat:float" → 콜론 앞이 실제 이름,
    # ":START_ID"/":END_ID"/":TYPE" → 콜론 뒤가 실제 이름 (앞은 빈 문자열)
    if col.startswith(":"):
        return col[1:]
    return col.split(":")[0]


def _load_rows(filename: str) -> list[dict]:
    df = pd.read_csv(GRAPH_DIR / filename)
    df = df.rename(columns=_strip_type_suffix)
    df = df.where(pd.notna(df), None)
    return df.to_dict("records")


def _run_batched(driver: Driver, database: str, label: str, query: str, rows: list[dict]) -> None:
    total = len(rows)
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        driver.execute_query(query, rows=batch, database_=database)
        done = min(start + BATCH_SIZE, total)
        print(f"  {label}: {done:,}/{total:,}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    print(f"연결 성공: {uri} (database={database})")

    print("[1/8] 제약조건 생성")
    for stmt in CONSTRAINTS:
        driver.execute_query(stmt, database_=database)

    print("[2/8] Region 노드")
    _run_batched(
        driver, database, "Region",
        "UNWIND $rows AS row MERGE (r:Region {id: row.id}) SET r.name = row.name",
        _load_rows("region_nodes.csv"),
    )

    print("[3/8] Category 노드")
    _run_batched(
        driver, database, "Category",
        "UNWIND $rows AS row MERGE (c:Category {code: row.code}) "
        "SET c.name = row.name, c.group = row.group",
        _load_rows("category_nodes.csv"),
    )

    print("[4/8] Place 노드")
    _run_batched(
        driver, database, "Place",
        """
        UNWIND $rows AS row
        MERGE (p:Place {id: row.id})
        SET p.name = row.name, p.place_type = row.place_type,
            p.category_major_code = row.category_major_code,
            p.category_major_name = row.category_major_name,
            p.category_medium_code = row.category_medium_code,
            p.category_medium_name = row.category_medium_name,
            p.address = row.address, p.lat = row.lat, p.lng = row.lng,
            p.business_hours = row.business_hours, p.off_days = row.off_days
        """,
        _load_rows("place_nodes.csv"),
    )

    print("[5/8] IS_LOCATED_IN")
    _run_batched(
        driver, database, "IS_LOCATED_IN",
        """
        UNWIND $rows AS row
        MATCH (p:Place {id: row.START_ID}), (r:Region {id: row.END_ID})
        MERGE (p)-[:IS_LOCATED_IN]->(r)
        """,
        _load_rows("rel_is_located_in.csv"),
    )

    print("[6/8] PART_OF")
    _run_batched(
        driver, database, "PART_OF",
        """
        UNWIND $rows AS row
        MATCH (c:Region {id: row.START_ID}), (parent:Region {id: row.END_ID})
        MERGE (c)-[:PART_OF]->(parent)
        """,
        _load_rows("rel_part_of.csv"),
    )

    print("[7/8] HAS_CATEGORY")
    _run_batched(
        driver, database, "HAS_CATEGORY",
        """
        UNWIND $rows AS row
        MATCH (p:Place {id: row.START_ID}), (c:Category {code: row.END_ID})
        MERGE (p)-[:HAS_CATEGORY]->(c)
        """,
        _load_rows("rel_has_category.csv"),
    )

    print("[8/8] NEAR_BY (용량 큼 — Free 티어 쿼터로 중간에 멈출 수 있음)")
    near_by_rows = _load_rows("rel_near_by.csv")
    loaded = 0
    try:
        for start in range(0, len(near_by_rows), BATCH_SIZE):
            batch = near_by_rows[start : start + BATCH_SIZE]
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (a:Place {id: row.START_ID}), (b:Place {id: row.END_ID})
                MERGE (a)-[rel:NEAR_BY]->(b)
                SET rel.distance_m = row.distance_m, rel.walk_min = row.walk_min
                """,
                rows=batch,
                database_=database,
            )
            loaded = min(start + BATCH_SIZE, len(near_by_rows))
            print(f"  NEAR_BY: {loaded:,}/{len(near_by_rows):,}")
    except Neo4jError as exc:
        print(f"\nNEAR_BY 적재 {loaded:,}/{len(near_by_rows):,}건에서 중단됨: {exc}")
        print("(Place/Region/Category + IS_LOCATED_IN/PART_OF/HAS_CATEGORY는 이미 적재 완료)")
        driver.close()
        sys.exit(1)

    driver.close()
    print("\n=== 적재 완료 ===")


if __name__ == "__main__":
    main()
