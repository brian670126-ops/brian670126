"""
tx_fetcher.py  v3
台指期（TX）資料自動抓取模組
來源：台灣期貨交易所（taifex.com.tw）
合併日盤＋夜盤：Open=日盤O, High=max(日H,夜H), Low=min(日L,夜L), Close=夜盤C
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import argparse
import os
import time

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "three_gate", "data", "auto")
DAILY_CSV  = os.path.join(DATA_DIR, "TX_daily.csv")
WEEKLY_CSV = os.path.join(DATA_DIR, "TX_weekly.csv")
os.makedirs(DATA_DIR, exist_ok=True)

TAIFEX_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":    "https://www.taifex.com.tw/",
    "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PRICE_MIN = 5000    # 台指期合理最低價
PRICE_MAX = 100000  # 台指期合理最高價


def is_price(v):
    """判斷是否為合理的台指期價格"""
    try:
        f = float(str(v).replace(",", ""))
        return PRICE_MIN < f < PRICE_MAX
    except:
        return False


def parse_ohlc_from_cells(cells):
    """
    從一行 cells 中找出 OHLC：
    策略：找出所有合理價格的位置，第一個=Open, max=High, min=Low, 最後一個=Close
    """
    prices = []
    for i, c in enumerate(cells):
        c = str(c).replace(",", "").strip()
        try:
            f = float(c)
            if PRICE_MIN < f < PRICE_MAX:
                prices.append((i, f))
        except:
            pass

    if len(prices) < 4:
        return None

    vals = [p[1] for p in prices]
    return {
        "open":  vals[0],
        "high":  max(vals),
        "low":   min(vals),
        "close": vals[-1],
    }


def fetch_session(date: datetime, market_code: str) -> dict | None:
    date_str = date.strftime("%Y/%m/%d")
    params = {
        "queryType":    "1",
        "marketCode":   market_code,
        "dateaddcnt":   "0",
        "commodity_id": "TX",
        "queryDate":    date_str,
    }
    try:
        resp = requests.get(TAIFEX_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] {date_str} session={market_code}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    best = None

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 6:
                continue

            # 找 TX 開頭的行（近月合約）
            if cells[0] not in ("TX", "臺股期貨"):
                continue

            ohlc = parse_ohlc_from_cells(cells)
            if ohlc is None:
                continue

            # 成交量：找最後幾欄中最大的整數
            vol = 0
            for c in reversed(cells):
                c = str(c).replace(",", "").strip()
                try:
                    v = int(float(c))
                    if v > 0 and v < 10_000_000:
                        vol = v
                        break
                except:
                    pass

            if best is None or vol > best.get("volume", 0):
                best = {**ohlc, "volume": vol}

    return best


def is_trading_day(date: datetime) -> bool:
    return date.weekday() < 5


def fetch_tx_daily(date: datetime) -> dict | None:
    if not is_trading_day(date):
        print(f"[SKIP] {date.strftime('%Y-%m-%d')} 非交易日")
        return None

    day   = fetch_session(date, "0")
    night = fetch_session(date, "1")

    if day is None and night is None:
        print(f"[MISS] {date.strftime('%Y-%m-%d')} 無有效資料（可能休市）")
        return None

    if day is None:
        result = {"open": night["open"], "high": night["high"],
                  "low": night["low"],   "close": night["close"],
                  "volume": night["volume"]}
        tag = "夜"
    elif night is None:
        result = {"open": day["open"], "high": day["high"],
                  "low": day["low"],   "close": day["close"],
                  "volume": day["volume"]}
        tag = "日"
    else:
        result = {
            "open":   day["open"],
            "high":   max(day["high"],  night["high"]),
            "low":    min(day["low"],   night["low"]),
            "close":  night["close"],
            "volume": day["volume"] + night["volume"],
        }
        tag = "日+夜"

    result["date"] = date.strftime("%Y-%m-%d")
    print(f"[OK] {result['date']} TX({tag}) "
          f"O={result['open']:.0f} H={result['high']:.0f} "
          f"L={result['low']:.0f}  C={result['close']:.0f} "
          f"Vol={result['volume']}")
    return result


def load_daily() -> pd.DataFrame:
    if os.path.exists(DAILY_CSV):
        return pd.read_csv(DAILY_CSV, parse_dates=["date"])
    return pd.DataFrame(columns=["date","open","high","low","close","volume"])


def save_daily(df: pd.DataFrame):
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(DAILY_CSV, index=False, date_format="%Y-%m-%d")
    print(f"[SAVED] 日線 CSV：{DAILY_CSV}（共 {len(df)} 筆）")


def upsert(rows) -> pd.DataFrame:
    if isinstance(rows, dict):
        rows = [rows]
    df = load_daily()
    new = pd.DataFrame(rows)
    new["date"] = pd.to_datetime(new["date"])
    df = df[~df["date"].isin(new["date"])]
    df = pd.concat([df, new], ignore_index=True)
    save_daily(df)
    return df


def build_weekly(df_daily: pd.DataFrame):
    df = df_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")

    # 只保留合理價格的日線（過濾掉舊版錯誤資料）
    df = df[df["close"] > PRICE_MIN]

    weekly = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna(subset=["open", "close"])
    weekly = weekly[weekly["open"] > PRICE_MIN].reset_index()
    weekly.rename(columns={"date": "week_end"}, inplace=True)
    weekly["week_end"] = weekly["week_end"].dt.strftime("%Y-%m-%d")
    weekly.to_csv(WEEKLY_CSV, index=False)
    print(f"[SAVED] 週線 CSV：{WEEKLY_CSV}（共 {len(weekly)} 筆）")


def backfill(days: int = 90):
    print(f"[BACKFILL] 補抓過去 {days} 天（日盤＋夜盤）...")
    today = datetime.today()
    rows = []
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        row = fetch_tx_daily(d)
        if row:
            rows.append(row)
        time.sleep(0.8)
    if rows:
        df = upsert(rows)
        build_weekly(df)
    print(f"[DONE] 共抓到 {len(rows)} 筆")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",     type=str, default=None)
    parser.add_argument("--weekly",   action="store_true")
    parser.add_argument("--backfill", type=int, default=0)
    args = parser.parse_args()

    if args.backfill > 0:
        backfill(args.backfill)
    else:
        target = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.today()
        row = fetch_tx_daily(target)
        if row:
            df = upsert(row)
        elif os.path.exists(DAILY_CSV):
            df = load_daily()
        else:
            print("[WARN] 無資料，結束")
            exit(0)

        if args.weekly or target.weekday() == 4:
            build_weekly(df)
