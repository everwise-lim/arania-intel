"""아라니아 거래처 인텔리전스 — 일일 실행 엔트리포인트.

사용:
  python src/main.py                 # 최근 2일
  python src/main.py --days 7        # 주간 롤업
  python src/main.py --no-dart       # 뉴스만
  python src/main.py --mock          # API 키 없이 파이프라인 검증
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pipeline
import report

KST = dt.timezone(dt.timedelta(hours=9))

MOCK = [
    {"source": "mock", "title": "르세라핌, 8월 신보 컴백 확정…콘셉트 포토 공개",
     "body": "쏘스뮤직은 공식 입장을 통해 발매를 확정했다고 밝혔다.",
     "url": "https://example.com/1", "published": dt.datetime.now(KST)},
    {"source": "mock", "title": "어트랙트, 전속계약 분쟁 관련 가처분 소송 제기",
     "body": "어트랙트는 법적 대응에 나섰다고 공식 발표했다.",
     "url": "https://example.com/2", "published": dt.datetime.now(KST)},
    {"source": "mock", "title": "노머스, 플레이브 월드투어 확정…티켓 오픈 예정",
     "body": "노머스는 아시아 투어 일정을 알렸다고 전해졌다.",
     "url": "https://example.com/3", "published": dt.datetime.now(KST)},
    {"source": "mock", "title": "판타지오, 3분기 영업손실 확대…자본잠식 우려",
     "body": "공시에 따르면 적자 전환이 확인됐다.",
     "url": "https://example.com/4", "published": dt.datetime.now(KST)},
]


def run_mock() -> list[dict]:
    companies, rules = pipeline.load_companies(), pipeline.load_rules()
    matched = []
    for item in MOCK:
        c, how = pipeline.match_company(item["title"], item["body"], companies)
        if not c:
            print(f"  [미매칭] {item['title'][:44]}")
            continue
        matched.append((item, c, how))
    return pipeline.apply_caps(pipeline.build_events(matched, rules), rules)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--no-dart", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()

    print(f"[{dt.datetime.now(KST):%Y-%m-%d %H:%M}] 수집 시작 (days={a.days})")
    if a.mock:
        events, stats = run_mock(), {"수집": len(MOCK), "채택": 0}
        stats["채택"] = len(events)
    else:
        events, stats = pipeline.run(days=a.days, use_dart=not a.no_dart)
    print(f"  이벤트 {len(events)}건 (긴급 {sum(e['alert']=='URGENT' for e in events)}건)")

    html = report.render(events, stats)
    report.publish(events, stats)
    print(f"  브리프 → {html}")

    if not a.no_mail:
        report.send_mail(html, sum(e["alert"] == "URGENT" for e in events))


if __name__ == "__main__":
    main()
