"""
tx_fetcher.py  v5
台指期（TX）資料自動抓取模組
來源：台灣期貨交易所（taifex.com.tw）
合併日盤＋夜盤：Open=日盤O, High=max(日H,夜H), Low=min(日L,夜L), Close=夜盤C

v5 修正重點（結算日換月問題）：
    每月第3個星期三是TX結算日，當天近月合約會在早盤結算後停止交易，
    成交量主力轉移到新的近月合約。若日盤、夜盤「各自」抓成交量最大的
    TX列，結算日當天可能日盤抓到舊合約、夜盤抓到新合約，開高低收會
    變成兩個不同合約拼起來，數字對不起來。
    v5 做法：日盤、夜盤都先抓「所有到期月份」的資料，再用「當天日盤+
    夜盤合計成交量最大」的那個月份為準，日盤、夜盤都固定抓同一個月份
    的資料，避免結算日拼錯合約。

台期所欄位順序（已確認）：
[0]=契約 [1]=到期月份 [2]=開盤價 [3]=最高價 [4]=最低價 [5]=最後成交價
[6]=漲跌值 [7]=漲跌% [8]=*成交量 [9]=結算價 [10]=*未沖銷契約量
[11]=最後最佳買價 [12]=最後最佳賣價 [13]=歷史最高 [14]=歷史最低
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

PRICE_MIN = 5000
PRICE_MAX = 100000


def to_float(s):
    try:
        return float(str(s).replace(",", "").strip())
    except:
        return None


def to_int(s):
    try:
        return int(str(s).replace(",", "").strip())
    except:
        return 0


def is_trading_day(date: datetime) -> bool:
    return date.weekday() < 5


def fetch_session_all(date: datetime, market_code: str) -> dict:
    """
    抓取指定日期、時段「所有到期月份」的 TX 合約 OHLC。
    回傳 {到期月份字串: {open,high,low,close,volume}}。
    上層再依「當天日盤+夜盤合計成交量最大」的月份統一取用，
    避免結算日（每月第3個星期三）換月時日盤/夜盤各抓到不同合約。
    """
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
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    results = {}

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]

            # 第一欄必須是 TX
            if len(cells) < 9 or cells[0] != "TX":
                continue

            month = cells[1].strip()
            o   = to_float(cells[2])
            h   = to_float(cells[3])
            l   = to_float(cells[4])
            c   = to_float(cells[5])
            vol = to_int(cells[8])

            # 驗證價格合理
            if not all([o, h, l, c]):
                continue
            if not (PRICE_MIN < o < PRICE_MAX and
                    PRICE_MIN < h < PRICE_MAX and
                    PRICE_MIN < l < PRICE_MAX and
                    PRICE_MIN < c < PRICE_MAX):
                continue
            if h < l or h < o or h < c:
                continue

            if month not in results or vol > results[month]["volume"]:
                results[month] = {"open": o, "high": h, "low": l, "close": c, "volume": vol}

    return results


def fetch_tx_daily(date: datetime) -> dict | None:
    if not is_trading_day(date):
        print(f"[SKIP] {date.strftime('%Y-%m-%d')} 非交易日")
        return None

    day_rows   = fetch_session_all(date, "0")   # 日盤，所有月份
    night_rows = fetch_session_all(date, "1")   # 夜盤，所有月份

    if not day_rows and not night_rows:
        print(f"[MISS] {date.strftime('%Y-%m-%d')} 無資料（可能休市）")
        return None

    # 以「日盤+夜盤合計成交量最大」的月份為準，日盤、夜盤都固定取該月份
    # （結算日換月時，避免日盤抓到舊合約、夜盤抓到新合約造成拼接錯誤）
    months = set(day_rows) | set(night_rows)
    combined_vol = {
        m: day_rows.get(m, {}).get("volume", 0) + night_rows.get(m, {}).get("volume", 0)
        for m in months
    }
    target = max(combined_vol, key=combined_vol.get)

    day   = day_rows.get(target)
    night = night_rows.get(target)

    if day and night:
        result = {
            "open":   day["open"],
            "high":   max(day["high"],  night["high"]),
            "low":    min(day["low"],   night["low"]),
            "close":  night["close"],
            "volume": day["volume"] + night["volume"],
        }
        tag = f"日+夜 契約{target}"
    elif night:
        result = {**night}
        tag = f"夜 契約{target}"
    else:
        result = {**day}
        tag = f"日 契約{target}"

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
    # 過濾掉舊版錯誤資料（high 重複出現的異常值）
    df = df[df["close"] > PRICE_MIN]
    df = df[~df["date"].isin(new["date"])]
    df = pd.concat([df, new], ignore_index=True)
    save_daily(df)
    return df


def build_weekly(df_daily: pd.DataFrame):
    df = df_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["close"] > PRICE_MIN]   # 過濾舊版錯誤資料
    df = df.sort_values("date").set_index("date")

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
