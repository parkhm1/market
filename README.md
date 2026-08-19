# 한국 증시 유동성 지표

두 지표를 최근 3년 일별로 그리는 페이지.

1. **시가총액 대비 고객예탁금** — 투자자예탁금 ÷ (KOSPI + KOSDAQ 시가총액)
2. **M2 대비 신용거래융자 잔고** — 신용거래융자 잔고 ÷ M2(광의통화, 말잔)

## 홈페이지로 올리기 — 방법 A: Streamlit Community Cloud (추천)

접속할 때마다 원자료를 확인하므로 **따로 예약 실행을 걸 필요가 없다.**
같은 자료를 반복해 받지 않도록 1시간 캐시가 걸려 있고, 화면의 `지금 다시 받기` 로 즉시 새로 받을 수 있다.

1. GitHub 공개 저장소에 아래 6개 파일을 올린다.

   `app.py` · `fetch_data.py` · `build_site.py` · `requirements.txt` · `data.json` · `README.md`

   저장소 화면에서 **Add file → Upload files** 로 끌어다 놓으면 된다 (git 인증 필요 없음).
   git 으로 올릴 거면:

   ```bash
   git remote add origin https://github.com/<사용자명>/<저장소명>.git
   git push -u origin main
   ```

2. [share.streamlit.io](https://share.streamlit.io) → **Create app** → 저장소 선택,
   **Main file path** 에 `app.py` 입력 → **Deploy**

3. (선택) 앱 설정 **Settings → Secrets** 에 한 줄 추가:

   ```toml
   ECOS_API_KEY = "발급받은키"
   ```

   넣지 않으면 한국은행 공개 `sample` 키로 동작한다. M2 는 월별 30여 건이라 문제없다.

주소는 `https://<앱이름>.streamlit.app` 이 된다.

## 방법 B: GitHub Pages (정적 배포)

`.github/workflows/update.yml` 이 매일 09:30 / 17:30 KST 에 원자료를 받아 `index.html` 을
만들고 Pages 로 배포한다. 방법 A 를 쓸 거면 이 워크플로는 지워도 된다.

저장소 설정에서:

1. **Settings → Pages → Source** 를 **GitHub Actions** 로
2. **Settings → Actions → General → Workflow permissions** 를 **Read and write** 로
3. (선택) **Settings → Secrets and variables → Actions** 에 `ECOS_API_KEY`

주소는 `https://<사용자명>.github.io/<저장소명>/`.

## 구성

| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit 엔트리 포인트. 접속 시 수집 → 같은 화면을 iframe 으로 렌더 |
| `fetch_data.py` | 금융투자협회 FreeSIS(일별) + 한국은행 ECOS(월별) 수집. `collect()` 는 dict 반환, 단독 실행하면 `data.json` 저장 |
| `build_site.py` | 지표 계산 + 화면 생성. `render(data)` → (head, body). 단독 실행하면 `index.html` / `artifact.html` 저장 |
| `dart.py` | 전자공시(DART) 조회. 수주잔고·재무·공시목록. `DART_API_KEY` 필요 |
| `data.json` | 원자료 캐시. 커밋해 두므로 수집이 실패해도 직전 자료로 화면이 뜬다 |
| `update.ps1` | 윈도우에서 수동 갱신 (`index.html` 재생성) |
| `.github/workflows/update.yml` | 방법 B 용 워크플로 |

로컬 확인:

```bash
python -m streamlit run app.py
```

## 전자공시 조회

```bash
export DART_API_KEY=발급받은키          # https://opendart.fss.or.kr
python dart.py 프로텍 --order           # 수주상황 (수주총액·기납품액·수주잔고)
python dart.py 프로텍                   # 최근 2년 정기보고서 목록
python dart.py 프로텍 --fin 2026 --rpt 반기
```

인증키는 **환경변수로만** 넣는다. 이 저장소는 공개 저장소라 키를 파일에 적어 커밋하면 그대로 노출된다.
`.env.example` 을 `.env` 로 복사해 쓰는 방법도 있다 (`.env` 는 `.gitignore` 에 있다).

## 알아둘 것

- **FreeSIS 가 해외 IP 를 막는지는 확인되지 않았다.** Streamlit Cloud 와 GitHub Actions 는
  모두 해외 서버에서 돈다. 배포 후 첫 접속에서 자료가 안 나오면 이게 원인이다.
  그 경우 수집만 국내(이 PC 또는 국내 VPS)에서 돌리고 `data.json` 만 푸시하는 구조로 바꿔야 한다.
- FreeSIS 는 공개 API 계약이 아니다. 응답 형식이 바뀌면 `fetch_data.py` 의
  `OBJ_NM` / `TMPV*` 매핑을 다시 확인해야 한다 (`getSrvData.do` 메타데이터로 컬럼 순서 확인).
- M2 는 2~3개월 지연 공표된다. 월말값을 일별로 선형보간하고, 마지막 공표월 이후 구간은
  M2 를 고정한 잠정 계산이라 차트에서 점선으로 표시한다.
- 자료일이 5일 이상 밀리면 화면 상단에 경고가 뜬다.
- 투자 판단의 책임은 이용자에게 있다.
