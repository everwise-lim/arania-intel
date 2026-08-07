"""수집 레이어 — 네이버 뉴스 API / 구글뉴스 RSS / DART 전자공시."""
from __future__ import annotations

import io
import os
import random
import re
import time
import zipfile
import datetime as dt
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

KST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Arania-Intel/1.0 (CFO Office)"}
TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    s = TAG.sub("", s or "")
    for a, b in (("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&apos;", "'")):
        s = s.replace(a, b)
    return s.strip()


# ─────────────────────────── 네이버 뉴스 검색 API ───────────────────────────
# 무료 25,000 콜/일. https://developers.naver.com → 애플리케이션 등록 → 검색 API
def naver_news(query: str, display: int = 30, sort: str = "date") -> list[dict]:
    cid, csec = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not (cid and csec):
        return []
    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": query, "display": display, "sort": sort},
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec, **UA},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
    except Exception as e:                                    # noqa: BLE001
        print(f"  [naver] {query}: {e}")
        return []

    out = []
    for it in items:
        try:
            pub = dt.datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %z").astimezone(KST)
        except Exception:                                     # noqa: BLE001
            pub = dt.datetime.now(KST)
        out.append({
            "source": "naver",
            "title": _clean(it.get("title", "")),
            "body": _clean(it.get("description", "")),
            "url": it.get("originallink") or it.get("link", ""),
            "published": pub,
        })
    return out


# ─────────────────────────── 구글 뉴스 RSS (키 불필요) ───────────────────────────
# 실측: 연속 호출 시 503(Service Unavailable) 다발 → 간격 + 지수 백오프 필수
_GOOGLE_GAP = 1.5          # 호출 간 최소 간격(초)
_last_call = [0.0]


def google_news(query: str, when: str = "2d", retries: int = 3) -> list[dict]:
    url = (f"https://news.google.com/rss/search?q={quote(query)}+when:{when}"
           "&hl=ko&gl=KR&ceid=KR:ko")
    root = None
    for attempt in range(retries):
        wait = _GOOGLE_GAP - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            r = requests.get(url, headers=UA, timeout=15)
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt * 3 + random.uniform(0, 1.5))
                continue
            r.raise_for_status()
            root = ET.fromstring(r.content)
            break
        except Exception as e:                                # noqa: BLE001
            if attempt == retries - 1:
                print(f"  [google] {query}: {type(e).__name__}")
            else:
                time.sleep(2 ** attempt * 3)
    if root is None:
        return []

    out = []
    for item in root.iter("item"):
        pd = (item.findtext("pubDate") or "").strip()
        try:
            pub = dt.datetime.strptime(pd, "%a, %d %b %Y %H:%M:%S %Z").replace(
                tzinfo=dt.timezone.utc).astimezone(KST)
        except Exception:                                     # noqa: BLE001
            pub = dt.datetime.now(KST)
        out.append({
            "source": "google",
            "title": _clean(item.findtext("title") or ""),
            "body": _clean(item.findtext("description") or "")[:400],
            "url": item.findtext("link") or "",
            "published": pub,
        })
    return out


# ─────────────────────────── DART 전자공시 ───────────────────────────
# 무료. https://opendart.fss.or.kr → 인증키 신청
_CORP_CACHE: dict[str, str] | None = None


def dart_corp_index() -> dict[str, str]:
    """회사명 → corp_code 매핑. 1회 다운로드 후 메모리 캐시."""
    global _CORP_CACHE
    if _CORP_CACHE is not None:
        return _CORP_CACHE
    key = os.getenv("DART_API_KEY")
    _CORP_CACHE = {}
    if not key:
        return _CORP_CACHE
    try:
        r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                         params={"crtfc_key": key}, headers=UA, timeout=60)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml = z.read(z.namelist()[0])
        for el in ET.fromstring(xml).iter("list"):
            name = (el.findtext("corp_name") or "").strip()
            code = (el.findtext("corp_code") or "").strip()
            if name and code:
                _CORP_CACHE[_norm(name)] = code
    except Exception as e:                                    # noqa: BLE001
        print(f"  [dart] corpCode 로드 실패: {e}")
    return _CORP_CACHE


def _norm(s: str) -> str:
    return re.sub(r"[\s()（）주\.]", "", s)


def dart_filings(corp_names: list[str], days: int = 2) -> list[dict]:
    """지정 회사들의 최근 공시 목록."""
    key = os.getenv("DART_API_KEY")
    if not key:
        return []
    idx = dart_corp_index()
    end = dt.datetime.now(KST).date()
    beg = end - dt.timedelta(days=days)
    out = []
    for name in corp_names:
        code = idx.get(_norm(name))
        if not code:
            continue
        try:
            r = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                params={"crtfc_key": key, "corp_code": code,
                        "bgn_de": beg.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
                        "page_count": 50},
                headers=UA, timeout=15)
            data = r.json()
            for it in data.get("list", []):
                out.append({
                    "source": "dart",
                    "title": f"[공시] {it.get('report_nm','')}",
                    "body": f"{it.get('corp_name','')} / 제출인 {it.get('flr_nm','')}",
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it.get('rcept_no','')}",
                    "published": dt.datetime.strptime(it.get("rcept_dt", beg.strftime("%Y%m%d")),
                                                      "%Y%m%d").replace(tzinfo=KST),
                    "company_hint": name,
                })
        except Exception as e:                                # noqa: BLE001
            print(f"  [dart] {name}: {e}")
        time.sleep(0.15)
    return out
