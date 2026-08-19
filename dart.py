# -*- coding: utf-8 -*-
"""
전자공시(DART) OpenAPI 조회

사업보고서 / 반기보고서 / 분기보고서에서 다음을 뽑는다.
  - 수주상황 (수주총액 · 기납품액 · 수주잔고)
  - 매출 및 판매 실적
  - 주요 재무수치

인증키
  환경변수 DART_API_KEY 에 넣는다. 저장소에 키를 적어 두지 않는다.
  https://opendart.fss.or.kr → 인증키 신청 (일 20,000건)

사용법
  export DART_API_KEY=발급받은키

  python dart.py 프로텍                 # 최근 보고서 목록
  python dart.py 프로텍 --order         # 수주상황 표만 뽑기
  python dart.py 053610 --order         # 종목코드로도 된다
  python dart.py 프로텍 --fin 2026 --rpt 반기
  python dart.py --order 프로텍 티에스이 기가비스 티엘비   # 여러 개 비교

참고
  - corp_code(고유번호) 목록은 zip 으로 받아 corp_codes.json 에 캐시한다.
  - 보고서 원문(document.xml)은 zip 안에 XML 이 들어 있고, 그 XML 안의
    <TABLE> 들 중 '수주' 가 들어간 표를 찾아 텍스트로 편다.
  - 수주잔고 공시는 의무가 아니다. 회사에 따라 표가 아예 없을 수 있고,
    그 경우 '해당사항 없음' 으로 표시한다.
"""

import io
import json
import os
import re
import sys
import zipfile
from datetime import date

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CORP_CACHE = os.path.join(HERE, "corp_codes.json")

BASE = "https://opendart.fss.or.kr/api"
TIMEOUT = 30

# 보고서 코드
REPRT = {
    "1분기": "11013",
    "반기": "11012",
    "3분기": "11014",
    "사업": "11011",
}

# 정기공시 상세유형
PBLNTF_DETAIL = "A001,A002,A003"     # 사업보고서, 반기보고서, 분기보고서


class DartError(RuntimeError):
    pass


def key():
    """DART 인증키. 환경변수 DART_API_KEY 에서 읽는다."""
    k = os.environ.get("DART_API_KEY", "").strip()
    if not k:
        raise DartError(
            "DART_API_KEY 가 없다.\n"
            "  export DART_API_KEY=발급받은키\n"
            "  키 발급: https://opendart.fss.or.kr"
        )
    return k


def _get(path, **params):
    params["crtfc_key"] = key()
    r = requests.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _get_json(path, **params):
    j = _get(path, **params).json()
    status = j.get("status")
    if status == "013":                       # 조회된 데이터 없음
        return None
    if status != "000":
        raise DartError(f"{path}: [{status}] {j.get('message')}")
    return j


# ---------------------------------------------------------------- 고유번호

def load_corp_codes(refresh=False):
    """전체 상장·비상장사의 고유번호 목록. 한 번 받아 캐시한다."""
    if not refresh and os.path.exists(CORP_CACHE):
        with open(CORP_CACHE, encoding="utf-8") as f:
            return json.load(f)

    r = _get("corpCode.xml")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml = z.read(z.namelist()[0]).decode("utf-8")

    out = {}
    for m in re.finditer(r"<list>(.*?)</list>", xml, re.S):
        blk = m.group(1)

        def tag(t):
            mm = re.search(rf"<{t}>(.*?)</{t}>", blk, re.S)
            return (mm.group(1) if mm else "").strip()

        stock = tag("stock_code")
        if not stock:                          # 상장사만 남긴다
            continue
        out[stock] = {
            "corp_code": tag("corp_code"),
            "corp_name": tag("corp_name"),
            "stock_code": stock,
        }

    with open(CORP_CACHE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def find_corp(q):
    """종목코드(053610) 또는 회사명(프로텍) 으로 고유번호를 찾는다."""
    codes = load_corp_codes()
    q = q.strip()

    if re.fullmatch(r"\d{6}", q):
        if q not in codes:
            raise DartError(f"종목코드 {q} 를 찾을 수 없다 (상장사만 대상).")
        return codes[q]

    exact = [v for v in codes.values() if v["corp_name"] == q]
    if exact:
        return exact[0]

    part = [v for v in codes.values() if q in v["corp_name"]]
    if not part:
        raise DartError(f"'{q}' 에 해당하는 회사가 없다.")
    if len(part) > 1:
        names = ", ".join(f"{v['corp_name']}({v['stock_code']})" for v in part[:10])
        raise DartError(f"'{q}' 로 여러 곳이 잡힌다: {names}")
    return part[0]


# ---------------------------------------------------------------- 공시 목록

def filings(corp_code, years=2, detail=PBLNTF_DETAIL):
    """정기보고서 목록 (최근 것부터)."""
    today = date.today()
    j = _get_json(
        "list.json",
        corp_code=corp_code,
        bgn_de=f"{today.year - years}{today:%m%d}",
        end_de=f"{today:%Y%m%d}",
        pblntf_detail_ty=detail,
        page_count=100,
    )
    if not j:
        return []
    return sorted(j["list"], key=lambda x: x["rcept_dt"], reverse=True)


# ---------------------------------------------------------------- 보고서 원문

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\xa0]+")


def _text(s):
    s = re.sub(r"<BR\s*/?>", " ", s, flags=re.I)
    s = _TAG.sub("", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return _WS.sub(" ", s).strip()


def document(rcept_no):
    """보고서 원문 XML. zip 으로 내려와 그 안의 파일들을 이어 붙인다."""
    r = _get("document.xml", rcept_no=rcept_no)
    if r.content[:2] != b"PK":                 # zip 이 아니면 에러 XML
        raise DartError(f"원문을 받지 못했다: {_text(r.text)[:200]}")
    parts = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for n in z.namelist():
            raw = z.read(n)
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    parts.append(raw.decode(enc))
                    break
                except UnicodeDecodeError:
                    continue
    return "\n".join(parts)


def tables(xml, keyword):
    """본문 XML 에서 keyword 가 들어간 TABLE 을 행 단위로 편다."""
    out = []
    for m in re.finditer(r"<TABLE[^>]*>.*?</TABLE>", xml, re.S | re.I):
        blk = m.group(0)
        if keyword not in _text(blk):
            continue
        rows = []
        for tr in re.finditer(r"<TR[^>]*>(.*?)</TR>", blk, re.S | re.I):
            cells = [_text(td.group(1)) for td in
                     re.finditer(r"<T[DH][^>]*>(.*?)</T[DH]>", tr.group(1), re.S | re.I)]
            if any(c for c in cells):
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def order_backlog(rcept_no):
    """수주상황 표. 없으면 빈 리스트."""
    xml = document(rcept_no)
    found = tables(xml, "수주")
    # '수주' 가 주석에만 나오는 표는 걸러낸다 (열이 3개 미만이면 표가 아님)
    return [t for t in found if max(len(r) for r in t) >= 3]


# ---------------------------------------------------------------- 재무

def financials(corp_code, year, reprt="반기", fs_div="CFS"):
    """단일회사 전체 재무제표. fs_div: CFS 연결 / OFS 별도."""
    j = _get_json(
        "fnlttSinglAcntAll.json",
        corp_code=corp_code,
        bsns_year=str(year),
        reprt_code=REPRT[reprt],
        fs_div=fs_div,
    )
    return j["list"] if j else []


def pick(rows, *names):
    """계정명으로 골라낸다."""
    out = {}
    for r in rows:
        nm = r.get("account_nm", "").replace(" ", "")
        for want in names:
            if want.replace(" ", "") == nm:
                out[want] = r
    return out


# ---------------------------------------------------------------- 출력

def _w(s, n):
    """한글 폭을 감안한 좌측 정렬."""
    wide = sum(1 for c in s if ord(c) > 0x1100)
    return s + " " * max(0, n - len(s) - wide)


def show_filings(name, rows):
    print(f"\n{'=' * 72}\n{name} — 정기보고서\n{'=' * 72}")
    if not rows:
        print("  최근 2년 내 정기보고서가 없다.")
        return
    for r in rows:
        print(f"  {r['rcept_dt']}  {_w(r['report_nm'], 34)}  {r['rcept_no']}")


def show_backlog(name, rcept_no, report_nm):
    print(f"\n{'=' * 72}\n{name} — 수주상황  [{report_nm}]\n{'=' * 72}")
    try:
        tabs = order_backlog(rcept_no)
    except DartError as e:
        print(f"  ! {e}")
        return
    if not tabs:
        print("  수주상황 표가 없다. (수주잔고는 의무 공시 항목이 아니다)")
        return
    for t in tabs:
        width = max(len(r) for r in t)
        for row in t:
            row = row + [""] * (width - len(row))
            print("  " + " | ".join(_w(c, 16) for c in row))
        print()


# ---------------------------------------------------------------- CLI

def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}

    if not args:
        print(__doc__)
        return 1

    want_order = "--order" in flags
    want_fin = "--fin" in flags

    year = None
    reprt = "반기"
    for i, a in enumerate(argv):
        if a == "--fin" and i + 1 < len(argv):
            year = argv[i + 1]
        if a == "--rpt" and i + 1 < len(argv):
            reprt = argv[i + 1]
    if year and year in args:
        args.remove(year)
    if reprt in args:
        args.remove(reprt)

    for q in args:
        try:
            corp = find_corp(q)
        except DartError as e:
            print(f"\n! {e}")
            continue

        name = f"{corp['corp_name']} ({corp['stock_code']})"
        rows = filings(corp["corp_code"])

        if want_order:
            if not rows:
                print(f"\n{name}: 정기보고서가 없다.")
                continue
            latest = rows[0]
            show_backlog(name, latest["rcept_no"], latest["report_nm"])
        elif want_fin:
            fin = financials(corp["corp_code"], year or date.today().year, reprt)
            print(f"\n{'=' * 72}\n{name} — {year} {reprt} 재무 (연결)\n{'=' * 72}")
            got = pick(fin, "매출액", "영업이익", "당기순이익",
                       "현금및현금성자산", "단기차입금", "장기차입금", "자본총계")
            if not got:
                print("  자료가 없다. 연도/보고서 종류를 확인할 것.")
            for k, r in got.items():
                cur = r.get("thstrm_amount", "").strip() or "-"
                print(f"  {_w(k, 18)} {cur:>20}")
        else:
            show_filings(name, rows)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except DartError as e:
        print(f"\n! {e}", file=sys.stderr)
        sys.exit(2)
