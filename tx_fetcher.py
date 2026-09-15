"""
tx_fetcher.py
台指期（TX）資料自動抓取模組
來源：台灣期貨交易所（taifex.com.tw）
功能：
  1. 抓取每日 TX 近月合約 OHLC
  2. 存成日線 CSV
  3. 每週彙整成週線 CSV
用法：
  python tx_fetcher.py              # 抓今日資料
  python tx_fetcher.py --date 2026-09-15  # 抓指定日期
  python tx_fetcher.py --weekly     # 強制重新彙整週線
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import argparse
import os
import re
import time

# ── 路徑設定（配合你的 repo 結構）──────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "three_gate", "data", "auto")
DAILY_CSV   = os.path.join(DATA_DIR, "TX_daily.csv")
WEEKLY_CSV  = os.path.join(DATA_DIR, "TX_weekly.csv")
os.makedirs(DATA_DIR, exist_ok=True)

# ── 台期所 URL ─────────────────────────────────────────────────────────────
TAIFEX_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DataBot/1.0)",
    "Referer": "https://www.taifex.com.tw/"
}


def is_trading_day(date: datetime) -> bool:
    """簡單判斷是否為交易日（排除週六日）"""
    return date.weekday() < 5


def fetch_tx_daily(date: datetime) -> dict | None:
    """
    從台期所抓指定日期的 TX 近月合約 OHLC。
    回傳 dict: {date, open, high, low, close, volume} 或 None（非交易日/無資料）
    """
    if not is_trading_day(date):
        print(f"[SKIP] {date.strftime('%Y-%m-%d')} 非交易日")
        return None

    date_str = date.strftime("%Y/%m/%d")
    params = {"queryType": "1", "marketCode": "0", "dateaddcnt": "0",
              "commodity_id": "TX", "queryDate": date_str}

    try:
        resp = requests.get(TAIFEX_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] 抓取失敗: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            # 找含有 TX 的行，且有開高低收資料
            if len(cells) < 8:
                continue
            if cells[0] != "TX":
                continue
            # 找近月合約（月份最近的那筆，成交量最大）
            try:
                open_p  = float(cells[2].replace(",", ""))
                high_p  = float(cells[3].replace(",", ""))
                low_p   = float(cells[4].replace(",", ""))
                close_p = float(cells[5].replace(",", ""))
                volume  = int(cells[7].replace(",", "")) if cells[7].replace(",", "").isdigit() else 0

                if open_p > 0 and close_p > 0:
                    print(f"[OK] {date.strftime('%Y-%m-%d')} TX O={open_p} H={high_p} L={low_p} C={close_p} Vol={volume}")
                    return {
                        "date":   date.strftime("%Y-%m-%d"),
                        "open":   open_p,
                        "high":   high_p,
                        "low":    low_p,
                        "close":  close_p,
                        "volume": volume
                    }
            except (ValueError, IndexError):
                continue

    print(f"[MISS] {date_str} 無有效 TX 資料（可能休市）")
    return None


def update_daily_csv(new_row: dict) -> pd.DataFrame:
    """把新資料加到日線 CSV（避免重複）"""
    if os.path.exists(DAILY_CSV):
        df = pd.read_csv(DAILY_CSV, parse_dates=["date"])
    else:
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    new_df = pd.DataFrame([new_row])
    new_df["date"] = pd.to_datetime(new_df["date"])

    # 去重：移除已存在的同日資料再加入
    df = df[df["date"] != new_df["date"].iloc[0]]
    df = pd.concat([df, new_df], ignore_index=True)
    df = df.sort_values("date").reset_index(drop=True)

    df.to_csv(DAILY_CSV, index=False, date_format="%Y-%m-%d")
    print(f"[SAVED] 日線 CSV 更新：{DAILY_CSV}（共 {len(df)} 筆）")
    return df


def build_weekly_csv(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    從日線資料彙整週線（週一到週五，以週五為代表日）。
    只產出完整週（有結束的週，即週五已過）。
    """
    df = df_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    # 以週為單位 resample（週五為週末）
    df.set_index("date", inplace=True)
    weekly = df.resample("W-FRI").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum"
    }).dropna(subset=["open", "close"])

    # 只保留有資料的週
    weekly = weekly[weekly["open"] > 0]
    weekly = weekly.reset_index()
    weekly.rename(columns={"date": "week_end"}, inplace=True)
    weekly["week_end"] = weekly["week_end"].dt.strftime("%Y-%m-%d")

    weekly.to_csv(WEEKLY_CSV, index=False)
    print(f"[SAVED] 週線 CSV 更新：{WEEKLY_CSV}（共 {len(weekly)} 筆）")
    return weekly


def backfill(days: int = 30):
    """補抓過去 N 天的資料"""
    print(f"[BACKFILL] 補抓過去 {days} 天資料...")
    today = datetime.today()
    rows = []
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        row = fetch_tx_daily(d)
        if row:
            rows.append(row)
        time.sleep(0.5)  # 避免打太快

    if rows:
        df = update_daily_csv_bulk(rows)
        build_weekly_csv(df)


def update_daily_csv_bulk(rows: list) -> pd.DataFrame:
    """批量寫入多筆資料"""
    if os.path.exists(DAILY_CSV):
        df = pd.read_csv(DAILY_CSV, parse_dates=["date"])
    else:
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    new_df = pd.DataFrame(rows)
    new_df["date"] = pd.to_datetime(new_df["date"])
    df = df[~df["date"].isin(new_df["date"])]
    df = pd.concat([df, new_df], ignore_index=True)
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(DAILY_CSV, index=False, date_format="%Y-%m-%d")
    print(f"[SAVED] 日線 CSV 更新：{DAILY_CSV}（共 {len(df)} 筆）")
    return df


# ── 主程式 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="台指期 TX 資料抓取")
    parser.add_argument("--date",    type=str, help="指定日期 YYYY-MM-DD（預設今日）")
    parser.add_argument("--weekly",  action="store_true", help="強制重新彙整週線")
    parser.add_argument("--backfill",type=int, default=0, help="補抓過去 N 天資料")
    args = parser.parse_args()

    if args.backfill > 0:
        backfill(args.backfill)
    else:
        target = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.today()
        row = fetch_tx_daily(target)

        if row:
            df_daily = update_daily_csv(row)
        elif os.path.exists(DAILY_CSV):
            df_daily = pd.read_csv(DAILY_CSV, parse_dates=["date"])
        else:
            print("[WARN] 無日線資料，結束")
            exit(0)

        # 每週五自動彙整週線，或強制重建
        if args.weekly or target.weekday() == 4:  # 4 = 週五
            build_weekly_csv(df_daily)
            print("[INFO] 週線已更新")
