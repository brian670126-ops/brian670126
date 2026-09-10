# -*- coding: utf-8 -*-
"""
daily_pipeline.py
==================
每天自動執行一次的主程式：
  1. 讀 watchlist.csv（你要追蹤的目標股清單）
  2. 讀 relation_map_v2.csv，找出每檔目標股對應的關聯股
  3. 用 yfinance 增量更新（只抓最近一段時間，不用每次都抓全部歷史）目標股 +
     所有關聯股的股價
  4. 對每檔目標股跑 correlation_engine 的計分表 + 趨勢延續分數
  5. 把結果彙整成一份報表，存到 reports/YYYY-MM-DD.csv，並印出摘要

設計成可以被排程工具（cron / launchd）每天觸發一次，不需要人工介入。
"""

from __future__ import annotations
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from data_fetcher import fetch_yfinance_ohlcv          # noqa: E402
from correlation_engine import (                        # noqa: E402
    load_returns, build_relation_scorecard, trend_continuation_score,
)
from dashboard_builder import build_and_save_dashboard  # noqa: E402

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "global"
REPORT_DIR = BASE_DIR / "reports"
RELATION_MAP_PATH = BASE_DIR / "relation_map_v2.csv"
WATCHLIST_PATH = BASE_DIR / "watchlist.csv"
LOG_PATH = BASE_DIR / "daily_pipeline.log"

# 台灣時間(UTC+8)——GitHub Actions 執行機器本身用的是 UTC 系統時間，
# 若直接用 datetime.now()，遇到執行時間拉長、跨過 UTC 午夜時，「今天」
# 會被算成前一天，導致報表被存成錯誤日期的檔名（甚至覆蓋掉前一天的報表）。
# 所以「今天」一律以台灣時間為準，跟伺服器本身在哪個時區、跑多久都無關。
TAIWAN_TZ = timezone(timedelta(hours=8))


def today_taiwan() -> str:
    return datetime.now(TAIWAN_TZ).strftime("%Y-%m-%d")

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    line = f"[{datetime.now(TAIWAN_TZ):%Y-%m-%d %H:%M:%S} 台灣時間] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def update_ticker_csv(ticker: str, lookback_days: int = 400):
    """增量更新：抓最近 lookback_days 天，跟舊資料合併去重後存回去。
    lookback_days 設寬一點（例如 400 天）確保相關係數視窗(120日)永遠有足夠資料，
    同時避免每天都要重抓全部歷史（節省時間與避免被限流）。"""
    fp = DATA_DIR / f"{ticker.replace('/', '_')}.csv"
    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    new_df = fetch_yfinance_ohlcv(ticker, start=start)

    if fp.exists():
        old_df = pd.read_csv(fp, parse_dates=["datetime"])
        merged = pd.concat([old_df, new_df]).drop_duplicates(subset="datetime").sort_values("datetime")
    else:
        merged = new_df.sort_values("datetime")

    merged.to_csv(fp, index=False)
    return fp


def run_for_target(target_ticker: str, target_number: int, relation_map: pd.DataFrame) -> dict:
    relation_for_target = relation_map[
        (relation_map["編號"] == target_number) & (relation_map["關聯欄位"] != "台灣核心股")
    ].drop_duplicates(subset="yfinance_ticker")

    price_data = {}
    try:
        update_ticker_csv(target_ticker)
        price_data[target_ticker] = load_returns(str(DATA_DIR / f"{target_ticker}.csv"))
    except Exception as e:  # noqa: BLE001
        log(f"⚠️ 目標股 {target_ticker} 更新失敗：{e}")
        return {"target": target_ticker, "error": str(e)}

    for _, row in relation_for_target.iterrows():
        t = row.get("yfinance_ticker")
        if not t or pd.isna(t):
            continue
        try:
            update_ticker_csv(t)
            price_data[t] = load_returns(str(DATA_DIR / f"{t}.csv"))
        except Exception as e:  # noqa: BLE001
            log(f"⚠️ 關聯股 {t} 更新失敗，跳過：{e}")
        time.sleep(0.8)  # 放慢一點，避免被 Yahoo 限流

    scorecard = build_relation_scorecard(target_ticker, relation_for_target, price_data)
    latest_returns = {t: s.iloc[-1] for t, s in price_data.items() if t != target_ticker and len(s)}
    score = trend_continuation_score(scorecard, latest_returns)

    return {
        "target": target_ticker,
        "date": today_taiwan(),
        "direction_score": score["direction_score"],
        "score_100": score["score_100"],
        "label": score["label"],
        "confidence": score["confidence"],
        "top_contributors": score["contributing"][:5],
        "scorecard": scorecard,
    }


def main():
    if not WATCHLIST_PATH.exists():
        log(f"找不到 {WATCHLIST_PATH}，請先建立 watchlist.csv（欄位：編號, 目標股代號）")
        return

    watchlist = pd.read_csv(WATCHLIST_PATH)
    relation_map = pd.read_csv(RELATION_MAP_PATH)

    today = today_taiwan()
    report_rows = []
    log(f"開始執行每日分析，共 {len(watchlist)} 檔目標股")

    for _, row in watchlist.iterrows():
        target_number = int(row["編號"])
        target_ticker = str(row["目標股代號"])
        log(f"處理中：編號{target_number} - {target_ticker}")
        try:
            result = run_for_target(target_ticker, target_number, relation_map)
        except Exception as e:  # noqa: BLE001
            log(f"❌ {target_ticker} 執行失敗：{e}\n{traceback.format_exc()}")
            continue

        if "error" in result:
            continue

        result["scorecard"].to_csv(
            REPORT_DIR / f"scorecard_{target_ticker.replace('.', '_')}_{today}.csv",
            index=False, encoding="utf-8-sig",
        )
        report_rows.append({
            "日期": today, "目標股": target_ticker,
            "趨勢延續分數": result["direction_score"],
            "趨勢延續分數_100": result["score_100"],
            "趨勢延續標籤": result["label"],
            "信心": result["confidence"],
            "主要貢獻1": result["top_contributors"][0]["公司名稱"] if result["top_contributors"] else "",
        })
        log(f"完成：{target_ticker} 趨勢延續分數={result['score_100']}（{result['label']}，{result['confidence']}）")

    if report_rows:
        summary = pd.DataFrame(report_rows)
        summary_path = REPORT_DIR / f"summary_{today}.csv"
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
        log(f"每日摘要已存到 {summary_path}")

        try:
            dashboard_path = build_and_save_dashboard(report_rows, today)
            log(f"好讀版看板已存到 {dashboard_path}（同一份也存了 dashboard_{today}.html）")
        except Exception as e:  # noqa: BLE001
            log(f"⚠️ 產生看板失敗（不影響報表本身）：{e}\n{traceback.format_exc()}")

    log("本次執行完畢\n")


if __name__ == "__main__":
    main()
