# -*- coding: utf-8 -*-
"""
correlation_engine.py
======================
把「全球產業連動總表」裡的★★★★★星等（產業關聯重要度），逐步換成實際數據算出來的
相關係數 / 領先—落後勝率，用來判斷台灣個股當天的趨勢是否會延續。

延續 Brian 既有回測框架的統計原則：
- 樣本數門檻：<30=僅供觀察；30–100=可謹慎推論方向；>100–200=具參考意義
- 用卡方檢定驗證方向一致性github.com/brian670126-ops/brian670126是否顯著偏離隨機
- 極端事件（樣本太少）用合併分組處理，而不是硬湊樣本數

輸入資料格式（沿用你既有的 CSV 慣例）：
    datetime, open, high, low, close, volume
    - 台股／台指期：可用你現有的分鐘或日資料
    - 全球關聯股：用 data_fetcher.py 抓到的日資料（yfinance predominantly daily bar）

核心概念
--------
1. rolling_correlation      台股與關聯股「報酬率」的 20/60/120 日滾動相關係數
2. lagged_directional_test  「海外股 T 日漲跌方向」→「台股 T+1 日漲跌方向」的同向勝率 + 卡方檢定
3. build_relation_scorecard 把 relation_map.csv 裡每一檔關聯股，換算成一張「實際數據版」的關聯度計分表
4. trend_continuation_score 針對目標股，用計分表 + 最新一天各關聯股報酬率，算出「趨勢延續分數」
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


# ----------------------------------------------------------------------
# 樣本數 → 可信度分級（沿用 Brian 既有的門檻慣例）
# ----------------------------------------------------------------------
def sample_confidence_label(n: int) -> str:
    if n < 30:
        return "樣本不足（<30，僅供觀察，不做方向推論）"
    elif n < 100:
        return "樣本偏少（30–100，可謹慎推論方向）"
    elif n < 200:
        return "樣本尚可（100–200，具參考意義）"
    else:
        return "樣本充足（>200，具統計意義）"


# ----------------------------------------------------------------------
# 顯示比例尺與級距標籤（2026-09-08 與 Brian 討論定案）
# ----------------------------------------------------------------------
# 相關係數 / 趨勢延續分數原本是 -1~+1，顯示時 x100 換成 -100~+100 比較有感覺。
# 級距每 10 分一階（共 20 階），文字標籤依「強度」分組共用，相關係数跟趨勢延續
# 分數語意不同（同動強弱 vs 會不會延續、往哪個方向），用兩套標籤。
# 這只是顯示層的轉換，不影響 composite_weight / 卡方檢定 / 樣本數門檻的計算邏輯。

CORR_TIER_LABELS = [
    (70, 100, "強烈同向連動"),
    (40, 70, "中度同向連動"),
    (10, 40, "弱同向連動"),
    (-10, 10, "幾乎無關聯"),
    (-40, -10, "弱反向連動"),
    (-70, -40, "中度反向連動"),
    (-100, -70, "強烈反向連動"),
]

TREND_TIER_LABELS = [
    (70, 100, "強烈偏多延續"),
    (40, 70, "中度偏多延續"),
    (10, 40, "弱偏多延續"),
    (-10, 10, "方向不明/觀望"),
    (-40, -10, "弱偏空延續"),
    (-70, -40, "中度偏空延續"),
    (-100, -70, "強烈偏空延續"),
]


def scale_to_100(x: float) -> Optional[float]:
    """-1~+1 轉成 -100~+100，純顯示用，不改變底層統計意義。"""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x) * 100, 1)


def label_for_score(score_100: Optional[float], label_table: list) -> str:
    if score_100 is None:
        return "無資料"
    for lo, hi, label in label_table:
        if lo <= score_100 <= hi:
            return label
    return "無資料"


# ----------------------------------------------------------------------
# 1. 讀取價格資料 → 報酬率序列
# ----------------------------------------------------------------------
def load_returns(csv_path: str, datetime_col: str = "datetime",
                  price_col: str = "close", freq: Optional[str] = None) -> pd.Series:
    """讀取 OHLCV CSV，回傳以 datetime 為 index 的日報酬率（簡單報酬率）。
    若資料是分鐘線，可傳入 freq='1D' 先重採樣成日收盤價再算報酬率。"""
    df = pd.read_csv(csv_path, parse_dates=[datetime_col])
    df = df.set_index(datetime_col).sort_index()
    price = df[price_col]
    if freq:
        price = price.resample(freq).last().dropna()
    returns = price.pct_change().dropna()
    returns.name = price_col
    return returns


def align_returns(target: pd.Series, peer: pd.Series) -> pd.DataFrame:
    """把台股與關聯股的報酬率對齊到共同交易日，並各自標記欄位名稱。"""
    aligned = pd.concat(
        [target.rename("target"), peer.rename("peer")], axis=1, join="inner"
    ).dropna()
    return aligned


# ----------------------------------------------------------------------
# 2. 滾動相關係數（20 / 60 / 120 日）
# ----------------------------------------------------------------------
def rolling_correlation(target: pd.Series, peer: pd.Series,
                         windows=(10, 20, 60, 120)) -> pd.DataFrame:
    aligned = align_returns(target, peer)
    out = pd.DataFrame(index=aligned.index)
    for w in windows:
        out[f"corr_{w}d"] = aligned["target"].rolling(w).corr(aligned["peer"])
    return out


def latest_correlation_summary(target: pd.Series, peer: pd.Series,
                                windows=(10, 20, 60, 120)) -> dict:
    """回傳目前最新一筆的 20/60/120 日相關係數（給計分表用）。"""
    roll = rolling_correlation(target, peer, windows)
    if roll.empty:
        return {f"corr_{w}d": np.nan for w in windows}
    last = roll.iloc[-1]
    return {col: last[col] for col in roll.columns}


# ----------------------------------------------------------------------
# 3. 落後—領先方向勝率（海外 T 日 → 台股 T+1 日）+ 卡方檢定
# ----------------------------------------------------------------------
@dataclass
class LaggedDirectionalResult:
    n: int
    win_rate: float          # 海外 T 漲、台股 T+1 也漲（或都跌）的同向比例
    chi2_stat: float
    chi2_pvalue: float
    confidence_label: str


def lagged_directional_test(peer: pd.Series, target: pd.Series,
                             lag: int = 1) -> LaggedDirectionalResult:
    """
    檢定：peer 在 T 日的漲跌方向，能否預測 target 在 T+lag 日的漲跌方向。
    用 2x2 列聯表做卡方檢定（peer 漲/跌 × target 漲/跌），
    避免把「同向」的巧合誤判為有意義的領先關係。
    """
    aligned = pd.concat(
        [peer.rename("peer"), target.rename("target")], axis=1, join="inner"
    ).dropna()
    if aligned.empty:
        return LaggedDirectionalResult(0, np.nan, np.nan, np.nan, sample_confidence_label(0))

    peer_sign = np.sign(aligned["peer"])
    target_sign_fwd = np.sign(aligned["target"].shift(-lag))
    df = pd.concat([peer_sign.rename("peer_sign"),
                     target_sign_fwd.rename("target_sign")], axis=1).dropna()
    df = df[(df["peer_sign"] != 0) & (df["target_sign"] != 0)]

    n = len(df)
    if n == 0:
        return LaggedDirectionalResult(0, np.nan, np.nan, np.nan, sample_confidence_label(0))

    same_dir = (df["peer_sign"] == df["target_sign"]).sum()
    win_rate = same_dir / n

    # 2x2 列聯表：列=peer漲/跌，欄=target(T+lag)漲/跌
    table = pd.crosstab(df["peer_sign"] > 0, df["target_sign"] > 0)
    # 補齊缺的欄/列，避免 crosstab 只有一類時形狀不足 2x2
    for idx in [True, False]:
        if idx not in table.index:
            table.loc[idx] = 0
        if idx not in table.columns:
            table[idx] = 0
    table = table.sort_index().sort_index(axis=1)

    try:
        from scipy.stats import chi2_contingency
        chi2_stat, chi2_p, _, _ = chi2_contingency(table.values)
    except Exception:
        chi2_stat, chi2_p = np.nan, np.nan

    return LaggedDirectionalResult(
        n=n,
        win_rate=win_rate,
        chi2_stat=chi2_stat,
        chi2_pvalue=chi2_p,
        confidence_label=sample_confidence_label(n),
    )


# ----------------------------------------------------------------------
# 4. 把 relation_map.csv 的星等，換算成「實際數據版」計分表
# ----------------------------------------------------------------------
def build_relation_scorecard(target_ticker: str,
                              relation_df: pd.DataFrame,
                              price_data: dict[str, pd.Series],
                              lag: int = 1,
                              windows=(10, 20, 60, 120)) -> pd.DataFrame:
    """
    relation_df: 從 relation_map.csv 讀進來、且已篩選出「編號==目標股所在列」的關聯股清單
                 需要欄位：關聯欄位, 公司名稱, yfinance_ticker, 星等
    price_data:  dict，key 是 yfinance_ticker，value 是該股的日報酬率 pd.Series
                 (用 load_returns 讀進來的結果)

    輸出：一張表，每一列是一檔關聯股，欄位包含：
      - 產業關聯星等（原始主觀評分，1–5）
      - corr_20d / corr_60d / corr_120d（實際滾動相關係數）
      - lag_n（領先—落後檢定的樣本數）
      - lag_win_rate（海外 T → 台股 T+1 同向勝率）
      - lag_chi2_pvalue
      - 樣本可信度標籤
      - composite_weight（建議的實際數據權重，見下方公式）
    """
    if target_ticker not in price_data:
        raise ValueError(f"找不到目標股 {target_ticker} 的價格資料，請先用 data_fetcher.py 抓取")

    target_returns = price_data[target_ticker]
    rows = []
    for _, r in relation_df.iterrows():
        peer_ticker = r.get("yfinance_ticker")
        if not peer_ticker or peer_ticker not in price_data or peer_ticker == target_ticker:
            continue
        peer_returns = price_data[peer_ticker]

        corr_summary = latest_correlation_summary(target_returns, peer_returns, windows)
        lag_result = lagged_directional_test(peer_returns, target_returns, lag=lag)

        corr_120 = corr_summary.get("corr_120d", np.nan)
        corr_component = abs(corr_120) if pd.notna(corr_120) else 0.0
        win_component = max(0.0, (lag_result.win_rate - 0.5) * 2) if pd.notna(lag_result.win_rate) else 0.0

        if lag_result.n < 30:
            composite_weight = 0.0
        else:
            sig_boost = 1.0
            if pd.notna(lag_result.chi2_pvalue) and lag_result.chi2_pvalue < 0.05:
                sig_boost = 1.2
            composite_weight = round(((corr_component + win_component) / 2) * sig_boost, 3)

        corr_10 = corr_summary.get("corr_10d", np.nan)

        rows.append({
            "關聯欄位": r.get("關聯欄位"),
            "公司名稱": r.get("公司名稱"),
            "股票代號": peer_ticker,
            "原始星等": r.get("星等"),
            **corr_summary,
            "corr_10d_x100": scale_to_100(corr_10),
            "corr_10d_註記": "樣本僅10天,樣本<30,僅供觀察,不影響權重",
            "corr_20d_x100": scale_to_100(corr_summary.get("corr_20d")),
            "corr_60d_x100": scale_to_100(corr_summary.get("corr_60d")),
            "corr_120d_x100": scale_to_100(corr_120),
            "corr_120d_標籤": label_for_score(scale_to_100(corr_120), CORR_TIER_LABELS),
            "lag_n": lag_result.n,
            "lag_win_rate": round(lag_result.win_rate, 3) if pd.notna(lag_result.win_rate) else np.nan,
            "lag_chi2_pvalue": lag_result.chi2_pvalue,
            "樣本可信度": lag_result.confidence_label,
            "composite_weight": composite_weight,
        })

    scorecard = pd.DataFrame(rows).sort_values("composite_weight", ascending=False)
    return scorecard


# ----------------------------------------------------------------------
# 5. 趨勢延續分數：目標股「今天的走勢，明天/接下來會不會延續」
# ----------------------------------------------------------------------
def trend_continuation_score(scorecard: pd.DataFrame,
                              latest_peer_returns: dict[str, float]) -> dict:
    """
    用計分表（composite_weight）當權重，把「昨晚／今天各關聯股的報酬率方向」
    做加權平均，估計台灣個股隔天趨勢延續的方向與強度。
    """
    if scorecard.empty:
        return {"direction_score": 0.0, "confidence": "無可用關聯股資料", "contributing": []}

    contributing = []
    weighted_sum = 0.0
    weight_total = 0.0

    for _, row in scorecard.iterrows():
        ticker = row["股票代號"]
        w = row["composite_weight"]
        if w <= 0 or ticker not in latest_peer_returns:
            continue
        r = latest_peer_returns[ticker]
        sign = np.sign(r)
        weighted_sum += w * sign
        weight_total += w
        contributing.append({
            "股票代號": ticker,
            "公司名稱": row["公司名稱"],
            "weight": w,
            "當日報酬率": r,
            "貢獻方向": "多" if sign > 0 else ("空" if sign < 0 else "平"),
            "lag_n": row.get("lag_n", np.nan),
        })

    if weight_total == 0:
        return {"direction_score": 0.0, "score_100": 0.0, "label": "無足夠資料",
                "confidence": "尚無有效權重（樣本不足或缺當日資料）",
                "contributing": contributing}

    direction_score = weighted_sum / weight_total
    n_effective = len(contributing)
    lag_ns = [c["lag_n"] for c in contributing if pd.notna(c["lag_n"])]
    min_lag_n = int(min(lag_ns)) if lag_ns else 0
    confidence = (
        f"納入 {n_effective} 檔關聯股；其中天數樣本最少的一檔為 {min_lag_n} 天"
        f"（{sample_confidence_label(min_lag_n)}）"
    )
    score_100 = scale_to_100(direction_score)

    return {
        "direction_score": round(float(direction_score), 3),
        "score_100": score_100,
        "label": label_for_score(score_100, TREND_TIER_LABELS),
        "confidence": confidence,
        "contributing": sorted(contributing, key=lambda x: -abs(x["weight"])),
    }


# ----------------------------------------------------------------------
# 6. 均線二次確認濾網（只套用在「強烈偏多／強烈偏空延續」這兩個最極端的訊號）
#    2026-09-11 與 Brian 討論定案：trend_continuation_score 是「當天各關聯股
#    方向」加權出來的即時訊號，分數再怎麼極端，也不保證目標股「自己的價格」
#    已經真的轉向。用目標股自己的 5日／20日均線做一次事後確認，避免把分數
#    雖然極端、但股價自己根本還沒轉強（或轉弱）的標的，當成可以推薦的標的。
#    只套用在最極端的兩端，中度／弱訊號不套用——理由見
#    claude 專案文件 trend_score_interpretation_framework.md 第 5 節的延伸決議。
# ----------------------------------------------------------------------
def load_close_prices(csv_path: str, datetime_col: str = "datetime",
                       price_col: str = "close") -> pd.Series:
    """讀取 OHLCV CSV，回傳以 datetime 為 index 的『收盤價』序列（不是報酬率）。
    均線要算在實際價格上，不是報酬率上，所以跟 load_returns 分開一支函式。"""
    df = pd.read_csv(csv_path, parse_dates=[datetime_col])
    df = df.set_index(datetime_col).sort_index()
    price = df[price_col].dropna()
    price.name = price_col
    return price


def ma_alignment_check(close: pd.Series, short_window: int = 5,
                        long_window: int = 20) -> dict:
    """
    用目標股自己的收盤價，算出最新一天的均線狀態：
      - 多頭排列：5日均線 > 20日均線
      - 空頭排列：5日均線 < 20日均線
      - 站上/跌破5日線：今天收盤價 相對 5日均線 的位置
    這支函式只描述「均線現在長什麼樣子」，不含買賣建議——建議判斷交給
    apply_directional_filter，跟趨勢延續分數的方向合併判斷。
    """
    close = close.dropna()
    if len(close) < long_window:
        return {
            "收盤價": None, "5日均線": None, "20日均線": None,
            "均線排列": "資料不足",
            "均線排列註記": f"收盤價樣本只有 {len(close)} 天，不足 {long_window} 天，無法算20日均線",
        }

    ma_short = close.rolling(short_window).mean()
    ma_long = close.rolling(long_window).mean()

    last_close = float(close.iloc[-1])
    last_ma_short = float(ma_short.iloc[-1])
    last_ma_long = float(ma_long.iloc[-1])

    if last_ma_short > last_ma_long:
        alignment = "多頭排列"
    elif last_ma_short < last_ma_long:
        alignment = "空頭排列"
    else:
        alignment = "糾結"

    return {
        "收盤價": round(last_close, 2),
        "5日均線": round(last_ma_short, 2),
        "20日均線": round(last_ma_long, 2),
        "均線排列": alignment,
        "站上5日線": bool(last_close > last_ma_short),
    }


def apply_directional_filter(label: str, ma_result: dict) -> dict:
    """
    只對「強烈偏多延續」「強烈偏空延續」做均線二次確認：
      - 強烈偏多延續 + 多頭排列(5>20) + 站上5日線 → 推薦買進
      - 強烈偏空延續 + 空頭排列(5<20) + 跌破5日線 → 留意／警示
    分數方向跟均線方向對不上時，維持原始標籤，但不列入推薦／留意名單，
    並在註記裡誠實寫出「為什麼沒過濾網」，而不是靜默忽略。
    """
    if ma_result.get("均線排列") == "資料不足":
        return {"均線濾網": "", "均線濾網註記": ma_result.get("均線排列註記", "資料不足")}

    alignment = ma_result.get("均線排列")
    above_short = ma_result.get("站上5日線")

    if label == "強烈偏多延續":
        passed = (alignment == "多頭排列") and above_short
        if passed:
            return {"均線濾網": "推薦買進",
                    "均線濾網註記": "分數強烈偏多，均線也是多頭排列且站上5日線，兩者一致"}
        return {"均線濾網": "訊號未過濾(偏多)",
                "均線濾網註記": "分數強烈偏多，但均線還不是多頭排列或尚未站上5日線，暫不列入推薦"}

    if label == "強烈偏空延續":
        passed = (alignment == "空頭排列") and (not above_short)
        if passed:
            return {"均線濾網": "留意/警示",
                    "均線濾網註記": "分數強烈偏空，均線也是空頭排列且跌破5日線，兩者一致"}
        return {"均線濾網": "訊號未過濾(偏空)",
                "均線濾網註記": "分數強烈偏空，但均線還不是空頭排列或尚未跌破5日線，暫不列入留意名單"}

    return {"均線濾網": "", "均線濾網註記": "非強烈訊號，不套用均線濾網"}


if __name__ == "__main__":
    print(__doc__)
