from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import streamlit as st

st.set_page_config(page_title="가계부 대시보드", page_icon="📊", layout="wide")

EXCEL_FILE = Path(__file__).parent / "houseaccountfile.xlsx"


@st.cache_data
def get_sheet_names(filepath: str) -> list[str]:
    """엑셀 파일의 시트 이름 목록을 반환합니다."""
    xls = pd.ExcelFile(filepath, engine="openpyxl")
    return xls.sheet_names


@st.cache_data
def load_sheet_as_dataframe(filepath: str, sheet_name: str) -> pd.DataFrame:
    """엑셀 시트를 DataFrame으로 로드합니다."""
    df = pd.read_excel(filepath, sheet_name=sheet_name, engine="openpyxl")

    if df.empty:
        return pd.DataFrame()

    # Common column aliases for Korean household book datasets.
    rename_map = {
        "일자": "date",
        "날짜": "date",
        "Date": "date",
        "분류": "category",
        "카테고리": "category",
        "Category": "category",
        "금액": "amount",
        "지출금액": "amount",
        "Amount": "amount",
        "구분": "type",
        "수입/지출": "type",
        "Type": "type",
        "메모": "memo",
        "비고": "memo",
        "Memo": "memo",
    }

    for old_name, new_name in rename_map.items():
        if old_name in df.columns and new_name not in df.columns:
            df = df.rename(columns={old_name: new_name})

    return df


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required analytics columns exist and have correct dtypes."""
    required = ["date", "category", "amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            "필수 컬럼이 없습니다: " + ", ".join(missing) + ". "
            "(필수: date, category, amount 또는 한글 별칭 컬럼)"
        )

    out = df.copy()

    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["amount"] = (
        out["amount"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.strip()
    )
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")

    out = out.dropna(subset=["date", "amount"])

    # If type is missing, assume negative amount as expense, positive as income.
    if "type" not in out.columns:
        out["type"] = out["amount"].apply(lambda x: "지출" if x < 0 else "수입")

    # Normalize type labels.
    out["type"] = out["type"].astype(str).str.strip().replace(
        {
            "expense": "지출",
            "income": "수입",
            "EXPENSE": "지출",
            "INCOME": "수입",
        }
    )

    out["month"] = out["date"].dt.to_period("M").astype(str)
    out["abs_amount"] = out["amount"].abs()

    return out


def kpi_cards(df: pd.DataFrame) -> None:
    income = df.loc[df["type"] == "수입", "amount"].sum()
    expense = df.loc[df["type"] == "지출", "abs_amount"].sum()
    net = income - expense

    c1, c2, c3 = st.columns(3)
    c1.metric("총 수입", f"{income:,.0f} 원")
    c2.metric("총 지출", f"{expense:,.0f} 원")
    c3.metric("순수지", f"{net:,.0f} 원")


def monthly_trend_chart(df: pd.DataFrame) -> None:
    monthly = (
        df.groupby(["month", "type"], as_index=False)["amount"].sum()
    )

    # Keep expense positive for visual comparison.
    monthly.loc[monthly["type"] == "지출", "amount"] = monthly.loc[
        monthly["type"] == "지출", "amount"
    ].abs()

    fig = px.line(
        monthly,
        x="month",
        y="amount",
        color="type",
        markers=True,
        title="월별 수입/지출 추이",
    )
    fig.update_layout(legend_title_text="구분", yaxis_title="금액")
    st.plotly_chart(fig, use_container_width=True)


def category_expense_chart(df: pd.DataFrame) -> None:
    expense_df = df[df["type"] == "지출"].copy()
    if expense_df.empty:
        st.info("지출 데이터가 없어 카테고리 차트를 표시할 수 없습니다.")
        return

    grouped = expense_df.groupby("category", as_index=False).agg(
        abs_amount=("abs_amount", "sum")
    ).sort_values(by="abs_amount", ascending=False)

    fig = px.pie(
        grouped,
        names="category",
        values="abs_amount",
        title="카테고리별 지출 비중",
        hole=0.35,
    )
    st.plotly_chart(fig, use_container_width=True)


def daily_flow_chart(df: pd.DataFrame) -> None:
    daily = df.assign(day=df["date"].dt.date).groupby("day", as_index=False)["amount"].sum()

    fig = px.bar(daily, x="day", y="amount", title="일별 순증감")
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.title("가계부 대시보드")
    st.caption("Python + Streamlit + pandas + plotly (로컬 엑셀)")

    filepath = str(EXCEL_FILE)

    if not EXCEL_FILE.exists():
        st.error(f"엑셀 파일을 찾을 수 없습니다: {filepath}")
        return

    with st.sidebar:
        st.header("📂 엑셀 파일 설정")
        st.write(f"파일: `{EXCEL_FILE.name}`")

        try:
            sheet_names = get_sheet_names(filepath)
        except Exception as exc:
            st.error(f"엑셀 파일 읽기 실패: {exc}")
            return

        if not sheet_names:
            st.warning("시트가 없습니다.")
            return

        worksheet_name = st.selectbox(
            "워크시트 선택",
            options=sheet_names,
            help="엑셀 파일 내 시트 목록",
        )

        run_button = st.button("불러오기", type="primary", use_container_width=True)

    if not run_button:
        st.info("왼쪽 사이드바에서 워크시트를 선택하고 불러오기를 눌러주세요.")
        return

    try:
        raw_df = load_sheet_as_dataframe(filepath, worksheet_name)
        if raw_df.empty:
            st.warning("시트에 데이터가 없습니다.")
            return

        df = normalize_dataframe(raw_df)

    except Exception as exc:
        st.error(f"데이터 로딩 실패: {exc}")
        return

    min_date = df["date"].min().date()
    max_date = df["date"].max().date()

    date_range = st.date_input(
        "기간 선택",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    if len(date_range) == 2:  # type: ignore[arg-type]
        start, end = date_range
        filtered = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)].copy()
    else:
        filtered = df.copy()

    selected_categories = st.multiselect(
        "카테고리 필터", options=sorted(filtered["category"].dropna().astype(str).unique())
    )
    if selected_categories:
        filtered = filtered[filtered["category"].astype(str).isin(selected_categories)]

    if filtered.empty:
        st.warning("선택한 조건의 데이터가 없습니다.")
        return

    kpi_cards(filtered)

    left, right = st.columns(2)
    with left:
        monthly_trend_chart(filtered)
    with right:
        category_expense_chart(filtered)

    daily_flow_chart(filtered)

    with st.expander("원본 데이터 보기"):
        st.dataframe(filtered.sort_values("date", ascending=False), use_container_width=True)


if __name__ == "__main__":
    main()
