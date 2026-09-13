"""
yfinance 資料抓取模組

抓取商品的日 K + 週 K
儲存到 data/auto/ 資料夾
"""

import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

import yaml
import yfinance as yf
import pandas as pd


ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / 'config' / 'symbols.yaml'
DATA_DIR = ROOT / 'data' / 'auto'


def load_symbols():
    """讀取商品清單"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def fetch_daily(yf_symbol: str, days: int = 90) -> pd.DataFrame:
    """
    抓取日 K (預設近 90 天)
    """
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        df = yf.download(
            yf_symbol,
            start=start,
            end=end,
            interval='1d',
            progress=False,
            auto_adjust=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df.columns = [c.lower() if c != 'Date' else 'date' for c in df.columns]
        return df[['date', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        print(f"[ERROR] {yf_symbol}: {e}")
        return pd.DataFrame()


def fetch_weekly(yf_symbol: str, weeks: int = 52) -> pd.DataFrame:
    """
    抓取週 K (預設近一年 52 週)
    """
    end = datetime.now()
    start = end - timedelta(weeks=weeks + 5)
    try:
        df = yf.download(
            yf_symbol,
            start=start,
            end=end,
            interval='1wk',
            progress=False,
            auto_adjust=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df.columns = [c.lower() if c != 'Date' else 'date' for c in df.columns]
        return df[['date', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        print(f"[ERROR] {yf_symbol} weekly: {e}")
        return pd.DataFrame()


def fetch_all():
    """
    抓取所有商品的日 + 週資料
    儲存到 data/auto/{code}_daily.csv 和 {code}_weekly.csv
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    cfg = load_symbols()
    results = {}
    
    for item in cfg.get('auto', []):
        code = item['code']
        yf_sym = item['yf_symbol']
        name = item['name']
        
        print(f"抓取 {code} ({name}) [{yf_sym}]...")
        
        # 日
        df_d = fetch_daily(yf_sym)
        if len(df_d) > 0:
            df_d.to_csv(DATA_DIR / f'{code}_daily.csv', index=False)
            print(f"  日 K: {len(df_d)} 筆, 最新 {df_d['date'].iloc[-1]}")
        
        # 週
        df_w = fetch_weekly(yf_sym)
        if len(df_w) > 0:
            df_w.to_csv(DATA_DIR / f'{code}_weekly.csv', index=False)
            print(f"  週 K: {len(df_w)} 筆, 最新 {df_w['date'].iloc[-1]}")
        
        results[code] = {
            'daily': len(df_d),
            'weekly': len(df_w),
            'last_daily': str(df_d['date'].iloc[-1]) if len(df_d) > 0 else None,
            'last_weekly': str(df_w['date'].iloc[-1]) if len(df_w) > 0 else None,
        }
    
    # 儲存抓取狀態
    status_path = DATA_DIR / '_fetch_status.json'
    with open(status_path, 'w', encoding='utf-8') as f:
        json.dump({
            'fetched_at': datetime.now().isoformat(),
            'results': results,
        }, f, ensure_ascii=False, indent=2)
    
    return results


if __name__ == '__main__':
    print("=" * 60)
    print("三關價系統 - yfinance 資料抓取")
    print(f"執行時間: {datetime.now().isoformat()}")
    print("=" * 60)
    
    results = fetch_all()
    
    print("\n" + "=" * 60)
    print("完成摘要:")
    print("=" * 60)
    for code, info in results.items():
        status = "✓" if info['daily'] > 0 else "✗"
        print(f"{status} {code}: 日 {info['daily']} 筆, 週 {info['weekly']} 筆")
