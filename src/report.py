"""산출 레이어 v3 — 이벤트 단위 브리프 / docs 퍼블리시 / 메일."""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import shutil
import smtplib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = DOCS / "data"
BRIEFS = DOCS / "briefs"
KST = dt.timezone(dt.timedelta(hours=9))

INK, CYAN, MAGENTA, PAPER = "#1B2A4A", "#0B8FBF", "#C2185B", "#F7F8FA"

CSS = f"""
body{{font-family:Pretendard,'Malgun Gothic',-apple-system,sans-serif;margin:0;
padding:20px;background:{PAPER};color:#16202E;font-size:14px;line-height:1.55}}
.wrap{{max-width:940px;margin:0 auto;background:#fff;padding:28px;
border-top:4px solid {INK}}}
h1{{font-size:20px;margin:0 0 3px;color:{INK};letter-spacing:-.02em}}
.sub{{color:#6B7684;font-size:12px;margin-bottom:20px}}
h2{{font-size:14px;color:{INK};margin:26px 0 8px;padding-bottom:5px;
border-bottom:1px solid #DDE1E8;letter-spacing:-.01em}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th{{background:{INK};color:#fff;padding:7px 6px;text-align:left;font-weight:600}}
td{{padding:8px 6px;border-bottom:1px solid #EDF0F4;vertical-align:top}}
a{{color:{INK}}} .num{{font-variant-numeric:tabular-nums;text-align:right}}
.k{{display:inline-block;padding:1px 6px;border-radius:2px;font-size:11px;font-weight:700}}
.pre{{background:#E3F4FA;color:{CYAN}}} .post{{background:#FCE4EC;color:{MAGENTA}}}
.u{{background:{MAGENTA};color:#fff}}
.kpi{{display:flex;gap:10px;margin-bottom:6px}}
.kpi div{{flex:1;background:#F2F4F7;padding:10px 12px;border-left:3px solid {CYAN}}}
.kpi .n{{font-size:24px;font-weight:700;color:{INK};font-variant-numeric:tabular-nums}}
.kpi .l{{font-size:11px;color:#6B7684}}
.m{{font-size:11px;color:#8A94A6}}
.f{{margin-top:24px;padding-top:10px;border-top:1px solid #DDE1E8;font-size:11px;color:#8A94A6}}
"""


def _row(e: dict) -> str:
    u = '<span class="k u">긴급</span> ' if e["alert"] == "URGENT" else ""
    cls = "pre" if e["cat_type"] == "PRE" else "post"
    more = f" · 동일 사안 {e['n_articles']}건 보도" if e["n_articles"] > 1 else ""
    return (f'<tr><td><b>{e["company"]}</b><br><span class="m">{e["group"]} · {e["grade"]}등급</span></td>'
            f'<td><span class="k {cls}">{e["cat_label"]}</span></td>'
            f'<td>{u}<a href="{e["url"]}" target="_blank">{e["title"][:88]}</a>'
            f'<br><span class="m">{e["keywords"]} · {e["source"]} · '
            f'{e["published"].strftime("%m/%d %H:%M")}{more} · 매칭 {e["match"]}</span></td>'
            f'<td class="num"><b>{e["score"]}</b></td>'
            f'<td class="num">{e.get("expected_order_by") or "-"}</td></tr>')


def _tbl(rows, empty="해당 없음"):
    if not rows:
        return f'<p class="m">{empty}</p>'
    h = ("<tr><th style='width:18%'>거래처</th><th style='width:14%'>이벤트</th><th>사안</th>"
         "<th style='width:7%'>스코어</th><th style='width:11%'>발주 예상</th></tr>")
    return f"<table>{h}{''.join(_row(e) for e in rows)}</table>"


def render(events: list[dict], stats: dict) -> Path:
    now = dt.datetime.now(KST)
    urg = [e for e in events if e["alert"] == "URGENT"]
    pre = [e for e in events if e["cat_type"] == "PRE" and e["alert"] != "URGENT"]
    post = [e for e in events if e["cat_type"] == "POST" and e["alert"] != "URGENT"]
    funnel = " → ".join(f"{k} {v:,}" for k, v in stats.items())

    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>거래처 인텔리전스 브리프 {now:%Y-%m-%d}</title><style>{CSS}</style></head><body>
<div class="wrap">
<h1>거래처 인텔리전스 일일 브리프</h1>
<div class="sub">{now:%Y년 %m월 %d일 %H:%M} KST · (주)아라니아 CFO실</div>
<div class="kpi">
<div><div class="n">{len(urg)}</div><div class="l">긴급</div></div>
<div><div class="n">{len(pre)}</div><div class="l">사전지표 (수주)</div></div>
<div><div class="n">{len(post)}</div><div class="l">사후지표 (리스크)</div></div>
<div><div class="n">{len({e["code"] for e in events})}</div><div class="l">감지 거래처</div></div>
</div>
<h2>1. 긴급 — 당일 조치</h2>{_tbl(urg, "긴급 사안 없음")}
<h2>2. 사전지표 — 수주·생산 계획</h2>{_tbl(pre)}
<h2>3. 사후지표 — 채권·리스크</h2>{_tbl(post)}
<div class="f">수집 퍼널: {funnel}<br>
스코어 = 영향도 × 확실성 × 등급배수 × 보도확산 · 긴급 5.0↑ / 브리프 3.0↑ ·
거래처당 최대 3건 · 동일 사안은 1건으로 병합<br>
'발주 예상'은 이벤트별 통상 리드타임 추정치로 영업 확인 필요</div>
</div></body></html>"""

    for d in (DOCS, DATA, BRIEFS):
        d.mkdir(parents=True, exist_ok=True)
    p = BRIEFS / f"brief_{now:%Y%m%d}.html"
    p.write_text(html, encoding="utf-8")
    return p


def publish(events: list[dict], stats: dict) -> None:
    """docs/ 로 데이터 퍼블리시 — GitHub Pages 대시보드가 읽는다."""
    now = dt.datetime.now(KST)
    DATA.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "config" / "companies.csv", DATA / "companies.csv")

    cols = ["published", "code", "company", "group", "grade", "cat_type", "category",
            "cat_label", "alert", "score", "certainty", "n_articles", "keywords",
            "expected_order_by", "title", "url", "source", "match"]
    p = DATA / "events_master.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        for e in events:
            w.writerow({**e, "published": e["published"].strftime("%Y-%m-%d %H:%M")})

    (DATA / "latest.json").write_text(json.dumps({
        "generated": now.isoformat(), "stats": stats,
        "events": [{**e, "published": e["published"].isoformat()} for e in events],
    }, ensure_ascii=False), encoding="utf-8")

    briefs = sorted((f.name for f in BRIEFS.glob("brief_*.html")), reverse=True)
    (DATA / "briefs.json").write_text(json.dumps(briefs, ensure_ascii=False), encoding="utf-8")


def send_mail(path: Path, n_urgent: int) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    user, pw, to = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"), os.getenv("MAIL_TO", "")
    if not (user and pw and to):
        print("  [mail] 환경변수 미설정 - 발송 생략")
        return
    m = EmailMessage()
    m["Subject"] = (f"{'[긴급 %d건] ' % n_urgent if n_urgent else ''}"
                    f"거래처 인텔리전스 브리프 {dt.datetime.now(KST):%Y-%m-%d}")
    m["From"], m["To"] = user, to
    m.set_content("HTML 지원 메일 클라이언트에서 확인하십시오.")
    m.add_alternative(path.read_text(encoding="utf-8"), subtype="html")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(m)
    print(f"  [mail] 발송 완료 → {to}")
