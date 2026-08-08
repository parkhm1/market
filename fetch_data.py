# -*- coding: utf-8 -*-
"""
한국 증시 유동성 지표 원자료 수집

지표 1: 고객예탁금 / 국내 주식시장 시가총액 (KOSPI + KOSDAQ)
지표 2: 신용거래융자 잔고 / M2(광의통화, 말잔)

자료원
  - 금융투자협회 FreeSIS (일별)
      STATSCU0100000060  증시자금추이        -> 투자자예탁금
      STATSCU0100000070  신용공여 잔고 추이  -> 신용거래융자(전체)
      STATSCU0100000020  유가증권시장        -> KOSPI 시가총액
      STATSCU0100000030  코스닥시장          -> KOSDAQ 시가총액
  - 한국은행 ECOS OpenAPI (월별)
      161Y008 / BBGA00   M2(말잔, 원계열)

출력: data.json  (모든 금액 단위 = 원)
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

FREESIS_URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
FREESIS_HOME = "https://freesis.kofia.or.kr/stat/main.do"

def ecos_key():
    """ECOS 인증키: 환경변수 ECOS_API_KEY 가 있으면 사용, 없으면 공개 sample 키(1회 10건 제한).
    호출 시점에 읽는다 — Streamlit 처럼 import 이후에 키를 넣는 경우가 있다."""
    return os.environ.get("ECOS_API_KEY", "").strip() or "sample"

YEARS = 3


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- FreeSIS

def freesis_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.get(FREESIS_HOME, timeout=30)
    return s


def freesis_series(s, obj_nm, start, end, value_col, extra=None):
    """FreeSIS 일별 통계를 [(YYYYMMDD, float), ...] 오름차순으로 반환."""
    dm = {
        "tmpV1": "D",            # 자료주기 = 일
        "tmpV45": start,         # 조회 시작일
        "tmpV46": end,           # 조회 종료일
        "tmpV40": "1",           # 금액 단위 나눔값 (1 = 원)
        "OBJ_NM": obj_nm,
    }
    if extra:
        dm.update(extra)
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Referer": "https://freesis.kofia.or.kr/",
    }
    last_err = None
    for attempt in range(3):
        try:
            r = s.post(FREESIS_URL, data=json.dumps({"dmSearch": dm}).encode("utf-8"),
                       headers=headers, timeout=120)
            payload = r.json()
            break
        except Exception as e:                     # HTML 오류 페이지 등
            last_err = e
            time.sleep(2 + 3 * attempt)
    else:
        raise RuntimeError("FreeSIS %s 조회 실패: %s" % (obj_nm, last_err))

    rows = payload.get("ds1") or []
    out = []
    for row in rows:
        d = row.get("TMPV1")
        v = row.get(value_col)
        if not d or v is None:
            continue
        out.append((str(d), float(v)))
    out.sort(key=lambda t: t[0])
    log("  FreeSIS %s %-9s %4d건  (%s ~ %s)"
        % (obj_nm, value_col, len(out), out[0][0] if out else "-", out[-1][0] if out else "-"))
    return out


# ------------------------------------------------------------------- ECOS

def ecos_m2(start_ym, end_ym):
    """M2(말잔, 원계열) 월별 시계열을 [(YYYYMM, 원), ...] 오름차순으로 반환."""
    key = ecos_key()
    rows = []
    page, size = 1, (10 if key == "sample" else 1000)
    while True:
        url = ("https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/%d/%d/"
               "161Y008/M/%s/%s/BBGA00" % (key, page, page + size - 1, start_ym, end_ym))
        r = requests.get(url, timeout=60)
        j = r.json()
        if "StatisticSearch" not in j:
            code = (j.get("RESULT") or {}).get("CODE", "")
            msg = (j.get("RESULT") or {}).get("MESSAGE", r.text[:200])
            if rows and code == "INFO-200":        # 마지막 페이지 이후
                break
            raise RuntimeError("ECOS 조회 실패 [%s] %s" % (code, msg))
        got = j["StatisticSearch"]["row"]
        rows += got
        if len(got) < size:
            break
        page += size

    out = []
    for x in rows:
        try:
            out.append((x["TIME"], float(x["DATA_VALUE"]) * 1e9))   # 십억원 -> 원
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda t: t[0])
    log("  ECOS   161Y008 BBGA00  %4d건  (%s ~ %s)  key=%s"
        % (len(out), out[0][0] if out else "-", out[-1][0] if out else "-",
           "env" if key != "sample" else "sample"))
    return out


# ------------------------------------------------------------------- 수집

def collect():
    """모든 계열을 받아 하나의 dict 로 반환. (파일로 쓰지 않는다)"""
    today = date.today()
    start = today - timedelta(days=365 * YEARS + 10)
    s_ymd, e_ymd = start.strftime("%Y%m%d"), today.strftime("%Y%m%d")
    # M2 는 2~3개월 지연 공표 -> 조회 시작을 넉넉히 앞당긴다
    m2_start = (start - timedelta(days=95)).strftime("%Y%m")
    m2_end = today.strftime("%Y%m")

    log("조회기간 %s ~ %s" % (s_ymd, e_ymd))

    s = freesis_session()
    deposit = freesis_series(s, "STATSCU0100000060BO", s_ymd, e_ymd, "TMPV2")
    credit = freesis_series(s, "STATSCU0100000070BO", s_ymd, e_ymd, "TMPV2")
    kospi = freesis_series(s, "STATSCU0100000020BO", s_ymd, e_ymd, "TMPV5",
                           extra={"tmpV41": "1"})
    kosdaq = freesis_series(s, "STATSCU0100000030BO", s_ymd, e_ymd, "TMPV5",
                            extra={"tmpV41": "1"})
    m2 = ecos_m2(m2_start, m2_end)

    for name, series in [("투자자예탁금", deposit), ("신용거래융자", credit),
                         ("KOSPI 시가총액", kospi), ("KOSDAQ 시가총액", kosdaq),
                         ("M2", m2)]:
        if not series:
            raise RuntimeError("%s 자료가 비어 있습니다." % name)

    data = {
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "range": {"start": s_ymd, "end": e_ymd, "years": YEARS},
        "unit": "KRW",
        "daily": {
            "deposit": deposit,
            "credit": credit,
            "mktcap_kospi": kospi,
            "mktcap_kosdaq": kosdaq,
        },
        "monthly": {"m2": m2},
        "sources": {
            "deposit": "금융투자협회 FreeSIS 증시자금추이 (투자자예탁금, 장내파생상품 거래예수금 제외)",
            "credit": "금융투자협회 FreeSIS 신용공여 잔고 추이 (신용거래융자 전체)",
            "mktcap": "금융투자협회 FreeSIS 유가증권시장·코스닥시장 시가총액",
            "m2": "한국은행 ECOS 161Y008 M2(말잔, 원계열)",
        },
    }
    return data


def main():
    data = collect()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log("저장 완료: %s" % OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("실패: %s" % exc)
        sys.exit(1)
