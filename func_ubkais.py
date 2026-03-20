import pandas as pd
import numpy as np
import requests
import urllib3
import sys
import io
import logging
import airportsdata
import pytz

# 한글 출력을 위한 설정
sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# 'InsecureRequestWarning' 경고 문구 숨기기
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Log 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def depskd(search_date, airline_3let, airport_4let):
    url = "https://ubikais.fois.go.kr:8030/sysUbikais/biz/fpl/selectDep.fois"

    params = {
        "downloadYn": "1",
        "srchDate": "2025-10-03",
        "srchDatesh": search_date,
        "srchAl": airline_3let,
        "srchFln": "",
        "srchDep": airport_4let,
        "srchArr": "",
        "dummy": "134942279",
        "cmd": "get-records",
        "limit": "100",
        "offset": "0"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        if "records" in data and data["records"]:
            df = pd.DataFrame(data["records"])
            # logger.info(f"DEP {search_date} {airline_3let} {airport_4let} {len(df)} data loaded")
            return df
        return None
    except requests.exceptions.RequestException as e:
        logger.info(f"요청 중 오류 발생: {e}")
        return None

def arrskd(search_date, airline_3let, airport_4let):
    url = "https://ubikais.fois.go.kr:8030/sysUbikais/biz/fpl/selectArr.fois"
    
    # print(airline_3let)
    params = {
        "downloadYn": "1",
        "srchDate": "2025-10-03",
        "srchDatesh": search_date,
        "srchAl": airline_3let,
        "srchFln": "",
        "srchDep": "",
        "srchArr": airport_4let,
        "dummy": "150707486",
        "cmd": "get-records",
        "limit": "100",
        "offset": "0"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        if "records" in data and data["records"]:
            df = pd.DataFrame(data["records"])
            # logger.info(f"ARR {search_date} {airline_3let} {airport_4let} {len(df)} data loaded")
            return df
        return None
    except requests.exceptions.RequestException as e:
        logger.info(f"요청 중 오류 발생: {e}")
        return None

def process_flight_schedule(start_date, end_date, icao_airline, icao_codes, file_name):
    """
    항공 스케줄 데이터를 수집하고 가공하여 지정된 파일명으로 엑셀 저장
    start_date: 시작 날짜(yyyymmdd - 문자열)
    end_date: 종료 날짜(yyyymmdd - 문자열)
    icao_airline: 항공사 코드(ICAO 코드 - 리스트, 단 공백문자열("")로 입력시 전체편 검색)
    icao_codes: 공항 코드(ICAO 코드 - 리스트)
    file_name: 저장할 파일명(엑셀 파일명 - 문자열) Ex. "./flight_schedule_20250330.xlsx"
    """
    date_list = pd.date_range(start=start_date, end=end_date)
    dep_df_list = []
    arr_df_list = []

    # 1. 전체 작업 횟수 계산
    total_tasks = len(icao_airline) * len(date_list) * len(icao_codes)
    current_task = 0

    if total_tasks == 0:
        logger.info("작업할 데이터가 없습니다.")
        return


    for airline in icao_airline:
        for date in date_list:
            search_date = date.strftime("%Y%m%d")
            for airport in icao_codes:
                dep_df = depskd(search_date, airline, airport)
                arr_df = arrskd(search_date, airline, airport)
                
                if dep_df is not None:
                    dep_df_list.append(dep_df)
                if arr_df is not None:
                    arr_df_list.append(arr_df)

                # 3. 진행률 계산 및 출력
                current_task += 1
                progress = (current_task / total_tasks) * 100
                if airline=="":
                    try:
                        logger.info(f"[{progress:>6.2f}%] | All-{search_date}-{airport}-{len(dep_df)}/{len(arr_df)}")
                    except:
                        pass
                else:
                    try:
                        logger.info(f"[{progress:>6.2f}%] | {airline}-{search_date}-{airport}-{len(dep_df)}/{len(arr_df)}")
                    except:
                        pass

    dep_df_final = pd.DataFrame()
    arr_df_final = pd.DataFrame()

    if dep_df_list:
        dep_df_final = pd.concat(dep_df_list, ignore_index=True)
        dep_df_final.rename(columns={'depStatus': 'Status', 'standDep': 'Stand', 'blockOffTime': 'Ramp IN/OUT'}, inplace=True)
        dep_df_final['Sort'] = "DEP"
        logger.info(f"Departure data frame combined")

    if arr_df_list:
        arr_df_final = pd.concat(arr_df_list, ignore_index=True)
        arr_df_final.rename(columns={'arrStatus': 'Status', 'standArr': 'Stand', 'blockOnTime': 'Ramp IN/OUT'}, inplace=True)
        arr_df_final['Sort'] = "ARR"
        logger.info(f"Arrival data frame combined")

    if dep_df_final.empty and arr_df_final.empty:
        logger.info("No Record.")
        return

    combined_df = pd.concat([dep_df_final, arr_df_final], ignore_index=True)

    # Stand 컬럼 정규화
    combined_df['Stand'] = combined_df['Stand'].apply(lambda x: str(x).lstrip('0') if pd.notna(x) and str(x).lstrip('0') != "" else ("0" if pd.notna(x) and str(x) == "0" else x))

    cols_to_remove = ['flightPk', 'fplYn', 'amsRecPk', 'amsRecPkCha', 'chaYn']
    final_df = combined_df.drop(columns=cols_to_remove, errors='ignore')

    airports = airportsdata.load('ICAO')
    tz_map = {iata: info['tz'] for iata, info in airports.items()}

    def icao_to_iata(icao):
        if pd.isna(icao) or icao not in airports: return None
        iata = airports[icao]['iata']
        return iata if iata else None

    final_df['Depstn'] = final_df['apIcao'].apply(icao_to_iata)
    final_df['Arrstn'] = final_df['apArr'].apply(icao_to_iata)

    # 시간 계산
    for col in ['schTime', 'etd', 'atd']:
        final_df[col] = pd.to_datetime(final_df['schDate'] + final_df[col], format='%Y%m%d%H%M', errors='coerce')
    for col in ['sta', 'eta', 'ata']:
        final_df[col] = pd.to_datetime(final_df['staDate'] + final_df[col], format='%Y%m%d%H%M', errors='coerce')

    target_date = np.where(final_df['Sort'] == 'DEP', final_df['schDate'], final_df['staDate'])
    final_df['Ramp_Datetime'] = pd.to_datetime(target_date + final_df['Ramp IN/OUT'], format='%Y%m%d%H%M', errors='coerce')

    def convert_to_utc(row, time_col, apo_col):
        iata_code = row[apo_col]
        local_time = row[time_col]
        if pd.isna(local_time) or iata_code not in tz_map: return None
        try:
            local_tz = pytz.timezone(tz_map[iata_code])
            return local_tz.localize(local_time).astimezone(pytz.UTC)
        except: return None

    final_df['schTime_UTC'] = final_df.apply(lambda r: convert_to_utc(r, 'schTime', 'apIcao'), axis=1)
    final_df['atd_UTC'] = final_df.apply(lambda r: convert_to_utc(r, 'atd', 'apIcao'), axis=1)
    final_df['sta_UTC'] = final_df.apply(lambda r: convert_to_utc(r, 'sta', 'apArr'), axis=1)
    final_df['ata_UTC'] = final_df.apply(lambda r: convert_to_utc(r, 'ata', 'apArr'), axis=1)
    final_df['Ramp_Datetime_UTC'] = final_df.apply(
        lambda r: convert_to_utc(r, 'Ramp_Datetime', 'apIcao' if r['Sort'] == 'DEP' else 'apArr'), axis=1
    )

    # TZ 제거 및 Blocktime 계산
    utc_cols = ['schTime_UTC', 'atd_UTC', 'sta_UTC', 'ata_UTC', 'Ramp_Datetime_UTC']
    for col in utc_cols:
        final_df[col] = final_df[col].dt.tz_localize(None)

    duration = final_df['sta_UTC'] - final_df['schTime_UTC']
    final_df.loc[duration < pd.Timedelta(0), 'sta_UTC'] += pd.Timedelta(days=1)
    final_df['Blocktime'] = (final_df['sta_UTC'] - final_df['schTime_UTC']).dt.total_seconds() / 60
    final_df['Blocktime'] = final_df['Blocktime'].fillna(0).astype(int)

    final_df['Stand'] = final_df['Stand'].apply(lambda val: str(val).lstrip('0') if pd.notna(val) and str(val).lstrip('0') != "" else ("0" if pd.notna(val) else val))
    final_df['SCH DATE_KST'] = pd.to_datetime(final_df['schDate'], format='%Y%m%d').dt.date

    rename_map = {
        'SCH DATE_KST': 'Sch_date_KST', 'Sort': 'Sort', 'fpId': 'Fltno',
        'Depstn': 'Depstn', 'Arrstn': 'Arrstn', 'acId': 'Acno',
        'acType': 'Actype', 'Status': 'Status', 'nat': 'NAT', 'Stand': 'Stand',
        'schTime_UTC': 'STD_UTC', 'sta_UTC': 'STA_UTC', 'atd_UTC': 'ATD_UTC',
        'ata_UTC': 'ATA_UTC', 'Ramp_Datetime_UTC': 'Ramp_UTC', 'Blocktime': 'Blocktime'
    }

    final_output_df = final_df[list(rename_map.keys())].rename(columns=rename_map)

    def assign_bt_idx(group):
        # 1. CNL(결항)인 레코드는 그룹 로직에 상관없이 무조건 N
        # (단, 모든 결과값을 담을 컬럼을 미리 N으로 초기화)
        group['Bt_idx'] = 'N'
        
        # CNL이 아닌 데이터들만 추출해서 로직 판단
        valid_mask = group['Status'] != 'CNL'
        valid_data = group[valid_mask]
        
        # 만약 유효한 데이터가 없으면 모두 N인 상태로 반환
        if len(valid_data) == 0:
            return group

        # 2. 유효 데이터가 1개인 경우
        if len(valid_data) == 1:
            group.loc[valid_mask, 'Bt_idx'] = 'Y'
            return group
        
        # 3. 유효 데이터 중 DIV 상태가 포함되어 있는지 확인
        has_div = (valid_data['Status'] == 'DIV').any()
        
        if has_div:
            # DIV가 있으면 DIV인 레코드만 Y
            group.loc[valid_mask & (group['Status'] == 'DIV'), 'Bt_idx'] = 'Y'
        else:
            # DIV가 없고 중복인 경우 (DEP/ARR 세트 등)
            # Sort가 DEP인 레코드만 Y
            group.loc[valid_mask & (group['Sort'] == 'DEP'), 'Bt_idx'] = 'Y'
            
        return group

    final_output_df = final_output_df.groupby(['Sch_date_KST', 'Fltno'], group_keys=False).apply(assign_bt_idx)

    # 엑셀 저장 (입력받은 file_name 사용)
    final_output_df.to_excel(file_name, index=False)
    logger.info(f"Excel downloaed: {file_name}")

if __name__ == "__main__":
    # 호출부 예시
    start = "20250330"
    end = "20250330"
    airlines = [""]
    airports = ["RKSI", "RKSS"]
    target_file = "./flight_schedule_20250330.xlsx" # 파일명 변수화

    process_flight_schedule(start, end, airlines, airports, target_file)