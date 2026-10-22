#!/usr/bin/env python3
"""
send_kline_report.py  v5
每日寄送 TX + T5F 日K線三關價分析報告
深色主題 HTML，含 OHLC、振幅分析、三關價表、全球18商品、策略建議
"""

import csv
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路徑設定 ───────────────────────────────────────────────
BASE     = Path(__file__).parent
DATA_DIR = BASE / 'three_gate' / 'data' / 'auto'

# ── 時區 ──────────────────────────────────────────────────
TW = timezone(timedelta(hours=8))
TODAY         = datetime.now(TW).strftime('%Y-%m-%d')
WEEKDAY_MAP   = ['週一','週二','週三','週四','週五','週六','週日']
TODAY_WEEKDAY = WEEKDAY_MAP[datetime.now(TW).weekday()]

# ── 全球商品清單（順序即報告順序）────────────────────────
COMMODITIES = [
    # (代碼, 中文名, 類別, 格式, 說明備註)
    ('TX',     '台指期',       '🇹🇼 台灣期貨',   '.0f',  ''),
    ('T5F',    '台灣50',       '🇹🇼 台灣期貨',   '.2f',  ''),
    ('ES',     'S&P500',       '🇺🇸 美股期貨',   '.2f',  ''),
    ('NQ',     'Nasdaq',       '🇺🇸 美股期貨',   '.2f',  ''),
    ('YM',     '道瓊',         '🇺🇸 美股期貨',   '.0f',  ''),
    ('RTY',    'Russell 2000', '🇺🇸 美股期貨',   '.2f',  ''),
    ('N225',   '日經225',      '🌏 亞洲指數',    '.0f',  ''),
    ('HSI',    '恆生',         '🌏 亞洲指數',    '.0f',  ''),
    ('SSE',    '上證',         '🌏 亞洲指數',    '.2f',  ''),
    ('DAX',    'DAX',          '🇪🇺 歐洲指數',   '.2f',  ''),
    ('FTSE',   'FTSE 100',     '🇪🇺 歐洲指數',   '.0f',  ''),
    ('GC',     '黃金',         '🪙 大宗商品',    '.2f',  '避險需求'),
    ('SI',     '白銀',         '🪙 大宗商品',    '.2f',  ''),
    ('CL',     '原油 WTI',     '🪙 大宗商品',    '.2f',  ''),
    ('NG',     '天然氣',       '🪙 大宗商品',    '.2f',  ''),
    ('BTC',    '比特幣',       '₿ 加密/外匯',   '.0f',  ''),
    ('ETH',    '以太幣',       '₿ 加密/外匯',   '.2f',  ''),
    ('USDTWD', '美元/新台幣',  '₿ 加密/外匯',   '.2f',  '台幣走勢'),
]

# ── CSV 讀取 ───────────────────────────────────────────────
def read_csv_last_n(path: Path, n: int = 22) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return rows[-n:] if len(rows) >= n else rows

# ── 三關價計算 ─────────────────────────────────────────────
def calc_gates(h, l, c):
    m  = (h + l + 2*c) / 4
    b1 = 2*m - l
    b2 = 3*m - 2*l
    b3 = h + (h - l)
    s1 = 2*m - h
    s2 = 3*m - 2*h
    s3 = l - (h - l)
    return dict(m=m, b1=b1, b2=b2, b3=b3, s1=s1, s2=s2, s3=s3)

# ── 振幅均值 ───────────────────────────────────────────────
def calc_avg_range(rows, n_days):
    """計算近 n_days 日的振幅均值（不含最後一筆）"""
    hist = rows[:-1]
    sample = hist[-n_days:] if len(hist) >= n_days else hist
    if not sample:
        return 0.0
    ranges = [float(r.get('high',0) or 0) - float(r.get('low',0) or 0) for r in sample]
    return sum(ranges) / len(ranges) if ranges else 0.0

# ── 位置判斷 ───────────────────────────────────────────────
def zone_label(c, gates):
    if c >= gates['b2']:
        return 'B2以上', 'z-b2up'
    elif c >= gates['b1']:
        return 'B1~B2', 'z-b1b2'
    elif c >= gates['m']:
        return 'M~B1', 'z-mb1'
    elif c >= gates['s1']:
        return 'S1~M', 'z-s1m'
    elif c >= gates['s2']:
        return 'S2~S1', 'z-s2s1'
    else:
        return 'S2以下', 'z-s2dn'

def direction_label(c, gates):
    if c >= gates['b2']:
        return '多方', True
    elif c >= gates['m']:
        return '偏多', True
    elif c >= gates['s2']:
        return '空方', False
    else:
        return '空方 恐慌區', False

# ── 警訊強度 ───────────────────────────────────────────────
def warn_level(c, gates, prev_c):
    """根據位置和跌幅判斷警訊強度"""
    score = 0
    if c < gates['s2']:
        score += 3
    elif c < gates['s1']:
        score += 1
    if prev_c > 0:
        chg_pct = (c - prev_c) / prev_c * 100
        if chg_pct < -2:
            score += 2
        elif chg_pct < -1:
            score += 1
    if score >= 3:
        return '●●●', 'ws', 'wb-strong', '強'
    elif score >= 2:
        return '●●', 'wm', 'wb-mid', '中'
    elif score >= 1:
        return '●', 'wk', 'wb-weak', '弱'
    else:
        return '', '', 'wb-none', '—'

# ── CSS ────────────────────────────────────────────────────
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#1c2128;--bg4:#21262d;
  --border:#30363d;--border2:#21262d;
  --fg:#e6edf3;--fg2:#c9d1d9;--fg3:#8b949e;
  --bull:#3fb950;--bear:#f85149;--warn:#d29922;--accent:#58a6ff;
  color-scheme:dark;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--fg);font-family:'Noto Sans TC',Arial,sans-serif;font-size:13px;padding:0 14px;}
.wrap{max-width:1100px;margin:0 auto;padding:16px 0 28px;}
.hdr{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.htitle{font-size:1.4rem;font-weight:700;color:var(--accent);}
.hsub{color:var(--fg3);font-size:.74rem;margin-top:3px;}
.hmeta{text-align:right;font-size:.72rem;color:var(--fg3);line-height:1.9;}
.hbadge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.72rem;font-weight:700;margin-left:6px;}
.hb-bear{background:#3a0505;color:#f85149;}
.hb-bull{background:#0d2818;color:#3fb950;}
.hb-warn{background:#2d1a00;color:#f0883e;}
.statrow{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;}
.stat{background:var(--bg2);border-radius:7px;padding:10px 14px;flex:1;min-width:110px;border-top:3px solid;}
.stat .sn{font-size:1.4rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1;}
.stat .sl{font-size:.68rem;color:var(--fg3);margin-top:2px;}
.sec{background:var(--bg2);border-radius:8px;margin-bottom:12px;overflow:hidden;}
.st{padding:8px 14px;background:var(--bg3);font-weight:600;font-size:.83rem;border-bottom:1px solid var(--border);}
.twocol{display:grid;grid-template-columns:1fr 1fr;gap:0;}
.col{padding:13px 14px;border-right:1px solid var(--border);}
.col:last-child{border-right:none;}
.clabel{font-size:.69rem;color:var(--accent);font-weight:700;letter-spacing:.05em;text-transform:uppercase;margin-bottom:8px;}
table.gt{width:100%;border-collapse:collapse;font-size:.77rem;}
table.gt th{background:var(--bg);padding:4px 8px;text-align:right;color:var(--fg3);font-weight:500;border-bottom:1px solid var(--border2);}
table.gt th:first-child{text-align:left;}
table.gt td{padding:5px 8px;border-bottom:1px solid var(--bg4);text-align:right;font-variant-numeric:tabular-nums;}
table.gt td.gk{text-align:left;font-weight:700;color:var(--fg2);}
table.gt td.gv{font-family:monospace;font-weight:600;}
table.gt td.gd{font-size:.71rem;}
table.gt tr.row-b3 td{background:#0d1e0f;}
table.gt tr.row-b2 td{background:#0d1e0f;}
table.gt tr.row-b1 td{background:#102010;}
table.gt tr.row-m  td{background:#2d2100;}
table.gt tr.row-s1 td{background:#1a0f00;}
table.gt tr.row-s2 td{background:#1f0a0a;}
table.gt tr.row-s3 td{background:#250505;}
table.gt tr.row-dh td{background:#0d1f2e;}
table.gt tr.row-dc td{background:#12182a;}
table.gt tr.row-dl td{background:#1f0f11;}
.lb{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.62rem;font-weight:700;}
.lb-gate{background:#0d2818;color:#3fb950;}
.lb-day{background:#0d1e3a;color:#58a6ff;}
.lb-cur{background:transparent;color:#58a6ff;border:1px solid #58a6ff66;}
.zb{display:inline-block;padding:2px 6px;border-radius:3px;font-size:.65rem;font-weight:700;}
.z-b2up{background:#0d2818;color:#3fb950;}
.z-b1b2{background:#112211;color:#56d364;}
.z-mb1{background:#2d2100;color:#d29922;}
.z-s1m{background:#2d1500;color:#f0883e;}
.z-s2s1{background:#2d0f0f;color:#f85149;}
.z-s2dn{background:#3a0505;color:#ff7b72;}
.wb{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.63rem;font-weight:700;}
.wb-strong{background:#2d0a0a;color:#ff7b72;}
.wb-mid{background:#2d1a00;color:#f0883e;}
.wb-weak{background:#2d2500;color:#d29922;}
.wb-none{background:#1c2128;color:#8b949e;}
.slist{list-style:none;padding:0;}
.slist li{padding:6px 0;border-bottom:1px solid var(--border2);font-size:.78rem;line-height:1.6;display:flex;gap:7px;align-items:flex-start;}
.slist li:last-child{border-bottom:none;}
.rnk{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;font-size:.62rem;font-weight:700;flex-shrink:0;margin-top:1px;}
.r1{background:#c9510c;color:#fff;}.r2{background:#388bfd;color:#fff;}
.r3{background:#2ea043;color:#fff;}.r4{background:#3d3d3d;color:#aaa;}
.tag{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.62rem;font-weight:700;margin-right:3px;white-space:nowrap;}
.tlong{background:#0d2818;color:#3fb950;}.tshort{background:#3a0505;color:#f85149;}
.tstop{background:#3a1a00;color:#f0883e;}.twatch{background:#1c1c2e;color:#79c0ff;}.thold{background:#1c2128;color:#8b949e;}
table.mt{width:100%;border-collapse:collapse;font-size:.74rem;}
table.mt th{background:var(--bg);padding:5px 8px;text-align:left;color:var(--fg3);font-weight:500;border-bottom:1px solid var(--border);white-space:nowrap;}
table.mt th:nth-child(n+3){text-align:right;}
table.mt td{padding:5px 8px;border-bottom:1px solid var(--bg4);vertical-align:middle;}
table.mt td:nth-child(n+3){text-align:right;font-variant-numeric:tabular-nums;}
table.mt tr.cat-hdr td{background:var(--bg3);color:var(--fg3);font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;padding:3px 8px;}
table.mt tr:hover td{background:#1c2128;}
.pos{color:var(--bull);}.neg{color:var(--bear);}.neu{color:var(--fg3);}
.warn-dot{font-size:.6rem;letter-spacing:1px;}
.ws{color:#f85149;}.wm{color:#e3a400;}.wk{color:#d29922;}
.ding{padding:11px 14px;font-size:.79rem;line-height:1.85;color:var(--fg2);}
.ding p{margin-bottom:6px;}.ding strong{color:var(--accent);}
.footer{text-align:center;padding:12px;color:var(--fg3);font-size:.68rem;border-top:1px solid var(--border2);margin-top:14px;}
@media(max-width:640px){
  .twocol{grid-template-columns:1fr;}
  .col{border-right:none;border-bottom:1px solid var(--border);}
  table.mt{font-size:.68rem;}
}
"""

# ── OHLC 區塊 ──────────────────────────────────────────────
def build_ohlc_block(today_row, prev_row, rows_hist, label, is_t5f=False):
    fmt = '.2f' if is_t5f else '.0f'
    o = float(today_row.get('open',0) or 0)
    h = float(today_row.get('high',0) or 0)
    l = float(today_row.get('low',0) or 0)
    c = float(today_row.get('close',0) or 0)
    prev_o = float(prev_row.get('open',0) or 0) if prev_row else 0
    prev_c = float(prev_row.get('close',0) or 0) if prev_row else 0

    # 開盤相對前日收
    open_diff = o - prev_c if prev_c else 0
    open_tag = f'+{open_diff:{fmt}} 開高 🔺' if open_diff > 0 else (f'{open_diff:{fmt}} 開低 🔻' if open_diff < 0 else '平開 ➡️')
    open_color = '#3fb950' if open_diff > 0 else ('#f85149' if open_diff < 0 else '#8b949e')
    open_bg = '#0d1a0d' if open_diff > 0 else ('#1f0a0a' if open_diff < 0 else '#1c2128')

    # 收盤漲跌
    chg = c - prev_c if prev_c else 0
    chg_tag = f'{chg:+{fmt}} 收漲 🔺' if chg > 0 else f'{chg:{fmt}} 收跌 🔻'
    chg_color = '#3fb950' if chg > 0 else '#f85149'
    close_border = '#3fb95044' if chg > 0 else '#f8514944'

    # 今日最高與歷史高點
    all_highs = [float(r.get('high',0) or 0) for r in rows_hist]
    peak_h = max(all_highs) if all_highs else h
    prev_h = float(prev_row.get('high',0) or 0) if prev_row else h
    h_diff = h - prev_h
    h_tag = f'{h_diff:+{fmt}} 高點新高 🔺' if h_diff > 0 else f'{h_diff:{fmt}} 高點新低 🔻'
    h_color = '#3fb950' if h_diff > 0 else '#f85149'
    h_bg = '#0d1a0d' if h_diff > 0 else '#1f0a0a'

    # 今日最低與歷史低點
    prev_l = float(prev_row.get('low',0) or 0) if prev_row else l
    l_diff = l - prev_l
    l_tag = f'{l_diff:+{fmt}} 低點新高 🔺' if l_diff > 0 else f'{l_diff:{fmt}} 低點新低 🔻'
    l_color = '#3fb950' if l_diff > 0 else '#f85149'
    l_bg = '#0d1a0d' if l_diff > 0 else '#1f0a0a'

    # 高點峰值日期（找最高）
    peak_date = ''
    for r in reversed(rows_hist):
        if abs(float(r.get('high',0) or 0) - peak_h) < 0.01:
            peak_date = r.get('date','')[-5:].replace('-','/')
            break

    return f'''
<div class="col">
  <div class="clabel" style="margin-bottom:10px;">{label}</div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:5px;">
    <div style="flex:1;min-width:70px;background:var(--bg3);border-radius:6px 6px 0 0;padding:8px 10px 6px;text-align:center;">
      <div style="font-size:.63rem;color:var(--fg3);margin-bottom:3px;">開盤</div>
      <div style="font-family:monospace;font-size:1.05rem;font-weight:700;color:var(--fg2);">{o:{fmt}}</div>
    </div>
    <div style="flex:1;min-width:70px;background:var(--bg3);border-radius:6px 6px 0 0;padding:8px 10px 6px;text-align:center;">
      <div style="font-size:.63rem;color:var(--fg3);margin-bottom:3px;">最高</div>
      <div style="font-family:monospace;font-size:1.05rem;font-weight:700;color:var(--bull);">{h:{fmt}}</div>
    </div>
    <div style="flex:1;min-width:70px;background:var(--bg3);border-radius:6px 6px 0 0;padding:8px 10px 6px;text-align:center;">
      <div style="font-size:.63rem;color:var(--fg3);margin-bottom:3px;">最低</div>
      <div style="font-family:monospace;font-size:1.05rem;font-weight:700;color:var(--bear);">{l:{fmt}}</div>
    </div>
    <div style="flex:1;min-width:70px;background:var(--bg3);border-radius:6px 6px 0 0;padding:8px 10px 6px;text-align:center;border:1px solid {close_border};border-bottom:none;">
      <div style="font-size:.63rem;color:var(--bear);margin-bottom:3px;">收盤 <span style="font-size:.58rem;color:var(--fg3);">（全日盤）</span></div>
      <div style="font-family:monospace;font-size:1.05rem;font-weight:700;color:{'var(--bull)' if chg>=0 else 'var(--bear)'};">{c:{fmt}}</div>
    </div>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;">
    <div style="flex:1;min-width:70px;background:{open_bg};border-radius:0 0 6px 6px;padding:4px 10px 6px;text-align:center;">
      <div style="font-size:.62rem;color:{open_color};font-weight:700;">{open_tag}</div>
      <div style="font-size:.59rem;color:var(--fg3);">vs 前日收 {prev_c:{fmt}}</div>
    </div>
    <div style="flex:1;min-width:70px;background:{h_bg};border-radius:0 0 6px 6px;padding:4px 10px 6px;text-align:center;">
      <div style="font-size:.62rem;color:{h_color};font-weight:700;">{h_tag}</div>
      <div style="font-size:.59rem;color:var(--fg3);">高點峰值 {peak_h:{fmt}}（{peak_date}）</div>
    </div>
    <div style="flex:1;min-width:70px;background:{l_bg};border-radius:0 0 6px 6px;padding:4px 10px 6px;text-align:center;">
      <div style="font-size:.62rem;color:{l_color};font-weight:700;">{l_tag}</div>
      <div style="font-size:.59rem;color:var(--fg3);">前低 {prev_l:{fmt}}</div>
    </div>
    <div style="flex:1;min-width:70px;background:{'#0d1a0d' if chg>=0 else '#1f0a0a'};border-radius:0 0 6px 6px;padding:4px 10px 6px;text-align:center;border:1px solid {'#3fb95022' if chg>=0 else '#f8514922'};border-top:none;">
      <div style="font-size:.62rem;color:{chg_color};font-weight:700;">{chg_tag}</div>
      <div style="font-size:.59rem;color:var(--fg3);">vs 前日收 {prev_c:{fmt}}</div>
    </div>
  </div>
</div>'''

# ── 振幅區塊 ───────────────────────────────────────────────
def build_range_block(today_row, rows, label, is_t5f=False):
    fmt = '.2f' if is_t5f else '.0f'
    h = float(today_row.get('high',0) or 0)
    l = float(today_row.get('low',0) or 0)
    rng = h - l
    avg5  = calc_avg_range(rows, 5)
    avg10 = calc_avg_range(rows, 10)
    avg20 = calc_avg_range(rows, 20)

    def pct_diff(r, avg):
        if avg <= 0: return ''
        d = (r - avg) / avg * 100
        return f'今日 {d:+.0f}%'

    # 視覺條寬度（相對avg20，最大90%）
    bar_pct = min(int(rng / avg20 * 50), 90) if avg20 > 0 else 30
    bar5  = min(int(avg5  / avg20 * 50), 90) if avg20 > 0 else 50
    bar10 = min(int(avg10 / avg20 * 50), 90) if avg20 > 0 else 45
    bar20 = 50  # 基準

    # 判讀文字
    if avg20 > 0:
        ratio = rng / avg20
        if ratio < 0.7:
            judge = f'🔵 縮量低振幅 — 今日振幅 {rng:{fmt}} 低於各均幅，量縮格局'
        elif ratio > 1.3:
            judge = f'🔴 放量大振幅 — 今日振幅 {rng:{fmt}} 高於各均幅，波動劇烈'
        else:
            judge = f'⚪ 正常振幅 — 今日振幅 {rng:{fmt}} 接近均幅水準'
    else:
        judge = f'振幅 {rng:{fmt}}'

    return f'''
<div class="col">
  <div class="clabel" style="margin-bottom:10px;">{label}</div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
    <div style="flex:1.3;min-width:80px;background:var(--bg3);border-radius:6px;padding:10px 10px 8px;text-align:center;border:1px solid #d2992244;">
      <div style="font-size:.63rem;color:var(--warn);margin-bottom:3px;font-weight:600;">今日振幅</div>
      <div style="font-family:monospace;font-size:1.2rem;font-weight:700;color:var(--warn);">{rng:{fmt}}</div>
      <div style="font-size:.59rem;color:var(--fg3);margin-top:2px;">高 {h:{fmt}} / 低 {l:{fmt}}</div>
    </div>
    <div style="flex:1;min-width:68px;background:var(--bg3);border-radius:6px;padding:8px 8px 6px;text-align:center;">
      <div style="font-size:.62rem;color:var(--fg3);margin-bottom:3px;">5日均幅</div>
      <div style="font-family:monospace;font-size:1rem;font-weight:700;color:var(--fg2);">{avg5:{fmt}}</div>
      <div style="font-size:.62rem;font-weight:700;color:var(--bull);margin-top:2px;">{pct_diff(rng,avg5)}</div>
    </div>
    <div style="flex:1;min-width:68px;background:var(--bg3);border-radius:6px;padding:8px 8px 6px;text-align:center;">
      <div style="font-size:.62rem;color:var(--fg3);margin-bottom:3px;">10日均幅</div>
      <div style="font-family:monospace;font-size:1rem;font-weight:700;color:var(--fg2);">{avg10:{fmt}}</div>
      <div style="font-size:.62rem;font-weight:700;color:var(--bull);margin-top:2px;">{pct_diff(rng,avg10)}</div>
    </div>
    <div style="flex:1;min-width:68px;background:var(--bg3);border-radius:6px;padding:8px 8px 6px;text-align:center;">
      <div style="font-size:.62rem;color:var(--fg3);margin-bottom:3px;">20日均幅</div>
      <div style="font-family:monospace;font-size:1rem;font-weight:700;color:var(--fg2);">{avg20:{fmt}}</div>
      <div style="font-size:.62rem;font-weight:700;color:var(--bull);margin-top:2px;">{pct_diff(rng,avg20)}</div>
    </div>
  </div>
  <div style="margin-bottom:4px;">
    <div style="font-size:.62rem;color:var(--fg3);margin-bottom:4px;">振幅比較（相對20日均幅）</div>
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">
      <div style="width:34px;font-size:.62rem;color:var(--warn);text-align:right;flex-shrink:0;">今日</div>
      <div style="flex:1;background:var(--bg4);border-radius:3px;height:12px;overflow:hidden;">
        <div style="width:{bar_pct}%;height:100%;background:linear-gradient(90deg,#d29922,#f0883e);border-radius:3px;"></div>
      </div>
      <div style="width:36px;font-size:.62rem;font-family:monospace;color:var(--warn);font-weight:700;">{rng:{fmt}}</div>
    </div>
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">
      <div style="width:34px;font-size:.62rem;color:var(--fg3);text-align:right;flex-shrink:0;">5日均</div>
      <div style="flex:1;background:var(--bg4);border-radius:3px;height:10px;overflow:hidden;">
        <div style="width:{bar5}%;height:100%;background:#3d3d3d;border-radius:3px;"></div>
      </div>
      <div style="width:36px;font-size:.62rem;font-family:monospace;color:var(--fg3);">{avg5:{fmt}}</div>
    </div>
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">
      <div style="width:34px;font-size:.62rem;color:var(--fg3);text-align:right;flex-shrink:0;">10日均</div>
      <div style="flex:1;background:var(--bg4);border-radius:3px;height:10px;overflow:hidden;">
        <div style="width:{bar10}%;height:100%;background:#2d3d3d;border-radius:3px;"></div>
      </div>
      <div style="width:36px;font-size:.62rem;font-family:monospace;color:var(--fg3);">{avg10:{fmt}}</div>
    </div>
    <div style="display:flex;align-items:center;gap:6px;">
      <div style="width:34px;font-size:.62rem;color:var(--fg3);text-align:right;flex-shrink:0;">20日均</div>
      <div style="flex:1;background:var(--bg4);border-radius:3px;height:10px;overflow:hidden;">
        <div style="width:{bar20}%;height:100%;background:#263d3d;border-radius:3px;"></div>
      </div>
      <div style="width:36px;font-size:.62rem;font-family:monospace;color:var(--fg3);">{avg20:{fmt}}</div>
    </div>
  </div>
  <div style="margin-top:6px;padding:5px 8px;background:var(--bg4);border-radius:4px;border-left:2px solid #58a6ff;">
    <span style="font-size:.65rem;color:#58a6ff;font-weight:700;">{judge.split("—")[0].strip()}</span>
    <span style="font-size:.63rem;color:var(--fg3);"> — {judge.split("—")[1].strip() if "—" in judge else ""}</span>
  </div>
</div>'''

# ── 三關價表格 ─────────────────────────────────────────────
def build_gate_table(gates, today_row, prev_row, label, is_t5f=False):
    fmt = '.2f' if is_t5f else '.0f'
    c = float(today_row.get('close',0) or 0)
    prev_h = float(prev_row.get('high',0) or 0) if prev_row else 0
    prev_l = float(prev_row.get('low',0) or 0) if prev_row else 0

    zone, zone_cls = zone_label(c, gates)
    is_panic = c < gates['s2']
    is_bull  = c >= gates['b2']

    zone_style = 'background:#3d0f0f;color:#f85149;' if is_panic else ''
    badge_color = '🔴 恐慌區' if is_panic else ('🟢 強多區' if is_bull else '')

    def row(cls, key, src_cls, src_label, val, diff, note, val_color='', note_color=''):
        diff_str = f'+{diff:{fmt}}' if diff > 0 else (f'{diff:{fmt}}' if diff < 0 else '—')
        diff_cls = 'pos' if diff > 0 else ('neg' if diff < 0 else '')
        vc = f'color:{val_color};' if val_color else ''
        nc = f'color:{note_color};' if note_color else 'color:var(--fg3);'
        return f'''<tr class="{cls}">
          <td class="gk">{key}</td>
          <td><span class="lb {src_cls}">{src_label}</span></td>
          <td class="gv" style="{vc}">{val:{fmt}}</td>
          <td class="gd {diff_cls}">{diff_str}</td>
          <td class="gd" style="{nc}">{note}</td>
        </tr>'''

    rows_html  = row('row-b3', 'B3',    'lb-gate', '今日關卡', gates['b3'], gates['b3']-c, '強多上限')
    rows_html += row('row-b2', 'B2',    'lb-gate', '今日關卡', gates['b2'], gates['b2']-c, '多方確認', '#3fb950')
    rows_html += row('row-b1', 'B1',    'lb-gate', '今日關卡', gates['b1'], gates['b1']-c, '主要壓力', '#58a6ff', '#d29922')
    if prev_h > 0:
        rows_html += row('row-dh', '昨日高', 'lb-day',  '昨日盤',  prev_h,     prev_h-c,   '昨日高點', '#79c0ff')
    rows_html += row('row-m',  'M',     'lb-gate', '今日關卡', gates['m'],  gates['m']-c,  '⬅ 多空分界', '#d29922', '#d29922')
    rows_html += f'''<tr class="row-dc">
      <td class="gk">昨日收★</td>
      <td><span class="lb lb-cur">★昨收</span></td>
      <td class="gv" style="color:#f85149;">{c:{fmt}}</td>
      <td class="gd">—</td>
      <td class="gd" style="color:#f85149;">{zone}</td>
    </tr>'''
    if prev_l > 0:
        rows_html += row('row-dl', '昨日低', 'lb-day',  '昨日盤',  prev_l,     prev_l-c,   '昨日低點', '#79c0ff')
    rows_html += row('row-s1', 'S1',    'lb-gate', '今日關卡', gates['s1'], gates['s1']-c, '第一支撐')
    rows_html += row('row-s2', 'S2 ⬅', 'lb-gate', '今日關卡', gates['s2'], gates['s2']-c, '超賣警示', '#f85149', '#f85149')
    rows_html += row('row-s3', 'S3',    'lb-gate', '今日關卡', gates['s3'], gates['s3']-c, '深空支撐', '#f85149')

    warn_msg = f'⚠️ 昨收 {c:{fmt}} 位於 S2（{gates["s2"]:{fmt}}）以下——空方恐慌格局' if is_panic else \
               f'✅ 昨收 {c:{fmt}} 位於 M（{gates["m"]:{fmt}}）以上——多方偏向' if c >= gates['m'] else \
               f'⚠️ 昨收 {c:{fmt}} 位於 S2~M 空方區間，需守 S1（{gates["s1"]:{fmt}}）'

    warn_bg = '#1f0a0a' if is_panic else ('#0d1e0f' if c >= gates['m'] else '#2d1a00')
    warn_color = '#f85149' if is_panic else ('#3fb950' if c >= gates['m'] else '#f0883e')

    badge_html = f'<span class="wb wb-strong" style="margin-left:4px;">{badge_color}</span>' if badge_color else ''

    return f'''
<div class="col">
  <div class="clabel">{label}
    <span class="zb {zone_cls}" style="{zone_style}">{zone}</span>
    {badge_html}
  </div>
  <table class="gt">
    <thead><tr><th>價位</th><th>來源</th><th>數值</th><th>距昨收</th><th>說明</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <div style="font-size:.68rem;color:{warn_color};margin-top:5px;padding:4px 6px;background:{warn_bg};border-radius:4px;">
    {warn_msg}
  </div>
</div>'''

# ── 策略區塊 ───────────────────────────────────────────────
def build_strategy(gates, today_c, label, is_t5f=False):
    fmt = '.2f' if is_t5f else '.0f'
    m   = gates['m']
    b1  = gates['b1']
    b2  = gates['b2']
    s1  = gates['s1']
    s2  = gates['s2']
    zone, _ = zone_label(today_c, gates)
    is_panic = today_c < s2
    is_above_m = today_c >= m

    if is_panic:
        items = [
            ('r1', 'tstop', '首要', f'M（{m:{fmt}}）是今日多空樞紐',
             f'昨收 {today_c:{fmt}} 跌入 S2 以下恐慌區。今日若能站上 M（{m:{fmt}}），偏多操作；否則偏空觀望。'),
            ('r2', 'tshort', '順空主軸', f'反彈至 M（{m:{fmt}}）無法站穩 → 繼續做空',
             f'空方格局明確，反彈至 M 附近（{m:{fmt}}±{20 if is_t5f else 50}）被壓回，可順勢做空，目標 S1（{s1:{fmt}}）→ S2（{s2:{fmt}}）。'),
            ('r3', 'twatch', '觀察多方條件', f'若站穩 M（{m:{fmt}}）+ 量配合，才考慮極輕倉試多',
             f'S2以下彈到 M 是試多區，須量放且收盤站穩 M 以上才成立。倉位 1/3 以下，停損設 S1（{s1:{fmt}}）跌破。'),
            ('r4', 'tstop', '停損紀律', f'跌破昨低 → 恐慌加深，清多轉觀望',
             f'任何多單停損不超過 B2（{b2:{fmt}}）。恐慌區不猜底，執行停損優先。'),
        ]
    elif is_above_m:
        items = [
            ('r1', 'tlong', '多方主軸', f'M（{m:{fmt}}）以上偏多，守 M 操作',
             f'昨收 {today_c:{fmt}} 位於 M 以上，多方偏向。逢 M 附近回測是做多機會，目標 B1（{b1:{fmt}}）→ B2（{b2:{fmt}}）。'),
            ('r2', 'twatch', '觀察 B2', f'突破 B2（{b2:{fmt}}）→ 強多訊號，加碼追多',
             f'B2 突破是多方確認關卡，突破且守住可追多，目標 B3。注意假突破風險（多頭年假突破率約 26-40%）。'),
            ('r3', 'tshort', '多轉空條件', f'跌破 M（{m:{fmt}}）且量縮 → 減多觀望',
             f'M 失守後若量縮持續，需減多倉。跌破 S1（{s1:{fmt}}）則清多，方向切至空方。'),
            ('r4', 'tstop', '停損紀律', f'停損設於 S1（{s1:{fmt}}）跌破',
             f'多單嚴格停損，S1 跌破減碼，S2（{s2:{fmt}}）跌破清空。'),
        ]
    else:
        items = [
            ('r1', 'twatch', '觀望為主', f'S2~M 震盪區，等方向明確',
             f'昨收 {today_c:{fmt}} 在 S2~M 之間，多空拉鋸。等待站上 M（{m:{fmt}}）或跌破 S2（{s2:{fmt}}）再決策。'),
            ('r2', 'tlong', '守 S1 做多條件', f'站穩 S1（{s1:{fmt}}）+ 反彈量放 → 輕倉試多',
             f'若價格守住 S1 且出現量增反彈，輕倉試多目標 M（{m:{fmt}}），空間有限。'),
            ('r3', 'tshort', '跌破 S2 做空', f'跌破 S2（{s2:{fmt}}）→ 轉空方恐慌格局',
             f'S2 收死代表空方確認，不逆勢抄底，等量縮止跌訊號。'),
            ('r4', 'tstop', '停損紀律', f'多單停損 S2，空單停損 M',
             f'嚴格執行停損，不在震盪區加大倉位。'),
        ]

    li_html = ''
    for idx, (rnk_cls, tag_cls, tag_txt, title, detail) in enumerate(items):
        li_html += f'''
        <li>
          <span class="rnk {rnk_cls}">{idx+1}</span>
          <div><span class="tag {tag_cls}">{tag_txt}</span><strong>{title}</strong><br>
          <span style="color:var(--fg3);font-size:.75rem;">{detail}</span></div>
        </li>'''

    return f'''
<div class="col">
  <div class="clabel">{label} 今日策略</div>
  <ul class="slist">{li_html}</ul>
</div>'''

# ── 全球18商品表格 ─────────────────────────────────────────
def build_global_table(data_dir: Path, report_date: str) -> str:
    rows_html = ''
    prev_cat  = ''

    for code, name, cat, fmt, note in COMMODITIES:
        # 分類標題列
        if cat != prev_cat:
            rows_html += f'<tr class="cat-hdr"><td colspan="7">{cat}</td></tr>\n'
            prev_cat = cat

        csv_path = data_dir / f'{code}_daily.csv'
        rows = read_csv_last_n(csv_path, 3)

        if len(rows) < 2:
            rows_html += f'<tr><td>{name}</td><td style="font-family:monospace;color:var(--fg3)">{code}</td><td colspan="5" class="neu">資料不足</td></tr>\n'
            continue

        today_r = rows[-1]
        prev_r  = rows[-2]
        c    = float(today_r.get('close',0) or 0)
        prev_c = float(prev_r.get('close',0) or 0)
        prev_h = float(prev_r.get('high',0) or 0)
        prev_l = float(prev_r.get('low',0) or 0)

        gates = calc_gates(prev_h, prev_l, prev_c)
        zone, zone_cls = zone_label(c, gates)
        direction, is_bull_dir = direction_label(c, gates)
        dots, dot_cls, wb_cls, wb_txt = warn_level(c, gates, prev_c)

        chg_pct = (c - prev_c) / prev_c * 100 if prev_c else 0
        chg_cls = 'pos' if chg_pct > 0 else ('neg' if chg_pct < 0 else 'neu')
        dir_color = 'var(--bull)' if is_bull_dir else '#f85149'

        note_td = f' {note}' if note else ''
        dir_display = direction + note_td

        dot_span = f' <span class="wb {wb_cls}">{wb_txt}</span>' if dots else '<span class="wb wb-none">—</span>'
        rows_html += f'''<tr>
          <td>{name}</td>
          <td style="font-family:monospace;color:var(--fg3)">{code}</td>
          <td style="font-family:monospace;">{c:{fmt}}</td>
          <td class="{chg_cls}">{chg_pct:+.2f}%</td>
          <td><span class="zb {zone_cls}" style="font-size:.63rem;">{zone}</span></td>
          <td><span class="warn-dot {dot_cls}">{dots}</span>{dot_span}</td>
          <td style="font-size:.7rem;color:{dir_color}">{dir_display}</td>
        </tr>\n'''

    return f'''
<div class="sec">
  <div class="st">🌐 全球 18 商品方向對照（日線，{report_date} 收盤）</div>
  <div style="overflow-x:auto;padding:0 0 8px;">
    <table class="mt">
      <thead>
        <tr><th>商品</th><th>代碼</th><th>收盤</th><th>漲跌%</th><th>方向</th><th>警訊</th><th>所在區間</th></tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</div>'''

# ── 老師叮嚀 ───────────────────────────────────────────────
def build_ding(tx_gates, tx_c, tx_rng, avg20_tx, t5f_gates, t5f_c):
    fmt_tx  = '.0f'
    fmt_t5f = '.2f'
    tx_zone, _  = zone_label(tx_c, tx_gates)
    t5f_zone, _ = zone_label(t5f_c, t5f_gates)

    # 勝算評估
    if tx_c < tx_gates['s2']:
        odds = '偏空 7 成 / 偏多 3 成'
        odds_color = '#f85149'
        odds_bg = '#1f0a0a'
        main_msg = 'S2以下恐慌區，主軸順空觀望，彈至 M 再看反應動態調整。'
    elif tx_c >= tx_gates['b2']:
        odds = '偏多 7 成 / 偏空 3 成'
        odds_color = '#3fb950'
        odds_bg = '#0d1e0f'
        main_msg = 'B2以上強多格局，主軸做多，注意假突破風險。'
    elif tx_c >= tx_gates['m']:
        odds = '偏多 6 成 / 偏空 4 成'
        odds_color = '#d29922'
        odds_bg = '#2d2100'
        main_msg = 'M以上偏多，守 M 做多，等 B1/B2 確認。'
    else:
        odds = '多空各半，震盪觀望'
        odds_color = '#8b949e'
        odds_bg = '#1c2128'
        main_msg = 'S2~M 震盪區，等方向明確再出手。'

    range_ratio = tx_rng / avg20_tx * 100 if avg20_tx > 0 else 100
    range_comment = f'今日 TX 振幅 {tx_rng:{fmt_tx}} 點，為 20 日均幅的 {range_ratio:.0f}%。' + \
                    ('量縮跌 S2 是「低能量的空方延伸」，不是恐慌崩潰量，持續觀察量能。' if range_ratio < 80 else
                     '放量大波動，注意方向確認後的延續性。' if range_ratio > 120 else
                     '振幅正常，盤面無特殊訊號。')

    ma02_msg = ('S2 以下操作原則：空方主戰場在 S2~M，彈到 M（' + f'{tx_gates["m"]:{fmt_tx}}' + '）是觀察點而非進多點。') \
               if tx_c < tx_gates['s2'] else \
               ('M 以上操作原則：多方有慣性，持倉做多，逢回測 M 附近加碼。')

    return f'''
<div class="sec">
  <div class="st">🎓 老師叮嚀</div>
  <div class="ding">
    <p><strong>D-01（動態調整核心）</strong>　TX {tx_zone}，T5F {t5f_zone}。結構訊號需搭配盤中量能動態修正，靜態關卡只是框架。</p>
    <p><strong>MA-02（漲跌不對稱）</strong>　{ma02_msg}</p>
    <p><strong>V-03（量能判讀）</strong>　{range_comment}</p>
    <p><strong>KN-03（全球聯動）</strong>　請參考上方全球18商品表格，確認 TX 方向與美股、亞洲市場的共振程度。台股若要方向確認，需美股同步配合。</p>
    <p style="color:{odds_color};font-size:.75rem;margin-top:6px;padding:6px 8px;background:{odds_bg};border-radius:4px;border-left:3px solid {odds_color};">
      ⚠️ 今日勝算評估：<strong>{odds}</strong>。{main_msg}最終決策權在您自己。
    </p>
  </div>
</div>'''

# ── 主報告建構 ─────────────────────────────────────────────
def build_html() -> str:
    tx_rows  = read_csv_last_n(DATA_DIR / 'TX_daily.csv',  22)
    t5f_rows = read_csv_last_n(DATA_DIR / 'T5F_daily.csv', 22)

    if len(tx_rows) < 2:
        return '<p>TX 資料不足</p>'

    # TX：用最後一筆作為「今日」，倒數第二筆作為「前日」
    tx_today  = tx_rows[-1]
    tx_prev   = tx_rows[-2]
    tx_c      = float(tx_today.get('close',0) or 0)
    tx_gates  = calc_gates(
        float(tx_prev.get('high',0) or 0),
        float(tx_prev.get('low',0) or 0),
        float(tx_prev.get('close',0) or 0)
    )
    report_date = tx_today.get('date', TODAY)

    # T5F
    t5f_today = t5f_rows[-1] if len(t5f_rows) >= 1 else {}
    t5f_prev  = t5f_rows[-2] if len(t5f_rows) >= 2 else {}
    t5f_c     = float(t5f_today.get('close',0) or 0) if t5f_today else 0
    t5f_gates = calc_gates(
        float(t5f_prev.get('high',0) or 0),
        float(t5f_prev.get('low',0) or 0),
        float(t5f_prev.get('close',0) or 0)
    ) if t5f_prev else calc_gates(1,1,1)

    # 振幅
    tx_rng  = float(tx_today.get('high',0) or 0) - float(tx_today.get('low',0) or 0)
    avg20_tx = calc_avg_range(tx_rows, 20)

    # 標題 badge
    tx_zone, tx_zone_cls = zone_label(tx_c, tx_gates)
    if tx_c < tx_gates['s2']:
        badge_html = '<span class="hbadge hb-bear">🔴 TX 空方</span><span class="hbadge hb-bear">🔴 恐慌區</span>'
    elif tx_c >= tx_gates['b2']:
        badge_html = '<span class="hbadge hb-bull">🟢 TX 多方</span><span class="hbadge hb-bull">🟢 強多區</span>'
    elif tx_c >= tx_gates['m']:
        badge_html = '<span class="hbadge hb-bull">🟢 TX 偏多</span>'
    else:
        badge_html = '<span class="hbadge hb-warn">🟡 TX 空方區</span>'

    # 報告日（次一交易日）
    report_dt = datetime.strptime(report_date, '%Y-%m-%d') + timedelta(days=1)
    while report_dt.weekday() >= 5:
        report_dt += timedelta(days=1)
    report_day_str = f'{report_dt.strftime("%m/%d")}（{WEEKDAY_MAP[report_dt.weekday()]}）'

    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>三關價日報 {report_date}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<div class="hdr">
  <div>
    <div class="htitle">三關價日報 {badge_html}</div>
    <div class="hsub">台指期 TX・台灣50 T5F・日線三關價・依 {report_date} 收盤計算・{report_day_str} 有效</div>
  </div>
  <div class="hmeta">
    資料日 {report_date}<br>
    報告日 {report_day_str}<br>
    蘭老師AI分身
  </div>
</div>

<div class="sec" style="margin-bottom:10px;">
  <div class="st">📅 昨日全日盤 OHLC（{report_date}・日盤＋夜盤合計）</div>
  <div class="twocol">
    {build_ohlc_block(tx_today, tx_prev, tx_rows, '台指期 TX', is_t5f=False)}
    {build_ohlc_block(t5f_today, t5f_prev, t5f_rows, '台灣50 T5F', is_t5f=True) if t5f_today else '<div class="col"><div class="clabel">台灣50 T5F</div><p style="color:var(--fg3);padding:10px;">資料不足</p></div>'}
  </div>
</div>

<div class="sec" style="margin-bottom:10px;">
  <div class="st">📊 振幅分析（今日 vs 均幅比較）</div>
  <div class="twocol">
    {build_range_block(tx_today, tx_rows, '台指期 TX', is_t5f=False)}
    {build_range_block(t5f_today, t5f_rows, '台灣50 T5F', is_t5f=True) if t5f_today else '<div class="col"><p style="color:var(--fg3);padding:10px;">資料不足</p></div>'}
  </div>
</div>

<div class="sec">
  <div class="st">📐 今日三關價（{report_day_str} 有效，依 {report_date} 收盤計算）</div>
  <div class="twocol">
    {build_gate_table(tx_gates, tx_today, tx_prev, '台指期 TX', is_t5f=False)}
    {build_gate_table(t5f_gates, t5f_today, t5f_prev, '台灣50 T5F', is_t5f=True) if t5f_today and t5f_prev else '<div class="col"><p style="color:var(--fg3);padding:10px;">資料不足</p></div>'}
  </div>
</div>

<div class="sec">
  <div class="st">🎯 今日操作策略（依重要性排序）</div>
  <div class="twocol">
    {build_strategy(tx_gates, tx_c, '台指期 TX', is_t5f=False)}
    {build_strategy(t5f_gates, t5f_c, '台灣50 T5F', is_t5f=True) if t5f_c > 0 else '<div class="col"><p style="color:var(--fg3);padding:10px;">資料不足</p></div>'}
  </div>
</div>

{build_global_table(DATA_DIR, report_date)}

{build_ding(tx_gates, tx_c, tx_rng, avg20_tx, t5f_gates, t5f_c)}

<div class="footer">
  三關價日報・依 {report_date} 收盤計算・{report_day_str} 有效<br>
  蘭老師AI分身・群益金鼎証券 中山分公司・僅供參考，投資決策請自行判斷
</div>

</div>
</body>
</html>'''

# ── 寄信 ───────────────────────────────────────────────────
def send_email():
    smtp_user = os.environ['SMTP_USER']
    smtp_pass = os.environ['SMTP_PASS']
    mail_to   = os.environ['MAIL_TO']

    html = build_html()

    # 從 HTML 標題推算報告日期
    tx_rows = read_csv_last_n(DATA_DIR / 'TX_daily.csv', 2)
    report_date = tx_rows[-1].get('date', TODAY) if tx_rows else TODAY
    report_dt = datetime.strptime(report_date, '%Y-%m-%d') + timedelta(days=1)
    while report_dt.weekday() >= 5:
        report_dt += timedelta(days=1)
    report_day_str = f'{report_dt.strftime("%m/%d")}（{WEEKDAY_MAP[report_dt.weekday()]}）'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'三關價每日彙總報表 {TODAY} {TODAY_WEEKDAY}'
    msg['From']    = smtp_user
    msg['To']      = mail_to
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, mail_to.split(','), msg.as_string())
    print(f'✅ 日報已寄出：{TODAY}')

if __name__ == '__main__':
    send_email()
