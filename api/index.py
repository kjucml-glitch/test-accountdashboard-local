"""
Vercel Serverless Function – 가계부 대시보드
Flask WSGI app that Vercel can serve as a serverless function.
"""
from __future__ import annotations

import json
import os
from typing import Any

import gspread
import pandas as pd
import plotly  # type: ignore[import-untyped]
import plotly.express as px  # type: ignore[import-untyped]
from flask import Flask, request
from google.oauth2.service_account import Credentials  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

app = Flask(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_credentials() -> Credentials:
    """Resolve credentials from env var GCP_SERVICE_ACCOUNT_JSON or file."""
    raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        info = json.loads(raw)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if cred_path and os.path.exists(cred_path):
        return Credentials.from_service_account_file(cred_path, scopes=SCOPES)

    raise ValueError("GCP_SERVICE_ACCOUNT_JSON 또는 GOOGLE_APPLICATION_CREDENTIALS 환경변수를 설정하세요.")


def _get_gspread_client() -> gspread.Client:
    return gspread.authorize(_get_credentials())


def _get_drive_service() -> Any:
    return build("drive", "v3", credentials=_get_credentials(), cache_discovery=False)


# ---------------------------------------------------------------------------
# Data helpers (reused from app.py logic)
# ---------------------------------------------------------------------------

RENAME_MAP: dict[str, str] = {
    "일자": "date", "날짜": "date", "Date": "date",
    "분류": "category", "카테고리": "category", "Category": "category",
    "금액": "amount", "지출금액": "amount", "Amount": "amount",
    "구분": "type", "수입/지출": "type", "Type": "type",
    "메모": "memo", "비고": "memo", "Memo": "memo",
}


def load_sheet(spreadsheet_id: str, worksheet_name: str) -> pd.DataFrame:
    client = _get_gspread_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    ws = spreadsheet.worksheet(worksheet_name)
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    for old, new in RENAME_MAP.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})
    return df


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "category", "amount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("필수 컬럼 누락: " + ", ".join(missing))
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["amount"] = (
        out["amount"].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.strip()
    )
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    out = out.dropna(subset=["date", "amount"])
    if "type" not in out.columns:
        out["type"] = out["amount"].apply(lambda x: "지출" if x < 0 else "수입")
    out["type"] = out["type"].astype(str).str.strip().replace(
        {"expense": "지출", "income": "수입", "EXPENSE": "지출", "INCOME": "수입"}
    )
    out["month"] = out["date"].dt.to_period("M").astype(str)
    out["abs_amount"] = out["amount"].abs()
    return out


def list_sheets_in_folder(folder_id: str) -> dict[str, str]:
    service = _get_drive_service()
    q = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    res = service.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=100).execute()
    return {f["name"]: f["id"] for f in res.get("files", [])}


def list_worksheets(spreadsheet_id: str) -> list[str]:
    client = _get_gspread_client()
    return [ws.title for ws in client.open_by_key(spreadsheet_id).worksheets()]


# ---------------------------------------------------------------------------
# Chart builders (return Plotly JSON for embedding)
# ---------------------------------------------------------------------------

def _chart_to_html(fig: Any) -> str:
    return plotly.io.to_html(fig, full_html=False, include_plotlyjs=False)


def build_charts(df: pd.DataFrame) -> dict[str, str]:
    charts: dict[str, str] = {}

    # KPI
    income = float(df.loc[df["type"] == "수입", "amount"].sum())
    expense = float(df.loc[df["type"] == "지출", "abs_amount"].sum())
    net = income - expense
    charts["kpi"] = f"""
    <div style="display:flex;gap:24px;margin-bottom:24px;">
      <div style="flex:1;background:#e8f5e9;border-radius:12px;padding:20px;text-align:center;">
        <div style="font-size:14px;color:#666;">총 수입</div>
        <div style="font-size:28px;font-weight:bold;color:#2e7d32;">{income:,.0f} 원</div>
      </div>
      <div style="flex:1;background:#ffebee;border-radius:12px;padding:20px;text-align:center;">
        <div style="font-size:14px;color:#666;">총 지출</div>
        <div style="font-size:28px;font-weight:bold;color:#c62828;">{expense:,.0f} 원</div>
      </div>
      <div style="flex:1;background:#e3f2fd;border-radius:12px;padding:20px;text-align:center;">
        <div style="font-size:14px;color:#666;">순수지</div>
        <div style="font-size:28px;font-weight:bold;color:#1565c0;">{net:,.0f} 원</div>
      </div>
    </div>"""

    # Monthly trend
    monthly = df.groupby(["month", "type"], as_index=False)["amount"].sum()
    monthly.loc[monthly["type"] == "지출", "amount"] = monthly.loc[monthly["type"] == "지출", "amount"].abs()
    fig = px.line(monthly, x="month", y="amount", color="type", markers=True, title="월별 수입/지출 추이")
    fig.update_layout(legend_title_text="구분", yaxis_title="금액")
    charts["monthly"] = _chart_to_html(fig)

    # Category pie
    exp_df = df[df["type"] == "지출"]
    if not exp_df.empty:
        grouped = exp_df.groupby("category", as_index=False).agg(abs_amount=("abs_amount", "sum"))
        grouped = grouped.sort_values(by="abs_amount", ascending=False)
        fig = px.pie(grouped, names="category", values="abs_amount", title="카테고리별 지출 비중", hole=0.35)
        charts["category"] = _chart_to_html(fig)

    # Daily bar
    daily = df.assign(day=df["date"].dt.date).groupby("day", as_index=False)["amount"].sum()
    fig = px.bar(daily, x="day", y="amount", title="일별 순증감")
    charts["daily"] = _chart_to_html(fig)

    return charts


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def render_page(charts: dict[str, str], raw_html: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>가계부 대시보드</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:'Segoe UI',sans-serif; background:#f5f5f5; padding:24px; }}
    h1 {{ text-align:center; margin-bottom:8px; }}
    .subtitle {{ text-align:center; color:#888; margin-bottom:24px; font-size:14px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px; }}
    .card {{ background:#fff; border-radius:12px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }}
    .full {{ grid-column:1/-1; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:8px 12px; text-align:left; border-bottom:1px solid #eee; }}
    th {{ background:#f0f0f0; position:sticky; top:0; }}
    .table-wrap {{ max-height:400px; overflow-y:auto; }}
    @media(max-width:768px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <h1>📊 가계부 대시보드</h1>
  <p class="subtitle">Python + Flask + gspread + pandas + plotly (Vercel)</p>

  {charts.get("kpi", "")}

  <div class="grid">
    <div class="card">{charts.get("monthly", "")}</div>
    <div class="card">{charts.get("category", "<p>지출 데이터 없음</p>")}</div>
    <div class="card full">{charts.get("daily", "")}</div>
    <div class="card full">
      <h3 style="margin-bottom:12px;">원본 데이터</h3>
      <div class="table-wrap">{raw_html}</div>
    </div>
  </div>
</body>
</html>"""


def render_error(msg: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/><title>오류</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;background:#f5f5f5;}}
.box{{background:#fff;padding:40px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.1);max-width:600px;}}
h2{{color:#c62828;margin-bottom:12px;}}</style></head>
<body><div class="box"><h2>⚠️ 오류</h2><p>{msg}</p></div></body></html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index() -> str:
    folder_id = os.getenv("FOLDER_ID", "").strip()
    spreadsheet_id = request.args.get("sheet_id", "").strip()
    worksheet_name = request.args.get("ws", "").strip()

    try:
        # If no sheet specified, try to pick the first one from the folder
        if not spreadsheet_id and folder_id:
            sheets = list_sheets_in_folder(folder_id)
            if sheets:
                spreadsheet_id = next(iter(sheets.values()))

        if not spreadsheet_id:
            return render_error(
                "표시할 스프레드시트가 없습니다. "
                "FOLDER_ID 환경변수를 설정하거나 ?sheet_id=...&ws=... 쿼리를 사용하세요."
            )

        if not worksheet_name:
            ws_list = list_worksheets(spreadsheet_id)
            worksheet_name = ws_list[0] if ws_list else "Sheet1"

        raw_df = load_sheet(spreadsheet_id, worksheet_name)
        if raw_df.empty:
            return render_error("시트에 데이터가 없습니다.")

        df = normalize(raw_df)
        charts = build_charts(df)

        display_df = df.sort_values("date", ascending=False)[["date", "category", "type", "amount", "memo"]].copy() if "memo" in df.columns else df.sort_values("date", ascending=False)[["date", "category", "type", "amount"]].copy()
        display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
        raw_html = display_df.to_html(index=False, classes="data-table")

        return render_page(charts, raw_html)

    except Exception as exc:
        return render_error(str(exc))


@app.route("/api/sheets")
def api_sheets() -> dict[str, Any]:
    """List sheets in the configured folder (JSON API)."""
    folder_id = os.getenv("FOLDER_ID", "")
    if not folder_id:
        return {"error": "FOLDER_ID not configured"}, 400  # type: ignore[return-value]
    return list_sheets_in_folder(folder_id)
