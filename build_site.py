# -*- coding: utf-8 -*-
"""
data.json -> index.html (단일 파일 정적 페이지) / artifact.html (Artifact 업로드용 본문)

지표 1: 고객예탁금 / 시가총액(KOSPI+KOSDAQ)   * 일별
지표 2: 신용거래융자 잔고 / M2(말잔)           * 일별 잔고 / 월말 M2 보간
"""

import calendar
import json
import os
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")

JO = 1e12  # 조원


# ---------------------------------------------------------------- 계열 가공

def to_ord(ymd):
    return date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])).toordinal()


def month_end_ord(ym):
    y, m = int(ym[:4]), int(ym[4:6])
    return date(y, m, calendar.monthrange(y, m)[1]).toordinal()


def interpolate_m2(m2_monthly, day_ords):
    """월말 M2를 일별로 선형보간. 마지막 공표월 이후는 수평 유지(잠정)."""
    anchors = [(month_end_ord(ym), v) for ym, v in m2_monthly]
    anchors.sort()
    last_anchor = anchors[-1][0]
    out, provisional = [], []
    i = 0
    for o in day_ords:
        while i + 1 < len(anchors) and anchors[i + 1][0] <= o:
            i += 1
        if o <= anchors[0][0]:
            v = anchors[0][1]
        elif i + 1 >= len(anchors):
            v = anchors[-1][1]
        else:
            o0, v0 = anchors[i]
            o1, v1 = anchors[i + 1]
            v = v0 + (v1 - v0) * (o - o0) / (o1 - o0)
        out.append(v)
        provisional.append(o > last_anchor)
    return out, provisional, anchors[-1][0]


def build_series(data):
    d = data["daily"]
    deposit = dict(d["deposit"])
    credit = dict(d["credit"])
    kospi = dict(d["mktcap_kospi"])
    kosdaq = dict(d["mktcap_kosdaq"])
    kidx = dict(d.get("kospi_index") or [])

    # 각 점: [일자, 비율%, 분자(조), 분모(조), KOSPI지수]
    # 지표 1 --------------------------------------------------------------
    dates1 = sorted(set(deposit) & set(kospi) & set(kosdaq))
    s1 = []
    for t in dates1:
        den = kospi[t] + kosdaq[t]
        if den <= 0:
            continue
        s1.append([t, round(deposit[t] / den * 100, 4),
                   round(deposit[t] / JO, 2), round(den / JO, 1),
                   kidx.get(t)])

    # 지표 2 --------------------------------------------------------------
    dates2 = sorted(credit)
    m2_vals, prov, last_m2_ord = interpolate_m2(data["monthly"]["m2"],
                                                [to_ord(t) for t in dates2])
    s2, first_prov = [], None
    for idx, t in enumerate(dates2):
        m2v = m2_vals[idx]
        if m2v <= 0:
            continue
        if prov[idx] and first_prov is None:
            first_prov = len(s2)
        s2.append([t, round(credit[t] / m2v * 100, 4),
                   round(credit[t] / JO, 2), round(m2v / JO, 0),
                   kidx.get(t)])

    last_m2_ym = max(ym for ym, _ in data["monthly"]["m2"])
    return s1, s2, first_prov, last_m2_ym


def stats(points, lo=None):
    vals = [p[1] for p in points]
    cur = vals[-1]
    prev = vals[-2] if len(vals) > 1 else cur
    rank = sum(1 for v in vals if v <= cur) / len(vals) * 100
    return {
        "cur": cur, "delta": cur - prev,
        "min": min(vals), "max": max(vals),
        "avg": sum(vals) / len(vals), "pct": rank,
        "curDate": points[-1][0], "prevDate": points[-2][0] if len(points) > 1 else points[-1][0],
        "minDate": points[vals.index(min(vals))][0],
        "maxDate": points[vals.index(max(vals))][0],
    }


# ------------------------------------------------------------------- 페이지

TITLE = "한국 증시 유동성 지표"


def render(data):
    s1, s2, first_prov, last_m2_ym = build_series(data)
    charts = [
        {
            "id": "deposit",
            "eyebrow": "지표 1",
            "title": "시가총액 대비 고객예탁금",
            "formula": "투자자예탁금 ÷ (KOSPI + KOSDAQ 시가총액)",
            "note": "증시 대기자금의 상대적 크기. 값이 높으면 시장 규모에 비해 투자 대기 현금이 두껍다는 뜻입니다.",
            "color": 1,
            "digits": 2,
            "numLabel": "투자자예탁금",
            "denLabel": "시가총액",
            "points": s1,
            "stats": stats(s1),
            "provFrom": None,
        },
        {
            "id": "credit",
            "eyebrow": "지표 2",
            "title": "M2 대비 신용거래융자 잔고",
            "formula": "신용거래융자 잔고 ÷ M2(광의통화, 말잔)",
            "note": "경제 전체 통화량에 견준 빚투 규모. 과열·레버리지 축적의 대리지표로 읽습니다.",
            "color": 2,
            "digits": 3,
            "numLabel": "신용융자잔고",
            "denLabel": "M2",
            "points": s2,
            "stats": stats(s2),
            "provFrom": first_prov,
        },
    ]

    payload = {
        "charts": charts,
        "fetchedAt": data["fetched_at"],
        "lastM2": last_m2_ym,
        "sources": data["sources"],
    }

    fetched = datetime.fromisoformat(data["fetched_at"])
    m2_label = "%s년 %s월" % (last_m2_ym[:4], last_m2_ym[4:].lstrip("0"))

    head = """<title>%s</title>
<style>
%s
</style>""" % (TITLE, CSS)

    body = """
<div class="page" id="app">
  <header class="masthead">
    <p class="eyebrow">KOFIA · BOK 일일 갱신</p>
    <h1>%(title)s</h1>
    <p class="lede">국내 주식시장 시가총액 대비 고객예탁금, 그리고 M2 대비 신용거래융자 잔고.
      두 지표 모두 최근 3년 구간을 일별로 보여줍니다.</p>
    <p class="meta">
      <span>최신 자료일 <b id="asof">–</b></span>
      <span class="dot">·</span>
      <span>갱신 %(fetched)s</span>
    </p>
    <p class="stale" id="stale" hidden></p>
  </header>

  <div class="filters" role="group" aria-label="차트 표시 설정">
    <span class="filters-label">조회 기간</span>
    <div class="segmented" id="rangeCtl">
      <button type="button" data-days="90">3개월</button>
      <button type="button" data-days="182">6개월</button>
      <button type="button" data-days="365">1년</button>
      <button type="button" data-days="0" class="is-on" aria-pressed="true">3년</button>
    </div>
    <label class="check"><input type="checkbox" id="kospiCtl" checked> KOSPI 지수 겹쳐 보기</label>
    <span class="zoomchip" id="zoomChip" hidden></span>
  </div>
  <p class="hint">차트 위에서 <b>마우스 휠을 올리면 확대, 내리면 축소</b>됩니다(커서가 가리키는 날짜가 기준).
    확대한 뒤에는 <b>좌우로 끌어</b> 구간을 옮길 수 있습니다(<b>Shift + 휠</b>도 됩니다).
    두 번 클릭하거나 <b>Esc</b>를 누르면 원래대로 돌아옵니다. 확대와 KOSPI 표시는 두 차트에 함께 적용됩니다.</p>

  <main class="stack" id="cards"></main>

  <footer class="footnotes">
    <h2>자료원과 읽는 법</h2>
    <ul>
      <li><b>투자자예탁금</b> — 금융투자협회 FreeSIS 「증시자금추이」. 장내파생상품 거래예수금은 제외한 수치입니다.</li>
      <li><b>신용거래융자 잔고</b> — 금융투자협회 FreeSIS 「신용공여 잔고 추이」의 신용거래융자 전체(유가증권 + 코스닥).</li>
      <li><b>시가총액</b> — 금융투자협회 FreeSIS 유가증권시장·코스닥시장 시가총액의 합.</li>
      <li><b>M2</b> — 한국은행 ECOS 「M2 상품별 구성내역(말잔, 원계열)」. 월별 통계이므로 월말값을 일별로 선형보간했고,
        가장 최근 공표월은 <b>%(m2label)s</b>입니다. 그 이후 구간은 M2를 마지막 값으로 고정한 <b>잠정 계산</b>이며
        차트에서 점선으로 표시됩니다.</li>
      <li>예탁금·신용융자는 결제 주기 때문에 시가총액보다 1영업일 늦게 확정되는 날이 있습니다.
        두 계열이 모두 존재하는 날짜만 그렸습니다.</li>
      <li>투자 판단의 책임은 이용자에게 있습니다. 원자료에 오류나 지연이 있을 수 있습니다.</li>
    </ul>
  </footer>
</div>

<script id="payload" type="application/json">%(payload)s</script>
<script>
%(js)s
</script>
""" % {
        "title": TITLE,
        "fetched": fetched.strftime("%Y-%m-%d %H:%M"),
        "m2label": m2_label,
        "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "js": JS,
    }
    return head, body


CSS = r"""
*, *::before, *::after { box-sizing: border-box; }

:root {
  color-scheme: light;
  --plane:        #f9f9f7;
  --surface:      #fcfcfb;
  --ink:          #0b0b0b;
  --ink-2:        #52514e;
  --ink-muted:    #898781;
  --grid:         #e1e0d9;
  --axis:         #c3c2b7;
  --hairline:     rgba(11,11,11,0.10);
  --series-1:     #2a78d6;
  --series-2:     #eb6834;
  --series-3:     #1baf7a;
  --up:           #006300;
  --down:         #d03b3b;
  --wash:         rgba(11,11,11,0.04);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --plane:      #0d0d0d;
    --surface:    #1a1a19;
    --ink:        #ffffff;
    --ink-2:      #c3c2b7;
    --ink-muted:  #898781;
    --grid:       #2c2c2a;
    --axis:       #383835;
    --hairline:   rgba(255,255,255,0.10);
    --series-1:   #3987e5;
    --series-2:   #d95926;
    --series-3:   #199e70;
    --up:         #0ca30c;
    --down:       #e66767;
    --wash:       rgba(255,255,255,0.06);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane:      #0d0d0d;
  --surface:    #1a1a19;
  --ink:        #ffffff;
  --ink-2:      #c3c2b7;
  --ink-muted:  #898781;
  --grid:       #2c2c2a;
  --axis:       #383835;
  --hairline:   rgba(255,255,255,0.10);
  --series-1:   #3987e5;
  --series-2:   #d95926;
  --series-3:   #199e70;
  --up:         #0ca30c;
  --down:       #e66767;
  --wash:       rgba(255,255,255,0.06);
}

body {
  margin: 0;
  background: var(--plane);
  color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 960px; margin: 0 auto; padding: 48px 20px 72px; }

.eyebrow {
  margin: 0 0 10px;
  font-size: 11px; font-weight: 650; letter-spacing: .09em; text-transform: uppercase;
  color: var(--ink-muted);
}
.masthead h1 { margin: 0 0 12px; font-size: clamp(26px, 4.2vw, 38px); line-height: 1.2; letter-spacing: -.02em; }
.masthead .lede { margin: 0 0 14px; max-width: 62ch; color: var(--ink-2); }
.masthead .meta { margin: 0; font-size: 13px; color: var(--ink-muted); }
.masthead .meta b { color: var(--ink-2); font-weight: 600; }
.masthead .dot { margin: 0 8px; }
.stale {
  margin: 14px 0 0; padding: 9px 13px; font-size: 13px; color: var(--ink-2);
  background: var(--surface); border: 1px solid var(--hairline);
  border-left: 3px solid #fab219; border-radius: 8px; max-width: 62ch;
}
.stale b { color: var(--ink); font-weight: 600; }

.filters {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  margin: 28px 0 18px;
}
.filters-label { font-size: 12px; letter-spacing: .04em; color: var(--ink-muted); }
.segmented { display: flex; gap: 2px; background: var(--wash); border-radius: 9px; padding: 3px; }
.segmented button {
  appearance: none; border: 0; background: transparent; cursor: pointer;
  font: inherit; font-size: 13px; color: var(--ink-2);
  padding: 6px 13px; border-radius: 7px; min-height: 32px;
}
.segmented button:hover { color: var(--ink); }
.segmented button.is-on { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,.08); }
.segmented button:focus-visible { outline: 2px solid var(--series-1); outline-offset: 1px; }

.check { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink-2); cursor: pointer; min-height: 32px; }
.check input { width: 15px; height: 15px; accent-color: var(--series-3); cursor: pointer; margin: 0; }
.check:hover { color: var(--ink); }

/* hidden 속성이 display 선언에 지지 않도록 명시한다 */
.zoomchip[hidden] { display: none; }
.zoomchip {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12.5px; color: var(--ink-2); background: var(--wash);
  border-radius: 7px; padding: 4px 4px 4px 11px; font-variant-numeric: tabular-nums;
}
.zoomchip button {
  appearance: none; border: 0; background: none; cursor: pointer; font: inherit;
  color: var(--ink-muted); line-height: 1; padding: 5px 7px; border-radius: 5px;
}
.zoomchip button:hover { color: var(--ink); background: var(--surface); }
.zoomchip button:focus-visible { outline: 2px solid var(--series-1); outline-offset: 1px; }

.hint { margin: -6px 0 18px; font-size: 12.5px; color: var(--ink-muted); }
.hint b { color: var(--ink-2); font-weight: 600; }

.stack { display: flex; flex-direction: column; gap: 26px; }

.card {
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: 14px;
  padding: 24px 24px 18px;
}
.card-head { display: flex; flex-wrap: wrap; gap: 20px 32px; align-items: flex-start; justify-content: space-between; }
.card-head h2 { margin: 0 0 6px; font-size: 19px; letter-spacing: -.01em; }
.formula { margin: 0; font-size: 13px; color: var(--ink-2); }
.formula .op { color: var(--ink-muted); }
.note { margin: 10px 0 0; font-size: 13px; color: var(--ink-muted); max-width: 52ch; }

.hero { text-align: right; flex: 0 0 auto; }
.hero-val { font-size: clamp(30px, 5vw, 42px); font-weight: 660; line-height: 1.05; letter-spacing: -.025em; }
.hero-val .pct { font-size: .5em; font-weight: 500; color: var(--ink-2); margin-left: 3px; }
.hero-sub { font-size: 12.5px; color: var(--ink-muted); margin-top: 5px; }
.delta { font-weight: 600; }
.delta.pos { color: var(--up); }
.delta.neg { color: var(--down); }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 1px; margin: 20px 0 6px; background: var(--hairline); border-radius: 10px; overflow: hidden; }
.tile { background: var(--surface); padding: 11px 13px; }
.tile dt { font-size: 11.5px; color: var(--ink-muted); margin: 0 0 3px; }
.tile dd { margin: 0; font-size: 16px; font-weight: 600; }
.tile dd small { display: block; font-size: 11px; font-weight: 400; color: var(--ink-muted); margin-top: 1px; }

.viewtabs { display: flex; gap: 14px; margin: 18px 0 4px; border-bottom: 1px solid var(--hairline); }
.viewtabs button {
  appearance: none; border: 0; background: none; cursor: pointer; font: inherit;
  font-size: 13px; color: var(--ink-muted); padding: 7px 1px 9px; min-height: 32px;
  border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.viewtabs button.is-on { color: var(--ink); font-weight: 600; border-bottom-color: currentColor; }
.viewtabs button:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; border-radius: 4px; }

.legend { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin: 12px 0 0; font-size: 12px; color: var(--ink-muted); }
.legend .swatch { display: inline-block; width: 15px; height: 2px; border-radius: 1px; }
.legend .swatch.dashed { height: 0; background: none; }
.legend .gap { width: 8px; }
.legend .dim { opacity: .72; }
.caveat { margin: 8px 0 0; font-size: 11.5px; line-height: 1.5; color: var(--ink-muted); max-width: 66ch; }
.card.is-table .caveat { display: none; }
/* KOSPI 를 끄면 오른쪽 축이 사라지므로 그에 딸린 범례·주의문도 함께 감춘다 */
.card.no-kospi .caveat, .card.no-kospi .k-item { display: none; }
.card.is-table .legend { display: none; }

.plotwrap { position: relative; margin-top: 8px; touch-action: pan-y; }
.plotwrap svg { display: block; width: 100%; height: auto; touch-action: pan-y; }
/* 확대 중일 때만 끌 수 있다 */
.card.zoomed .plotwrap { cursor: grab; }
/* .card.zoomed .plotwrap 보다 특이도가 높아야 커서가 바뀐다 */
.card.zoomed .plotwrap.is-panning, .plotwrap.is-panning { cursor: grabbing; user-select: none; }
.plotwrap.is-panning svg { pointer-events: none; }
.plotwrap svg:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; border-radius: 6px; }

.tip {
  position: absolute; pointer-events: none; opacity: 0; transform: translate(-50%, -100%);
  background: var(--surface); border: 1px solid var(--hairline); border-radius: 9px;
  padding: 9px 11px; font-size: 12.5px; line-height: 1.45; white-space: nowrap;
  box-shadow: 0 6px 20px rgba(0,0,0,.13); transition: opacity .1s linear; z-index: 4;
}
.tip.is-on { opacity: 1; }
.tip-date { color: var(--ink-muted); font-size: 11.5px; margin-bottom: 3px; }
.tip-main { font-weight: 660; font-size: 15px; }
.tip-rows { margin: 5px 0 0; padding: 5px 0 0; border-top: 1px solid var(--hairline); color: var(--ink-2); }
.tip-rows div { display: flex; justify-content: space-between; gap: 16px; font-variant-numeric: tabular-nums; }
.tip-flag { margin-top: 4px; color: var(--ink-muted); font-size: 11.5px; }

.tablewrap { display: none; max-height: 420px; overflow: auto; margin-top: 12px; border: 1px solid var(--hairline); border-radius: 10px; }
.card.is-table .tablewrap { display: block; }
.card.is-table .plotwrap { display: none; }
table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { padding: 7px 12px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { position: sticky; top: 0; background: var(--surface); color: var(--ink-2); font-weight: 600; text-align: right; box-shadow: inset 0 -1px 0 var(--axis); }
th:first-child, td:first-child { text-align: left; }
tbody tr:last-child td { border-bottom: 0; }
td.prov { color: var(--ink-muted); }
.tablenote { margin: 0; padding: 8px 12px; font-size: 12px; color: var(--ink-muted); border-top: 1px solid var(--grid); background: var(--surface); position: sticky; bottom: 0; }

.footnotes { margin-top: 44px; padding-top: 22px; border-top: 1px solid var(--hairline); }
.footnotes h2 { font-size: 13px; letter-spacing: .04em; text-transform: uppercase; color: var(--ink-muted); margin: 0 0 12px; font-weight: 650; }
.footnotes ul { margin: 0; padding-left: 18px; color: var(--ink-2); font-size: 13px; }
.footnotes li { margin-bottom: 7px; }
.footnotes b { color: var(--ink); font-weight: 600; }

@media (max-width: 620px) {
  .page { padding: 32px 15px 56px; }
  .card { padding: 18px 15px 14px; border-radius: 12px; }
  .card-head { gap: 14px; }
  .hero { text-align: left; }
}
"""


JS = r"""
(function () {
  "use strict";
  var P = JSON.parse(document.getElementById("payload").textContent);
  var charts = P.charts;
  var rangeDays = 0;            /* 기간 프리셋 (0 = 전체) */
  var zoomWin = null;           /* 휠로 좁힌 창 {a, b} — 날짜 일련값 */
  var showKospi = true;
  var ZOOM_STEP = 0.78;         /* 휠 한 칸당 창 배율 */
  var MIN_SPAN = 20;            /* 최소 창 너비(일). 영업일 14일쯤 */

  function fmt(v, d) { return v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function dateLabel(t) { return t.slice(0, 4) + "." + t.slice(4, 6) + "." + t.slice(6, 8); }
  function ordOf(t) { return Date.UTC(+t.slice(0, 4), +t.slice(4, 6) - 1, +t.slice(6, 8)) / 86400000; }

  var asof = charts[0].points[charts[0].points.length - 1][0];
  document.getElementById("asof").textContent = dateLabel(asof);

  /* 자동 갱신이 멈췄는지 보는 이가 알 수 있게 — 자료일이 너무 오래됐으면 알린다 */
  (function () {
    var now = new Date();
    var days = Math.floor(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / 86400000) - ordOf(asof);
    if (days <= 5) return;
    var el = document.getElementById("stale");
    el.innerHTML = "⚠ 최신 자료일이 <b>" + dateLabel(asof) + "</b>로, " + days +
      "일 전입니다. 자동 갱신이 멈췄거나 자료원 공표가 지연된 상태일 수 있습니다.";
    el.hidden = false;
  })();

  /* ---------- 카드 마크업 ---------- */
  var cards = document.getElementById("cards");
  charts.forEach(function (c) {
    var s = c.stats, d = c.digits;
    var sign = s.delta > 0 ? "pos" : (s.delta < 0 ? "neg" : "");
    var arrow = s.delta > 0 ? "▲" : (s.delta < 0 ? "▼" : "–");
    var el = document.createElement("section");
    el.className = "card";
    el.id = "card-" + c.id;
    el.innerHTML =
      '<div class="card-head">' +
        '<div>' +
          '<p class="eyebrow">' + c.eyebrow + '</p>' +
          '<h2>' + c.title + '</h2>' +
          '<p class="formula">' + c.formula + '</p>' +
          '<p class="note">' + c.note + '</p>' +
        '</div>' +
        '<div class="hero">' +
          '<div class="hero-val">' + fmt(s.cur, d) + '<span class="pct">%</span></div>' +
          '<div class="hero-sub">' + dateLabel(s.curDate) + ' · 전일대비 ' +
            '<span class="delta ' + sign + '">' + arrow + ' ' + fmt(Math.abs(s.delta), d) + 'p</span></div>' +
        '</div>' +
      '</div>' +
      '<dl class="tiles">' +
        '<div class="tile"><dt>3년 평균</dt><dd>' + fmt(s.avg, d) + '%</dd></div>' +
        '<div class="tile"><dt>3년 최고</dt><dd>' + fmt(s.max, d) + '%<small>' + dateLabel(s.maxDate) + '</small></dd></div>' +
        '<div class="tile"><dt>3년 최저</dt><dd>' + fmt(s.min, d) + '%<small>' + dateLabel(s.minDate) + '</small></dd></div>' +
        '<div class="tile"><dt>3년 백분위</dt><dd>' + Math.round(s.pct) + '<small>0 = 최저, 100 = 최고</small></dd></div>' +
      '</dl>' +
      '<div class="viewtabs" role="tablist">' +
        '<button type="button" class="is-on" data-view="chart" role="tab" aria-selected="true">차트</button>' +
        '<button type="button" data-view="table" role="tab" aria-selected="false">표로 보기</button>' +
      '</div>' +
      '<div class="legend">' +
        '<span class="swatch" style="background:var(--series-' + c.color + ');opacity:.35"></span>일별' +
        '<span class="gap"></span>' +
        '<span class="swatch" style="background:var(--series-' + c.color + ')"></span>5영업일 이동평균' +
        (c.provFrom == null ? '' :
          '<span class="gap"></span><span class="swatch dashed" style="border-top:2px dashed var(--series-' +
          c.color + ')"></span>M2 미공표 구간 · 잠정') +
        '<span class="gap"></span><span class="swatch" style="background:var(--axis)"></span>' +
        '<span class="avgval">기간 평균</span>' +
        '<span class="k-item"><span class="gap"></span>' +
          '<span class="swatch" style="background:var(--series-3)"></span>' +
          'KOSPI 지수 <span class="dim">(오른쪽 축)</span></span>' +
      '</div>' +
      '<p class="caveat">두 축의 높이를 맞추는 방식은 임의입니다. 선이 만나거나 교차하는 지점에는 ' +
        '의미가 없으니, 모양과 전환점만 비교해서 보세요.</p>' +
      '<div class="plotwrap"><div class="tip" role="status" aria-live="polite"></div></div>' +
      '<div class="tablewrap"></div>';
    cards.appendChild(el);

    el.querySelectorAll(".viewtabs button").forEach(function (b) {
      b.addEventListener("click", function () {
        el.querySelectorAll(".viewtabs button").forEach(function (o) {
          var on = o === b;
          o.classList.toggle("is-on", on);
          o.setAttribute("aria-selected", on ? "true" : "false");
        });
        el.classList.toggle("is-table", b.dataset.view === "table");
        if (b.dataset.view === "chart") drawOne(c);
      });
    });
    buildTable(c, el.querySelector(".tablewrap"));
    setupPan(el);
  });

  /* 확대 상태에서 좌우로 끌어 구간을 옮긴다.
     핸들러는 .plotwrap 에 한 번만 붙인다 — 다시 그릴 때마다 svg 는 교체되므로
     svg 에 붙이면 이동 중에 드래그가 끊긴다. */
  function setupPan(card) {
    var wrap = card.querySelector(".plotwrap");
    var pan = null;
    function svgUnitX(clientX) {
      var g = card._geom, r = wrap.getBoundingClientRect();
      return (clientX - r.left) / r.width * g.W;
    }
    wrap.addEventListener("pointerdown", function (e) {
      if (!zoomWin || !card._geom) return;
      if (e.pointerType === "mouse" && e.button !== 0) return;
      var g = card._geom, x = svgUnitX(e.clientX);
      if (x < g.ml || x > g.ml + g.iw) return;          /* 플롯 밖은 그냥 둔다 */
      e.preventDefault();
      var w = windowNow();
      pan = { x: x, a: w.a, b: w.b };
      wrap.classList.add("is-panning");
      try { wrap.setPointerCapture(e.pointerId); } catch (_) {}
    });
    wrap.addEventListener("pointermove", function (e) {
      if (!pan || !card._geom) return;
      var g = card._geom;
      /* 오른쪽으로 끌면 과거로 — 그림이 손을 따라온다 */
      var days = (svgUnitX(e.clientX) - pan.x) / g.iw * (pan.b - pan.a);
      shiftWindow(pan.a - days, pan.b - days);
    });
    function stop(e) {
      if (!pan) return;
      pan = null;
      wrap.classList.remove("is-panning");
      try { wrap.releasePointerCapture(e.pointerId); } catch (_) {}
    }
    wrap.addEventListener("pointerup", stop);
    wrap.addEventListener("pointercancel", stop);
  }

  /* ---------- 표 ---------- */
  function buildTable(c, host) {
    var rows = c.points.slice().reverse();
    var html = '<table><thead><tr><th scope="col">일자</th><th scope="col">비율 (%)</th>' +
      '<th scope="col">' + c.numLabel + ' (조원)</th><th scope="col">' + c.denLabel + ' (조원)</th>' +
      '<th scope="col">KOSPI 지수</th></tr></thead><tbody>';
    var provStart = c.provFrom == null ? Infinity : c.provFrom;
    for (var i = 0; i < rows.length; i++) {
      var p = rows[i];
      var isProv = (c.points.length - 1 - i) >= provStart;
      html += '<tr><th scope="row" style="text-align:left;font-weight:400;position:static;background:none;box-shadow:none">' +
        dateLabel(p[0]) + '</th>' +
        '<td' + (isProv ? ' class="prov"' : '') + '>' + fmt(p[1], c.digits) + (isProv ? ' *' : '') + '</td>' +
        '<td>' + fmt(p[2], p[2] < 100 ? 2 : 1) + '</td>' +
        '<td>' + fmt(p[3], 0) + '</td>' +
        '<td>' + (p[4] == null ? '–' : fmt(p[4], 2)) + '</td></tr>';
    }
    html += '</tbody></table>';
    if (c.provFrom != null) html += '<p class="tablenote">* M2 미공표 구간 · 잠정 계산</p>';
    host.innerHTML = html;
  }

  /* ---------- 차트 ---------- */
  var SVGNS = "http://www.w3.org/2000/svg";
  function mk(n, a) { var e = document.createElementNS(SVGNS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }

  function niceTicks(lo, hi, want) {
    var span = hi - lo; if (span <= 0) span = Math.abs(hi) || 1;
    var raw = span / want, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
    var step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
    var out = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  /* 창(window) 계산 — 프리셋이 바깥 한계, 휠 확대는 그 안에서만 움직인다 */
  function fullWindow() {
    var lo = Infinity, hi = -Infinity;
    charts.forEach(function (c) {
      lo = Math.min(lo, ordOf(c.points[0][0]));
      hi = Math.max(hi, ordOf(c.points[c.points.length - 1][0]));
    });
    return { a: lo, b: hi };
  }
  function baseWindow() {
    var f = fullWindow();
    return rangeDays ? { a: Math.max(f.a, f.b - rangeDays), b: f.b } : f;
  }
  function windowNow() { return zoomWin || baseWindow(); }

  function visible(c) {
    var w = windowNow();
    return c.points.filter(function (p) {
      var o = ordOf(p[0]);
      return o >= w.a && o <= w.b;
    });
  }

  function ymdOf(ord) {
    var d = new Date(Math.round(ord) * 86400000);
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return "" + d.getUTCFullYear() + p(d.getUTCMonth() + 1) + p(d.getUTCDate());
  }

  /* 창을 적용한다. 어느 차트든 점이 5개 미만 남으면 무시한다. */
  function setWindow(a, b) {
    var base = baseWindow();
    a = Math.max(base.a, a);
    b = Math.min(base.b, b);
    if (b - a < MIN_SPAN - 0.5) return false;
    var ok = charts.every(function (c) {
      return c.points.filter(function (p) {
        var o = ordOf(p[0]); return o >= a && o <= b;
      }).length >= 5;
    });
    if (!ok) return false;
    zoomWin = (b - a >= base.b - base.a - 0.5) ? null : { a: a, b: b };
    renderZoomChip();
    drawAll();
    return true;
  }

  function clearZoom() {
    if (!zoomWin) return;
    zoomWin = null;
    renderZoomChip();
    drawAll();
  }

  /* 확대 창을 같은 너비로 좌우로 민다. 바깥 한계에 닿으면 거기서 멈춘다. */
  function shiftWindow(a, b) {
    var base = baseWindow(), span = b - a;
    if (a < base.a) { a = base.a; b = a + span; }
    if (b > base.b) { b = base.b; a = b - span; }
    zoomWin = { a: a, b: b };
    renderZoomChip();
    drawAllSoon();
  }

  /* 이동 중에는 프레임마다 한 번만 다시 그린다 */
  var rafPending = false;
  function drawAllSoon() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () { rafPending = false; drawAll(); });
  }

  function renderZoomChip() {
    /* 확대 중일 때만 손 모양 커서를 준다 — 끌 수 있다는 신호 */
    charts.forEach(function (c) {
      var el = document.getElementById("card-" + c.id);
      if (el) el.classList.toggle("zoomed", !!zoomWin);
    });
    var el = document.getElementById("zoomChip");
    if (!zoomWin) { el.hidden = true; el.textContent = ""; return; }
    el.hidden = false;
    el.textContent = "확대 " + dateLabel(ymdOf(zoomWin.a)) + " ~ " + dateLabel(ymdOf(zoomWin.b)) + " ";
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = "✕";
    b.setAttribute("aria-label", "확대 해제");
    b.addEventListener("click", clearZoom);
    el.appendChild(b);
  }

  function drawOne(c) {
    var card = document.getElementById("card-" + c.id);
    var wrap = card.querySelector(".plotwrap");
    var tip = wrap.querySelector(".tip");
    var old = wrap.querySelector("svg");
    if (old) old.remove();

    var pts = visible(c);
    if (pts.length < 2) return;

    /* KOSPI 지수가 있는 날짜. 체크를 끄면 오른쪽 축과 함께 사라진다. */
    var kIdx = [];
    for (var q = 0; q < pts.length; q++) { if (pts[q][4] != null) kIdx.push(q); }
    var hasK = showKospi && kIdx.length >= 2;

    var W = Math.max(320, wrap.clientWidth || 640);
    var H = Math.max(250, Math.min(370, Math.round(W * 0.46)));
    var m = { t: 26, r: hasK ? 58 : 16, b: 28, l: 52 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var col = "var(--series-" + c.color + ")";
    var colK = "var(--series-3)";

    var vals = pts.map(function (p) { return p[1]; });
    var o0 = ordOf(pts[0][0]), o1 = ordOf(pts[pts.length - 1][0]);
    var X = function (i) { return m.l + (ordOf(pts[i][0]) - o0) / (o1 - o0) * iw; };

    /* 값 범위에 여유를 둔 스케일. 두 계열이 같은 그림에 겹치므로 축은 둘이다. */
    function scaleOf(arr) {
      var lo = Math.min.apply(null, arr), hi = Math.max.apply(null, arr);
      var pad = (hi - lo) * 0.14 || Math.abs(hi) * 0.05 || 1;
      var a = lo - pad, b = hi + pad;
      return { lo: a, hi: b, y: function (v) { return m.t + (b - v) / (b - a) * ih; } };
    }
    var A = scaleOf(vals);
    var kvals = kIdx.map(function (i) { return pts[i][4]; });
    var B = hasK ? scaleOf(kvals) : null;

    var svg = mk("svg", {
      viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", tabindex: "0",
      "aria-label": c.title + " 추이와 KOSPI 지수를 겹쳐 그린 차트. " + dateLabel(pts[0][0]) + "부터 " +
        dateLabel(pts[pts.length - 1][0]) + "까지. 최근값 " + fmt(c.stats.cur, c.digits) + "%" +
        (hasK ? ", 같은 날 KOSPI " + fmt(kvals[kvals.length - 1], 2) +
                ". 두 축의 높이 맞춤은 임의이므로 선이 만나는 지점에는 의미가 없습니다." : ".")
    });

    /* 왼쪽 축 — 격자선은 이쪽만 그린다 (양쪽 다 그리면 격자가 두 겹이 된다) */
    niceTicks(A.lo, A.hi, 5).forEach(function (v) {
      var y = A.y(v);
      svg.appendChild(mk("line", { x1: m.l, x2: m.l + iw, y1: y, y2: y,
        stroke: "var(--grid)", "stroke-width": 1 }));
      var tx = mk("text", { x: m.l - 9, y: y + 4, "text-anchor": "end", fill: "var(--ink-muted)",
        "font-size": 11, "font-variant-numeric": "tabular-nums" });
      tx.textContent = fmt(v, c.digits);
      svg.appendChild(tx);
    });

    /* 오른쪽 축 — KOSPI. 격자 대신 짧은 눈금선으로 축에 붙인다 */
    if (hasK) {
      niceTicks(B.lo, B.hi, 5).forEach(function (v) {
        var y = B.y(v);
        svg.appendChild(mk("line", { x1: m.l + iw, x2: m.l + iw + 4, y1: y, y2: y,
          stroke: "var(--axis)", "stroke-width": 1 }));
        var tx = mk("text", { x: m.l + iw + 8, y: y + 4, "text-anchor": "start", fill: "var(--ink-muted)",
          "font-size": 11, "font-variant-numeric": "tabular-nums" });
        tx.textContent = fmt(v, 0);
        svg.appendChild(tx);
      });
    }
    svg.appendChild(mk("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih,
      stroke: "var(--axis)", "stroke-width": 1 }));

    /* 축 이름 — 어느 선이 어느 축인지 잇는다.
       색은 앞뒤의 선 표식이 지고, 글자는 잉크 색을 쓴다.
       표식은 각 축 바깐쪽(왼쪽 이름은 왼편, 오른쪽 이름은 오른편)에 두어 글자와 겹치지 않는다. */
    function axisName(x, side, name, stroke) {
      var sw = 13, pad = 5;
      var lx = side === "right" ? x + 4 : x;
      svg.appendChild(mk("line", { x1: lx, x2: lx + sw, y1: m.t - 13, y2: m.t - 13,
        stroke: stroke, "stroke-width": 2, "stroke-linecap": "round" }));
      var tx = mk("text", { y: m.t - 9, fill: "var(--ink-muted)", "font-size": 11,
        x: side === "right" ? x : x + sw + pad,
        "text-anchor": side === "right" ? "end" : "start" });
      tx.textContent = name;
      svg.appendChild(tx);
    }
    axisName(m.l, "left", c.title + " (%)", col);
    if (hasK) axisName(m.l + iw, "right", "KOSPI 지수", colK);

    /* x 눈금 — 보이는 구간 길이에 맞춘다 (확대하면 월.일까지) */
    var spanDays = o1 - o0;
    var shortSpan = spanDays <= 120;
    var seen = {}, xt = [];
    pts.forEach(function (p, i) {
      var key = shortSpan ? p[0]
              : (spanDays <= 400 ? p[0].slice(0, 6)
                                 : p[0].slice(0, 4) + Math.ceil(+p[0].slice(4, 6) / 6));
      if (!seen[key]) { seen[key] = 1; xt.push(i); }
    });
    if (xt.length > 8) xt = xt.filter(function (_, k) { return k % Math.ceil(xt.length / 8) === 0; });
    xt.forEach(function (i) {
      var t = pts[i][0];
      var tx = mk("text", { x: X(i), y: H - 9, "text-anchor": "middle", fill: "var(--ink-muted)",
        "font-size": 11, "font-variant-numeric": "tabular-nums" });
      tx.textContent = shortSpan ? t.slice(4, 6) + "." + t.slice(6, 8)
                                 : t.slice(2, 4) + "." + t.slice(4, 6);
      svg.appendChild(tx);
    });

    /* 기간 평균 기준선 — 값은 범례와 타일이 말해준다 */
    var avg = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
    if (avg > A.lo && avg < A.hi) {
      svg.appendChild(mk("line", { x1: m.l, x2: m.l + iw, y1: A.y(avg), y2: A.y(avg),
        stroke: "var(--axis)", "stroke-width": 1 }));
    }
    card.querySelector(".legend .avgval").textContent = "기간 평균 " + fmt(avg, c.digits) + "%";

    /* 5영업일 이동평균 */
    var ma = vals.map(function (_, i) {
      var a = Math.max(0, i - 4), n = i - a + 1, s = 0;
      for (var k = a; k <= i; k++) s += vals[k];
      return s / n;
    });

    /* 잠정(M2 미공표) 구간 시작 */
    var provIdx = null;
    if (c.provFrom != null) {
      var provDate = c.points[c.provFrom][0];
      for (var k = 0; k < pts.length; k++) { if (pts[k][0] >= provDate) { provIdx = k; break; } }
    }
    var cut = provIdx == null ? pts.length - 1 : Math.max(0, provIdx - 1);

    function pathOf(idxs, valOf, sc) {
      var s = "";
      for (var k = 0; k < idxs.length; k++) {
        var i = idxs[k];
        s += (k === 0 ? "M" : "L") + X(i).toFixed(1) + " " + sc.y(valOf(i)).toFixed(1);
      }
      return s;
    }
    function span(a, b) { var r = []; for (var i = a; i <= b; i++) r.push(i); return r; }
    function draw(d, stroke, width, opts) {
      var at = { d: d, fill: "none", stroke: stroke, "stroke-width": width,
                 "stroke-linejoin": "round", "stroke-linecap": "round" };
      for (var k in (opts || {})) at[k] = opts[k];
      svg.appendChild(mk("path", at));
    }

    /* --- KOSPI 지수 (뒤에 깔린다) --- */
    if (hasK) {
      draw(pathOf(kIdx, function (i) { return pts[i][4]; }, B), colK, 1.75);
      endLabel(B, kIdx[kIdx.length - 1], kvals[kvals.length - 1], 0, "", colK);
    }

    /* --- 비율 (앞에 온다) --- */
    var all = span(0, pts.length - 1);
    draw(pathOf(all, function (i) { return vals[i]; }, A), col, 1.25, { opacity: 0.3 });
    draw(pathOf(span(0, cut), function (i) { return ma[i]; }, A), col, 2.25);
    if (provIdx != null && cut < pts.length - 1) {
      draw(pathOf(span(cut, pts.length - 1), function (i) { return ma[i]; }, A), col, 2.25,
           { "stroke-dasharray": "4 3" });
    }
    endLabel(A, pts.length - 1, vals[vals.length - 1], c.digits, "%", col);

    /* 겹친 선끼리 붙어 보이지 않게 끝점 표식에 배경색 링을 두른다 */
    function endLabel(sc, i, v, digits, suffix, stroke) {
      var x = X(i), y = sc.y(v);
      svg.appendChild(mk("circle", { cx: x, cy: y, r: 4.5, fill: stroke,
        stroke: "var(--surface)", "stroke-width": 2 }));
      var lbl = mk("text", { x: x - 8, y: y - 9, "text-anchor": "end", fill: "var(--ink)",
        "font-size": 12, "font-weight": 650 });
      lbl.textContent = fmt(v, digits) + suffix;
      svg.appendChild(lbl);
    }

    /* 호버 레이어 — 십자선 하나가 두 계열을 함께 가리킨다 */
    var cross = mk("line", { y1: m.t, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1, opacity: 0 });
    var dotA = mk("circle", { r: 5, fill: col, stroke: "var(--surface)", "stroke-width": 2, opacity: 0 });
    var dotB = mk("circle", { r: 5, fill: colK, stroke: "var(--surface)", "stroke-width": 2, opacity: 0 });
    svg.appendChild(cross); svg.appendChild(dotA); svg.appendChild(dotB);
    svg.appendChild(mk("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" }));

    var cur = -1;
    function focus(i) {
      if (i < 0 || i >= pts.length) return;
      cur = i;
      var p = pts[i], x = X(i), y = A.y(p[1]);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("opacity", 1);
      dotA.setAttribute("cx", x); dotA.setAttribute("cy", y); dotA.setAttribute("opacity", 1);
      if (hasK && p[4] != null) {
        dotB.setAttribute("cx", x); dotB.setAttribute("cy", B.y(p[4])); dotB.setAttribute("opacity", 1);
      } else {
        dotB.setAttribute("opacity", 0);
      }
      var isProv = provIdx != null && i >= provIdx;
      tip.innerHTML =
        '<div class="tip-date">' + dateLabel(p[0]) + '</div>' +
        '<div class="tip-main">' + fmt(p[1], c.digits) + '%</div>' +
        '<div class="tip-rows">' +
          '<div><span>' + c.numLabel + '</span><span>' + fmt(p[2], p[2] < 100 ? 2 : 1) + '조</span></div>' +
          '<div><span>' + c.denLabel + '</span><span>' + fmt(p[3], 0) + '조</span></div>' +
          '<div><span>KOSPI</span><span>' + (p[4] == null ? '–' : fmt(p[4], 2)) + '</span></div>' +
        '</div>' +
        (isProv ? '<div class="tip-flag">M2 미공표 구간 · 잠정</div>' : '');
      tip.classList.add("is-on");
      var sc = wrap.clientWidth / W;
      tip.style.left = Math.min(Math.max(x * sc, 76), wrap.clientWidth - 76) + "px";
      tip.style.top = (y * sc - 12) + "px";
    }
    function blur() {
      cross.setAttribute("opacity", 0);
      dotA.setAttribute("opacity", 0);
      dotB.setAttribute("opacity", 0);
      tip.classList.remove("is-on");
    }

    function svgX(clientX) {
      var r = svg.getBoundingClientRect();
      return (clientX - r.left) / r.width * W;
    }
    function indexAt(x) {
      var target = o0 + (x - m.l) / iw * (o1 - o0);
      var best = 0, bd = Infinity;
      for (var i = 0; i < pts.length; i++) {
        var d = Math.abs(ordOf(pts[i][0]) - target);
        if (d < bd) { bd = d; best = i; }
      }
      return best;
    }

    svg.addEventListener("pointermove", function (e) {
      if (wrap.classList.contains("is-panning")) return;   /* 끌고 있을 때는 십자선을 쉬게 둔다 */
      focus(indexAt(svgX(e.clientX)));
    });
    svg.addEventListener("pointerleave", blur);
    svg.addEventListener("dblclick", clearZoom);

    /* 마우스 휠로 확대·축소. 커서 밑 날짜를 붙잡고 창을 좁히거나 넓힌다.
       한계에 닿았으면 preventDefault 하지 않고 넘겨서 페이지 스크롤을 막지 않는다. */
    svg.addEventListener("wheel", function (e) {
      if (!e.deltaY) return;
      var base = baseWindow(), cur = windowNow();

      /* Shift + 휠 = 좌우 이동 */
      if (e.shiftKey && zoomWin) {
        var sp = cur.b - cur.a, step = sp * 0.08 * (e.deltaY > 0 ? 1 : -1);
        if (step > 0 && cur.b >= base.b - 0.5) return;
        if (step < 0 && cur.a <= base.a + 0.5) return;
        e.preventDefault();
        blur();
        shiftWindow(cur.a + step, cur.b + step);
        return;
      }

      var spanNow = cur.b - cur.a;
      var maxSpan = base.b - base.a;
      var want = spanNow * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);

      /* 더 넓힐 수도, 더 좁힐 수도 없으면 휠은 페이지 몫이다 */
      if (want >= spanNow && spanNow >= maxSpan - 0.5) return;
      if (want <= spanNow && spanNow <= MIN_SPAN + 0.5) return;
      e.preventDefault();

      var span = Math.max(MIN_SPAN, Math.min(maxSpan, want));
      var frac = Math.max(0, Math.min(1, (svgX(e.clientX) - m.l) / iw));
      var anchor = cur.a + spanNow * frac;          /* 커서가 가리키는 날짜 */
      var a = anchor - span * frac;
      if (a < base.a) a = base.a;
      if (a + span > base.b) a = base.b - span;
      setWindow(a, a + span);
    }, { passive: false });

    svg.addEventListener("focus", function () { focus(cur < 0 ? pts.length - 1 : cur); });
    svg.addEventListener("blur", blur);
    svg.addEventListener("keydown", function (e) {
      var step = e.shiftKey ? 20 : 1;
      if (e.key === "ArrowLeft") { focus(Math.max(0, (cur < 0 ? pts.length - 1 : cur) - step)); e.preventDefault(); }
      else if (e.key === "ArrowRight") { focus(Math.min(pts.length - 1, (cur < 0 ? pts.length - 1 : cur) + step)); e.preventDefault(); }
      else if (e.key === "Home") { focus(0); e.preventDefault(); }
      else if (e.key === "End") { focus(pts.length - 1); e.preventDefault(); }
      /* 휠이 없어도 확대할 수 있게 — 지금 보이는 위치를 중심으로 좁히고 넓힌다 */
      else if (e.key === "+" || e.key === "=") { zoomKey(ZOOM_STEP); e.preventDefault(); }
      else if (e.key === "-" || e.key === "_") { zoomKey(1 / ZOOM_STEP); e.preventDefault(); }
      /* 확대 중이면 Esc 로 해제, 아니면 십자선만 숨긴다 */
      else if (e.key === "Escape") { if (zoomWin) { clearZoom(); } else { blur(); } }
    });

    function zoomKey(factor) {
      var base = baseWindow(), cur = windowNow();
      var spanNow = cur.b - cur.a;
      var span = Math.max(MIN_SPAN, Math.min(base.b - base.a, spanNow * factor));
      var mid = cur.a + spanNow / 2;
      var a = Math.max(base.a, Math.min(base.b - span, mid - span / 2));
      setWindow(a, a + span);
    }

    /* 이동 핸들러가 현재 플롯 영역을 알 수 있게 남겨둔다 */
    card._geom = { W: W, ml: m.l, iw: iw };

    wrap.insertBefore(svg, tip);
  }

  function drawAll() { charts.forEach(function (c) { if (!document.getElementById("card-" + c.id).classList.contains("is-table")) drawOne(c); }); }

  document.querySelectorAll("#rangeCtl button").forEach(function (b) {
    b.addEventListener("click", function () {
      rangeDays = +b.dataset.days;
      zoom = null;                       /* 프리셋을 고르면 확대는 풀린다 */
      renderZoomChip();
      document.querySelectorAll("#rangeCtl button").forEach(function (o) {
        var on = o === b;
        o.classList.toggle("is-on", on);
        o.setAttribute("aria-pressed", on ? "true" : "false");
      });
      drawAll();
    });
  });

  document.getElementById("kospiCtl").addEventListener("change", function () {
    showKospi = this.checked;
    charts.forEach(function (c) {
      document.getElementById("card-" + c.id).classList.toggle("no-kospi", !showKospi);
    });
    drawAll();
  });

  drawAll();
  var rt;
  window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(drawAll, 120); });
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(drawAll);
  }
})();
"""


def main():
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    head, body = render(data)

    standalone = ('<!doctype html>\n<html lang="ko">\n<head>\n'
                  '<meta charset="utf-8">\n'
                  '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                  + head + "\n</head>\n<body>\n" + body + "</body>\n</html>\n")
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(standalone)
    with open(os.path.join(HERE, "artifact.html"), "w", encoding="utf-8") as f:
        f.write(head + "\n" + body)
    print("index.html / artifact.html 생성 완료")


if __name__ == "__main__":
    main()
