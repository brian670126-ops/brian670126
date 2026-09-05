# -*- coding: utf-8 -*-
"""
data_fetcher.py
================
負責把 relation_map.csv / unique_tickers.csv 裡列出的全球關聯股，抓成跟你
台指期資料一樣的格式：datetime, open, high, low, close, volume。

⚠️ 執行環境提醒
----------------
這支程式需要對外連網（yfinance 會打 Yahoo Finance API），請在你自己的電腦或
有網路權限的環境執行，而不是在這個對話的沙箱容器裡（這裡的網路白名單只開放
pypi / github 等套件來源，沒有開放財經資料網域）。

用法
----
    python data_fetcher.py --tickers unique_tickers.csv --out data/global --start 2018-01-01

會在 data/global/ 底下，依每個 ticker 各存一個 CSV，欄位為：
    datetime, open, high, low, close, volume

台股本身（proprietary 資料）
-----------------------------
你已經有台指期的分鐘資料格式，個股的部分建議兩個選擇：
  1. 若券商/資料商也能給日線 OHLCV，直接用 load_local_ohlcv() 讀進來對齊格式即可。
  2. 若暫時沒有个股資料來源，也可以先用 yfinance 抓台股（代號後綴 .TW，
     例如 2330.TW），精度足夠拿來做「日線層級」的相關係數/勝率驗證；
     等你有更準的資料源後再換掉即可，correlation_engine.py 對資料來源沒有假設。
"""

from __future__ import annotations
import argparse
import time
from pathlib import Path

import pandas as pd


def fetch_yfinance_ohlcv(ticker: str, start: str = "2018-01-01",
                          end: str | None = None, retries: int = 3,
                          pause: float = 1.5) -> pd.DataFrame:
    """抓單一 ticker 的日線 OHLCV，回傳欄位標準化為
    datetime, open, high, low, close, volume。"""
    import yfinance as yf

    last_err = None
    for attempt in range(retries):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
            if df.empty:
                raise ValueError(f"{ticker} 沒有抓到任何資料，請確認代號是否正確（尤其台股需要 .TW / .TWO 後綴）")
            df = df.reset_index()
            # yfinance 新版可能回傳 MultiIndex 欄位，攤平成單層
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] if c[1] == '' or c[1] == ticker else c[0] for c in df.columns]
            df = df.rename(columns={
                "Date": "datetime", "Open": "open", "High": "high",
                "Low": "low", "Close": "close", "Volume": "volume",
            })
            return df[["datetime", "open", "high", "low", "close", "volume"]]
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(pause)
    raise RuntimeError(f"抓取 {ticker} 失敗，重試 {retries} 次後仍失敗：{last_err}")


def fetch_batch(tickers: list[str], out_dir: str, start: str = "2018-01-01",
                 end: str | None = None, pause: float = 1.5) -> dict[str, str]:
    """批次抓取多檔 ticker，逐檔存成 CSV，回傳 {ticker: 檔案路徑}。
    刻意逐檔 sleep，避免打太快被限流；失敗的 ticker 會印出來但不中斷整批。"""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    results = {}
    failed = []
    for i, t in enumerate(tickers, 1):
        try:
            df = fetch_yfinance_ohlcv(t, start=start, end=end)
            fp = out_path / f"{t.replace('/', '_')}.csv"
            df.to_csv(fp, index=False)
            results[t] = str(fp)
            print(f"[{i}/{len(tickers)}] 完成：{t} -> {fp}")
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(tickers)}] 失敗：{t}（{e}）")
            failed.append(t)
        time.sleep(pause)
    if failed:
        print("\n以下 ticker 抓取失敗，請手動確認代號或改用其他資料源：")
        for t in failed:
            print(f"  - {t}")
    return results


def load_local_ohlcv(csv_path: str, datetime_col: str = "datetime") -> pd.DataFrame:
    """讀取你自己既有格式的 CSV（datetime, open, high, low, close, volume）。"""
    df = pd.read_csv(csv_path, parse_dates=[datetime_col])
    return df.sort_values(datetime_col).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="批次抓取 relation_map 內的全球關聯股 OHLCV 資料")
    parser.add_argument("--tickers", required=True, help="unique_tickers.csv 路徑（一欄 yfinance_ticker）")
    parser.add_argument("--out", default="data/global", help="輸出資料夾")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--pause", type=float, default=1.5, help="每檔之間的秒數間隔，避免被限流")
    args = parser.parse_args()

    tickers_df = pd.read_csv(args.tickers)
    tickers = tickers_df["yfinance_ticker"].dropna().unique().tolist()
    print(f"共 {len(tickers)} 檔待抓取，輸出到 {args.out}/")
    fetch_batch(tickers, args.out, start=args.start, end=args.end, pause=args.pause)


if __name__ == "__main__":
    main()
