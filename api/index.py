"""
Vercel Serverless Function – 가계부 대시보드 (로컬 엑셀 파일)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import plotly  # type: ignore[import-untyped]
import plotly.express as px  # type: ignore[import-untyped]
from flask import Flask  # type: ignore[import-untyped]

app = Flask(__name__)

EXCEL_FILE = Path(__file__).resolve().parent.parent / "houseaccountfile.xlsx"

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

RENAME_MAP: dict[str, str] = {
    "일자": "date", "날짜": "date", "Date": "date",
    "분류": "category", "카테고리": "category", "Category": "category",
    "금액": "amount", "지출금액": "amount", "Amount": "amount",
    "구분": "type", "수입/지출": "type", "Type": "type",
    "메모": "memo", "비고": "memo", "Memo": "memo",
}


def load_sheet(filepath: Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(filepath, sheet_name=sheet_name, engine="openpyxl")
    if df.empty:
        return pd.DataFrame()
    for old, new in RENAME_MAP.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    # 수입/지출이 별도 컬럼인 경우 amount와 type을 합성
    if "amount" not in df.columns and "수입" in df.columns and "지출" in df.columns:
        df["수입"] = pd.to_numeric(df["수입"], errors="coerce").fillna(0)
        df["지출"] = pd.to_numeric(df["지출"], errors="coerce").fillna(0)
        df["amount"] = df["수입"] - df["지출"]
        df["type"] = df.apply(
            lambda r: "수입" if r["수입"] > 0 else "지출", axis=1
        )

    return df


def get_sheet_names(filepath: Path) -> list[str]:
    xls = pd.ExcelFile(filepath, engine="openpyxl")
    return xls.sheet_names


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


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def _chart_to_html(fig: Any) -> str:
    return plotly.io.to_html(fig, full_html=False, include_plotlyjs=False)


def build_charts(df: pd.DataFrame) -> dict[str, str]:
    charts: dict[str, str] = {}

    income = float(df.loc[df["type"] == "수입", "amount"].sum())  # type: ignore[union-attr]
    expense = float(df.loc[df["type"] == "지출", "abs_amount"].sum())  # type: ignore[union-attr]
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

    monthly = df.groupby(["month", "type"], as_index=False)["amount"].sum()
    monthly.loc[monthly["type"] == "지출", "amount"] = monthly.loc[monthly["type"] == "지출", "amount"].abs()
    fig = px.line(monthly, x="month", y="amount", color="type", markers=True, title="월별 수입/지출 추이")
    fig.update_layout(legend_title_text="구분", yaxis_title="금액")
    charts["monthly"] = _chart_to_html(fig)

    exp_df = df[df["type"] == "지출"]
    if not exp_df.empty:
        grouped = exp_df.groupby("category", as_index=False).agg(abs_amount=("abs_amount", "sum"))
        grouped = grouped.sort_values(by="abs_amount", ascending=False)  # type: ignore[call-overload]
        fig = px.pie(grouped, names="category", values="abs_amount", title="카테고리별 지출 비중", hole=0.35)
        charts["category"] = _chart_to_html(fig)

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
  <p class="subtitle">Python + Flask + pandas + plotly (로컬 엑셀 · Vercel)</p>

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
    try:
        if not EXCEL_FILE.exists():
            return render_error(f"엑셀 파일을 찾을 수 없습니다: {EXCEL_FILE.name}")

        sheet_names = get_sheet_names(EXCEL_FILE)
        if not sheet_names:
            return render_error("엑셀 파일에 시트가 없습니다.")

        worksheet_name = sheet_names[0]

        raw_df = load_sheet(EXCEL_FILE, worksheet_name)
        if raw_df.empty:
            return render_error("시트에 데이터가 없습니다.")

        df = normalize(raw_df)
        charts = build_charts(df)

        display_cols = ["date", "category", "type", "amount"]
        if "memo" in df.columns:
            display_cols.append("memo")
        display_df = df.sort_values("date", ascending=False)[display_cols].copy()
        display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
        raw_html = display_df.to_html(index=False, classes="data-table")

        return render_page(charts, raw_html)

    except Exception as exc:
        return render_error(str(exc))
