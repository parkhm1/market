# -*- coding: utf-8 -*-
"""
Streamlit Community Cloud 용 엔트리 포인트 (Main file path: app.py).

접속할 때마다 원자료를 확인하므로 언제 어디서나 최신 상태가 나온다.
같은 자료를 반복해서 받지 않도록 1시간 캐시(@st.cache_data ttl=3600)를 둔다.
차트/레이아웃은 index.html 과 완전히 같은 코드(build_site.render)를 쓴다.
"""

import json
import os

import streamlit as st
import streamlit.components.v1 as components

import build_site
import fetch_data

HERE = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="한국 증시 유동성 지표", page_icon="📊", layout="wide")

# Streamlit 기본 여백/툴바를 걷어내 일반 웹페이지처럼 보이게 한다.
st.markdown("""
<style>
  header[data-testid="stHeader"] { display: none; }
  .block-container { padding: 0 !important; max-width: 100% !important; }
  footer { display: none; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner="원자료를 받고 있습니다…")
def fetch_fresh():
    """성공한 수집만 캐시한다. 예외가 나면 st.cache_data 는 캐시하지 않으므로 다음 접속에 다시 시도한다."""
    try:                                  # secrets.toml 이 없으면 예외가 난다
        if "ECOS_API_KEY" in st.secrets:
            os.environ["ECOS_API_KEY"] = str(st.secrets["ECOS_API_KEY"])
    except Exception:
        pass                              # 인증키 없이 공개 sample 키로 진행
    return fetch_data.collect()


def load_data():
    """원자료 수집. 실패하면 저장소에 커밋된 data.json 으로 대체한다."""
    try:
        return fetch_fresh(), None
    except Exception as exc:
        detail = getattr(exc, "detail", None) or "%s: %s" % (type(exc).__name__, exc)
        path = os.path.join(HERE, "data.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f), detail
        raise


data, warn = load_data()

if warn:
    st.warning("원자료를 받지 못해 저장된 직전 자료를 보여줍니다.", icon="⚠️")
    with st.expander("수집 실패 상세 (원문 포함)"):
        st.code(warn, language="text")

head, body = build_site.render(data)
components.html(head + body, height=2400, scrolling=True)

col1, col2 = st.columns([1, 4])
with col1:
    if st.button("지금 다시 받기", help="캐시를 비우고 원자료를 다시 받습니다"):
        fetch_fresh.clear()
        st.rerun()
with col2:
    st.caption("수집 코드 %s · 자료 %s"
               % (fetch_data.VERSION, data.get("fetched_at", "?")[:16].replace("T", " ")))
