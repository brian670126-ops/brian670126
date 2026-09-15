"""
tx_fetcher.py
台指期（TX）資料自動抓取模組
來源：台灣期貨交易所（taifex.com.tw）
功能：
  1. 抓取每日 TX 近月合約 OHLC（日盤＋夜盤合併）
     - Open  = 日盤開盤價
     - High  = max(日盤最高, 夜盤最高)
     - Low   = min(日盤最低, 夜盤最低)
     - Close = 夜盤收盤價（若夜盤無資料則用日盤收盤）
  2. 存成日線 CSV
  3. 每週彙整成週線 CSV
用法：
  python tx_fetcher.py              # 抓今日資料
  python tx_fetcher.py --date 2026-09-15
  python tx_fetcher.py --weekly     # 強制重新彙整週線
  python tx_fetcher.py --backfill 90
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import argparse
import os
import time

# ── 路徑設定 ───────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "three_gate", "data", "auto")
DAILY_CSV = os.path.join(DATA_DIR, "TX_daily.csv")
WEEKLY_CSV= os.path.join(DATA_DIR, "TX_weekly.csv")
os.makedirs(DATA_DIR, exist_ok=True)

# ── 台期所 URL ─────────────────────────────────────────────────────────────
TAIFEX_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DataBot/1.0)",
    "Referer":    "https://www.taifex.com.tw/"
}

# marketCode: 0=日盤一般交易時段, 1=夜盤盤後交易時段
SESSION_DAY   = "0"
SESSION_NIGHT = "1"


def is_trading_day(date: datetime) -> bool:
    return date.weekday() < 5  # 排除週六日


def fetch_session(date: datetime, market_code: str) -> dict | None:
    """
    抓取指定日期、指定時段（日盤/夜盤）的 TX 近月合約 OHLC。
    回傳 dict: {open, high, low, close, volume} 或 None
    """
    date_str = date.strftime("%Y/%m/%d")
    params = {
        "queryType":   "1",
        "marketCode":  market_code,
        "dateaddcnt":  "0",
        "commodity_id":"TX",
        "queryDate":   date_str
    }
    try:
        resp = requests.get(TAIFEX_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] 抓取失敗 (date={date_str} session={market_code}): {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    best = None  # 取成交量最大的近月合約

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 8 or cells[0] != "TX":
                continue
            try:
                o = float(cells[2].replace(",", ""))
                h = float(cells[3].replace(",", ""))
                l = float(cells[4].replace(",", ""))
                c = float(cells[5].replace(",", ""))
                vol_str = cells[7].replace(",", "")
                vol = int(vol_str) if vol_str.isdigit() else 0
                if o > 0 and c > 0:
                    if best is None or vol > best["volume"]:
                        best = {"open": o, "high": h, "low": l,
                                "close": c, "volume": vol}
            except (ValueError, IndexError):
                continue

    return best


def fetch_tx_daily(date: datetime) -> dict | None:
    """
    合併日盤＋夜盤，回傳當日完整 OHLC：
      Open  = 日盤 Open
      High  = max(日盤 H, 夜盤 H)
      Low   = min(日盤 L, 夜盤 L)
      Close = 夜盤 Close（若無夜盤則用日盤 Close）
    """
    if not is_trading_day(date):
        print(f"[SKIP] {date.strftime('%Y-%m-%d')} 非交易日")
        return None

    day   = fetch_session(date, SESSION_DAY)
    night = fetch_session(date, SESSION_NIGHT)

    if day is None and night is None:
        print(f"[MISS] {date.strftime('%Y-%m-%d')} 無有效資料（可能休市）")
        return None

    if day is None:
        # 只有夜盤（不常見，但處理）
        result = {
            "date":   date.strftime("%Y-%m-%d"),
            "open":   night["open"],
            "high":   night["high"],
            "low":    night["low"],
            "close":  night["close"],
            "volume": night["volume"]
        }
    elif night is None:
        # 只有日盤
        result = {
            "date":   date.strftime("%Y-%m-%d"),
            "open":   day["open"],
            "high":   day["high"],
            "low":    day["low"],
            "close":  day["close"],
            "volume": day["volume"]
        }
    else:
        # 日盤＋夜盤合併
        result = {
            "date":   date.strftime("%Y-%m-%d"),
            "open":   day["open"],
            "high":   max(day["high"],  night["high"]),
            "low":    min(day["low"],   night["low"]),
            "close":  night["close"],
            "volume": day["volume"] + night["volume"]
        }

    session_tag = "日+夜" if (day and night) else ("日" if day else "夜")
    print(f"[OK] {result['date']} TX({session_tag}) "
          f"O={result['open']} H={result['high']} "
          f"L={result['low']}  C={result['close']} Vol={result['volume']}")
    return result


def load_daily() -> pd.DataFrame:
    if os.path.exists(DAILY_CSV):
        df = pd.read_csv(DAILY_CSV, parse_dates=["date"])
    else:
        df = pd.DataFrame(columns=["date","open","high","low","close","volume"])
    return df


def save_daily(df: pd.DataFrame):
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(DAILY_CSV, index=False, date_format="%Y-%m-%d")
    print(f"[SAVED] 日線 CSV：{DAILY_CSV}（共 {len(df)} 筆）")


def upsert_row(row: dict) -> pd.DataFrame:
    df = load_daily()
    new_df = pd.DataFrame([row])
    new_df["date"] = pd.to_datetime(new_df["date"])
    df = df[df["date"] != new_df["date"].iloc[0]]
    df = pd.concat([df, new_df], ignore_index=True)
    save_daily(df)
    return df


def upsert_rows(rows: list) -> pd.DataFrame:
    df = load_daily()
    new_df = pd.DataFrame(rows)
    new_df["date"] = pd.to_datetime(new_df["date"])
    df = df[~df["date"].isin(new_df["date"])]
    df = pd.concat([df, new_df], ignore_index=True)
    save_daily(df)
    return df


def build_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    df = df_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    weekly = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna(subset=["open", "close"])
    weekly = weekly[weekly["open"] > 0].reset_index()
    weekly.rename(columns={"date": "week_end"}, inplace=True)
    weekly["week_end"] = weekly["week_end"].dt.strftime("%Y-%m-%d")
    weekly.to_csv(WEEKLY_CSV, index=False)
    print(f"[SAVED] 週線 CSV：{WEEKLY_CSV}（共 {len(weekly)} 筆）")
    return weekly


def backfill(days: int = 90):
    print(f"[BACKFILL] 補抓過去 {days} 天資料（日盤＋夜盤合併）...")
    today = datetime.today()
    rows = []
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        row = fetch_tx_daily(d)
        if row:
            rows.append(row)
        time.sleep(0.8)  # 避免打太快被擋

    if rows:
        df = upsert_rows(rows)
        build_weekly(df)
    print(f"[BACKFILL] 完成，共抓到 {len(rows)} 筆")


# ── 主程式 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="台指期 TX 資料抓取（日盤＋夜盤合併）")
    parser.add_argument("--date",     type=str, help="指定日期 YYYY-MM-DD（預設今日）")
    parser.add_argument("--weekly",   action="store_true", help="強制重新彙整週線")
    parser.add_argument("--backfill", type=int, default=0, help="補抓過去 N 天資料")
    args = parser.parse_args()

    if args.backfill > 0:
        backfill(args.backfill)
    else:
        target = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.today()
        row = fetch_tx_daily(target)

        if row:
            df_daily = upsert_row(row)
        elif os.path.exists(DAILY_CSV):
            df_daily = load_daily()
        else:
            print("[WARN] 無日線資料，結束")
            exit(0)

        # 週五自動彙整，或強制重建
        if args.weekly or target.weekday() == 4:
            build_weekly(df_daily)
            print("[INFO] 週線已更新")
