# 三關價系統 - 全球多商品分析

自動化計算全球 18 個商品的**三關價**、**觸碰**、**方向**、**警訊** 與**策略區間**。

## 商品清單

**手動輸入 (每天你貼 OHLC)**:
- TX 台指期
- T5F 台灣 50 期貨

**yfinance 自動抓取 (16 項)**:
- 美股期指: ES / NQ / YM / RTY
- 亞洲指數: N225 / HSI / SSE
- 歐洲指數: DAX / FTSE
- 商品: GC / SI / CL / NG
- 加密貨幣: BTC / ETH
- 匯率: USDTWD

## 系統架構

```
three_gate/
├── config/
│   └── symbols.yaml            # 商品清單設定
├── src/
│   ├── three_gate_calc.py      # 三關價核心公式
│   ├── fetch_yfinance.py       # 抓取自動商品
│   ├── read_manual.py          # 讀取手動商品
│   └── analyze.py              # 主分析 + 產出報告
├── data/
│   ├── manual/                 # 你手動輸入的 OHLC
│   │   ├── TX_daily.csv
│   │   ├── TX_weekly.csv
│   │   ├── T5F_daily.csv
│   │   └── T5F_weekly.csv
│   └── auto/                   # yfinance 自動抓的
│       ├── ES_daily.csv
│       └── ...
├── analysis/                   # Excel 分析結果 (自動產出)
├── strategy/                   # 策略 Markdown (自動產出)
│   ├── latest.md              # 多商品對照報告 ← 首要看
│   ├── TX_daily.md            # 各商品單獨分析
│   └── ...
├── .github/workflows/
│   └── three_gate.yml         # 每天 06:00 台灣時間自動執行
├── main.py                     # 一鍵執行入口
├── requirements.txt
└── README.md
```

## 執行時機

**排程**: 每天台灣時間 **06:00** 自動執行 (夜盤 05:00 收後 1 小時緩衝)
- Cron: `0 22 * * 0-4` (UTC)
- 涵蓋: 週一到週五交易日

## 手動輸入 OHLC (台指期、台 50 期)

### 方式 1: 直接編輯 CSV

編輯 `data/manual/TX_daily.csv`:
```csv
date,open,high,low,close,volume
2026-09-08,47480,47593,46561,47055,0
2026-09-09,47076,47592,46747,46984,0
2026-09-10,46940,46950,46015,46072,0
```

### 方式 2: 用 Python CLI

```python
from src.read_manual import append_daily
append_daily('TX', '2026-09-10', 46940, 46950, 46015, 46072)
```

## 手動執行

```bash
cd three_gate
pip install -r requirements.txt
python main.py
```

## 產出檔案

### 📋 多商品對照報告 (首要看)
`strategy/latest.md`
- 全 18 商品方向對照表
- 多方商品清單
- 空方商品清單  
- 警訊商品清單

### 📝 單商品策略 (詳細分析)
`strategy/{code}_daily.md`
`strategy/{code}_weekly.md`
- 目前狀態: 收盤 / 方向 / 警訊 / 所在區間
- 當前週期三關價 + 距收盤距離
- 明日/下週預測三關價
- M-B1 策略實戰參考

### 📊 Excel 完整表格
`analysis/{code}_daily.xlsx`
`analysis/{code}_weekly.xlsx`
- 每筆 OHLC + 三關價 + 觸碰 + 方向 + 警訊
- 最後一列是明日/下週預測三關價 (橘色標示)

## 三關價公式

- **M** = (H + L + 2C) / 4
- **B1** = 2M - L
- **B2** = 3M - 2L
- **B3** = H + (H - L)
- **S1** = 2M - H
- **S2** = 3M - 2H
- **S3** = L - (H - L)

**方向判定** (用**當前週期的 S2/B2**):
- 收 > B2 → 多方
- 收 < S2 → 空方
- 中間 → 延續前期方向

**觸碰符號 (v8)**:
- B 系列: H ≥ B → ✓
- S 系列: L ≤ S → ✓
- M: C > M → ↑ / C < M → ↓
- 收盤最靠近的關卡: △C (M 加 C → ↑C/↓C)

**警訊系統** (多方時觀察反轉徵兆):
- 高、低、收 3 個都比前期低: **強警訊**
- 3 個中 2 個: **中警訊**
- 3 個中 1 個: **弱警訊**

## 實戰策略 (M-B1 策略)

**主戰場**: M ~ B1
- **短多**: M 附近進 → 目標 B1 → B2
- **短空**: B1 附近反彈失敗 → 目標 M
- **停損**: 破 S2 清空多單
- **不追多**: 過 B2
- **不做空**: 破 S2 以下

## GitHub Actions 設定

無需額外設定, workflow 已內建。第一次 push 後自動生效。

**手動觸發**: GitHub → Actions → "三關價系統" → Run workflow

## 常見問題

**Q: yfinance 抓不到台指期怎麼辦?**
A: 台指期用手動輸入 (方式已提供)。yfinance 只抓 16 個自動商品。

**Q: 為什麼 06:00 才跑?**
A: 台指期夜盤 05:00 收盤,需要 1 小時緩衝讓 yfinance 資料更新完成。

**Q: 週資料如何合併日資料?**
A: 週 K = 該週最後一個交易日 (通常週五) 的 OHLC (H = 該週最高、L = 該週最低、C = 該週最後收盤)。若最新資料還沒到週五,系統會自動合併到當週。

**Q: Actions 執行失敗怎麼辦?**
A: 到 GitHub → Actions 頁面看錯誤 log。常見原因: yfinance 網路異常 (重跑即可)、商品代碼變更 (改 symbols.yaml)。
