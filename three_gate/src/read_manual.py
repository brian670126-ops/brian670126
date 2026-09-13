"""
手動輸入資料讀取模組

從 data/manual/ 讀取手動輸入的 OHLC
支援兩種格式:
1. {code}_daily.csv  (日資料, 每天一列)
2. {code}_weekly.csv (週資料, 每週一列)

CSV 欄位: date, open, high, low, close, volume(選填)
"""

from pathlib import Path
import pandas as pd


ROOT = Path(__file__).parent.parent
MANUAL_DIR = ROOT / 'data' / 'manual'


def read_manual_daily(code: str) -> pd.DataFrame:
    """讀取手動輸入的日資料"""
    path = MANUAL_DIR / f'{code}_daily.csv'
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'])
    if 'volume' not in df.columns:
        df['volume'] = 0
    return df[['date', 'open', 'high', 'low', 'close', 'volume']].sort_values('date').reset_index(drop=True)


def read_manual_weekly(code: str) -> pd.DataFrame:
    """讀取手動輸入的週資料"""
    path = MANUAL_DIR / f'{code}_weekly.csv'
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'])
    if 'volume' not in df.columns:
        df['volume'] = 0
    return df[['date', 'open', 'high', 'low', 'close', 'volume']].sort_values('date').reset_index(drop=True)


def append_daily(code: str, date_str: str, o: float, h: float, l: float, c: float, v: float = 0):
    """
    新增一筆日資料到手動輸入區
    如果 date 已存在則更新
    """
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    path = MANUAL_DIR / f'{code}_daily.csv'
    
    if path.exists():
        df = pd.read_csv(path)
        df['date'] = pd.to_datetime(df['date'])
        target_date = pd.Timestamp(date_str)
        df = df[df['date'] != target_date]
    else:
        df = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    
    new_row = pd.DataFrame([{
        'date': pd.Timestamp(date_str),
        'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values('date').reset_index(drop=True)
    df.to_csv(path, index=False)
    print(f"寫入 {code}_daily.csv: {date_str} O={o} H={h} L={l} C={c}")


def append_weekly(code: str, date_str: str, o: float, h: float, l: float, c: float, v: float = 0):
    """新增一筆週資料 (date 應該是週五)"""
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    path = MANUAL_DIR / f'{code}_weekly.csv'
    
    if path.exists():
        df = pd.read_csv(path)
        df['date'] = pd.to_datetime(df['date'])
        target_date = pd.Timestamp(date_str)
        df = df[df['date'] != target_date]
    else:
        df = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    
    new_row = pd.DataFrame([{
        'date': pd.Timestamp(date_str),
        'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values('date').reset_index(drop=True)
    df.to_csv(path, index=False)
    print(f"寫入 {code}_weekly.csv: {date_str} O={o} H={h} L={l} C={c}")
