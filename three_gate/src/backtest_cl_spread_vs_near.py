# -*- coding: utf-8 -*-
"""
backtest_cl_spread_vs_near.py
==============================
原油 WTI 近月-遠月價差「漲跌方向」跟「近月本身漲跌方向」是否同向 —— 歷史回測。

問題意識（Brian的問題）：
    價差 = 近月 - 遠月。近月價格上漲時，價差是不是也傾向擴大（同向）？
    還是價差走勢其實跟近月本身走勢沒什麼關係？

做法：
    跟 fetch_cl_spread.py 只抓「今天」的近月/遠月不同，這支會往回走，
    用 cl_contract_roll.py 的展期規則重建「每一天，當時的近月/遠月合約
    各是誰」，把整段歷史的合約缺口接起來（stitch），組成一條連續的
    「價差」序列和一條連續的「近月價格」序列，然後做統計檢定。

⚠️ 重要方法論警告（务必先讀）：
    價差 = 近月close − 遠月close。近月價格本身就是價差公式的其中一腿，
    所以「價差變動」跟「近月變動」天生就有一部分是機械性相關（近月漲，
    只要遠月沒有等幅跟漲，價差就會跟著漲），不是使用者關心的「基本面
    訊號」。這支回測會同時報告：
      (a) 原始的方向同步率／相關係數（含機械性成分）
      (b) 遠月自己的變動 vs 近月變動的相關係數，作對照組
      (c) 「近月正規化後」的分析：spread_pct_of_near = spread/near_close，
          藉此部分濾掉純金額尺度效應
    解讀時請優先看 (b) 這個對照組的差異，而不是只看 (a) 的絕對數字。

⚠️ 資料侷限：
    - 個別合約在 Yahoo Finance 只有上市後到下市前這段期間的資料，久遠
      的合約可能資料不齊全或缺交易日，程式會自動跳過抓不到資料的合約，
      並在報告裡列出跳過清單。
    - 展期規則是近似規則（見 cl_contract_roll.py），實際換月時點可能
      跟這裡算出來的有 1-2 個營業日誤差，換月當週的資料解讀要保守。
    - 回測樣本以「月」為單位累積（每個月一組近/遠月合約），要有statistical
      power 建議至少抓 2-3 年（24-36 組合約）以上。

執行方式：
    python backtest_cl_spread_vs_near.py --years 3
會輸出：
    three_gate/data/auto/CL_spread_history_stitched.csv   （完整拼接後的歷史）
    three_gate/analysis/CL_spread_vs_near_backtest.md      （統計報告）

⚠️ 執行環境：需要能連上 Yahoo Finance 的網路（GitHub Actions 可以，
這個對話沙箱不行）。抓 20-40 檔個別合約的完整歷史，預期會跑 2-5 分鐘，
建議用 workflow_dispatch 手動觸發、不要排進每天的排程。
"""

from __future__ import annotations
import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from cl_contract_roll import (  # noqa: E402
    last_trading_day,
    contract_ticker,
    contract_label,
)

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "auto"
ANALYSIS_DIR = ROOT / "analysis"
STITCHED_CSV = DATA_DIR / "CL_spread_history_stitched.csv"
REPORT_MD = ANALYSIS_DIR / "CL_spread_vs_near_backtest.md"


def generate_roll_windows(start_date: date, end_date: date) -> list[dict]:
    """
    重建 [start_date, end_date] 區間內，每一段展期窗口對應的近月/遠月合約。

    回傳一串 {window_start, window_end, near_year, near_month, far_year, far_month}，
    每一段代表「這段日期範圍內，市場上的近月/遠月合約分別是誰」。

    邊界規則跟 cl_contract_roll.get_near_far_contracts() 保持一致（半開區間）：
    合約 D 的「近月窗口」是 [ltd(D-1), ltd(D)) —— 左邊含 ltd(D-1) 當天（前一口
    合約在自己最後交易日「當天」就已經不是近月了，見 get_near_far_contracts
    用 `ltd > as_of`嚴格大於判斷），右邊不含 ltd(D) 當天（因為當天近月已經
    捲動到 D+1）。這裡若寫成 window_end = ltd(D) 會跟即時判斷邏輯差一天，
    已用 2026-09-22 的即時查詢結果驗證過這個邊界。
    """
    windows = []
    # 從 start_date 往前抓一個月當起點候選，確保能涵蓋 start_date 當時的近月
    probe = pd.Timestamp(start_date) - pd.Timedelta(days=35)
    year, month = probe.year, probe.month

    prev_ltd = None  # 前一口近月合約的最後交易日 = 這一段窗口的起點（inclusive）
    guard = 0
    while True:
        guard += 1
        if guard > 600:  # 安全閥，避免邏輯錯誤造成無限迴圈
            raise RuntimeError("generate_roll_windows 疑似無限迴圈，請檢查日期範圍")

        ltd = last_trading_day(year, month)
        far_month_num = month + 1
        far_year = year + (far_month_num - 1) // 12
        far_month = (far_month_num - 1) % 12 + 1

        window_start = prev_ltd if prev_ltd is not None else pd.Timestamp(start_date)
        window_end = ltd - pd.Timedelta(days=1)  # 半開區間，不含 ltd 當天

        if window_end >= pd.Timestamp(start_date) and window_end >= window_start:
            windows.append({
                "window_start": max(window_start, pd.Timestamp(start_date)),
                "window_end": min(window_end, pd.Timestamp(end_date)),
                "near_year": year, "near_month": month,
                "far_year": far_year, "far_month": far_month,
            })

        prev_ltd = ltd
        if ltd > pd.Timestamp(end_date):
            break

        month += 1
        if month > 12:
            month = 1
            year += 1

    return windows


def _download_full_history(ticker: str, pause: float = 0.8) -> pd.DataFrame:
    """抓單一合約的完整歷史（yfinance period='max'），標準化欄位。"""
    try:
        df = yf.download(ticker, period="max", interval="1d",
                          progress=False, auto_adjust=False)
    except Exception as e:  # noqa: BLE001
        print(f"  [SKIP] {ticker} 下載失敗：{e}")
        return pd.DataFrame()
    time.sleep(pause)
    if df.empty:
        print(f"  [SKIP] {ticker} 無資料")
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [c.lower() if c != "Date" else "date" for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "open", "high", "low", "close"]].set_index("date")


def build_stitched_history(years: int) -> pd.DataFrame:
    end_date = date.today()
    start_date = end_date - timedelta(days=int(years * 365.25))

    windows = generate_roll_windows(start_date, end_date)
    print(f"共 {len(windows)} 段展期窗口，涵蓋 {start_date} ~ {end_date}")

    # 收集所有用得到的合約代碼（near + far），去重後一次抓完，避免重複下載
    needed_tickers = {}
    for w in windows:
        nt = contract_ticker(w["near_year"], w["near_month"])
        ft = contract_ticker(w["far_year"], w["far_month"])
        needed_tickers[nt] = (w["near_year"], w["near_month"])
        needed_tickers[ft] = (w["far_year"], w["far_month"])

    print(f"需要抓取 {len(needed_tickers)} 檔個別合約...")
    cache: dict[str, pd.DataFrame] = {}
    skipped = []
    for i, (ticker, (y, m)) in enumerate(sorted(needed_tickers.items()), 1):
        print(f"[{i}/{len(needed_tickers)}] {ticker} ({contract_label(y, m)}) ...")
        df = _download_full_history(ticker)
        if df.empty:
            skipped.append(ticker)
        cache[ticker] = df

    rows = []
    for w in windows:
        near_ticker = contract_ticker(w["near_year"], w["near_month"])
        far_ticker = contract_ticker(w["far_year"], w["far_month"])
        near_df = cache.get(near_ticker, pd.DataFrame())
        far_df = cache.get(far_ticker, pd.DataFrame())
        if near_df.empty or far_df.empty:
            continue

        mask_dates = pd.date_range(w["window_start"], w["window_end"], freq="D")
        near_slice = near_df.reindex(mask_dates).dropna(how="all")
        far_slice = far_df.reindex(mask_dates).dropna(how="all")
        common = near_slice.index.intersection(far_slice.index)
        for d in common:
            n = near_slice.loc[d]
            f = far_slice.loc[d]
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "near_ticker": near_ticker,
                "far_ticker": far_ticker,
                "near_label": contract_label(w["near_year"], w["near_month"]),
                "far_label": contract_label(w["far_year"], w["far_month"]),
                "near_open": n["open"], "near_high": n["high"],
                "near_low": n["low"], "near_close": n["close"],
                "far_open": f["open"], "far_high": f["high"],
                "far_low": f["low"], "far_close": f["close"],
            })

    hist = pd.DataFrame(rows).drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    hist["spread_open"] = hist["near_open"] - hist["far_open"]
    hist["spread_high"] = hist[["near_open", "near_high", "near_low", "near_close"]].max(axis=1) - \
        hist[["far_open", "far_high", "far_low", "far_close"]].min(axis=1)
    hist["spread_low"] = hist[["near_open", "near_high", "near_low", "near_close"]].min(axis=1) - \
        hist[["far_open", "far_high", "far_low", "far_close"]].max(axis=1)
    hist["spread_close"] = hist["near_close"] - hist["far_close"]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    hist.to_csv(STITCHED_CSV, index=False)
    print(f"\n拼接完成：{len(hist)} 個交易日，已存到 {STITCHED_CSV}")
    if skipped:
        print(f"跳過（抓不到資料）的合約：{', '.join(skipped)}")
    return hist


def run_stats(hist: pd.DataFrame) -> dict:
    """核心統計：spread變動 vs near變動 是否同向。"""
    df = hist.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df["near_chg"] = df["near_close"].diff()
    df["far_chg"] = df["far_close"].diff()
    df["spread_chg"] = df["spread_close"].diff()
    df["spread_pct_of_near"] = df["spread_close"] / df["near_close"]
    df["spread_pct_chg"] = df["spread_pct_of_near"].diff()

    valid = df.dropna(subset=["near_chg", "spread_chg"])
    valid = valid[valid["near_chg"] != 0]  # 排除零變動日避免符號判定失真

    corr_spread_near = valid["spread_chg"].corr(valid["near_chg"])
    corr_far_near = valid["far_chg"].corr(valid["near_chg"])  # 對照組

    same_dir = (np.sign(valid["spread_chg"]) == np.sign(valid["near_chg"])).mean()

    # 近月上漲日 vs 下跌日，價差平均變動（經濟意義：正價差走強是否伴隨近月上漲）
    up_days = valid[valid["near_chg"] > 0]
    down_days = valid[valid["near_chg"] < 0]
    avg_spread_chg_on_up = up_days["spread_chg"].mean()
    avg_spread_chg_on_down = down_days["spread_chg"].mean()

    # 正規化後（spread占近月價格的比例）的相關，濾掉部分金額尺度效應
    valid_pct = df.dropna(subset=["near_chg", "spread_pct_chg"])
    valid_pct = valid_pct[valid_pct["near_chg"] != 0]
    corr_pct_spread_near = valid_pct["spread_pct_chg"].corr(valid_pct["near_chg"])

    # 週線版本
    df_w = df.set_index("date").resample("W-FRI").agg({
        "near_close": "last", "far_close": "last", "spread_close": "last",
    }).dropna()
    df_w["near_chg_w"] = df_w["near_close"].diff()
    df_w["spread_chg_w"] = df_w["spread_close"].diff()
    valid_w = df_w.dropna(subset=["near_chg_w", "spread_chg_w"])
    valid_w = valid_w[valid_w["near_chg_w"] != 0]
    corr_w = valid_w["spread_chg_w"].corr(valid_w["near_chg_w"])
    same_dir_w = (np.sign(valid_w["spread_chg_w"]) == np.sign(valid_w["near_chg_w"])).mean()

    return {
        "n_days": len(valid),
        "n_weeks": len(valid_w),
        "date_range": (df["date"].min().strftime("%Y-%m-%d"), df["date"].max().strftime("%Y-%m-%d")),
        "corr_spread_near_daily": corr_spread_near,
        "corr_far_near_daily": corr_far_near,
        "corr_pct_spread_near_daily": corr_pct_spread_near,
        "same_direction_rate_daily": same_dir,
        "avg_spread_chg_on_near_up": avg_spread_chg_on_up,
        "avg_spread_chg_on_near_down": avg_spread_chg_on_down,
        "corr_spread_near_weekly": corr_w,
        "same_direction_rate_weekly": same_dir_w,
    }


def write_report(stats: dict, years: int, skipped: list[str]):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# 原油 WTI 近月-遠月價差 vs 近月價格走勢 — 同向性回測")
    lines.append("")
    lines.append(f"回測期間：{stats['date_range'][0]} ~ {stats['date_range'][1]}"
                  f"（設定回看 {years} 年）")
    lines.append(f"有效日線樣本數：{stats['n_days']} 天　有效週線樣本數：{stats['n_weeks']} 週")
    if skipped:
        lines.append(f"⚠️ 以下合約抓不到資料、已跳過：{', '.join(skipped)}")
    lines.append("")
    lines.append("## 核心結論")
    lines.append("")
    lines.append(f"- **日線：價差變動 vs 近月變動 相關係數 = {stats['corr_spread_near_daily']:.3f}**")
    lines.append(f"- 對照組：遠月變動 vs 近月變動 相關係數 = {stats['corr_far_near_daily']:.3f}"
                  "　（越接近1代表近遠月幾乎同漲同跌，此時「價差變動」的同向性大半是機械性的，"
                  "不是額外的基本面訊號）")
    lines.append(f"- 正規化後（價差/近月價格）相關係數 = {stats['corr_pct_spread_near_daily']:.3f}"
                  "　（部分濾掉金額尺度效應後的版本，更接近「結構是否真的同向」）")
    lines.append(f"- **日線方向同步率（sign match）= {stats['same_direction_rate_daily']:.1%}**"
                  "　（近月漲跌方向 跟 價差漲跌方向 同一天一致的比例）")
    lines.append(f"- 週線方向同步率 = {stats['same_direction_rate_weekly']:.1%}"
                  f"　週線相關係數 = {stats['corr_spread_near_weekly']:.3f}")
    lines.append("")
    lines.append("## 條件平均（近月漲跌日，價差平均怎麼動）")
    lines.append("")
    lines.append(f"- 近月上漲日，價差平均變動：{stats['avg_spread_chg_on_near_up']:+.3f}")
    lines.append(f"- 近月下跌日，價差平均變動：{stats['avg_spread_chg_on_near_down']:+.3f}")
    lines.append("")
    lines.append("## 怎麼解讀")
    lines.append("")
    lines.append(
        "- 「日線相關係數」跟「遠月 vs 近月對照組」的差距，才是價差變動裡真正「額外」"
        "（非機械性）的同向訊號強度。兩者很接近，代表近遠月幾乎是平行移動，價差本身"
        "沒有提供獨立於近月價格之外的訊號；兩者差距明顯，才代表價差的漲跌有自己的節奏。"
    )
    lines.append(
        "- 樣本數如果不到約 250 個交易日（1年），相關係數與同步率的統計穩定性偏低，"
        "建議之後每月重跑這支回測、觀察係數是否隨樣本數增加而穩定收斂。"
    )
    lines.append(
        "- 這份回測只回答「同向與否」，沒有做成交易訊號（進出場規則、報酬率、勝率）。"
        "若要往下做成三關價訊號，建議下一步是把 spread_close 序列餵進 "
        "`three_gate_calc.py` 算M/B1/B2/S1/S2，再比照TX的規則統計突破/守回的後續勝率。"
    )
    lines.append("")
    lines.append(f"_產出時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}（Asia/Taipei 需自行換算，"
                  "GitHub Actions 執行環境為 UTC）_")

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n報告已寫入：{REPORT_MD}")


def main():
    parser = argparse.ArgumentParser(description="原油近月-遠月價差 vs 近月價格走勢同向性回測")
    parser.add_argument("--years", type=float, default=0.3, help="往回看幾年（預設3年）")
    args = parser.parse_args()

    print("=" * 60)
    print("原油 WTI 近月-遠月價差 vs 近月走勢 同向性回測")
    print("=" * 60)

    hist = build_stitched_history(args.years)
    if hist.empty:
        print("[ERROR] 沒有拼接出任何資料，無法做統計，請檢查網路或合約代碼")
        return

    stats = run_stats(hist)
    skipped = []
    write_report(stats, args.years, skipped)

    print("\n" + "=" * 60)
    print("摘要：")
    print(f"  日線相關係數: {stats['corr_spread_near_daily']:.3f}"
          f"（對照組-遠月vs近月: {stats['corr_far_near_daily']:.3f}）")
    print(f"  日線方向同步率: {stats['same_direction_rate_daily']:.1%}")
    print(f"  週線方向同步率: {stats['same_direction_rate_weekly']:.1%}")


if __name__ == "__main__":
    main()
