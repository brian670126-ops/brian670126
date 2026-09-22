# -*- coding: utf-8 -*-
"""
cl_contract_roll.py
====================
原油 WTI (CL) 期貨近月/遠月合約代碼判斷。

Yahoo Finance 對個別到期月份合約的代碼格式是：
    CL + 月份代碼(1碼) + 年份後兩碼 + ".NYM"
    例如 2026年11月合約 = CLX26.NYM，2026年12月合約 = CLZ26.NYM

月份代碼（期貨業界標準，非任意字母）：
    1月F 2月G 3月H 4月J 5月K 6月M 7月N 8月Q 9月U 10月V 11月X 12月Z

展期規則（近似 CME WTI 規則，未計入美國假日，僅用日曆週末粗略校正）：
    交割月 D 的合約，最後交易日 = 交割月前一個月 25 日往前推 3 個營業日；
    若 25 日當天是週末，先往前校正到最近的營業日，再往前推 3 個營業日。
    只要「今天」超過某交割月合約的最後交易日，該合約就視為已到期／不再是近月。

    以此規則反推：只要當天日期 > 某月合約的最後交易日，就代表該月合約
    已經到期，近月會往後跳一個月。

⚠️ 侷限：這是近似規則，沒有考慮美國國定假日（會讓最後交易日誤差 1-2 個
營業日），也沒有處理原油合約偶爾因假日單獨调整最後交易日的例外情況。
用途是「每天自動判斷近月/遠月代碼」，不是交易所官方到期日資料源。若要
更精確，建議改用交易所公告的到期日表。
"""

from __future__ import annotations
from datetime import date
import pandas as pd

MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}


def _prior_business_day(ts: pd.Timestamp) -> pd.Timestamp:
    """若 ts 落在週末，往前校正到最近的營業日（週五）。"""
    d = ts
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d = d - pd.Timedelta(days=1)
    return d


def _subtract_business_days(ts: pd.Timestamp, n: int) -> pd.Timestamp:
    """從 ts 往前推 n 個營業日（只排除週末，不排除假日）。"""
    d = ts
    count = 0
    while count < n:
        d = d - pd.Timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


def last_trading_day(delivery_year: int, delivery_month: int) -> pd.Timestamp:
    """回傳某交割年月合約的（近似）最後交易日。"""
    prior_month = delivery_month - 1
    prior_year = delivery_year
    if prior_month == 0:
        prior_month = 12
        prior_year -= 1
    d25 = pd.Timestamp(year=prior_year, month=prior_month, day=25)
    d25 = _prior_business_day(d25)
    return _subtract_business_days(d25, 3)


def contract_ticker(delivery_year: int, delivery_month: int) -> str:
    """組出 Yahoo Finance 個別合約代碼，例如 CLX26.NYM。"""
    yy = delivery_year % 100
    code = MONTH_CODES[delivery_month]
    return f"CL{code}{yy:02d}.NYM"


def contract_label(delivery_year: int, delivery_month: int) -> str:
    """人類可讀標籤，例如 2026-11。"""
    return f"{delivery_year:04d}-{delivery_month:02d}"


def get_near_far_contracts(as_of: str | date | pd.Timestamp | None = None) -> dict:
    """
    判斷指定日期（預設今天）當下的近月 / 遠月合約。

    回傳：
        {
            "as_of": "2026-09-22",
            "near": {"year": 2026, "month": 11, "ticker": "CLX26.NYM", "label": "2026-11"},
            "far":  {"year": 2026, "month": 12, "ticker": "CLZ26.NYM", "label": "2026-12"},
            "near_last_trading_day": "2026-10-20",
        }
    """
    as_of_ts = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(date.today())

    year, month = as_of_ts.year, as_of_ts.month
    near = None
    near_ltd = None
    # 從當月開始往後找，直到找到「最後交易日 > 今天」的合約月份，即為近月
    for offset in range(0, 15):
        dm = month + offset
        dy = year + (dm - 1) // 12
        dm = (dm - 1) % 12 + 1
        ltd = last_trading_day(dy, dm)
        if ltd > as_of_ts:
            near = (dy, dm)
            near_ltd = ltd
            far_dm = dm + 1
            far_dy = dy + (far_dm - 1) // 12
            far_dm = (far_dm - 1) % 12 + 1
            far = (far_dy, far_dm)
            break
    if near is None:
        raise RuntimeError(f"找不到 {as_of_ts} 對應的近月合約，請檢查日期範圍")

    ny, nm = near
    fy, fm = far
    return {
        "as_of": as_of_ts.strftime("%Y-%m-%d"),
        "near": {"year": ny, "month": nm, "ticker": contract_ticker(ny, nm), "label": contract_label(ny, nm)},
        "far": {"year": fy, "month": fm, "ticker": contract_ticker(fy, fm), "label": contract_label(fy, fm)},
        "near_last_trading_day": near_ltd.strftime("%Y-%m-%d"),
    }


if __name__ == "__main__":
    import sys
    as_of_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = get_near_far_contracts(as_of_arg)
    print(result)
