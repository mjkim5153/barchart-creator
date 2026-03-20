# func_ubkais.py 사용 규칙 및 가이드

## 개요

`func_ubkais.py`는 한국 항공정보시스템(UBIKAIS)에서 항공편 스케줄 데이터를 수집하고 가공하는 파일입니다.
이 문서는 데이터 수집 후 데이터 가공(컬럼 변환) 규칙을 명시합니다.

---

## 데이터 수집

### 주요 함수

#### `depskd(search_date, airline_3let, airport_4let)`
- **목적**: 출발편 데이터 수집
- **매개변수**:
  - `search_date`: 조회 날짜 (yyyymmdd 형식, 문자열)
  - `airline_3let`: 항공사 코드 (ICAO 3자리 코드, 빈 문자열 시 전체 항공사)
  - `airport_4let`: 공항 코드 (ICAO 4자리 코드)
- **반환값**: 출발편 데이터프레임 (없으면 None)

#### `arrskd(search_date, airline_3let, airport_4let)`
- **목적**: 도착편 데이터 수집
- **매개변수**: depskd와 동일
- **반환값**: 도착편 데이터프레임 (없으면 None)

#### `process_flight_schedule(start_date, end_date, icao_airline, icao_codes, file_name)`
- **목적**: 지정된 기간의 모든 항공편 스케줄 데이터를 수집 및 가공하여 엑셀 파일로 저장
- **매개변수**:
  - `start_date`: 시작 날짜 (yyyymmdd 형식)
  - `end_date`: 종료 날짜 (yyyymmdd 형식)
  - `icao_airline`: 항공사 코드 리스트 (빈 문자열 ""로 입력 시 전체 항공사 조회)
  - `icao_codes`: 공항 코드 리스트 (ICAO 코드)
  - `file_name`: 저장할 엑셀 파일명 (예: "./flight_schedule_20260316.xlsx")

**사용 예시**:
```python
process_flight_schedule(
    start_date="20260316",
    end_date="20260316",
    icao_airline=[""],  # 전체 항공사
    icao_codes=["RKSI", "RKSS"],  # 인천, 김포
    file_name="./flight_schedule_20260316.xlsx"
)
```

---

## 데이터 가공 규칙

### 출력 컬럼 구조

함수 실행 후 생성되는 엑셀 파일의 컬럼 구조는 다음과 같습니다:

| 컬럼명 | 설명 | 데이터 타입 |
|--------|------|-----------|
| **Sch_date_KST** | 스케줄 날짜 (한국 시간) | date |
| **Sort** | 편종 | DEP(출발)/ARR(도착) |
| **Fltno** | 편명 (항공사코드+편번) | 예: KE123 |
| **Airline_Code** | 항공사 코드 (3자리) | 예: KAL, AAL, DLH |
| **Depstn** | 출발지 공항코드 (IATA) | 예: ICN, LAX |
| **Arrstn** | 도착지 공항코드 (IATA) | 예: LAX, NRT |
| **Domestic_Intl** | 국내선/국제선 구분 | 국내선/국제선 |
| **Acno** | 항공기 등록번호 | 예: HL7234 |
| **Actype** | 항공기 기종 | 예: B777, A350 |
| **Status** | 운항 상태 | ACT(운항)/CNL(결항)/DIV(우회) 등 |
| **Carrier_Type** | 항공사 성격 | 국적사/외항사 |
| **Stand** | 탑승 게이트 | 예: 101, 203 |
| **STD_UTC** | 출발 예정시각 (UTC) | datetime |
| **STD_KST** | 출발 예정시각 (한국시간) | datetime |
| **STA_UTC** | 도착 예정시각 (UTC) | datetime |
| **STA_KST** | 도착 예정시각 (한국시간) | datetime |
| **ATD_UTC** | 실제 출발시각 (UTC) | datetime |
| **ATA_UTC** | 실제 도착시각 (UTC) | datetime |
| **Ramp_UTC** | 램프 시간 (UTC) | datetime |
| **Blocktime** | 블록타임 (분) | int |
| **Bt_idx** | 블록타임 지표 | Y/N |
| **Actype_Grade** | 기종 등급 (A~E) | A/B/C/D/E |

---

## 컬럼 생성 규칙

### 1. 항공사 코드 추출

**원본**: `Fltno` 컬럼
**규칙**: 왼쪽 3자리 추출 → `Airline_Code` 컬럼 생성
**예시**:
- `KE123` → `KE` (앞 2자리) / 또는 `KAL` (ICAO 3자리 코드로 변환되어 있을 수 있음)

**추가 처리**:
- 나머지 부분(편번)은 원본 `Fltno` 컬럼에 그대로 유지

---

### 2. 국내선/국제선 구분

**원본**: `Depstn`, `Arrstn` 컬럼
**규칙**:
- **국내선**: 출발지와 도착지가 **모두 한국 공항**일 때만 "국내선"
- **국제선**: 출발지 또는 도착지 중 **하나라도 해외 공항**이면 "국제선"

**한국 공항 판단 기준**: IATA 코드가 한국 공항(ICN, GMP, PUS, CJU, KWJ, CJJ, YNY, CNJ, MWX 등)인지 확인

**저장**: `Domestic_Intl` 컬럼에 "국내선" 또는 "국제선" 저장

**예시**:
```
Depstn=ICN, Arrstn=PUS  → 국내선
Depstn=ICN, Arrstn=LAX  → 국제선
Depstn=NRT, Arrstn=ICN  → 국제선
```

---

### 3. 항공사 성격 분류 (국적사/외항사)

**원본**: `Airline_Code` 컬럼
**규칙**: 다음 항공사 코드에 해당하면 "국적사", 나머지는 "외항사"

**국적사 항공사 코드**:
- KAL (대한항공)
- AAR (아시아나항공)
- JJA (제주항공)
- TWB (티웨이항공)
- JNA (진에어)
- ESR (이스타항공)
- ABL (에어부산)
- ASV (에어서울)
- EOK (동방항공)
- PTA (에어인천)
- APZ (에어프레미엄)

**저장**: `Carrier_Type` 컬럼에 "국적사" 또는 "외항사" 저장

**예시**:
```
Airline_Code=KAL  → 국적사
Airline_Code=AAL  → 외항사
Airline_Code=DLH  → 외항사
```

---

### 4. 시간대 변환

**규칙**: UTC 시간에 9시간을 더하여 한국 표준시(KST)로 변환

**변환 대상 컬럼**:
- `STD_UTC` → `STD_KST` 생성 (출발 예정시각)
- `STA_UTC` → `STA_KST` 생성 (도착 예정시각)

**저장 방식**: 기존 UTC 컬럼은 유지하고, 별도의 `_KST` 컬럼 생성

**예시**:
```
STD_UTC: 2026-03-16 05:00:00 (UTC)
→ STD_KST: 2026-03-16 14:00:00 (KST/UTC+9)
```

---

### 5. 블록타임 지표 (Bt_idx) - **필수 포함 컬럼**

**규칙**: 같은 날짜와 편명(Fltno)을 기준으로 그룹화하여 Y인 경우 스케줄 바차트를 그릴때 사용(중복데이터 표출되지 않도록 제어하는 역할할)

**판단 로직** (스케줄 날짜와 편명으로 그룹화 후 적용):

1. **CNL(결항) 상태**: 무조건 `N`
2. **유효 데이터 1개**: `Y`
3. **DIV(우회) 상태 포함**: DIV 상태인 레코드만 `Y`, 나머지는 `N`
4. **DEP/ARR 중복인 경우** (DIV 없음): DEP 레코드만 `Y`, ARR은 `N`

**저장**: `Bt_idx` 컬럼에 "Y" 또는 "N" 저장

**예시**:
```
같은 편명의 DEP, ARR 레코드 2개
→ DEP: Bt_idx = Y
→ ARR: Bt_idx = N

DIV 상태의 레코드
→ Bt_idx = Y

CNL(결항) 레코드
→ Bt_idx = N

단일 레코드
→ Bt_idx = Y
```

**주의**: 최종 결과물(엑셀 파일)에는 **반드시** 이 컬럼이 포함되어야 합니다.

---

### 6. 기종 등급 (Actype_Grade)

**원본**: `Actype` 컬럼
**규칙**: 기종 코드를 등급으로 분류

| 등급 | 분류 | 기종 코드 |
|------|------|-----------|
| A | 소형 | AT7, DH8, E19, CRJ |
| B | 리저널 | E75, E90, BCS |
| C | 중형 | B737, B738, B739, B38M, A319, A320, A321, A20N, A21N |
| D | 대형 | B767, B787, B788, B789, A330, A332, A333 |
| E | 초대형 | B777, B772, B773, A350, A359, B747, B748, A380 |

**저장**: `Actype_Grade` 컬럼에 "A"~"E" 저장, 매핑되지 않는 기종은 빈 문자열

---

## 데이터 예시

아래는 `process_flight_schedule()` 실행 후 생성되는 데이터 샘플입니다. **Bt_idx 컬럼은 반드시 포함**되어야 합니다:

| Sch_date_KST | Sort | Fltno | Airline_Code | Depstn | Arrstn | Domestic_Intl | Carrier_Type | STD_KST | STA_KST | Blocktime | **Bt_idx** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-16 | DEP | KE101 | KAL | ICN | PUS | 국내선 | 국적사 | 2026-03-16 09:00:00 | 2026-03-16 10:20:00 | 80 | **Y** |
| 2026-03-16 | ARR | KE101 | KAL | PUS | ICN | 국내선 | 국적사 | 2026-03-16 10:30:00 | 2026-03-16 11:50:00 | 80 | **N** |
| 2026-03-16 | DEP | AA101 | AAL | ICN | LAX | 국제선 | 외항사 | 2026-03-16 11:30:00 | 2026-03-17 13:45:00 | 1275 | **Y** |
| 2026-03-16 | DEP | DLH101 | DLH | FRA | ICN | 국제선 | 외항사 | 2026-03-15 22:00:00 | 2026-03-16 16:30:00 | 645 | **Y** |

---

## 주의사항

1. **API 호출 제한**: UBIKAIS 시스템의 부하를 고려하여 대량의 데이터를 한 번에 수집하지 않도록 주의
2. **날짜 형식**: 모든 날짜는 `yyyymmdd` 형식(예: 20260316)으로 입력
3. **공항 코드**: ICAO 4자리 코드 사용 (IATA 코드 아님)
4. **결항/우회 처리**: `Status` 컬럼에 'CNL'(결항) 또는 'DIV'(우회) 값이 있으면 이를 참고하여 후처리
5. **Blocktime 계산**: STA_UTC - STD_UTC로 계산되며, 단위는 분(minute)
6. **바차트 날짜 보정**: `data_processor.py`의 `process_dataframe()`에서 STD_KST 날짜가 Sch_date_KST와 다를 경우, 시간은 유지하고 날짜를 Sch_date_KST 기준으로 이동시켜 해당 편이 바차트에 표출되도록 보정

---

## 참고 파일

- 데이터 수집 함수: `func_ubkais.py`
- 데이터 샘플: `examples/flight_schedule_20260316.xlsx`
