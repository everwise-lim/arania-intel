"""아티스트 로스터 초안 자동 수집 — Wikidata SPARQL.

나무위키/멜론 등은 이용약관상 크롤링 불가. Wikidata는 CC0로 상업적 재사용 허용.
커버리지는 완전하지 않으므로 '초안 생성 → 영업팀 검증' 용도로만 사용한다.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = "https://query.wikidata.org/sparql"
UA = {"User-Agent": "Arania-Intel/1.0 (CFO Office; contact: cfo@arania.co.kr)",
      "Accept": "application/sparql-results+json"}

# P264 = record label, P1830 = owner of, P749 = parent organization
QUERY = """
SELECT DISTINCT ?artistLabel ?labelLabel WHERE {
  ?label rdfs:label "%s"@ko .
  ?artist wdt:P264 ?label .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ko,en". }
}
LIMIT 200
"""


def fetch(company_name: str) -> list[str]:
    try:
        r = requests.get(ENDPOINT, params={"query": QUERY % company_name},
                         headers=UA, timeout=30)
        r.raise_for_status()
        rows = r.json()["results"]["bindings"]
        return sorted({x["artistLabel"]["value"] for x in rows})
    except Exception as e:                                    # noqa: BLE001
        print(f"  [wikidata] {company_name}: {e}")
        return []


def main() -> None:
    src = ROOT / "config" / "companies.csv"
    with open(src, encoding="utf-8-sig") as f:
        companies = list(csv.DictReader(f))

    out = ROOT / "out" / "roster_draft.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["code", "정식명", "검색명", "수집_아티스트", "수동입력_아티스트",
                    "검증자", "검증일", "출처"])
        for c in companies:
            names = set()
            for alias in [c["검색명"]] + [a for a in (c["별칭"] or "").split("|") if a]:
                names.update(fetch(alias))
                time.sleep(1.2)          # Wikidata 예절: 초당 1회 이하
            w.writerow([c["code"], c["정식명"], c["검색명"], "|".join(sorted(names)),
                        c.get("대표아티스트_초안", ""), "", "", "Wikidata SPARQL"])
            print(f"  {c['code']} {c['검색명']}: {len(names)}명")
    print(f"\n로스터 초안 → {out}")


if __name__ == "__main__":
    main()
