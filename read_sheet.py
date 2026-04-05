"""
로컬 엑셀 파일 읽기 프로그램
파일: houseaccountfile.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

EXCEL_FILE = Path(__file__).parent / "houseaccountfile.xlsx"


def read_excel_file() -> dict[str, pd.DataFrame]:
    """엑셀 파일의 모든 시트를 읽어 {시트명: DataFrame} 딕셔너리로 반환합니다."""
    if not EXCEL_FILE.exists():
        raise FileNotFoundError(f"엑셀 파일을 찾을 수 없습니다: {EXCEL_FILE}")

    xls = pd.ExcelFile(EXCEL_FILE, engine="openpyxl")
    all_sheets: dict[str, pd.DataFrame] = {}
    for name in xls.sheet_names:
        all_sheets[name] = pd.read_excel(xls, sheet_name=name)
    return all_sheets


def main() -> None:
    print(f"엑셀 파일 읽기: {EXCEL_FILE}")
    print("=" * 60)

    try:
        sheets = read_excel_file()
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 엑셀 파일 접근 실패: {e}")
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
