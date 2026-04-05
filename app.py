from __future__ import annotations

import os
from typing import Any

import gspread
import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import streamlit as st
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

load_dotenv()

st.set_page_config(page_title="가계부 대시보드", page_icon="📊", layout="wide")


@st.cache_resource
def get_gspread_client() -> gspread.Client:
    """Create and cache an authenticated gspread client."""
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not cred_path:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS 환경변수가 필요합니다.")

    if not os.path.exists(cred_path):
        raise FileNotFoundError(
            f"서비스 계정 키 파일을 찾을 수 없습니다: {cred_path}"
        )

    return gspread.service_account(filename=cred_path)


@st.cache_resource
def get_drive_service() -> Any:
    """Create and cache a Google Drive API service using service account credentials."""
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
    return build(
        "drive",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )


@st.cache_data(ttl=300)
def get_sheets_from_folder(folder_id: str) -> dict[str, str]:
    """
    List all Google Sheets in a folder.
    Returns dict: {file_name: file_id}
    """
    service = get_drive_service()
    query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"

    results = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=100,
    ).execute()

    files = results.get("files", [])
    return {f["name"]: f["id"] for f in files}


@st.cache_data(ttl=300)
def get_worksheets(spreadsheet_id: str) -> list[str]:
    """Get list of worksheet names in a spreadsheet."""
    client = get_gspread_client()
    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        return [ws.title for ws in spreadsheet.worksheets()]
    except Exception as e:
        st.error(f"워크시트 목록 조회 실패: {e}")
        return []


@st.cache_data(ttl=120)
def load_sheet_as_dataframe(spreadsheet_url: str, spreadsheet_id: str, worksheet_name: str) -> pd.DataFrame:
    """Load worksheet records into DataFrame with basic normalization."""
    client = get_gspread_client()

    if spreadsheet_url:
        spreadsheet = client.open_by_url(spreadsheet_url)
    elif spreadsheet_id:
        spreadsheet = client.open_by_key(spreadsheet_id)
    else:
        raise ValueError("SPREADSHEET_URL 또는 SPREADSHEET_ID 중 하나가 필요합니다.")

    worksheet = spreadsheet.worksheet(worksheet_name)
    values = worksheet.get_all_records()

    if not values:
        return pd.DataFrame()

    df = pd.DataFrame(values)

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
    st.caption("Python + Streamlit + gspread + pandas + plotly")

    default_folder_id = os.getenv("FOLDER_ID", "")

    with st.sidebar:
        st.header("📂 Google Drive 설정")
        
        folder_id = st.text_input(
            "폴더 ID (또는 공유 링크에서 추출)",
            value=default_folder_id,
            help="예: 1PB01d9EKdYmGlYaD3ivRN3-6FlHX_YC2"
        )

        spreadsheet_name = None
        spreadsheet_id = None
        worksheet_name = None

        if folder_id.strip():
            try:
                sheets_dict = get_sheets_from_folder(folder_id)
                if sheets_dict:
                    spreadsheet_name = st.selectbox(
                        "스프레드시트 선택",
                        options=list(sheets_dict.keys()),
                        help="폴더 내 Google Sheets 파일 목록"
                    )

                    if spreadsheet_name:
                        spreadsheet_id = sheets_dict[spreadsheet_name]
                        
                        worksheets = get_worksheets(spreadsheet_id)
                        if worksheets:
                            worksheet_name = st.selectbox(
                                "워크시트 선택",
                                options=worksheets,
                                help="스프레드시트 내 시트 목록"
                            )
                else:
                    st.warning("폴더에 Google Sheets 파일이 없습니다.")
            except Exception as exc:
                st.error(f"폴더 탐색 실패: {exc}")

        st.divider()
        st.header("⚙️ 또는 직접 입력")
        
        direct_url = st.text_input(
            "Spreadsheet URL",
            help="URL로 직접 지정할 수 있습니다."
        )
        direct_id = st.text_input(
            "Spreadsheet ID",
            help="ID로 직접 지정할 수 있습니다."
        )
        if worksheet_name is None and direct_id:
            direct_ws = st.text_input(
                "Worksheet 이름",
                value="Sheet1"
            )
        else:
            direct_ws = worksheet_name or "Sheet1"

        run_button = st.button("불러오기", type="primary", use_container_width=True)

        st.markdown("### 권한 체크")
        st.write("서비스 계정 이메일을 시트 공유 대상(뷰어 이상)으로 추가하세요.")

    if not run_button:
        st.info("왼쪽 사이드바에서 폴더를 선택하거나 스프레드시트 정보를 입력하고 불러오기를 눌러주세요.")
        return

    # Determine which source to use
    sheet_url: str = ""
    sheet_id: str = ""
    ws_name: str = direct_ws

    if spreadsheet_id and worksheet_name:
        sheet_id = str(spreadsheet_id)
        ws_name = worksheet_name
    elif direct_url or direct_id:
        sheet_url = direct_url or ""
        sheet_id = direct_id or ""
    else:
        st.error("스프레드시트 정보가 필요합니다.")
        return

    try:
        raw_df = load_sheet_as_dataframe(sheet_url, sheet_id, ws_name)
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
