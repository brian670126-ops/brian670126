"""
主執行入口 - 一鍵跑全流程

執行順序:
1. fetch_yfinance.py - 抓取 16 個自動商品的日/週 OHLC
2. analyze.py - 讀取手動 + 自動資料, 算三關價 + 產出報告

用法:
    cd three_gate
    python main.py

或分步:
    python src/fetch_yfinance.py   # 只抓資料
    python src/analyze.py          # 只分析

手動輸入 (每天你收盤後執行一次):
    python src/read_manual.py     # 有 CLI 介面
    或直接編輯 data/manual/TX_daily.csv
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from fetch_yfinance import fetch_all
from analyze import run_all


def main():
    print("=" * 70)
    print("三關價系統 - 全球多商品每日分析")
    print("=" * 70)
    
    # Step 1: 抓 yfinance 資料
    print("\n[Step 1/2] 抓取 yfinance 資料...")
    print("-" * 70)
    fetch_results = fetch_all()
    
    # Step 2: 分析
    print("\n[Step 2/2] 執行三關價分析...")
    print("-" * 70)
    analyses = run_all()
    
    # 總結
    print("\n" + "=" * 70)
    print("執行完成")
    print("=" * 70)
    print(f"\n產出檔案:")
    print(f"  📊 Excel:     three_gate/analysis/*.xlsx  (共 {sum(1 for a in analyses.values() if a)} 個)")
    print(f"  📝 策略單商品: three_gate/strategy/{{code}}_{{period}}.md")
    print(f"  📋 對照報告:   three_gate/strategy/latest.md")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
