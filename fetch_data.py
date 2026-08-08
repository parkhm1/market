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
import re
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

# FreeSIS 는 금액을 tmpV40 으로 나눠서 돌려준다. 원 단위로 받으면 15~16자리 숫자가 되는데,
# 해외 경로로 호출하면 11자리 이상 숫자열의 뒷부분이 '#' 로 마스킹돼 응답이 깨진다
# (카드번호·주민번호로 오인한 개인정보 필터로 보임). 억원 단위로 받으면 최대 8자리라 안전하다.
# 지표는 비율이라 억원 해상도로도 정밀도가 남는다 (상대오차 ~1e-7).
MONEY_DIV = 100000000          # 억원
SHARE_DIV = 1000               # 천주 (쓰지 않는 컬럼이지만 같이 짧게 받는다)

# 배포된 코드가 어느 버전인지 화면에서 바로 확인하기 위한 표시.
# 수집 로직을 바꿀 때마다 올린다.
VERSION = "2026-08-08c (억원 단위 + 마스킹 복원)"

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


class FreesisBadResponse(RuntimeError):
    """응답이 JSON 이 아닐 때. 원문을 그대로 담아 원인을 눈으로 확인할 수 있게 한다."""

    def __init__(self, obj_nm, span, resp, err):
        body = resp.content or b""
        self.detail = (
            "FreeSIS %s (%s) 응답을 JSON 으로 읽지 못했습니다.\n"
            "  코드버전  : %s\n"
            "  금액단위  : 1/%d 로 요청 (tmpV40)\n"
            "  오류      : %s\n"
            "  status    : %s\n"
            "  본문 길이 : %d bytes\n"
            "  종류      : %s / 추정 인코딩 %s\n"
            "  앞 240자  : %r\n"
            "  끝 160자  : %r"
            % (obj_nm, span, VERSION, MONEY_DIV, err, resp.status_code, len(body),
               resp.headers.get("content-type"), resp.encoding,
               body[:240], body[-160:])
        )
        super().__init__(self.detail)


def _freesis_post(s, dm, span):
    """FreeSIS 한 번 호출. 재시도하되, 마지막 실패는 원문을 담아 올린다."""
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://freesis.kofia.or.kr/",
        "X-Requested-With": "XMLHttpRequest",
    }
    body = json.dumps({"dmSearch": dm}).encode("utf-8")
    last = None
    for attempt in range(3):
        try:
            r = s.post(FREESIS_URL, data=body, headers=headers, timeout=120)
        except Exception as e:                       # 네트워크 자체 실패
            last = RuntimeError("FreeSIS %s (%s) 요청 실패: %s"
                                % (dm.get("OBJ_NM"), span, e))
        else:
            try:
                return json.loads(_unmask(r.text))
            except ValueError as e:                  # HTML 오류 페이지, 잘린 응답 등
                last = FreesisBadResponse(dm.get("OBJ_NM"), span, r, e)
        time.sleep(2 + 3 * attempt)
    raise last


# 숫자 뒤에 붙은 '#' 마스킹을 0 으로 되살린다. 억원 단위로 받으므로 정상적으로는
# 발동하지 않지만, 마스킹 임계값이 더 낮아지는 경우에도 페이지가 죽지 않게 두는 안전망이다.
# (되살린 값의 상대오차는 마스킹된 자리수만큼 — 억원 단위에서는 무시할 수준)
_MASK = re.compile(r"(?<=\d)#+")


def _unmask(text):
    fixed, n = _MASK.subn(lambda m: "0" * len(m.group()), text)
    if n:
        log("  주의: 마스킹된 숫자 %d개를 0으로 복원했습니다." % n)
    return fixed


def _year_spans(start, end):
    """조회구간을 1년 단위로 쪼갠다. 응답이 작을수록 잘림·시간초과에 강하다."""
    s_d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    e_d = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    spans, cur = [], s_d
    while cur <= e_d:
        nxt = min(date(cur.year + 1, cur.month, cur.day) - timedelta(days=1), e_d)
        spans.append((cur.strftime("%Y%m%d"), nxt.strftime("%Y%m%d")))
        cur = nxt + timedelta(days=1)
    return spans


def freesis_series(s, obj_nm, start, end, value_col, extra=None, scale=MONEY_DIV):
    """FreeSIS 일별 통계를 [(YYYYMMDD, 원), ...] 오름차순으로 반환."""
    merged = {}
    for c_start, c_end in _year_spans(start, end):
        dm = {
            "tmpV1": "D",                  # 자료주기 = 일
            "tmpV45": c_start,             # 조회 시작일
            "tmpV46": c_end,               # 조회 종료일
            "tmpV40": str(MONEY_DIV),      # 금액 나눔값
            "OBJ_NM": obj_nm,
        }
        if extra:
            dm.update(extra)
        payload = _freesis_post(s, dm, "%s~%s" % (c_start, c_end))
        for row in payload.get("ds1") or []:
            d, v = row.get("TMPV1"), row.get(value_col)
            if not d or v is None:
                continue
            merged[str(d)] = float(v) * scale

    out = sorted(merged.items())
    if not out:
        raise RuntimeError("FreeSIS %s %s 결과가 비어 있습니다." % (obj_nm, value_col))
    log("  FreeSIS %s %-9s %4d건  (%s ~ %s)"
        % (obj_nm, value_col, len(out), out[0][0], out[-1][0]))
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
                           extra={"tmpV41": str(SHARE_DIV)})
    kosdaq = freesis_series(s, "STATSCU0100000030BO", s_ymd, e_ymd, "TMPV5",
                            extra={"tmpV41": str(SHARE_DIV)})
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
