# -*- coding: utf-8 -*-
"""
KOBIS(영화진흥위원회) 일별 박스오피스 스트림릿 앱
-----------------------------------------------
- 매일 '어제' 날짜(한국 시간 기준) 기준의 박스오피스를 보여줍니다.
- 인증키는 st.secrets["KOBIS_KEY"]에서 불러옵니다. (코드에는 절대 넣지 않음)
- 같은 날짜에 대한 결과는 1시간 동안 캐시해서, API를 불필요하게 여러 번 호출하지 않습니다.
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 기본 내장 모듈: 시간대 계산용

# -------------------------------------------------
# 1. 기본 설정
# -------------------------------------------------
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


def get_yesterday_kst() -> str:
    """
    '어제' 날짜를 한국 시간(KST) 기준으로 계산해서
    KOBIS API가 요구하는 형식인 'yyyymmdd' 문자열로 돌려줍니다.

    배포 서버(스트림릿 클라우드)의 시계는 한국 시간이 아닐 수 있으므로,
    반드시 ZoneInfo("Asia/Seoul")를 이용해 한국 시간을 직접 계산합니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


# -------------------------------------------------
# 2. API 호출 함수 (1시간 캐시)
# -------------------------------------------------
@st.cache_data(ttl=3600)  # 3600초 = 1시간 동안 같은 날짜에 대한 결과를 기억함
def fetch_box_office(target_dt: str):
    """
    KOBIS API를 호출해서 해당 날짜(target_dt, 'yyyymmdd')의
    일별 박스오피스 목록을 가져옵니다.

    반환값: (성공 여부, 영화 목록 또는 에러 메시지)
    """
    api_key = st.secrets.get("KOBIS_KEY")

    if not api_key:
        return False, "KOBIS_KEY가 비밀 금고(secrets)에 설정되어 있지 않습니다. Streamlit Cloud의 앱 설정(Settings) > Secrets 메뉴에서 KOBIS_KEY 값을 추가해 주세요."

    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    # --- 2-1. 네트워크 요청 자체가 실패하는 경우 (인터넷 문제, 타임아웃 등) ---
    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, f"KOBIS 서버에 요청을 보내는 데 실패했습니다. 인터넷 연결 상태나 방화벽 설정을 확인해 주세요. (상세 오류: {e})"

    # --- 2-2. 응답이 200이 아닌 경우 (서버 오류 등) ---
    if response.status_code != 200:
        return False, f"KOBIS 서버가 정상적으로 응답하지 않았습니다. (상태 코드: {response.status_code}) 잠시 후 다시 시도해 주세요."

    # --- 2-3. 응답이 JSON 형식이 아닌 경우 ---
    try:
        data = response.json()
    except ValueError:
        return False, "KOBIS 서버 응답을 해석할 수 없습니다(JSON 형식이 아님). API 주소나 요청 방식이 맞는지 확인해 주세요."

    # --- 2-4. 인증키가 틀린 경우: 상태코드는 200이지만 faultInfo가 옴 ---
    if "faultInfo" in data:
        fault = data["faultInfo"]
        message = fault.get("message", "알 수 없는 오류")
        return False, f"KOBIS API에서 오류를 반환했습니다: {message}. 인증키(KOBIS_KEY)가 올바른지 다시 확인해 주세요."

    # --- 2-5. 정상 응답이지만 구조가 예상과 다른 경우 ---
    box_office_result = data.get("boxOfficeResult")
    if box_office_result is None:
        return False, "KOBIS 응답에서 boxOfficeResult를 찾을 수 없습니다. API 응답 구조가 변경되었을 수 있습니다."

    movie_list = box_office_result.get("dailyBoxOfficeList")

    # --- 2-6. 영화 목록이 비어 있는 경우 (예: 너무 이른 날짜, 집계 전 날짜 등) ---
    if not movie_list:
        return False, "해당 날짜의 박스오피스 데이터가 비어 있습니다. 조회 날짜가 아직 집계되지 않았거나, 너무 오래된 날짜일 수 있습니다."

    return True, movie_list


# -------------------------------------------------
# 3. 데이터 가공: 문자열 숫자를 실제 숫자(int)로 변환
# -------------------------------------------------
def build_dataframe(movie_list: list) -> pd.DataFrame:
    """
    KOBIS API가 돌려주는 원본 리스트(dict들의 리스트)를
    보기 좋은 pandas DataFrame으로 바꿔줍니다.
    이때 API에서 문자열로 오는 숫자 필드들을 int로 변환합니다.
    """
    df = pd.DataFrame(movie_list)

    # 숫자로 바꿔야 하는 컬럼들 (원본은 전부 문자열로 온다고 문서에 명시되어 있음)
    numeric_columns = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_columns:
        if col in df.columns:
            # errors="coerce": 혹시 이상한 값이 섞여 있어도 앱이 죽지 않고 NaN 처리 후 0으로 채움
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


# -------------------------------------------------
# 4. 화면 그리기
# -------------------------------------------------
def main():
    st.title("🎬 어제의 박스오피스")

    target_dt = get_yesterday_kst()
    display_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
    st.caption(f"조회 기준일(한국 시간 기준 어제): {display_date}")

    with st.spinner("박스오피스 정보를 불러오는 중입니다..."):
        success, result = fetch_box_office(target_dt)

    # --- 실패한 경우: 빈 화면 대신 안내 메시지 표시 ---
    if not success:
        st.error(result)
        st.info("문제가 계속되면 KOBIS 공식 사이트(kobis.or.kr)에서 서비스 상태를 확인해 보세요.")
        return

    movie_list = result
    df = build_dataframe(movie_list)

    # rank 기준으로 오름차순 정렬 (1위가 맨 위로)
    df = df.sort_values("rank").reset_index(drop=True)

    # -------------------------------------------------
    # 4-1. 1위 영화: 지표 카드 세 장
    # -------------------------------------------------
    st.subheader("🏆 1위 영화")
    top_movie = df.iloc[0]

    col1, col2, col3 = st.columns(3)
    col1.metric(label=f"{top_movie['movieNm']} — 관객수(어제)", value=f"{top_movie['audiCnt']:,}명")
    col2.metric(label="누적 관객수", value=f"{top_movie['audiAcc']:,}명")
    col3.metric(label="상영 스크린 수", value=f"{top_movie['scrnCnt']:,}개")

    st.divider()

    # -------------------------------------------------
    # 4-2. 관객수 상위 5편 막대그래프
    # -------------------------------------------------
    st.subheader("📊 관객수 상위 5편")
    top5 = df.sort_values("audiCnt", ascending=False).head(5)
    chart_df = top5.set_index("movieNm")[["audiCnt"]]
    chart_df.columns = ["어제 관객수"]
    st.bar_chart(chart_df)

    st.divider()

    # -------------------------------------------------
    # 4-3. 전체 표
    # -------------------------------------------------
    st.subheader("📋 전체 순위표")

    table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
    table_df.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "관객수": st.column_config.NumberColumn(format="%d"),
            "누적관객": st.column_config.NumberColumn(format="%d"),
            "스크린수": st.column_config.NumberColumn(format="%d"),
        },
    )


if __name__ == "__main__":
    main()
