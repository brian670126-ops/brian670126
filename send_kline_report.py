#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 蘭老師 TX 日K線分析報告 - 每日自動寄送

import os
import re
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime('%Y-%m-%d')
WEEKDAY_CN = ['一', '二', '三', '四', '五', '六', '日']
TODAY_WEEKDAY = WEEKDAY_CN[datetime.now(TW).weekday()]

BASE = Path(__file__).parent
STRATEGY_DIR = BASE / 'three_gate' / 'strategy'

TX_DAILY   = STRATEGY_DIR / 'TX_daily.md'
TX_WEEKLY  = STRATEGY_DIR / 'TX_weekly.md'
T5F_DAILY  = STRATEGY_DIR / 'T5F_daily.md'
LATEST_MD  = STRATEGY_DIR / 'latest.md'


def read_md(path):
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def parse_value(text, key):
    m = re.search(r'\*\*' + re.escape(key) + r'\*\*[：:]\s*(.+)', text)
    if m:
        return m.group(1).strip()
    m = re.search(re.escape(key) + r'[：:]\s*(.+)', text)
    if m:
        return m.group(1).strip()
    return '-'


def parse_gates(text):
    gates = {}
    for key in ['B3', 'B2', 'B1', 'M', 'S1', 'S2', 'S3']:
        m = re.search(key + r'[：:]\s*([\d,\.]+)', text)
        if m:
            try:
                gates[key] = float(m.group(1).replace(',', ''))
            except Exception:
                gates[key] = 0.0
        else:
            gates[key] = 0.0
    return gates


def direction_badge(direction):
    d = str(direction)
    if '多' in d:
        return '<span style="background:#e74c3c;color:#fff;padding:2px 10px;border-radius:4px;font-weight:bold;">多方</span>'
    elif '空' in d:
        return '<span style="background:#27ae60;color:#fff;padding:2px 10px;border-radius:4px;font-weight:bold;">空方</span>'
    else:
        return '<span style="background:#f39c12;color:#fff;padding:2px 10px;border-radius:4px;font-weight:bold;">中性</span>'


def alert_badge(alert):
    a = str(alert)
    if '強' in a:
        return '<span style="color:#e74c3c;font-weight:bold;">⚠️ ' + a + '</span>'
    elif '中' in a:
        return '<span style="color:#f39c12;font-weight:bold;">⚡ ' + a + '</span>'
    elif '弱' in a:
        return '<span style="color:#f1c40f;font-weight:bold;">💡 ' + a + '</span>'
    elif a == '-' or a == '' or '無' in a:
        return '<span style="color:#27ae60;">✅ 無警訊</span>'
    else:
        return '<span style="color:#95a5a6;">' + a + '</span>'


def gate_bar_html(gates, close_str):
    try:
        close = float(str(close_str).replace(',', ''))
    except Exception:
        close = 0.0

    rows = ''
    colors = {
        'B3': '#c0392b', 'B2': '#e74c3c', 'B1': '#e67e22',
        'M':  '#f39c12',
        'S1': '#27ae60', 'S2': '#1abc9c', 'S3': '#16a085'
    }
    labels = {
        'B3': '壓3', 'B2': '壓2', 'B1': '壓1',
        'M':  '中樞M',
        'S1': '撐1', 'S2': '撐2', 'S3': '撐3'
    }
    for key in ['B3', 'B2', 'B1', 'M', 'S1', 'S2', 'S3']:
        val = gates.get(key, 0.0)
        if val == 0.0:
            continue
        is_close = abs(val - close) < 50 if close > 0 else False
        border = '3px solid #2c3e50' if is_close else '1px solid transparent'
        val_fmt = '{:,.0f}'.format(val)
        rows += (
            '<tr>'
            '<td style="padding:4px 8px;font-weight:bold;color:' + colors[key] + ';">' + labels[key] + '</td>'
            '<td style="padding:4px 8px;font-family:monospace;font-size:15px;border:' + border + ';border-radius:3px;">' + val_fmt + '</td>'
            '<td style="padding:4px 8px;width:200px;">'
            '<div style="background:#ecf0f1;border-radius:3px;height:12px;overflow:hidden;">'
            '<div style="background:' + colors[key] + ';height:100%;width:60%;"></div>'
            '</div>'
            '</td>'
            '</tr>'
        )
    return '<table style="border-collapse:collapse;">' + rows + '</table>'


def parse_latest(text):
    lines = text.split('\n')
    commodities = []
    bull = []
    bear = []
    warn = []
    in_bull = False
    in_bear = False
    in_warn = False
    for line in lines:
        line = line.strip()
        if '多方' in line and ('商品' in line or '列表' in line or '清單' in line):
            in_bull = True
            in_bear = False
            in_warn = False
            continue
        if '空方' in line and ('商品' in line or '列表' in line or '清單' in line):
            in_bull = False
            in_bear = True
            in_warn = False
            continue
        if '警訊' in line and ('商品' in line or '列表' in line or '清單' in line):
            in_bull = False
            in_bear = False
            in_warn = True
            continue
        if line.startswith('#'):
            in_bull = False
            in_bear = False
            in_warn = False
            continue
        if line.startswith('|') and '|' in line[1:]:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 2 and '---' not in parts[0]:
                commodities.append(parts)
            continue
        if in_bull and line.startswith('-') and len(line) > 2:
            bull.append(line.lstrip('- ').strip())
        if in_bear and line.startswith('-') and len(line) > 2:
            bear.append(line.lstrip('- ').strip())
        if in_warn and line.startswith('-') and len(line) > 2:
            warn.append(line.lstrip('- ').strip())
    return commodities, bull, bear, warn


def chips_row(label, value, positive_good=True):
    v = str(value).replace(',', '').replace('+', '').strip()
    try:
        num = float(v)
        if num > 0:
            color = '#e74c3c' if positive_good else '#27ae60'
            sign = '+'
        elif num < 0:
            color = '#27ae60' if positive_good else '#e74c3c'
            sign = ''
        else:
            color = '#95a5a6'
            sign = ''
        disp = sign + '{:,.0f}'.format(num)
    except Exception:
        color = '#95a5a6'
        disp = value
    return (
        '<tr>'
        '<td style="padding:4px 12px;color:#7f8c8d;">' + label + '</td>'
        '<td style="padding:4px 12px;font-weight:bold;color:' + color + ';">' + disp + '</td>'
        '</tr>'
    )


def build_html(tx_d, tx_w, t5f_d, latest_text):
    tx_close     = parse_value(tx_d, '收盤')
    tx_direction = parse_value(tx_d, '方向')
    tx_alert     = parse_value(tx_d, '警訊')
    tx_date      = parse_value(tx_d, '日期')
    tx_range     = parse_value(tx_d, '區間')

    tx_w_direction = parse_value(tx_w, '方向')
    tx_w_alert     = parse_value(tx_w, '警訊')
    tx_w_range     = parse_value(tx_w, '區間')

    t5f_close     = parse_value(t5f_d, '收盤')
    t5f_direction = parse_value(t5f_d, '方向')
    t5f_alert     = parse_value(t5f_d, '警訊')

    m = re.search(r'(?:明日|下一交易日)[預測三關價：:\s]*(.+?)(?:\n\n|\Z)', tx_d, re.S)
    tomorrow_gates_text = m.group(0) if m else tx_d[-500:]
    gates = parse_gates(tomorrow_gates_text if m else tx_d)

    foreign   = parse_value(tx_d, '外資')
    trust     = parse_value(tx_d, '投信')
    dealer    = parse_value(tx_d, '自營商')
    margin    = parse_value(tx_d, '融資')
    short_pos = parse_value(tx_d, '融券')

    commodities, bull_list, bear_list, warn_list = parse_latest(latest_text)

    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>蘭老師 TX 日K報告</title>'
        '<style>'
        'body{font-family:"Helvetica Neue",Arial,sans-serif;background:#f5f6fa;margin:0;padding:0;}'
        '.wrap{max-width:680px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1);}'
        '.header{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);padding:28px 32px;color:#fff;}'
        '.header h1{margin:0 0 6px;font-size:22px;letter-spacing:1px;}'
        '.header p{margin:0;color:#aaa;font-size:13px;}'
        '.section{padding:20px 32px;border-bottom:1px solid #ecf0f1;}'
        '.section h2{margin:0 0 14px;font-size:16px;color:#2c3e50;border-left:4px solid #e74c3c;padding-left:10px;}'
        '.kv{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:10px;}'
        '.kv-item{background:#f8f9fa;border-radius:6px;padding:10px 16px;min-width:120px;}'
        '.kv-item .label{font-size:11px;color:#7f8c8d;margin-bottom:4px;}'
        '.kv-item .value{font-size:18px;font-weight:bold;color:#2c3e50;}'
        '.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;}'
        '.bull{background:#fdecea;color:#c0392b;}'
        '.bear{background:#e8f8f0;color:#1e8449;}'
        '.warn{background:#fef9e7;color:#b7950b;}'
        'table.commodity{width:100%;border-collapse:collapse;font-size:13px;}'
        'table.commodity th{background:#ecf0f1;padding:6px 8px;text-align:left;color:#7f8c8d;}'
        'table.commodity td{padding:6px 8px;border-bottom:1px solid #f0f0f0;}'
        '.footer{background:#f8f9fa;padding:16px 32px;font-size:12px;color:#95a5a6;text-align:center;}'
        '</style></head><body><div class="wrap">'
    )

    html += (
        '<div class="header">'
        '<h1>📊 蘭老師 TX 日K線分析報告</h1>'
        '<p>' + TODAY + '（星期' + TODAY_WEEKDAY + '）&nbsp;|&nbsp;台指期日報</p>'
        '</div>'
    )

    html += (
        '<div class="section">'
        '<h2>📈 台指期（TX）日線總覽</h2>'
        '<div class="kv">'
        '<div class="kv-item"><div class="label">資料日期</div><div class="value" style="font-size:14px;">' + tx_date + '</div></div>'
        '<div class="kv-item"><div class="label">收盤價</div><div class="value">' + tx_close + '</div></div>'
        '<div class="kv-item"><div class="label">日線方向</div><div class="value" style="font-size:15px;">' + direction_badge(tx_direction) + '</div></div>'
        '<div class="kv-item"><div class="label">警訊</div><div class="value" style="font-size:13px;">' + alert_badge(tx_alert) + '</div></div>'
        '<div class="kv-item"><div class="label">所在區間</div><div class="value" style="font-size:13px;">' + tx_range + '</div></div>'
        '</div>'
        '</div>'
    )

    html += (
        '<div class="section">'
        '<h2>🚦 明日預測三關價</h2>'
        + gate_bar_html(gates, tx_close) +
        '</div>'
    )

    html += (
        '<div class="section">'
        '<h2>📅 週線概況</h2>'
        '<div class="kv">'
        '<div class="kv-item"><div class="label">週線方向</div><div class="value" style="font-size:15px;">' + direction_badge(tx_w_direction) + '</div></div>'
        '<div class="kv-item"><div class="label">週線警訊</div><div class="value" style="font-size:13px;">' + alert_badge(tx_w_alert) + '</div></div>'
        '<div class="kv-item"><div class="label">週線區間</div><div class="value" style="font-size:13px;">' + tx_w_range + '</div></div>'
        '</div>'
        '</div>'
    )

    html += (
        '<div class="section">'
        '<h2>🔷 台灣50期貨（T5F）日線</h2>'
        '<div class="kv">'
        '<div class="kv-item"><div class="label">收盤價</div><div class="value">' + t5f_close + '</div></div>'
        '<div class="kv-item"><div class="label">方向</div><div class="value" style="font-size:15px;">' + direction_badge(t5f_direction) + '</div></div>'
        '<div class="kv-item"><div class="label">警訊</div><div class="value" style="font-size:13px;">' + alert_badge(t5f_alert) + '</div></div>'
        '</div>'
        '</div>'
    )

    if any(v != '-' for v in [foreign, trust, dealer]):
        html += (
            '<div class="section">'
            '<h2>💼 法人籌碼 / 融資券</h2>'
            '<table style="border-collapse:collapse;">'
            + chips_row('外資', foreign, True)
            + chips_row('投信', trust, True)
            + chips_row('自營商', dealer, True)
            + chips_row('融資餘額', margin, False)
            + chips_row('融券餘額', short_pos, False) +
            '</table>'
            '</div>'
        )

    if commodities:
        html += (
            '<div class="section">'
            '<h2>🌐 18商品全掃瞄</h2>'
            '<table class="commodity">'
            '<tr><th>商品</th><th>日線方向</th><th>警訊</th><th>區間</th></tr>'
        )
        for row in commodities[:20]:
            if len(row) >= 2:
                dir_cell = direction_badge(row[1]) if len(row) > 1 else '-'
                alert_cell = alert_badge(row[2]) if len(row) > 2 else '-'
                range_cell = row[3] if len(row) > 3 else '-'
                html += (
                    '<tr>'
                    '<td style="font-weight:bold;">' + row[0] + '</td>'
                    '<td>' + dir_cell + '</td>'
                    '<td>' + alert_cell + '</td>'
                    '<td style="font-size:12px;color:#7f8c8d;">' + range_cell + '</td>'
                    '</tr>'
                )
        html += '</table>'
        if bull_list:
            html += '<p style="margin-top:12px;"><span class="tag bull">多方</span> ' + '、'.join(bull_list[:8]) + '</p>'
        if bear_list:
            html += '<p><span class="tag bear">空方</span> ' + '、'.join(bear_list[:8]) + '</p>'
        if warn_list:
            html += '<p><span class="tag warn">警訊</span> ' + '、'.join(warn_list[:8]) + '</p>'
        html += '</div>'

    html += (
        '<div class="section" style="background:#fffbf0;">'
        '<h2>🎓 老師的叮嚀</h2>'
        '<p style="color:#7f8c8d;font-size:13px;line-height:1.8;margin:0 0 10px;">'
        '依據 <strong>D-01</strong>：「靜態規則是基礎，動態判斷是核心。」<br>'
        '→ 三關價是參考框架，盤中需依實際走勢動態調整判斷。'
        '</p>'
        '<p style="color:#7f8c8d;font-size:13px;line-height:1.8;margin:0 0 10px;">'
        '依據 <strong>D-02</strong>：「位置決定意義，同樣的K線在不同位置解讀不同。」<br>'
        '→ 請先確認目前收盤在三關價哪個區間，再決定操作方向。'
        '</p>'
        '<p style="color:#7f8c8d;font-size:13px;line-height:1.8;margin:0;">'
        '依據 <strong>V-03</strong>：「量是因，價是果。」<br>'
        '→ 開盤前確認夜盤量能，判斷今日突破的可信度。'
        '</p>'
        '</div>'
    )

    html += (
        '<div class="footer">'
        '<p>📌 投資的最終決策權在您自己。本報告基於三關價系統自動產生，僅供參考。</p>'
        '<p>新資訊進來時，判斷需動態調整（貝葉斯思維）。—— 蘭老師 AI 分身</p>'
        '</div>'
        '</div></body></html>'
    )

    return html


def send_email(html_body):
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASS', '')
    mail_to   = os.environ.get('MAIL_TO', '')

    if not smtp_user or not smtp_pass or not mail_to:
        print('ERROR: SMTP_USER / SMTP_PASS / MAIL_TO not set')
        sys.exit(1)

    msg = MIMEMultipart('alternative')
    msg['Subject'] = '📊 蘭老師 TX 日K報告 ' + TODAY + '（' + TODAY_WEEKDAY + '）'
    msg['From']    = smtp_user
    msg['To']      = mail_to
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, mail_to.split(','), msg.as_string())
    print('Mail sent to', mail_to)


def main():
    tx_d   = read_md(TX_DAILY)
    tx_w   = read_md(TX_WEEKLY)
    t5f_d  = read_md(T5F_DAILY)
    latest = read_md(LATEST_MD)

    if not tx_d:
        print('WARNING: TX_daily.md not found, sending empty report')

    html = build_html(tx_d, tx_w, t5f_d, latest)

    # 存 HTML 檔案到 reports/
    report_dir = BASE / 'three_gate' / 'reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / ('kline_report_' + TODAY + '.html')
    report_path.write_text(html, encoding='utf-8')
    print('HTML saved to', report_path)

    send_email(html)


if __name__ == '__main__':
    main()
