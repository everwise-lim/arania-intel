"""처리 레이어 v3 — 엄격 매칭 / 문맥 게이트 / 이벤트 군집화 / 분량 상한."""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))
HANGUL = re.compile(r"[가-힣]")
JOSA = "은는이가의에와과도로를을만께서부터까지처럼보다"


def load_companies() -> list[dict]:
    with open(ROOT / "config" / "companies.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        aliases = [r["검색명"]] + [a for a in (r.get("별칭") or "").split("|") if a]
        aliases = [a.strip() for a in aliases if len(a.strip()) >= 3]
        # 아티스트는 로스터 검증이 끝난 것만 매칭 근거로 사용
        artists = []
        if r.get("로스터확신도") == "높음":
            artists = [a.strip() for a in (r.get("대표아티스트_초안") or "").split("|")
                       if len(a.strip()) >= 3]
        r["_aliases"] = list(dict.fromkeys(aliases))
        r["_artists"] = artists
        r["_needles"] = [(n, "회사") for n in r["_aliases"]] + [(n, "아티스트") for n in artists]
    return rows


def load_rules() -> dict:
    with open(ROOT / "config" / "keywords.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ─────────────────────── 엄격 매칭 ───────────────────────
def has_token(text: str, needle: str) -> bool:
    """앞 글자가 한글이면 다른 단어의 일부 → 기각.
    예) '제이와이피엔터테인먼트' 안의 '이엔터테인먼트' 오탐 차단."""
    start = 0
    while True:
        i = text.find(needle, start)
        if i < 0:
            return False
        prev_ok = i == 0 or not HANGUL.match(text[i - 1])
        j = i + len(needle)
        nxt = text[j] if j < len(text) else ""
        next_ok = (not HANGUL.match(nxt)) or nxt in JOSA
        if prev_ok and next_ok:
            return True
        start = i + 1


# 플랫폼·유통 채널명은 기사 '출처'로 등장하므로 매칭 근거에서 제외한다.
# 예) "[NOTICE] 로켓펀치 수윤 계약 종료 안내 - Weverse" 는 위버스컴퍼니 사안이 아니다.
BLOCK_ALIAS = {"weverse", "위버스", "melon", "멜론", "genie", "지니뮤직", "flo", "vlive"}


def _scan(txt: str, companies: list[dict], kind: str) -> tuple[dict | None, str]:
    key = "_aliases" if kind == "회사" else "_artists"
    best, blen, hit = None, 0, ""
    for c in companies:
        for n in c[key]:
            if n.lower() in BLOCK_ALIAS:
                continue
            if len(n) > blen and has_token(txt, n):
                best, blen, hit = c, len(n), n
    return best, hit


def match_company(title: str, body: str, companies: list[dict]) -> tuple[dict | None, str]:
    """2단계 우선순위로 사안의 주체를 판정한다.
    회사명 > 아티스트명 — 아티스트명은 수식어로 쓰이는 경우가 많기 때문이다.
    예) "세븐틴 키운 한성수가 만든 하이브 신인 걸그룹 튜이드" → 주체는 하이브.
    제목에서 먼저 찾고, 없으면 본문으로 넓힌다. 끝내 못 찾으면 기사를 폐기한다."""
    for scope, txt in (("제목", title), ("본문", f"{title} {body}")):
        for kind in ("회사", "아티스트"):
            c, hit = _scan(txt, companies, kind)
            if c:
                return c, f"{scope}/{kind}:{hit}"
    return None, ""


# ─────────────────────── 분류 ───────────────────────
SUPPRESS = {
    "LEGAL_DISPUTE": ["CONTRACT_NEW"],
    "ARTIST_RISK": ["COMEBACK", "TOUR_MD", "DEBUT"],
    "DEBUT": ["COMEBACK"],        # 데뷔앨범은 발주 1건 — 컴백과 중복 계상 금지
    "CREDIT_RISK": ["LABEL_CORP"],
}


def classify(text: str, rules: dict) -> list[tuple[str, dict, list[str]]]:
    if any(g in text for g in rules["global_exclude"]):
        return []
    hits = []
    for cat, spec in rules["categories"].items():
        if any(x in text for x in spec.get("exclude", [])):
            continue
        req = spec.get("require_any")
        if req and not any(x in text for x in req):
            continue
        matched = [k for k in spec["keywords"] if k in text]
        if matched:
            hits.append((cat, spec, matched))
    found = {h[0] for h in hits}
    blocked = {b for f in found for b in SUPPRESS.get(f, [])}
    return [h for h in hits if h[0] not in blocked]


def certainty(text: str, rules: dict) -> tuple[str, float]:
    for lv in ("official", "press", "rumor"):
        if any(s in text for s in rules["certainty"][lv]["signals"]):
            return lv, rules["certainty"][lv]["weight"]
    return "press", 0.7


# ─────────────────────── 이벤트 군집화 ───────────────────────
STOP = set("공식 전문 속보 단독 오늘 내일 사진 포토 영상 기사 뉴스 그룹 아이돌 가수".split())


def norm_title(title: str) -> str:
    """매체별 표기 차이 흡수: 괄호·기호·공백 제거, 영문 소문자화."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title)
    t = re.sub(r"[^\w가-힣]", "", t).lower()
    for w in STOP:
        t = t.replace(w, "")
    return t


def ngrams(title: str, n: int = 3) -> set[str]:
    t = norm_title(title)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))} or {t}


def cluster(items: list[dict], thr: float = 0.28) -> list[list[dict]]:
    """같은 (거래처·카테고리) 안에서 제목 문자 3-gram 유사도로 동일 이벤트 묶기.
    매체마다 제목 어순·표기가 달라 단어 단위보다 문자 n-gram이 안정적."""
    groups: list[list[dict]] = []
    for it in sorted(items, key=lambda x: x["published"]):
        ng = ngrams(it["title"])
        best_g, best_s = None, 0.0
        for g in groups:
            sim = len(ng & g[0]["_ng"]) / max(1, min(len(ng), len(g[0]["_ng"])))
            if sim > best_s:
                best_g, best_s = g, sim
        if best_g is not None and best_s >= thr:
            best_g.append(it)
        else:
            it["_ng"] = ng
            groups.append([it])
    return groups


def corroboration_mult(n: int, table: dict) -> float:
    m = 1.0
    for k in sorted(table):
        if n >= int(k):
            m = table[k]
    return m


# ─────────────────────── 스코어 ───────────────────────
def build_events(matched: list[tuple[dict, dict, str]], rules: dict) -> list[dict]:
    """matched: (기사, 거래처, 매칭근거) → 이벤트 단위로 집계."""
    bucket: dict[tuple, list] = {}
    for item, comp, how in matched:
        text = f"{item['title']} {item['body']}"
        for cat, spec, kws in classify(text, rules):
            bucket.setdefault((comp["code"], cat), []).append(
                {**item, "_comp": comp, "_spec": spec, "_cat": cat, "_kws": kws, "_how": how})

    thr, events = rules["alert_threshold"], []
    for (code, cat), items in bucket.items():
        for grp in cluster(items):
            rep = max(grp, key=lambda x: (len(x.get("_kws", [])), x["published"]))
            comp, spec = rep["_comp"], rep["_spec"]
            joined = " ".join(f"{g['title']} {g['body']}" for g in grp)
            lv, cw = certainty(joined, rules)
            cm = corroboration_mult(len(grp), rules["corroboration"])
            score = spec["impact"] * cw * rules["tier_multiplier"].get(comp["모니터링등급"], 1.0) * cm
            tier = "URGENT" if score >= thr["URGENT"] else ("DAILY" if score >= thr["DAILY"] else "ARCHIVE")
            if spec.get("escalate") and comp["모니터링등급"] in ("S", "A"):
                tier = "URGENT"
            elif spec.get("escalate") and tier == "ARCHIVE":
                tier = "DAILY"
            exp = None
            if spec["type"] == "PRE" and spec["lead_days"] > 0:
                exp = (rep["published"] + dt.timedelta(days=spec["lead_days"])).date().isoformat()
            events.append({
                "published": rep["published"], "title": rep["title"], "url": rep["url"],
                "source": rep["source"], "code": code, "company": comp["정식명"],
                "group": comp["계열그룹"], "grade": comp["모니터링등급"],
                "category": cat, "cat_label": spec["label"], "cat_type": spec["type"],
                "impact": spec["impact"], "certainty": lv, "n_articles": len(grp),
                "score": round(score, 2), "alert": tier,
                "keywords": ", ".join(dict.fromkeys(rep["_kws"]))[:60],
                "match": rep["_how"], "expected_order_by": exp,
                "others": [g["url"] for g in grp[1:6]],
            })
    return events


def merge_cross_category(events: list[dict], thr: float = 0.13) -> list[dict]:
    """같은 거래처에서 카테고리만 다른 동일 사안(예: 데뷔앨범이 DEBUT+COMEBACK로 이중 계상)
    을 하나로 합친다. 발주는 1건이므로 이중 노출은 노이즈."""
    out: list[dict] = []
    for e in sorted(events, key=lambda x: -x["score"]):
        ng = ngrams(e["title"])
        dup = None
        for k in out:
            if k["code"] != e["code"]:
                continue
            if len(ng & k["_ng"]) / max(1, min(len(ng), len(k["_ng"]))) >= thr:
                dup = k
                break
        if dup:
            dup["n_articles"] += e["n_articles"]
            if e["cat_label"] not in dup["cat_label"]:
                dup["cat_label"] += f" / {e['cat_label']}"
        else:
            e["_ng"] = ng
            out.append(e)
    for e in out:
        e.pop("_ng", None)
    return out


def apply_caps(events: list[dict], rules: dict) -> list[dict]:
    caps = rules["caps"]
    events = [e for e in events if e["alert"] != "ARCHIVE"]
    events = merge_cross_category(events)
    events.sort(key=lambda e: (-e["score"], -e["n_articles"]))
    per, kept = {}, []
    for e in events:
        if per.get(e["code"], 0) >= caps["per_company"]:
            continue
        per[e["code"]] = per.get(e["code"], 0) + 1
        kept.append(e)
    urg = [e for e in kept if e["alert"] == "URGENT"][:caps["urgent"]]
    dly = [e for e in kept if e["alert"] == "DAILY"][:caps["daily"]]
    return urg + dly


# ─────────────────────── 실행 ───────────────────────
def build_queries(c: dict, rules: dict) -> list[str]:
    base, gr = c["검색명"], c.get("모니터링등급", "C")
    if gr == "S":
        qs = [base, f"{base} 컴백", f"{base} 앨범", f"{base} 계약"]
        qs += [f"{a} 앨범" for a in c["_artists"][:2]]
    elif gr == "A":
        qs = [base, f"{base} 컴백", f"{base} 계약"]
    elif gr == "B":
        qs = [base, f"{base} 앨범"]
    elif gr == "D":
        qs = [f"{base} 앨범"]
    else:
        qs = [base]
    return list(dict.fromkeys(qs))[:6]


def run(days: int = 2, use_dart: bool = True) -> tuple[list[dict], dict]:
    from collectors import naver_news, google_news, dart_filings

    companies, rules = load_companies(), load_rules()
    cutoff = dt.datetime.now(KST) - dt.timedelta(days=days)
    raw, seen = [], set()

    for c in companies:
        for q in build_queries(c, rules):
            for x in naver_news(q, display=20) + google_news(q, when=f"{days}d"):
                if x["url"] and x["url"] not in seen:
                    seen.add(x["url"])
                    raw.append(x)

    dart_items = []
    if use_dart:
        by_name = {c["정식명"]: c for c in companies}
        watch = [n for n, c in by_name.items() if c["모니터링등급"] in ("S", "A", "B")]
        dart_items = dart_filings(watch, days=days)

    stats = {"뉴스": len(raw), "공시": len(dart_items), "미매칭": 0}
    matched = []
    for item in raw:
        if item["published"] < cutoff:
            continue
        comp, how = match_company(item["title"], item["body"], companies)
        if not comp:
            stats["미매칭"] += 1
            continue
        matched.append((item, comp, how))
    for f in dart_items:
        comp = {c["정식명"]: c for c in companies}.get(f["company_hint"])
        if comp:
            matched.append((f, comp, "DART/공시"))

    stats["매칭"] = len(matched)
    events = build_events(matched, rules)
    stats["이벤트"] = len(events)
    final = apply_caps(events, rules)
    stats["채택"] = len(final)
    return final, stats
