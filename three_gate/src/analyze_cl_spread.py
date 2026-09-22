# -*- coding: utf-8 -*-
"""
analyze_cl_spread.py
======================
把原油近月-遠月「價差」的日線／週線 OHLC（fetch_cl_spread.py 抓的），
套進你既有的 three_gate_calc.py 公式，算出價差本身的三關價關卡、方向、
觸碰符號 —— 跟台指期(TX)、台灣50期貨(T5F)用同一套邏輯，輸出格式也比照
strategy/ 資料夾既有的檔案。

⚠️ 資料量提醒：跟TX累積15年、2000+週不同，價差資料才剛開始每天累積
（見 fetch_cl_spread.py），現階段只夠算「當下的關卡/方向/觸碰」，還
不夠拿來做：
    - 五日均線過濾（需要至少5個交易日）
    - 同步K線波段判斷（需要判斷連續5日站上/跌破的型態）
    - B2突破/S2守回的歷史勝率統計（需要大樣本，見 backtest_cl_spread_vs_near.py）
這些之後樣本夠了再補上，這支先把「關卡本身」跑起來，資料每天累積、
關卡每天自動更新，不用等樣本量。

執行方式：
    python analyze_cl_spread.py
會輸出：
    three_gate/strategy/CL_spread_daily.md
    three_gate/strategy/CL_spread_weekly.md
"""

from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from three_gate_calc import OHLC, calc_three_gate, determine_direction, calc_touch_symbols  # noqa: E402
