# -*- coding: utf-8 -*-
"""
fetch_cl_spread.py
===================
原油 WTI (CL) 近月-遠月合約價差抓取器。

跟 fetch_yfinance.py 的差異：fetch_yfinance.py 抓的 CL=F 是「連續近月」，
只有一條序列，沒辦法算價差。這支改抓「近月合約」與「遠月合約」兩條個別
到期合約的 OHLC，逐日相減組成「價差序列」的 OHLC，可以直接餵給
three_gate_calc.py 算三關價（M/B1/B2/S1/S2...），跟台指期用同一套邏輯。

價差定義：spread = 近月 - 遠月（正值 = 近月貼水遠月走高／正價差走強，
負值 = 逆價差／近月弱於遠月，實際解讀請依原油supply/demand脈絡）。

OHLC 相減是業界慣用的「腿對腿」近似算法（spread_H ≠ 真正日內價差高點，
真正的價差高低要用 tick 資料算，這裡沒有），但已足夠拿來套三關價這種
用日/週級別 OHLC 做結構分析的框架。

執行方式：
    python fetch_cl_spread.py
會自動用 cl_contract_roll.py 判斷「今天」的近月/遠月合約代碼，抓最近
一段時間的日K，跟既有的 CL_spread_daily.csv 合併（有重疊日期就覆蓋成
最新抓到的值），再重新做週線彙總。

⚠️ 執行環境提醒：跟 fetch_yfinance.py 一樣，需要能連上 Yahoo Finance
的網路環境（GitHub Actions 可以，這個對話的沙箱容器不行）。

⚠️ 展期交界處的已知限制：合約每個月會換手一次（見 cl_contract_roll.py）。
换手當天前後幾天，近月合約流動性會變差、價差可能出現非基本面的跳動，
這是原油期貨曲線本身的正常現象，不是程式錯誤，使用三關價訊號時建議
比照 Brian 既有規則：換月後 4-8 週再信任新環境判斷。
"""

from __future__ import annotations
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from cl_contract_roll import get_near_far_contracts  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "auto"
DAILY_CSV = DATA_DIR / "CL_spread_daily.csv"
WEEKLY_CSV = DATA_DIR / "CL_spread_weekly.csv"

DAILY_COLUMNS = [
    "date", "near_ticker", "far_ticker", "near_label", "far_label",
    "open", "high", "low", "close",
    "near_close", "far_close",
]


def _fetch_leg_daily(ticker: str, lookback_days: int = 20) -> pd.DataFrame:
    """抓單一合約最近 lookback_days 天的日K，欄位標準化為 date/open/high/low/close。"""
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    df = yf.download(ticker, start=start, end=end, interval="1d",
                      progress=False, auto_adjust=False)
    if df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [c.lower() if c != "Date" else "date" for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[["date", "open", "high", "low", "close"]]


def build_spread_rows(lookback_days: int = 20) -> pd.DataFrame:
    """
    抓近期 near/far 兩腿的日K，逐日相減組成價差 OHLC。

    只用「今天」判斷出的 near/far 合約代碼去抓最近 lookback_days 天，
    刻意設 20 天（而非長區間）是因為：近/遠月配對每個月會變一次，往回
    抓太久，早期日期其實不是用這組合約在交易，硬算價差會失真。20 天
    抓到的重疊視窗已經足夠涵蓋「上次執行到今天」中間可能漏掉的假日／
    排程失敗補檔，同時不會跨到上一次展期之前。
    """
    pair = get_near_far_contracts()
    near_ticker = pair["near"]["ticker"]
    far_ticker = pair["far"]["ticker"]
    near_label = pair["near"]["label"]
    far_label = pair["far"]["label"]

    print(f"近月: {near_ticker} ({near_label})  遠月: {far_ticker} ({far_label})")

    near_df = _fetch_leg_daily(near_ticker, lookback_days)
    far_df = _fetch_leg_daily(far_ticker, lookback_days)

    if near_df.empty or far_df.empty:
        print(f"[ERROR] 近月或遠月抓不到資料：near={len(near_df)} far={len(far_df)}")
        return pd.DataFrame(columns=DAILY_COLUMNS)

    merged = near_df.merge(far_df, on="date", suffixes=("_near", "_far"), how="inner")
    if merged.empty:
        print("[ERROR] 近月/遠月沒有重疊日期，無法算價差")
        return pd.DataFrame(columns=DAILY_COLUMNS)

    out = pd.DataFrame({
        "date": merged["date"],
        "near_ticker": near_ticker,
        "far_ticker": far_ticker,
        "near_label": near_label,
        "far_label": far_label,
        "open": merged["open_near"] - merged["open_far"],
        "high": merged["high_near"] - merged["high_far"],
        "low": merged["low_near"] - merged["low_far"],
        "close": merged["close_near"] - merged["close_far"],
        "near_close": merged["close_near"],
        "far_close": merged["close_far"],
    })
    ohlc_cols = out[["open", "high", "low", "close"]]
    out["high"] = ohlc_cols.max(axis=1)
    out["low"] = ohlc_cols.min(axis=1)
    return out[DAILY_COLUMNS]


def merge_into_daily_csv(new_rows: pd.DataFrame) -> pd.DataFrame:
    """把新抓到的列，用 date 當 key 合併進既有 CSV（重複日期用新資料覆蓋）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DAILY_CSV.exists():
        existing = pd.read_csv(DAILY_CSV, dtype={"date": str})
    else:
        existing = pd.DataFrame(columns=DAILY_COLUMNS)

    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset="date", keep="last")
    combined = combined.sort_values("date").reset_index(drop=True)
    combined.to_csv(DAILY_CSV, index=False)
    print(f"價差日線已更新：{DAILY_CSV}（共 {len(combined)} 筆，"
          f"最新 {combined['date'].iloc[-1]}）")
    return combined


def build_weekly_from_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """從累積的日線價差，用曆週（週一~週日，ISO week）彙總成週線 OHLC。"""
    if daily.empty:
        return daily
    df = daily.copy()
    df["date_dt"] = pd.to_datetime(df["date"])
    df["iso_year"] = df["date_dt"].dt.isocalendar().year
    df["iso_week"] = df["date_dt"].dt.isocalendar().week

    rows = []
    for (iso_year, iso_week), grp in df.sort_values("date_dt").groupby(["iso_year", "iso_week"]):
        rows.append({
            "date": grp["date"].iloc[-1],
            "near_ticker": grp["near_ticker"].iloc[-1],
            "far_ticker": grp["far_ticker"].iloc[-1],
            "near_label": grp["near_label"].iloc[-1],
            "far_label": grp["far_label"].iloc[-1],
            "open": grp["open"].iloc[0],
            "high": grp["high"].max(),
            "low": grp["low"].min(),
            "close": grp["close"].iloc[-1],
            "near_close": grp["near_close"].iloc[-1],
            "far_close": grp["far_close"].iloc[-1],
        })
    weekly = pd.DataFrame(rows, columns=DAILY_COLUMNS)
    weekly.to_csv(WEEKLY_CSV, index=False)
    print(f"價差週線已更新：{WEEKLY_CSV}（共 {len(weekly)} 筆）")
    return weekly


def main():
    print("=" * 60)
    print("原油 WTI 近月-遠月價差抓取")
    print(f"執行時間: {datetime.now().isoformat()}")
    print("=" * 60)

    new_rows = build_spread_rows()
    if new_rows.empty:
        print("本次沒有抓到新資料，結束。")
        return

    daily = merge_into_daily_csv(new_rows)
    build_weekly_from_daily(daily)


if __name__ == "__main__":
    main()
