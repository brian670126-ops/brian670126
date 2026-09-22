# -*- coding: utf-8 -*-
"""
fcn_backtest.py
================
美股 FCN（Fixed Coupon Note）3個月下跌風險回測。

規則（Brian 釘死版）：
  - 每一個交易日都視為一個新的「進場點」，進場收盤價正規化為 100（排除當天本身）
  - 往後觀察 63 個交易日（約等於 3 個月）
  - 用觀察期間內每天的 Low（最低價）判斷是否曾經跌破 80% / 75% / 70%
  - 「期間內曾跌破」跟「到期（第63天）時仍低於 80%」分開統計，不混為一談
    * 期間內曾跌破 X%：63天內任何一天的 Low <= 進場價 * X%
    * 到期仍 <80%：第63個交易日的 Close < 進場價 * 80%
  - 一律使用拆股調整後（split-adjusted）OHLC，不使用 total-return（含股息還原）價格
    -> yfinance auto_adjust=False 抓到的 Open/High/Low/Close 正是拆股調整、不含股息還原
  - 近5年資料區間；ARM 因 2023-09-14 才上市，樣本區間從上市日起算（樣本數會明顯較短）

用法：
    python fcn_backtest.py --tickers NVDA,AMD,TSM,INTC,MU,GOOGL,META,AAPL,MSFT,TSLA,UNH,DELL,ARM \
        --out reports/fcn_backtest.csv --years 5

輸出欄位：
    股票, 類別, 資料起始日, 資料結束日, 樣本數N, 跌破80%次數, 跌破80%比例,
    跌破75%次數, 跌破75%比例, 跌破70%次數, 跌破70%比例,
    到期仍低於80%次數, 到期仍低於80%比例
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

HOLD_DAYS = 63  # 約3個月交易日
IPO_OVERRIDES = {
    "ARM": "2023-09-14",  # ARM Holdings IPO
}
CATEGORY = {
    "NVDA": "AI／GPU", "AMD": "半導體", "TSM": "半導體", "INTC": "半導體",
    "MU": "記憶體", "GOOGL": "大型科技", "META": "大型科技", "AAPL": "大型科技",
    "MSFT": "大型科技", "TSLA": "電動車", "UNH": "醫療", "DELL": "AI伺服器",
    "ARM": "半導體IP",
}


def fetch_ohlc(ticker: str, start: str) -> pd.DataFrame:
    df = yf.download(ticker, start=start, progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"{ticker} 沒有抓到資料")
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if c[1] == "" or c[1] == ticker else c[0] for c in df.columns]
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                             "Low": "low", "Close": "close"})
    return df[["date", "open", "high", "low", "close"]].sort_values("date").reset_index(drop=True)


def backtest_one(ticker: str, years: int = 5) -> dict:
    default_start = (datetime.now() - timedelta(days=365 * years + 30)).strftime("%Y-%m-%d")
    start = IPO_OVERRIDES.get(ticker, default_start)
    # ARM 上市日已經比5年區間晚，取較晚的那個當起點
    if ticker in IPO_OVERRIDES:
        start = IPO_OVERRIDES[ticker]

    df = fetch_ohlc(ticker, start=start)
    n_rows = len(df)
    closes = df["close"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    dates = df["date"]

    n_valid = n_rows - HOLD_DAYS  # 每個進場點都要有完整63天可觀察
    breach80 = breach75 = breach70 = expiry_below80 = 0

    for t in range(max(0, n_valid)):
        entry_price = closes[t]
        if entry_price <= 0 or np.isnan(entry_price):
            continue
        window_low = lows[t + 1: t + 1 + HOLD_DAYS]
        if len(window_low) < HOLD_DAYS:
            continue
        norm_low = window_low / entry_price * 100.0
        min_norm_low = np.nanmin(norm_low)

        if min_norm_low <= 80:
            breach80 += 1
        if min_norm_low <= 75:
            breach75 += 1
        if min_norm_low <= 70:
            breach70 += 1

        expiry_close = closes[t + HOLD_DAYS]
        norm_expiry_close = expiry_close / entry_price * 100.0
        if norm_expiry_close < 80:
            expiry_below80 += 1

    n = max(0, n_valid)
    def pct(x):
        return round(x / n * 100, 1) if n > 0 else None

    return {
        "股票": ticker,
        "類別": CATEGORY.get(ticker, ""),
        "資料起始日": str(dates.iloc[0].date()) if n_rows else None,
        "資料結束日": str(dates.iloc[-1].date()) if n_rows else None,
        "樣本數N": n,
        "跌破80%次數": breach80, "跌破80%比例": pct(breach80),
        "跌破75%次數": breach75, "跌破75%比例": pct(breach75),
        "跌破70%次數": breach70, "跌破70%比例": pct(breach70),
        "到期仍低於80%次數": expiry_below80, "到期仍低於80%比例": pct(expiry_below80),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True, help="逗號分隔的ticker清單")
    ap.add_argument("--out", default="reports/fcn_backtest.csv")
    ap.add_argument("--years", type=int, default=5)
    args = ap.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    rows = []
    errors = []
    for t in tickers:
        print(f"處理中：{t}")
        try:
            rows.append(backtest_one(t, years=args.years))
        except Exception as e:  # noqa: BLE001
            print(f"失敗：{t}（{e}）")
            errors.append({"股票": t, "錯誤": str(e)})

    out_df = pd.DataFrame(rows)
    out_df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"完成，共 {len(rows)} 檔，輸出到 {args.out}")

    if errors:
        err_path = args.out.replace(".csv", "_errors.csv")
        pd.DataFrame(errors).to_csv(err_path, index=False, encoding="utf-8-sig")
        print(f"{len(errors)} 檔失敗，詳見 {err_path}")


if __name__ == "__main__":
    main()
