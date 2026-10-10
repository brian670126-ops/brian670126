#!/usr/bin/env python3
"""
send_kline_report.py  v4
每日寄送 TX + T5F 日K線三關價分析報告（含 OHLC、成交量、未平倉量）
"""

import csv
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路徑設定 ──────────────────────────────────────────────
BASE = Path(__file__).parent
TX_CSV  = BASE / 'three_gate' / 'data' / 'auto' / 'TX_daily.csv'
T5F_CSV = BASE / 'three_gate' / 'data' / 'auto' / 'T5F_daily.csv'

# ── 時區 ─────────────────────────────────────────────────
TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime('%Y-%m-%d')
WEEKDAY_MAP = ['週一','週二','週三','週四','週五','週六','週日']
TODAY_WEEKDAY = WEEKDAY_MAP[datetime.now(TW).weekday()]

# ── CSV 讀取 ──────────────────────────────────────────────
def read_csv_last_n(path: Path, n: int = 10) -> list[dict]:
    """讀取 CSV 最後 n 筆，回傳 list[dict]"""
    if not path.exists():
        return []
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return rows[-n:] if len(rows) >= n else rows

# ── 三關價計算 ────────────────────────────────────────────
def calc_gates(h, l, c):
    m  = (h + l + 2*c) / 4
    b1 = 2*m - l
    b2 = 3*m - 2*l
    b3 = h + (h - l)
    s1 = 2*m - h
    s2 = 3*m - 2*h
    s3 = l - (h - l)
    return dict(m=m, b1=b1, b2=b2, b3=b3, s1=s1, s2=s2, s3=s3)

# ── 成交量 / OI 統計 ──────────────────────────────────────
def calc_volume_stats(rows: list[dict], n: int = 5) -> dict:
    """
    回傳今日量、OI，以及近 n 日平均量，和高低判斷
    CSV 欄位：volume, oi（由 fetcher 寫入）
    """
    if not rows:
        return {}

    today = rows[-1]
    vol_today = int(float(today.get('volume', 0) or 0))
    oi_today  = int(float(today.get('oi', 0) or 0))

    # 近 n 日平均（不含今日）
    hist = rows[:-1]
    if hist:
        vols = [int(float(r.get('volume', 0) or 0)) for r in hist[-n:]]
        avg_vol = int(sum(vols) / len(vols)) if vols else 0
    else:
        avg_vol = vol_today

    # 量判斷
    if avg_vol > 0:
        ratio = vol_today / avg_vol
        if ratio >= 1.3:
            vol_judge = '🔴 放量'
        elif ratio <= 0.7:
            vol_judge = '🟢 縮量'
        else:
            vol_judge = '⚪ 正常'
    else:
        vol_judge = '—'

    # OI 判斷（與前日比）
    if len(rows) >= 2:
        oi_prev = int(float(rows[-2].get('oi', 0) or 0))
        oi_diff = oi_today - oi_prev
        if oi_diff > 500:
            oi_judge = f'🔴 增倉 +{oi_diff:,}'
        elif oi_diff < -500:
            oi_judge = f'🟢 減倉 {oi_diff:,}'
        else:
            oi_judge = f'⚪ 持平 {oi_diff:+,}'
    else:
        oi_judge = '—'

    return dict(
        vol_today=vol_today,
        avg_vol=avg_vol,
        vol_judge=vol_judge,
        oi_today=oi_today,
        oi_judge=oi_judge,
    )

# ── HTML 元件 ─────────────────────────────────────────────
def kv(label, value, color='#1a1a2e'):
    return f'''
    <div style="background:#f8f9fa;border-radius:8px;padding:10px 14px;margin:4px 0;">
      <span style="color:#666;font-size:12px;">{label}</span><br>
      <span style="color:{color};font-weight:700;font-size:16px;">{value}</span>
    </div>'''

def section_title(text):
    return f'<h3 style="color:#1a1a2e;border-left:4px solid #e74c3c;padding-left:10px;margin:20px 0 10px;">{text}</h3>'

def gate_table(gates, last_c, fmt='.0f'):
    rows_html = ''
    items = [
        ('B3', gates['b3'], '#ff6b6b'),
        ('B2', gates['b2'], '#ff9f43'),
        ('B1', gates['b1'], '#ffd32a'),
        ('M',  gates['m'],  '#48dbfb'),
        ('S1', gates['s1'], '#0abde3'),
        ('S2', gates['s2'], '#006ba6'),
        ('S3', gates['s3'], '#2c3e50'),
    ]
    for name, val, color in items:
        diff = val - last_c
        diff_str = f'+{diff:{fmt}}' if diff >= 0 else f'{diff:{fmt}}'
        highlight = ' font-weight:700;' if abs(diff) == min(abs(v - last_c) for _, v, _ in items) else ''
        rows_html += f'''
        <tr>
          <td style="padding:6px 12px;color:{color};font-weight:700;">{name}</td>
          <td style="padding:6px 12px;text-align:right;">{val:{fmt}}</td>
          <td style="padding:6px 12px;text-align:right;color:{"#e74c3c" if diff>=0 else "#27ae60"};{highlight}">{diff_str}</td>
        </tr>'''
    return f'''
    <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.1);">
      <thead>
        <tr style="background:#1a1a2e;color:#fff;">
          <th style="padding:8px 12px;text-align:left;">關卡</th>
          <th style="padding:8px 12px;text-align:right;">價位</th>
          <th style="padding:8px 12px;text-align:right;">距收盤</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>'''

def ohlc_vol_oi_block(stats: dict, today_row: dict, is_t5f: bool = False) -> str:
    fmt = '.2f' if is_t5f else '.0f'
    o = float(today_row.get('open', 0) or 0)
    h = float(today_row.get('high', 0) or 0)
    l = float(today_row.get('low',  0) or 0)
    c = float(today_row.get('close', 0) or 0)
    chg = c - o
    chg_str = f'+{chg:{fmt}}' if chg >= 0 else f'{chg:{fmt}}'
    chg_color = '#e74c3c' if chg >= 0 else '#27ae60'

    vol = f"{stats.get('vol_today', 0):,}"
    avg = f"{stats.get('avg_vol', 0):,}"
    oi  = f"{stats.get('oi_today', 0):,}"

    return f'''
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">
      {kv("開盤", f"{o:{fmt}}")}
      {kv("最高", f"{h:{fmt}}", "#e74c3c")}
      {kv("最低", f"{l:{fmt}}", "#27ae60")}
      {kv("收盤", f"{c:{fmt}}")}
      {kv("漲跌", chg_str, chg_color)}
      {kv("日期", today_row.get('date','—'))}
      {kv("成交量", vol)}
      {kv("5日均量", avg)}
      {kv("量判斷", stats.get('vol_judge','—'))}
      {kv("未平倉量", oi)}
      {kv("OI判斷", stats.get('oi_judge','—'))}
    </div>'''

def five_day_table(rows: list[dict], gates_list: list[dict], is_t5f: bool = False) -> str:
    fmt = '.2f' if is_t5f else '.0f'
    last5 = rows[-5:] if len(rows) >= 5 else rows
    last5_gates = gates_list[-5:] if len(gates_list) >= 5 else gates_list
    header = '<tr style="background:#1a1a2e;color:#fff;">' + \
             ''.join(f'<th style="padding:6px 10px;">{h}</th>' for h in
                     ['日期','開','高','低','收','量','OI','M']) + '</tr>'
    body = ''
    for r, g in zip(last5, last5_gates):
        c = float(r.get('close', 0) or 0)
        above_m = c >= g['m']
        bg = '#fff8f8' if above_m else '#f8fff8'
        body += f'<tr style="background:{bg};text-align:right;">'
        body += f'<td style="padding:5px 10px;text-align:left;">{r.get("date","")}</td>'
        for col in ['open','high','low','close']:
            body += f'<td style="padding:5px 10px;">{float(r.get(col,0) or 0):{fmt}}</td>'
        body += f'<td style="padding:5px 10px;">{int(float(r.get("volume",0) or 0)):,}</td>'
        body += f'<td style="padding:5px 10px;">{int(float(r.get("oi",0) or 0)):,}</td>'
        body += f'<td style="padding:5px 10px;color:#0984e3;">{g["m"]:{fmt}}</td>'
        body += '</tr>'
    return f'''
    <table style="width:100%;border-collapse:collapse;font-size:13px;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.1);">
      <thead>{header}</thead>
      <tbody>{body}</tbody>
    </table>'''

# ── 主報告建構 ────────────────────────────────────────────
def build_html() -> str:
    tx_rows  = read_csv_last_n(TX_CSV,  10)
    t5f_rows = read_csv_last_n(T5F_CSV, 10)

    def process(rows, label, is_t5f=False):
        if len(rows) < 2:
            return f'<p>{label} 資料不足</p>', ''
        # 今日關卡用前日 OHLC 計算
        prev = rows[-2]
        ph = float(prev.get('high',  0) or 0)
        pl = float(prev.get('low',   0) or 0)
        pc = float(prev.get('close', 0) or 0)
        gates = calc_gates(ph, pl, pc)

        today_row = rows[-1]
        last_c = float(today_row.get('close', 0) or 0)
        stats  = calc_volume_stats(rows, n=5)

        # 近5筆 gates（for 5-day table）
        gates_list = []
        for i in range(max(0, len(rows)-5), len(rows)):
            if i == 0:
                gates_list.append(gates)
                continue
            r = rows[i-1]
            g = calc_gates(
                float(r.get('high',0) or 0),
                float(r.get('low',0) or 0),
                float(r.get('close',0) or 0)
            )
            gates_list.append(g)

        fmt = '.2f' if is_t5f else '.0f'
        html = section_title(f'📊 {label} 今日三關價')
        html += ohlc_vol_oi_block(stats, today_row, is_t5f)
        html += gate_table(gates, last_c, fmt)
        html += '<br>'
        html += section_title(f'📅 {label} 近5日回顧')
        html += five_day_table(rows, gates_list, is_t5f)
        return html, ''

    tx_html,  _ = process(tx_rows,  '台指期 TX')
    t5f_html, _ = process(t5f_rows, '台灣50期貨 T5F', is_t5f=True)

    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>蘭老師 TX 深度日報 {TODAY}</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             max-width:680px;margin:0 auto;padding:20px;background:#f0f2f5;color:#1a1a2e;">

  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);
              color:#fff;border-radius:12px;padding:24px;margin-bottom:20px;text-align:center;">
    <h1 style="margin:0;font-size:22px;">🎯 蘭老師 TX 深度日報</h1>
    <p style="margin:8px 0 0;opacity:.8;">{TODAY} {TODAY_WEEKDAY} ｜ 三關價分析系統</p>
  </div>

  <div style="background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;
              box-shadow:0 2px 8px rgba(0,0,0,.08);">
    {tx_html}
  </div>

  <div style="background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;
              box-shadow:0 2px 8px rgba(0,0,0,.08);">
    {t5f_html}
  </div>

  <div style="text-align:center;color:#999;font-size:12px;margin-top:16px;">
    本報告由三關價自動分析系統產生 ｜ 僅供參考，不構成投資建議
  </div>

</body>
</html>'''

# ── 寄信 ──────────────────────────────────────────────────
def send_email():
    smtp_user = os.environ['SMTP_USER']
    smtp_pass = os.environ['SMTP_PASS']
    mail_to   = os.environ['MAIL_TO']

    html = build_html()

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'蘭老師 TX 深度日報 {TODAY} {TODAY_WEEKDAY}'
    msg['From']    = smtp_user
    msg['To']      = mail_to
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, mail_to.split(','), msg.as_string())
    print(f'✅ 日報已寄出：{TODAY}')

if __name__ == '__main__':
    send_email()
