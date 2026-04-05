"""
Google Spreadsheet 읽기 프로그램
스프레드시트: https://docs.google.com/spreadsheets/d/1nBAcZCmhB6moTdy4ofIaqZgQ2WMpwzxkEUc4-787OLc
"""
from __future__ import annotations

import json
import os
import sys

import gspread
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials  # type: ignore[import-untyped]

load_dotenv()

SPREADSHEET_ID = "1nBAcZCmhB6moTdy4ofIaqZgQ2WMpwzxkEUc4-787OLc"
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_credentials() -> Credentials:
    """서비스 계정 인증 정보를 로드합니다."""
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service-account.json")
    if os.path.exists(cred_path):
        return Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    raise FileNotFoundError(
        f"서비스 계정 키 파일을 찾을 수 없습니다: {cred_path}\n"
        "1) Google Cloud Console에서 서비스 계정 키(JSON)를 다운로드하세요.\n"
        "2) 파일명을 service-account.json 으로 프로젝트 루트에 저장하세요.\n"
        "3) 스프레드시트를 서비스 계정 이메일에 공유(뷰어)하세요."
    )


def read_spreadsheet() -> dict[str, pd.DataFrame]:
    """스프레드시트의 모든 워크시트를 읽어 {시트명: DataFrame} 딕셔너리로 반환합니다."""
    creds = get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    all_sheets: dict[str, pd.DataFrame] = {}
    for ws in spreadsheet.worksheets():
        records = ws.get_all_records()
        if records:
            all_sheets[ws.title] = pd.DataFrame(records)
        else:
            # 데이터가 없으면 헤더만이라도 가져오기
            header = ws.row_values(1)
            all_sheets[ws.title] = pd.DataFrame(columns=header) if header else pd.DataFrame()

    return all_sheets


def main() -> None:
    print(f"스프레드시트 읽기: {SPREADSHEET_ID}")
    print("=" * 60)

    try:
        sheets = read_spreadsheet()
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 스프레드시트 접근 실패: {e}")
        sys.exit(1)

    if not sheets:
        print("워크시트가 없습니다.")
        return

    for name, df in sheets.items():
        print(f"\n📄 워크시트: {name}")
        print(f"   행: {len(df)}, 열: {len(df.columns)}")
        print(f"   컬럼: {list(df.columns)}")
        print()
        if df.empty:
            print("   (데이터 없음)")
        else:
            print(df.to_string(index=False))
        print("-" * 60)


if __name__ == "__main__":
    main()
