# -*- coding: utf-8 -*-
"""
dashboard_builder.py
=====================
把當天的摘要報表(daily_pipeline.py 算出來的 report_rows)轉成一份好讀、可排序、
可篩選、依台股慣例(紅漲綠跌)上色的單頁 HTML 儀表板，存成：

    reports/dashboard_latest.html   —— 每天覆蓋，永遠是「今天」的版本
    reports/dashboard_YYYY-MM-DD.html —— 同一天也存一份帶日期的存檔版，方便回頭比較

內容包含：
    - 上方三個統計方塊（偏多／觀望／偏空檔數）
    - 一段「今日總覽」文字摘要 —— 依當天資料自動算出來的（最強偏多/偏空個股、
      最偏多/偏空的產業），不是每天手動寫的固定文字，資料一換文字就跟著換
    - 「產業別平均趨勢分數」橫向長條圖 —— 每個產業(編號分類)下所有目標股的
      平均分數，由高到低排序
    - 下方可排序／篩選／搜尋的個股明細表

daily_pipeline.py 算完所有目標股之後會自動呼叫 build_and_save_dashboard()，
不需要人工介入。也可以獨立執行（python dashboard_builder.py）重新產生今天的版本
（例如你手動重跑過 daily_pipeline.py 之後想重新產生儀表板）。
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
RELATION_MAP_PATH = BASE_DIR / "relation_map_v2.csv"
REPORT_DIR = BASE_DIR / "reports"

TAIWAN_TZ = timezone(timedelta(hours=8))


def _today_taiwan() -> str:
    return datetime.now(TAIWAN_TZ).strftime("%Y-%m-%d")


def _load_name_industry_map() -> tuple[dict, dict]:
    """從 relation_map_v2.csv 裡「台灣核心股／台灣高關聯股」的列，
    建出「股票代號 -> 公司名稱 / 產業」的對照表，讓儀表板能顯示中文名稱
    而不是只有冷冰冰的代號。"""
    rel = pd.read_csv(RELATION_MAP_PATH, encoding="utf-8-sig")
    core = rel[rel["關聯欄位"].isin(["台灣核心股", "台灣高關聯股"])][
        ["股票代號_單一", "公司名稱", "產業"]
    ].copy()
    core["股票代號_單一"] = core["股票代號_單一"].astype(str)
    name_map: dict = {}
    industry_map: dict = {}
    for _, r in core.iterrows():
        t = r["股票代號_單一"]
        if t not in name_map:
            name_map[t] = r["公司名稱"]
            industry_map[t] = r["產業"]
    return name_map, industry_map


def build_dashboard_rows(report_rows: list[dict]) -> list[dict]:
    """report_rows：daily_pipeline.py main() 裡累積的那份 list of dict
    （每個 dict 至少要有：目標股 / 趨勢延續分數_100 / 趨勢延續標籤 / 信心 / 主要貢獻1）。
    直接沿用同一次執行算出來的標籤字串，不重新用分數門檻判斷——
    這樣儀表板的顏色/標籤保證跟報表本身在級距邊界上完全一致。"""
    name_map, industry_map = _load_name_industry_map()
    rows = []
    for r in report_rows:
        ticker = r["目標股"]
        tnum = str(ticker).split(".")[0]
        top = r.get("主要貢獻1", "")
        rows.append({
            "ticker": ticker,
            "name": name_map.get(tnum, ""),
            "industry": industry_map.get(tnum, ""),
            "score100": round(float(r["趨勢延續分數_100"]), 1),
            "label": r["趨勢延續標籤"],
            "confidence": r["信心"],
            "top": top if isinstance(top, str) else "",
        })
    return rows


def render_html(rows: list[dict], report_date: str) -> str:
    data_json = json.dumps(rows, ensure_ascii=False)
    industries = sorted({r["industry"] for r in rows if r["industry"]})
    industries_json = json.dumps(industries, ensure_ascii=False)
    date_json = json.dumps(report_date, ensure_ascii=False)
    html = _TEMPLATE.replace("__DATA_JSON__", data_json)
    html = html.replace("__INDUSTRIES_JSON__", industries_json)
    html = html.replace("__REPORT_DATE__", date_json)
    return html


def build_and_save_dashboard(report_rows: list[dict], report_date: str) -> Path:
    rows = build_dashboard_rows(report_rows)
    html = render_html(rows, report_date)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = REPORT_DIR / "dashboard_latest.html"
    latest_path.write_text(html, encoding="utf-8")
    dated_path = REPORT_DIR / f"dashboard_{report_date}.html"
    dated_path.write_text(html, encoding="utf-8")
    return latest_path


_TEMPLATE = r'''<!doctype html>
<title>台股趨勢延續看板</title>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;600;700;900&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  color-scheme: light;
  --bg: #f6f4ef;
  --surface: #ffffff;
  --surface-2: #f0ede6;
  --ink: #17181a;
  --ink-muted: #5c5f63;
  --ink-faint: #8a8d90;
  --border: rgba(23,24,26,0.10);
  --border-strong: rgba(23,24,26,0.18);
  --accent: #1f3d52;
  --accent-ink: #ffffff;
  --accent-soft: #e7ecf0;

  --up-weak: #f0b3ac;
  --up-mid: #d24c3d;
  --up-strong: #932218;
  --up-weak-bg: #fbeae7;
  --up-mid-bg: #f8ded9;
  --up-strong-bg: #f4cec7;

  --down-weak: #a9d1ac;
  --down-mid: #3f8f4d;
  --down-strong: #1e5c2b;
  --down-weak-bg: #e6f2e5;
  --down-mid-bg: #dcedda;
  --down-strong-bg: #cfe4cd;

  --flat: #83878c;
  --flat-bg: #eceae5;

  --shadow: 0 1px 2px rgba(23,24,26,0.06), 0 8px 24px rgba(23,24,26,0.06);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #121316;
    --surface: #1b1d21;
    --surface-2: #202226;
    --ink: #f0f1f2;
    --ink-muted: #a6a9ad;
    --ink-faint: #797d82;
    --border: rgba(255,255,255,0.09);
    --border-strong: rgba(255,255,255,0.16);
    --accent: #86aecb;
    --accent-ink: #0e1720;
    --accent-soft: #22303b;

    --up-weak: #7e3d37;
    --up-mid: #c8564a;
    --up-strong: #ef8578;
    --up-weak-bg: #2c1c1b;
    --up-mid-bg: #3a211f;
    --up-strong-bg: #4a2521;

    --down-weak: #3c5f42;
    --down-mid: #4f9c5c;
    --down-strong: #7ed98d;
    --down-weak-bg: #1a2620;
    --down-mid-bg: #1e2f22;
    --down-strong-bg: #223a26;

    --flat: #9298a0;
    --flat-bg: #24262a;

    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #121316;
  --surface: #1b1d21;
  --surface-2: #202226;
  --ink: #f0f1f2;
  --ink-muted: #a6a9ad;
  --ink-faint: #797d82;
  --border: rgba(255,255,255,0.09);
  --border-strong: rgba(255,255,255,0.16);
  --accent: #86aecb;
  --accent-ink: #0e1720;
  --accent-soft: #22303b;

  --up-weak: #7e3d37;
  --up-mid: #c8564a;
  --up-strong: #ef8578;
  --up-weak-bg: #2c1c1b;
  --up-mid-bg: #3a211f;
  --up-strong-bg: #4a2521;

  --down-weak: #3c5f42;
  --down-mid: #4f9c5c;
  --down-strong: #7ed98d;
  --down-weak-bg: #1a2620;
  --down-mid-bg: #1e2f22;
  --down-strong-bg: #223a26;

  --flat: #9298a0;
  --flat-bg: #24262a;

  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Noto Sans TC", system-ui, -apple-system, "PingFang TC", "Microsoft JhengHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}
.wrap {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 24px 64px;
}

/* ---- header ---- */
header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px 24px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 22px;
}
.title-block h1 {
  font-size: 22px;
  font-weight: 900;
  margin: 0 0 4px;
  letter-spacing: -0.01em;
  text-wrap: balance;
}
.title-block p {
  margin: 0;
  color: var(--ink-muted);
  font-size: 13px;
}
.header-meta {
  text-align: right;
  font-size: 12px;
  color: var(--ink-faint);
  line-height: 1.6;
}
.header-meta .date {
  font-size: 14px;
  color: var(--ink);
  font-weight: 600;
}
.header-meta .date .mono { font-weight: 600; }

/* ---- stat tiles ---- */
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
  overflow: hidden;
}
.stat::before {
  content: "";
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: var(--stripe, var(--flat));
}
.stat.up { --stripe: var(--up-mid); }
.stat.flat { --stripe: var(--flat); }
.stat.down { --stripe: var(--down-mid); }
.stat .num {
  font-size: 26px;
  font-weight: 700;
  font-family: "IBM Plex Mono", monospace;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.stat .lbl {
  font-size: 12.5px;
  color: var(--ink-muted);
  line-height: 1.4;
}
.stat.up .num { color: var(--up-mid); }
.stat.down .num { color: var(--down-mid); }

/* ---- controls ---- */
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.controls input[type="search"] {
  flex: 1 1 200px;
  min-width: 160px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--ink);
  font-size: 13.5px;
  font-family: inherit;
}
.controls select {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--ink);
  font-size: 13px;
  font-family: inherit;
}
.controls input::placeholder { color: var(--ink-faint); }
.controls input:focus, .controls select:focus, .chip:focus-visible, th button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--ink-muted);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12.5px;
  cursor: pointer;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.chip .dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--dotcolor, var(--ink-faint));
  flex: none;
}
.chip[aria-pressed="true"] {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--ink);
  font-weight: 600;
}
.result-count {
  font-size: 12px;
  color: var(--ink-faint);
  margin: 2px 2px 10px;
}

/* ---- table ---- */
.table-scroll {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 880px;
}
thead th {
  position: sticky;
  top: 0;
  background: var(--surface);
  z-index: 1;
  text-align: left;
  font-size: 12px;
  color: var(--ink-faint);
  font-weight: 600;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-strong);
  white-space: nowrap;
}
thead th button {
  all: unset;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font: inherit;
  color: inherit;
}
thead th button .arrow { opacity: 0; font-size: 10px; }
thead th button[aria-sort]:not([aria-sort="none"]) .arrow,
thead th button:hover .arrow { opacity: 1; }
tbody td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 13.5px;
  vertical-align: middle;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: var(--surface-2); }
td.num-col { text-align: right; }
.ticker-cell .code { font-weight: 600; font-size: 13px; }
.ticker-cell .industry { color: var(--ink-faint); font-size: 11.5px; margin-top: 1px; }
.name-cell .company { font-weight: 500; }

/* diverging bar */
.bar-cell { width: 168px; }
.bar-track {
  position: relative;
  height: 18px;
  background: var(--surface-2);
  border-radius: 4px;
  overflow: hidden;
}
.bar-track .mid {
  position: absolute; left: 50%; top: 0; bottom: 0;
  width: 1px; background: var(--border-strong);
}
.bar-fill {
  position: absolute;
  top: 2px; bottom: 2px;
  border-radius: 3px;
  background: var(--barcolor, var(--flat));
}
.score-num {
  font-size: 13px;
  font-weight: 600;
  min-width: 42px;
  display: inline-block;
  text-align: right;
}

/* badges */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  background: var(--badgebg, var(--flat-bg));
  color: var(--badgefg, var(--flat));
}

/* confidence */
.conf-cell { max-width: 260px; }
.conf-main { font-size: 12.5px; color: var(--ink-muted); }
.conf-sub {
  font-size: 11.5px;
  color: var(--ink-faint);
  margin-top: 2px;
}
.top-contrib { font-size: 12.5px; color: var(--ink-muted); }

.empty-row td {
  text-align: center;
  padding: 40px 12px;
  color: var(--ink-faint);
  font-size: 13px;
}

/* legend */
.legend {
  margin-top: 18px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px 22px;
  align-items: center;
  font-size: 12px;
  color: var(--ink-muted);
}
.legend .group { display: flex; align-items: center; gap: 6px; }
.legend .swatch { width: 12px; height: 12px; border-radius: 3px; }
.legend-title { font-weight: 600; color: var(--ink-faint); }

footer {
  margin-top: 26px;
  font-size: 11.5px;
  color: var(--ink-faint);
  line-height: 1.7;
}
footer a { color: inherit; }


/* ---- narrative summary ---- */
.narrative {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
}
.narrative p {
  margin: 0 0 8px;
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--ink);
}
.narrative p:last-child { margin-bottom: 0; }
.narrative .hl-up { color: var(--up-mid); font-weight: 700; }
.narrative .hl-down { color: var(--down-mid); font-weight: 700; }

/* ---- industry aggregate chart ---- */
.industry-chart-wrap {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px 18px;
  margin-bottom: 20px;
  box-shadow: var(--shadow);
}
.section-heading {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-faint);
  margin: 0 0 4px;
}
.section-sub {
  font-size: 11.5px;
  color: var(--ink-faint);
  margin: 0 0 12px;
}
.ind-row {
  display: grid;
  grid-template-columns: 168px 1fr 68px;
  align-items: center;
  gap: 10px;
  padding: 2.5px 0;
}
.ind-row .ind-name {
  font-size: 12px;
  color: var(--ink-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ind-row .ind-track {
  position: relative;
  height: 11px;
  background: var(--surface-2);
  border-radius: 3px;
}
.ind-row .ind-track .mid {
  position: absolute; left: 50%; top: 0; bottom: 0;
  width: 1px; background: var(--border-strong);
}
.ind-row .ind-fill {
  position: absolute;
  top: 1px; bottom: 1px;
  border-radius: 2px;
}
.ind-row .ind-val {
  font-size: 11px;
  text-align: right;
  white-space: nowrap;
}
.ind-row .ind-n {
  color: var(--ink-faint);
  margin-left: 3px;
}

@media (max-width: 640px) {
  .stats { grid-template-columns: 1fr; }
  .wrap { padding: 20px 14px 48px; }
}
</style>

<div class="wrap">

  <header>
    <div class="title-block">
      <h1>台股趨勢延續看板</h1>
      <p>產業關聯量化追蹤・97 檔目標股・每個交易日台灣時間 07:30 自動更新</p>
    </div>
    <div class="header-meta">
      <div class="date">今日資料日期：<span class="mono" id="report-date">—</span></div>
      <div>依「趨勢延續分數」排序・點欄名可改排序</div>
    </div>
  </header>

  <div class="stats">
    <div class="stat up">
      <div>
        <div class="num" id="stat-up">–</div>
        <div class="lbl">偏多延續<br>（分數 &gt; 10）</div>
      </div>
    </div>
    <div class="stat flat">
      <div>
        <div class="num" id="stat-flat">–</div>
        <div class="lbl">方向不明／觀望<br>（-10 ~ 10）</div>
      </div>
    </div>
    <div class="stat down">
      <div>
        <div class="num" id="stat-down">–</div>
        <div class="lbl">偏空延續<br>（分數 &lt; -10）</div>
      </div>
    </div>
  </div>

  <div class="narrative" id="narrative"></div>

  <div class="industry-chart-wrap">
    <div class="section-heading">產業別平均趨勢分數</div>
    <div class="section-sub">同一個「編號」分類下所有目標股的分數平均，由高到低排序；n 是該產業納入平均的檔數</div>
    <div id="industry-chart"></div>
  </div>

  <div class="controls">
    <input type="search" id="search" placeholder="搜尋股票代號、公司名稱或產業…">
    <select id="industry-filter">
      <option value="">全部產業</option>
    </select>
    <div class="chips" id="label-chips" role="group" aria-label="依標籤篩選"></div>
  </div>
  <div class="result-count" id="result-count"></div>

  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th style="width:34px">#</th>
          <th data-key="ticker">股票<button data-key="ticker"><span>股票／產業</span><span class="arrow">▾</span></button></th>
          <th data-key="score100" style="width:184px"><button data-key="score100"><span>趨勢延續分數</span><span class="arrow">▾</span></button></th>
          <th data-key="label"><button data-key="label"><span>標籤</span><span class="arrow">▾</span></button></th>
          <th data-key="confidence">信心說明</th>
          <th data-key="top">主要貢獻</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>

  <div class="legend">
    <span class="legend-title">分數級距（台股慣例：紅漲・綠跌）</span>
    <span class="group"><span class="swatch" style="background:var(--up-strong)"></span>強烈偏多 (70~100)</span>
    <span class="group"><span class="swatch" style="background:var(--up-mid)"></span>中度偏多 (40~70)</span>
    <span class="group"><span class="swatch" style="background:var(--up-weak)"></span>弱偏多 (10~40)</span>
    <span class="group"><span class="swatch" style="background:var(--flat)"></span>方向不明 (-10~10)</span>
    <span class="group"><span class="swatch" style="background:var(--down-weak)"></span>弱偏空 (-40~-10)</span>
    <span class="group"><span class="swatch" style="background:var(--down-mid)"></span>中度偏空 (-70~-40)</span>
    <span class="group"><span class="swatch" style="background:var(--down-strong)"></span>強烈偏空 (-100~-70)</span>
  </div>

  <footer>
    分數為「趨勢延續分數」（-100~+100），依產業關聯股當日同向表現加權計算，僅供輔助參考，非投資建議；樣本數不足 30 天的關聯股不計入權重。信心說明包含兩件事：納入的關聯股檔數，以及這些關聯股各自的天數樣本是否充足。
  </footer>
</div>

<script>
const DATA = __DATA_JSON__;
const INDUSTRIES = __INDUSTRIES_JSON__;
const REPORT_DATE = __REPORT_DATE__;


// tier is looked up from the backend's own label string (correlation_engine.py
// label_for_score), never re-derived from the raw score — that guarantees the
// dashboard's color/side always agrees with the report even at tier boundaries.
const LABEL_TO_TIER = {
  '強烈偏多延續': {key:'up-strong', side:'up'},
  '中度偏多延續': {key:'up-mid', side:'up'},
  '弱偏多延續':   {key:'up-weak', side:'up'},
  '方向不明/觀望': {key:'flat', side:'flat'},
  '弱偏空延續':   {key:'down-weak', side:'down'},
  '中度偏空延續': {key:'down-mid', side:'down'},
  '強烈偏空延續': {key:'down-strong', side:'down'},
};
function tierOf(label) {
  return LABEL_TO_TIER[label] || {key:'flat', side:'flat'};
}
const TIER_META = {
  'up-strong':  {barVar:'--up-strong',  bgVar:'--up-strong-bg', fgVar:'--up-strong'},
  'up-mid':     {barVar:'--up-mid',     bgVar:'--up-mid-bg',    fgVar:'--up-mid'},
  'up-weak':    {barVar:'--up-weak',    bgVar:'--up-weak-bg',   fgVar:'--up-mid'},
  'flat':       {barVar:'--flat',       bgVar:'--flat-bg',      fgVar:'--flat'},
  'down-weak':  {barVar:'--down-weak',  bgVar:'--down-weak-bg', fgVar:'--down-mid'},
  'down-mid':   {barVar:'--down-mid',   bgVar:'--down-mid-bg',  fgVar:'--down-mid'},
  'down-strong':{barVar:'--down-strong',bgVar:'--down-strong-bg',fgVar:'--down-strong'},
};

// split confidence string "納入 X 檔關聯股；其中...(...)" into two lines
function splitConfidence(s) {
  if (!s) return {main:'', sub:''};
  const parts = s.split('；');
  return {main: parts[0] || '', sub: parts.slice(1).join('；')};
}

let state = {
  search: '',
  industry: '',
  labelFilter: null, // 'up' | 'flat' | 'down' | null
  sortKey: 'score100',
  sortDir: 'desc',
};

const LABEL_ORDER = ['強烈偏多延續','中度偏多延續','弱偏多延續','方向不明/觀望','弱偏空延續','中度偏空延續','強烈偏空延續'];

function init() {
  // report date
  document.getElementById('report-date').textContent = REPORT_DATE;

  // industry options
  const sel = document.getElementById('industry-filter');
  INDUSTRIES.forEach(ind => {
    const opt = document.createElement('option');
    opt.value = ind; opt.textContent = ind;
    sel.appendChild(opt);
  });
  sel.addEventListener('change', () => { state.industry = sel.value; render(); });

  document.getElementById('search').addEventListener('input', (e) => {
    state.search = e.target.value.trim().toLowerCase();
    render();
  });

  const chipsWrap = document.getElementById('label-chips');
  const chipDefs = [
    {key:'up', label:'偏多', color:'var(--up-mid)'},
    {key:'flat', label:'觀望', color:'var(--flat)'},
    {key:'down', label:'偏空', color:'var(--down-mid)'},
  ];
  chipDefs.forEach(cd => {
    const b = document.createElement('button');
    b.className = 'chip';
    b.type = 'button';
    b.setAttribute('aria-pressed', 'false');
    b.style.setProperty('--dotcolor', cd.color);
    b.innerHTML = `<span class="dot"></span>${cd.label}`;
    b.addEventListener('click', () => {
      state.labelFilter = (state.labelFilter === cd.key) ? null : cd.key;
      [...chipsWrap.children].forEach(c => c.setAttribute('aria-pressed', 'false'));
      if (state.labelFilter) b.setAttribute('aria-pressed', 'true');
      render();
    });
    chipsWrap.appendChild(b);
  });

  document.querySelectorAll('th button[data-key]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.key;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === 'desc' ? 'asc' : 'desc';
      } else {
        state.sortKey = key;
        state.sortDir = (key === 'score100') ? 'desc' : 'asc';
      }
      render();
    });
  });

  renderStats();
  renderNarrative();
  renderIndustryChart();
  render();
}

// ---- 產業別平均分數（依 DATA 動態算，每天資料一換這裡就自動跟著換）----
function computeIndustryStats() {
  const groups = {};
  DATA.forEach(d => {
    if (!d.industry) return;
    (groups[d.industry] = groups[d.industry] || []).push(d.score100);
  });
  return Object.entries(groups)
    .map(([industry, scores]) => ({
      industry,
      avg: scores.reduce((a, b) => a + b, 0) / scores.length,
      n: scores.length,
    }))
    .sort((a, b) => b.avg - a.avg);
}

function renderIndustryChart() {
  const stats = computeIndustryStats();
  const wrap = document.getElementById('industry-chart');
  wrap.innerHTML = '';
  stats.forEach(s => {
    const pct = Math.min(Math.abs(s.avg), 100) / 100 * 50;
    const color = s.avg > 10 ? 'var(--up-mid)' : s.avg < -10 ? 'var(--down-mid)' : 'var(--flat)';
    const row = document.createElement('div');
    row.className = 'ind-row';
    row.innerHTML = `
      <div class="ind-name" title="${escapeHtml(s.industry)}">${escapeHtml(s.industry)}</div>
      <div class="ind-track">
        <div class="mid"></div>
        <div class="ind-fill" style="background:${color};
          ${s.avg >= 0 ? `left:50%;width:${pct}%;` : `right:50%;width:${pct}%;`}"></div>
      </div>
      <div class="ind-val mono">${s.avg > 0 ? '+' : ''}${s.avg.toFixed(0)}<span class="ind-n">n=${s.n}</span></div>
    `;
    wrap.appendChild(row);
  });
}

// ---- 自動生成的文字總覽（每天依當天資料重新算，不是手寫的固定文字）----
function renderNarrative() {
  const total = DATA.length;
  const sides = DATA.map(d => tierOf(d.label).side);
  const up = sides.filter(s => s === 'up').length;
  const flat = sides.filter(s => s === 'flat').length;
  const down = sides.filter(s => s === 'down').length;

  let tilt;
  if (up > down * 1.3) tilt = '整體格局明顯偏多';
  else if (down > up * 1.3) tilt = '整體格局明顯偏空';
  else tilt = '整體多空互見，沒有一致方向';

  const bySore = DATA.slice().sort((a, b) => b.score100 - a.score100);
  const topBull = bySore.slice(0, 3);
  const topBear = bySore.slice(-3).slice().reverse();

  const fmtStock = d => `${escapeHtml(d.name)}（${d.score100 > 0 ? '+' : ''}${d.score100.toFixed(1)}）`;
  const bullNames = topBull.map(fmtStock).join('、');
  const bearNames = topBear.map(fmtStock).join('、');

  const indStats = computeIndustryStats();
  const indStatsQualified = indStats.filter(s => s.n >= 2); // 只挑至少2檔的產業，單一檔不足以代表整個產業
  const topBullInd = indStatsQualified.slice(0, 2);
  const topBearInd = indStatsQualified.slice(-2).slice().reverse();
  const fmtInd = s => `${escapeHtml(s.industry)}（平均 ${s.avg > 0 ? '+' : ''}${s.avg.toFixed(0)}，${s.n} 檔）`;

  const html = `
    <p>今天（${escapeHtml(REPORT_DATE)}）追蹤的 ${total} 檔目標股中，
    <span class="hl-up">偏多 ${up} 檔</span>、觀望 ${flat} 檔、
    <span class="hl-down">偏空 ${down} 檔</span>，${tilt}。</p>
    <p>個股方面，今天訊號最偏多的是 ${bullNames}；訊號最偏空的是 ${bearNames}。</p>
    ${indStatsQualified.length ? `<p>以產業別平均分數來看，${topBullInd.map(fmtInd).join('、')} 相對偏多；${topBearInd.map(fmtInd).join('、')} 相對偏空——完整 ${indStats.length} 個產業的排序見下方圖表。</p>` : ''}
  `;
  document.getElementById('narrative').innerHTML = html;
}

function renderStats() {
  const sides = DATA.map(d => tierOf(d.label).side);
  const up = sides.filter(s => s === 'up').length;
  const flat = sides.filter(s => s === 'flat').length;
  const down = sides.filter(s => s === 'down').length;
  document.getElementById('stat-up').textContent = up;
  document.getElementById('stat-flat').textContent = flat;
  document.getElementById('stat-down').textContent = down;
}

function matches(d) {
  if (state.industry && d.industry !== state.industry) return false;
  if (state.labelFilter) {
    const side = tierOf(d.label).side;
    if (side !== state.labelFilter) return false;
  }
  if (state.search) {
    const hay = (d.ticker + ' ' + d.name + ' ' + d.industry).toLowerCase();
    if (!hay.includes(state.search)) return false;
  }
  return true;
}

function sortRows(rows) {
  const {sortKey, sortDir} = state;
  const dir = sortDir === 'desc' ? -1 : 1;
  return rows.slice().sort((a, b) => {
    let av = a[sortKey], bv = b[sortKey];
    if (sortKey === 'label') {
      av = LABEL_ORDER.indexOf(a.label); bv = LABEL_ORDER.indexOf(b.label);
    }
    if (sortKey === 'ticker') {
      av = a.industry + a.ticker; bv = b.industry + b.ticker;
    }
    if (typeof av === 'string') return av.localeCompare(bv, 'zh-Hant') * dir;
    return (av - bv) * dir;
  });
}

function render() {
  const filtered = DATA.filter(matches);
  const sorted = sortRows(filtered);
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';

  document.getElementById('result-count').textContent =
    `顯示 ${sorted.length} / ${DATA.length} 檔`;

  document.querySelectorAll('th button[data-key]').forEach(btn => {
    btn.setAttribute('aria-sort', btn.dataset.key === state.sortKey
      ? (state.sortDir === 'desc' ? 'descending' : 'ascending') : 'none');
    const arrow = btn.querySelector('.arrow');
    if (btn.dataset.key === state.sortKey) {
      arrow.textContent = state.sortDir === 'desc' ? '▾' : '▴';
    }
  });

  if (!sorted.length) {
    const tr = document.createElement('tr');
    tr.className = 'empty-row';
    tr.innerHTML = `<td colspan="6">沒有符合條件的股票</td>`;
    tbody.appendChild(tr);
    return;
  }

  sorted.forEach((d, i) => {
    const tier = tierOf(d.label);
    const meta = TIER_META[tier.key];
    const conf = splitConfidence(d.confidence);
    const pct = Math.min(Math.abs(d.score100), 100) / 100 * 50; // half-width max
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="mono" style="color:var(--ink-faint)">${i + 1}</td>
      <td>
        <div class="ticker-cell">
          <div class="code mono">${d.ticker.replace('.TW','')} <span class="name-cell company">${escapeHtml(d.name)}</span></div>
          <div class="industry">${escapeHtml(d.industry)}</div>
        </div>
      </td>
      <td>
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="score-num mono" style="color:var(--${meta.fgVar.slice(2)})">${d.score100 > 0 ? '+' : ''}${d.score100.toFixed(1)}</span>
          <div class="bar-track" style="flex:1">
            <div class="mid"></div>
            <div class="bar-fill" style="background:var(${meta.barVar});
              ${d.score100 >= 0
                ? `left:50%; width:${pct}%;`
                : `right:50%; width:${pct}%;`}"></div>
          </div>
        </div>
      </td>
      <td><span class="badge" style="--badgebg:var(${meta.bgVar});--badgefg:var(${meta.fgVar})">${d.label}</span></td>
      <td class="conf-cell">
        <div class="conf-main">${escapeHtml(conf.main)}</div>
        <div class="conf-sub">${escapeHtml(conf.sub)}</div>
      </td>
      <td class="top-contrib">${escapeHtml(d.top)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

init();
</script>
'''


if __name__ == "__main__":
    # 獨立執行：讀今天(台灣時間)的 summary_YYYY-MM-DD.csv，重新產生一次儀表板。
    # 用在你手動重跑過 daily_pipeline.py、或想在本機重新產生今天版本的時候。
    today = _today_taiwan()
    summary_path = REPORT_DIR / f"summary_{today}.csv"
    if not summary_path.exists():
        raise SystemExit(f"找不到 {summary_path}，請先跑過 daily_pipeline.py 產生今天的摘要報表")
    df = pd.read_csv(summary_path, encoding="utf-8-sig")
    report_rows = df.to_dict(orient="records")
    out = build_and_save_dashboard(report_rows, today)
    print(f"已產生 {out}")
