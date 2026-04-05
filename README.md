# Account Dashboard (Google Sheets)

Google Sheets 기반 가계부를 Streamlit 대시보드로 시각화하는 앱입니다.

## 기술 스택
- Python
- Streamlit
- gspread
- pandas
- plotly
- google-api-python-client (Drive API 폴더 탐색)

## 1) 준비
1. Google Cloud에서 Service Account를 만들고 JSON 키를 발급받습니다.
2. 가계부 스프레드시트를 서비스 계정 이메일에 공유합니다.
3. JSON 키 파일을 프로젝트 루트에 저장합니다. (예: service-account.json)

## 2) 설치
```bash
pip install -r requirements.txt
```

## 3) 환경변수 설정
`.env.example`를 참고해 `.env` 파일을 생성합니다.

예시:
```env
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json
FOLDER_ID=1PB01d9EKdYmGlYaD3ivRN3-6FlHX_YC2
WORKSHEET_NAME=Sheet1
```

## 4) 실행
```bash
streamlit run app.py
```

## 사용 방법

### 방법 1: 폴더 내 파일 자동 탐색 (권장)
1. 사이드바에 폴더 ID를 입력합니다.
2. 폴더 내 Google Sheets 파일 목록이 자동으로 로드됩니다.
3. 드롭다운에서 원하는 스프레드시트를 선택하면 워크시트도 자동으로 로드됩니다.
4. 불러오기를 눌러 대시보드를 시작합니다.

### 방법 2: 직접 입력
1. 스프레드시트 URL 또는 ID를 직접 입력합니다.
2. 워크시트 이름을 입력합니다.
3. 불러오기를 눌러 대시보드를 시작합니다.

## 데이터 컬럼 가이드
다음 컬럼 중 별칭을 자동 인식합니다.

- date: 일자, 날짜, Date
- category: 분류, 카테고리, Category
- amount: 금액, 지출금액, Amount
- type(선택): 구분, 수입/지출, Type
- memo(선택): 메모, 비고, Memo

## 기본 제공 대시보드
- 총 수입 / 총 지출 / 순수지 KPI
- 월별 수입/지출 추이
- 카테고리별 지출 비중
- 일별 순증감
- 기간/카테고리 필터
