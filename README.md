# 아라니아 거래처 인텔리전스 시스템

매출 상위 150개 거래처의 **사전지표(수주 파이프라인)** 와 **사후지표(신용·계약 리스크)** 를
매일 자동 수집·분류·채점하여 CFO실 브리프로 산출한다.

- 대시보드 · 브리프 열람 : `docs/index.html`
- 거래처 마스터 편집(웹) : `docs/master.html`
- 감시 대상 원본 : `config/companies.csv` (편집기가 이 파일을 생성)

---

## 1. 웹 대시보드 켜기 (최초 1회)

저장소 **Settings → Pages → Build and deployment**
- Source: `Deploy from a branch`
- Branch: `main` / 폴더 `/docs` → Save

1~2분 뒤 `https://<계정>.github.io/arania-intel/` 로 접속된다.
엑셀 마스터는 더 이상 필요 없다. 거래처 정보는 전부 웹 편집기에서 수정한다.

## 2. 마스터 수정 절차

1. `master.html` 에서 노란 칸(별칭·아티스트·계열·구분·등급·비고) 수정
2. **저장하기** → `companies.csv` 다운로드 + 안내창
3. 안내창의 **클립보드에 복사** → **GitHub에서 파일 열기** → 전체 선택 후 붙여넣기 → Commit
4. 다음 실행(익일 08:00 또는 수동 Run workflow)부터 반영

## 3. 파이프라인 구조

```
수집   Google News RSS(무료) · DART OpenAPI(무료) · 네이버 뉴스 API(선택)
  │
매칭   제목 우선 → 본문. 거래처명·검증된 아티스트명이 실제로 등장할 때만 채택.
       앞 글자가 한글이면 다른 단어의 일부로 보고 기각(부분일치 오탐 차단).
       ★ 매칭 실패 기사는 폐기한다. 검색을 유발한 회사에 임의 배정하지 않는다.
  │
분류   전역 부정어 → 카테고리별 부정어 → 필수 동반어(문맥 게이트) → 키워드
  │
군집   같은 거래처·카테고리 안에서 제목 문자 3-gram 유사도로 동일 사안 병합.
       카테고리가 달라도 같은 사안이면 재병합(데뷔앨범의 DEBUT+COMEBACK 이중계상 방지).
  │
채점   score = 영향도(1~3) × 확실성(0.4~1.0) × 등급배수(S1.8~D0.5) × 보도확산(1.0~1.3)
       긴급 5.0↑ / 브리프 3.0↑ · 신용·분쟁·아티스트 리스크는 S·A등급이면 긴급 강제
  │
상한   거래처당 3건 · 긴급 15건 · 브리프 40건
  │
산출   docs/briefs/ HTML · docs/data/ JSON+CSV · 메일 발송
```

## 4. 등급 체계 (최근 3년 매출 기여도 기반)

| 등급 | 개사 | 최근3년 비중 | 일 질의 |
|---|---|---|---|
| S | 15 | 79.3% | 6 |
| A | 36 | 15.5% | 3 |
| B | 63 | 4.7% | 2 |
| C | 24 | 0.5% | 1 |
| D (휴면) | 12 | — | 1 |

## 5. 실행

```bash
pip install -r requirements.txt
python src/main.py --mock --no-mail   # 키 없이 파이프라인 검증
python src/main.py --days 2           # 일일
python src/main.py --days 7           # 주간 롤업
python src/roster.py                  # 로스터 초안 (Wikidata, 최초 1회)
```

자동 실행: `.github/workflows/daily.yml` — 매주 월~금 KST 08:00

## 6. 필요한 GitHub Secrets

| 이름 | 필수 | 발급처 |
|---|---|---|
| `DART_API_KEY` | ● | opendart.fss.or.kr |
| `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` | ● | Gmail 앱 비밀번호 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | ○ | developers.naver.com (없으면 자동 생략) |

## 7. 튜닝

정밀도를 더 올리려면 `config/keywords.yaml`:

- 무관 기사가 남으면 → 해당 카테고리 `exclude` 에 단어 추가
- 유효 신호를 놓치면 → `require_any` 완화 또는 `keywords` 추가
- 건수가 많으면 → `alert_threshold` 상향 또는 `caps` 축소
- 매칭이 안 되면 → 마스터 편집기에서 **별칭** 보강 (정확도의 대부분이 여기서 결정됨)

## 8. 준법

- 나무위키·멜론·지니 등 약관상 크롤링 금지 사이트 미사용
- 기사는 제목·링크·요약만 저장, 본문 전문 복제·재배포 금지
- 로스터 자동수집은 Wikidata(CC0)만 사용, 결과는 계약서로 검증
- 거래처 신용정보는 사내 여신 판단 목적에 한해 사용
