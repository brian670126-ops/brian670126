#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 蘭老師 TX 週線分析報告 - 每週六寄送

import os, re, smtplib, sys, csv
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime('%Y-%m-%d')
WEEKDAY_CN = ['一','二','三','四','五','六','日']
TODAY_WEEKDAY = WEEKDAY_CN[datetime.now(TW).weekday()]

BASE = Path(__file__).parent
DATA_DIR     = BASE / 'three_gate'
TX_CSV       = DATA_DIR / 'data' / 'auto' / 'TX_daily.csv'
T5F_CSV      = DATA_DIR / 'data' / 'auto' / 'T5F_daily.csv'
TX_WEEKLY    = DATA_DIR / 'data' / 'auto' / 'TX_weekly.csv'
T5F_WEEKLY   = DATA_DIR / 'data' / 'auto' / 'T5F_weekly.csv'


def read_csv_all(path):
    rows = []
    try:
        with open(path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        pass
    return rows


def safe_float(v, default=0.0):
    try:
        return float(str(v).replace(',', ''))
    except Exception:
        return default


def safe_int(v, default=0):
    try:
        return int(float(str(v).replace(',', '')))
    except Exception:
        return default


def calc_gates(h, l, c):
    """計算三關價七個關卡"""
    m  = (h + l + 2 * c) / 4
    b1 = 2 * m - l
    b2 = 3 * m - 2 * l
    b3 = 4 * m - 3 * l
    s1 = 2 * m - h
    s2 = 3 * m - 2 * h
    s3 = 4 * m - 3 * h
    return dict(m=m, b1=b1, b2=b2, b3=b3, s1=s1, s2=s2, s3=s3)


def get_this_week_ohlcv(daily_rows):
    """從日線 CSV 取本週（Mon-Fri）的資料，合成週 OHLC"""
    if not daily_rows:
        return None
    now = datetime.now(TW)
    # 本週一
    monday = now - timedelta(days=now.weekday())
    monday_str = monday.strftime('%Y-%m-%d')
    week_rows = []
    for r in daily_rows:
        d = r.get('date', '')
        if d >= monday_str:
            week_rows.append(r)
    if not week_rows:
        # fallback: 最後5筆
        week_rows = daily_rows[-5:]
    o  = safe_float(week_rows[0].get('open', 0))
    h  = max(safe_float(r.get('high',  0)) for r in week_rows)
    l  = min(safe_float(r.get('low',   999999)) for r in week_rows)
    c  = safe_float(week_rows[-1].get('close', 0))
    v  = sum(safe_int(r.get('volume', 0)) for r in week_rows)
    oi = safe_int(week_rows[-1].get('oi', 0))
    start_date = week_rows[0].get('date', '')
    end_date   = week_rows[-1].get('date', '')
    return dict(open=o, high=h, low=l, close=c, volume=v, oi=oi,
                start=start_date, end=end_date, days=len(week_rows))


def get_prev_week_ohlcv(weekly_rows):
    """從週線 CSV 取前兩週"""
    if not weekly_rows:
        return None, None
    last  = weekly_rows[-1]  if len(weekly_rows) >= 1 else None
    prev2 = weekly_rows[-2]  if len(weekly_rows) >= 2 else None
    return last, prev2


def direction_badge(bull):
    if bull:
        return '<span style="background:#e74c3c;color:#fff;padding:2px 10px;border-radius:4px;font-weight:bold;">🟢 多方</span>'
    return '<span style="background:#27ae60;color:#fff;padding:2px 10px;border-radius:4px;font-weight:bold;">🔴 空方</span>'


def gate_table_weekly(gates, close, label='下週三關價'):
    """週線三關價表格"""
    rows = [
        ('B3', '壓3', '#c0392b', gates.get('b3')),
        ('B2', '趨勢確認', '#e74c3c', gates.get('b2')),
        ('B1', '壓1',  '#e67e22', gates.get('b1')),
        ('M',  '中樞M', '#f39c12', gates.get('m')),
        ('S1', '撐1',  '#27ae60', gates.get('s1')),
        ('S2', '超賣警示', '#1abc9c', gates.get('s2')),
        ('S3', '撐3',  '#16a085', gates.get('s3')),
    ]
    html = '<table style="border-collapse:collapse;width:100%;margin-bottom:16px;">'
    html += ('<tr style="background:#f8f9fa;">'
             '<th style="padding:8px 12px;text-align:left;font-size:13px;color:#7f8c8d;">關卡</th>'
             '<th style="padding:8px 12px;text-align:left;font-size:13px;color:#7f8c8d;">定義</th>'
             '<th style="padding:8px 12px;text-align:left;font-size:13px;color:#7f8c8d;">數值</th>'
             '<th style="padding:8px 12px;text-align:left;font-size:13px;color:#7f8c8d;">距本週收</th>'
             '</tr>')
    for key, lbl, color, val in rows:
        if not val:
            continue
        diff = round(val - close, 0) if close else 0
        diff_str = ('+' if diff >= 0 else '') + '{:,.0f}'.format(diff)
        near = abs(diff) < 300 if close else False
        bg = '#fffde7' if near else '#fff'
        html += (
            '<tr style="background:' + bg + ';border-bottom:1px solid #f0f0f0;">'
            '<td style="padding:8px 12px;font-weight:bold;color:' + color + ';font-size:16px;">' + key + '</td>'
            '<td style="padding:8px 12px;color:#555;font-size:13px;">' + lbl + '</td>'
            '<td style="padding:8px 12px;font-family:monospace;font-size:16px;font-weight:bold;">'
            + '{:,.0f}'.format(val) + '</td>'
            '<td style="padding:8px 12px;color:' + ('#e74c3c' if diff > 0 else '#27ae60')
            + ';font-size:13px;font-weight:bold;">' + diff_str + '</td>'
            '</tr>'
        )
    html += '</table>'
    return html


def week_summary_table(this_week, prev_week_row):
    """本週 vs 上週對比"""
    rows_data = []
    if prev_week_row:
        pc = safe_float(prev_week_row.get('close', 0))
        ph = safe_float(prev_week_row.get('high',  0))
        pl = safe_float(prev_week_row.get('low',   0))
        po = safe_float(prev_week_row.get('open',  0))
        pv = safe_int(prev_week_row.get('volume', 0))
        poi = safe_int(prev_week_row.get('oi', 0))
        pd = prev_week_row.get('date', '上週')
        rows_data.append(('上週', pd, po, ph, pl, pc, pv, poi))
    if this_week:
        rows_data.append(('本週', this_week['start'] + '~' + this_week['end'],
                          this_week['open'], this_week['high'], this_week['low'],
                          this_week['close'], this_week['volume'], this_week['oi']))

    html = '<table style="border-collapse:collapse;width:100%;font-size:14px;">'
    html += ('<tr style="background:#1a1a2e;color:#fff;">'
             '<th style="padding:8px 12px;text-align:left;">週別</th>'
             '<th style="padding:8px 12px;">日期</th>'
             '<th style="padding:8px 12px;">開</th>'
             '<th style="padding:8px 12px;color:#ff8080;">高</th>'
             '<th style="padding:8px 12px;color:#80ff80;">低</th>'
             '<th style="padding:8px 12px;">收</th>'
             '<th style="padding:8px 12px;">週成交量</th>'
             '<th style="padding:8px 12px;">週末OI</th>'
             '</tr>')
    prev_close = 0
    for label, date, o, h, l, c, v, oi in rows_data:
        chg = c - prev_close if prev_close else 0
        chg_pct = chg / prev_close * 100 if prev_close else 0
        chg_str = ('+' if chg >= 0 else '') + '{:.0f} ({:.1f}%)'.format(chg, chg_pct) if prev_close else '-'
        chg_color = '#e74c3c' if chg >= 0 else '#27ae60'
        bg = '#f0fff0' if label == '本週' else '#fff'
        html += (
            '<tr style="background:' + bg + ';border-bottom:1px solid #e0e0e0;">'
            '<td style="padding:8px 12px;font-weight:bold;">' + label + '</td>'
            '<td style="padding:8px 12px;color:#7f8c8d;font-size:12px;">' + date + '</td>'
            '<td style="padding:8px 12px;font-family:monospace;">' + '{:,.0f}'.format(o) + '</td>'
            '<td style="padding:8px 12px;font-family:monospace;color:#e74c3c;">' + '{:,.0f}'.format(h) + '</td>'
            '<td style="padding:8px 12px;font-family:monospace;color:#27ae60;">' + '{:,.0f}'.format(l) + '</td>'
            '<td style="padding:8px 12px;font-family:monospace;font-weight:bold;">' + '{:,.0f}'.format(c) + '</td>'
            '<td style="padding:8px 12px;color:#7f8c8d;">' + '{:,}'.format(v) + '</td>'
            '<td style="padding:8px 12px;color:#7f8c8d;">' + ('{:,}'.format(oi) if oi else '-') + '</td>'
            '</tr>'
        )
        prev_close = c
    html += '</table>'
    return html


def environment_judgment(weekly_rows):
    """判斷目前市場環境（多頭/震盪/空頭）"""
    if len(weekly_rows) < 8:
        return '震盪', '樣本不足（<8週），暫定震盪環境'
    recent = weekly_rows[-8:]
    m_above = 0
    for i in range(1, len(recent)):
        row = recent[i]
        prev = recent[i-1]
        try:
            ph = safe_float(prev.get('high',  0))
            pl = safe_float(prev.get('low',   0))
            pc = safe_float(prev.get('close', 0))
            m  = (ph + pl + 2 * pc) / 4
            c  = safe_float(row.get('close',  0))
            if c >= m:
                m_above += 1
        except Exception:
            pass
    total = len(recent) - 1
    ratio = m_above / total if total > 0 else 0.5
    if ratio >= 0.65:
        env = '多頭'
        desc = '近8週 M以上收盤佔 {:.0f}%（≥65%），判定多頭環境'.format(ratio * 100)
    elif ratio < 0.50:
        env = '空頭'
        desc = '近8週 M以上收盤佔 {:.0f}%（<50%），判定空頭環境'.format(ratio * 100)
    else:
        env = '震盪'
        desc = '近8週 M以上收盤佔 {:.0f}%（50-65%），判定震盪環境'.format(ratio * 100)
    return env, desc


def weekly_signal_analysis(this_week, next_gates, prev_week_row, env):
    """分析本週訊號與下週操作方向"""
    if not this_week or not next_gates:
        return '<p>資料不足，無法分析</p>'

    c = this_week['close']
    b2 = next_gates.get('b2', 0)
    s2 = next_gates.get('s2', 0)
    m  = next_gates.get('m',  0)
    b1 = next_gates.get('b1', 0)
    s1 = next_gates.get('s1', 0)

    # 本週收盤 vs 本週計算出的三關價（用上週OHLC算）
    if prev_week_row:
        ph = safe_float(prev_week_row.get('high',  0))
        pl = safe_float(prev_week_row.get('low',   0))
        pc = safe_float(prev_week_row.get('close', 0))
        this_gates = calc_gates(ph, pl, pc)
        this_b2 = this_gates.get('b2', 0)
        this_m  = this_gates.get('m',  0)
        this_s2 = this_gates.get('s2', 0)
    else:
        this_b2 = this_s2 = this_m = 0

    signals = []

    # B2 突破判斷
    if this_b2 > 0 and c >= this_b2:
        pct_above = (c - this_b2) / this_b2 * 100
        if pct_above >= 1.5 and env == '多頭':
            signals.append(('🔴 強多訊號', 'B2突破幅度 {:.1f}%（≥1.5%），多頭年：第4週續漲81%，假突破僅26%，平均延續14週。積極做多。'.format(pct_above), '#e74c3c'))
        elif pct_above >= 0.5 and env == '多頭':
            signals.append(('🟠 偏多訊號', 'B2突破幅度 {:.1f}%（0.5-1.5%），多頭年第4週續漲54-73%，假突破33-39%。可操作但需注意假突破。'.format(pct_above), '#e67e22'))
        elif env == '空頭':
            signals.append(('⚠️ 空頭陷阱', 'B2雖突破，但空頭環境假突破率高達50-86%，不宜追多。', '#f39c12'))
        else:
            signals.append(('🟡 B2突破（震盪）', 'B2突破 {:.1f}%，震盪環境假突破率33-65%，輕倉謹慎追。'.format(pct_above), '#f1c40f'))

    # S2 守回判斷
    elif this_s2 > 0:
        h_week = this_week['high']
        l_week = this_week['low']
        if l_week <= this_s2 and c > this_s2:
            pct_below = (this_s2 - l_week) / this_s2 * 100
            if env == '多頭':
                if 0.5 <= pct_below <= 1.0:
                    signals.append(('⭐ 最佳S2守回', 'S2日內觸碰後收守，跌破幅度{:.1f}%（最佳0.5-1.0%區間），多頭年第4週反彈75%。積極做多。'.format(pct_below), '#e74c3c'))
                elif pct_below < 0.5:
                    signals.append(('🟢 S2守回', 'S2守回，跌破幅度{:.1f}%，多頭年第1週反彈65%。可做多，等週一確認。'.format(pct_below), '#27ae60'))
                else:
                    signals.append(('🟡 S2守回（深跌）', 'S2守回，跌破幅度{:.1f}%（>1%），第4週反彈率降，短反彈後注意是否再探底。'.format(pct_below), '#f1c40f'))
            elif env == '空頭':
                signals.append(('⚠️ S2守回（空頭失效）', 'S2守回在空頭環境反彈率僅42%，不建議做多。', '#e67e22'))
            else:
                signals.append(('🟢 S2守回（震盪）', 'S2守回，震盪年反彈率71%，可操作。', '#27ae60'))
        elif c <= this_s2:
            signals.append(('🔴 S2收死', '本週收盤跌破S2，多頭年反彈機會降（46%），空頭年63%續跌。等下週確認。', '#c0392b'))

    # 收盤在 M~B2
    elif this_m > 0 and this_m <= c < this_b2:
        ratio = (c - this_m) / (this_b2 - this_m) * 100 if this_b2 > this_m else 50
        if env == '多頭':
            signals.append(('🟢 多方格局維持', 'M~B2區間偏多，收盤在M以上第{:.0f}%位置。多頭環境M以下僅1.7週平均，結構健康。'.format(ratio), '#27ae60'))
        else:
            signals.append(('⚪ 中性整理', 'M~B2區間，{}環境下需觀察突破方向。'.format(env), '#7f8c8d'))

    if not signals:
        signals.append(('📊 觀察中', '本週收盤在正常區間，無強烈訊號。依環境（{}）謹慎操作。'.format(env), '#7f8c8d'))

    html = ''
    for title, desc, color in signals:
        html += (
            '<div style="border-left:4px solid ' + color + ';padding:12px 16px;margin-bottom:14px;'
            'background:#f9f9f9;border-radius:0 8px 8px 0;">'
            '<div style="font-size:15px;font-weight:bold;color:' + color + ';margin-bottom:6px;">'
            + title + '</div>'
            '<div style="font-size:13px;color:#555;line-height:1.6;">' + desc + '</div>'
            '</div>'
        )
    return html


def next_week_outlook(next_gates, c, env):
    """下週操作展望"""
    b2 = next_gates.get('b2', 0)
    b1 = next_gates.get('b1', 0)
    m  = next_gates.get('m',  0)
    s1 = next_gates.get('s1', 0)
    s2 = next_gates.get('s2', 0)

    lines = []
    if env == '多頭':
        lines.append(('多頭環境核心策略',
            '主戰場 <b>M~B1</b>（{:,.0f} ~ {:,.0f}）做多為主，拉回找買點'.format(m, b1),
            '#27ae60'))
        lines.append(('關鍵觀察', 'B2（{:,.0f}）突破且≥1.5% → 趨勢確認，可加碼多單'.format(b2), '#e74c3c'))
        lines.append(('停損守則', 'S2（{:,.0f}）跌破 → 清空多單，不做空'.format(s2), '#e67e22'))
    elif env == '空頭':
        lines.append(('空頭環境守則',
            '不逆勢做多，M以下黏性高（62%次週續跌），不輕易搶反彈', '#e74c3c'))
        lines.append(('觀察反轉條件',
            '需連續 4-8 週 M以上收盤佔比重回 ≥65% 才確認環境轉多', '#f39c12'))
    else:
        lines.append(('震盪環境策略',
            'M~B1 區間操作，不追高，不搶低，S2守回（71%有效）可試多', '#f39c12'))
        lines.append(('關鍵觀察', 'B2突破（假突破率33-65%）需等確認；S2守回勝率優於B2突破', '#7f8c8d'))

    html = ''
    for title, desc, color in lines:
        html += (
            '<div style="background:#f8f9fa;border-radius:8px;padding:12px 16px;'
            'margin-bottom:10px;border-top:3px solid ' + color + ';">'
            '<div style="font-size:13px;font-weight:bold;color:' + color + ';margin-bottom:4px;">'
            + title + '</div>'
            '<div style="font-size:13px;color:#333;">' + desc + '</div>'
            '</div>'
        )
    return html


def weekly_history_table(weekly_rows, n=8):
    """近N週週線歷史"""
    rows = weekly_rows[-n:] if len(weekly_rows) >= n else weekly_rows
    if not rows:
        return '<p style="color:#95a5a6;">無歷史資料</p>'
    html = '<table style="border-collapse:collapse;width:100%;font-size:13px;">'
    html += ('<tr style="background:#f8f9fa;">'
             '<th style="padding:6px 10px;text-align:left;">週別</th>'
             '<th style="padding:6px 10px;">開</th><th style="padding:6px 10px;color:#e74c3c;">高</th>'
             '<th style="padding:6px 10px;color:#27ae60;">低</th><th style="padding:6px 10px;">收</th>'
             '<th style="padding:6px 10px;">週漲跌</th>'
             '<th style="padding:6px 10px;">成交量</th>'
             '<th style="padding:6px 10px;">OI</th>'
             '<th style="padding:6px 10px;">M以上</th></tr>')
    prev_close = 0
    for r in rows:
        o  = safe_float(r.get('open',  0))
        h  = safe_float(r.get('high',  0))
        l  = safe_float(r.get('low',   0))
        c  = safe_float(r.get('close', 0))
        v  = safe_int(r.get('volume',  0))
        oi = safe_int(r.get('oi',      0))
        date = r.get('date', '')
        chg = c - prev_close if prev_close else 0
        chg_pct = chg / prev_close * 100 if prev_close else 0
        chg_str = ('+' if chg >= 0 else '') + '{:.0f}({:.1f}%)'.format(chg, chg_pct) if prev_close else '-'
        chg_color = '#e74c3c' if chg >= 0 else '#27ae60'
        candle = '🟥' if c < o else '🟩'

        # 計算本週三關價（用前週OHLC），判斷收盤是否在M以上
        m_above = '-'
        if prev_close > 0:
            # 用上週資料算M（簡化：只有close不夠，需上週OHLC，這裡用前週收盤估算）
            pass
        html += (
            '<tr style="border-bottom:1px solid #f0f0f0;">'
            '<td style="padding:6px 10px;color:#7f8c8d;">' + date + ' ' + candle + '</td>'
            '<td style="padding:6px 10px;font-family:monospace;">' + '{:,.0f}'.format(o) + '</td>'
            '<td style="padding:6px 10px;font-family:monospace;color:#e74c3c;">' + '{:,.0f}'.format(h) + '</td>'
            '<td style="padding:6px 10px;font-family:monospace;color:#27ae60;">' + '{:,.0f}'.format(l) + '</td>'
            '<td style="padding:6px 10px;font-family:monospace;font-weight:bold;">' + '{:,.0f}'.format(c) + '</td>'
            '<td style="padding:6px 10px;color:' + chg_color + ';">' + chg_str + '</td>'
            '<td style="padding:6px 10px;color:#7f8c8d;">' + '{:,}'.format(v) + '</td>'
            '<td style="padding:6px 10px;color:#95a5a6;font-size:12px;">' + ('{:,}'.format(oi) if oi else '-') + '</td>'
            '<td style="padding:6px 10px;">-</td>'
            '</tr>'
        )
        prev_close = c
    html += '</table>'
    return html


def build_weekly_html(tx_daily, t5f_daily, tx_weekly, t5f_weekly):
    # TX
    tx_this_week = get_this_week_ohlcv(tx_daily)
    tx_prev_w, tx_prev2_w = get_prev_week_ohlcv(tx_weekly)
    tx_env, tx_env_desc = environment_judgment(tx_weekly)

    # 下週三關價 = 用本週 OHLC 計算
    if tx_this_week:
        tx_next_gates = calc_gates(
            tx_this_week['high'], tx_this_week['low'], tx_this_week['close'])
    else:
        tx_next_gates = {}

    # T5F
    t5f_this_week = get_this_week_ohlcv(t5f_daily)
    t5f_prev_w, _ = get_prev_week_ohlcv(t5f_weekly)
    t5f_env, t5f_env_desc = environment_judgment(t5f_weekly)
    if t5f_this_week:
        t5f_next_gates = calc_gates(
            t5f_this_week['high'], t5f_this_week['low'], t5f_this_week['close'])
    else:
        t5f_next_gates = {}

    env_color = {'多頭': '#e74c3c', '震盪': '#f39c12', '空頭': '#27ae60'}
    tx_env_c  = env_color.get(tx_env,  '#7f8c8d')
    t5f_env_c = env_color.get(t5f_env, '#7f8c8d')

    # 算本週 ISO 週號
    now = datetime.now(TW)
    week_num = now.isocalendar()[1]

    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>蘭老師 TX 週報</title>'
        '<style>'
        'body{font-family:"Helvetica Neue",Arial,"Microsoft JhengHei",sans-serif;'
        'background:#f0f2f5;margin:0;padding:16px 0;}'
        '.wrap{max-width:800px;margin:0 auto;background:#fff;border-radius:12px;'
        'overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.12);}'
        '.header{background:linear-gradient(135deg,#0f3460 0%,#16213e 50%,#1a1a2e 100%);'
        'padding:36px 40px;color:#fff;}'
        '.header h1{margin:0 0 8px;font-size:26px;letter-spacing:2px;}'
        '.header p{margin:0;color:#aaa;font-size:14px;}'
        '.section{padding:24px 40px;border-bottom:2px solid #f0f0f0;}'
        '.section h2{margin:0 0 18px;font-size:18px;color:#1a1a2e;'
        'border-left:5px solid #0f3460;padding-left:14px;font-weight:bold;}'
        '.section h3{margin:14px 0 10px;font-size:14px;color:#2c3e50;}'
        '.env-badge{display:inline-block;padding:6px 18px;border-radius:20px;'
        'font-weight:bold;font-size:15px;color:#fff;margin-bottom:12px;}'
        '.footer{background:#1a1a2e;padding:22px 40px;font-size:12px;'
        'color:#7f8c8d;text-align:center;}'
        '</style></head><body><div class="wrap">'
    )

    html += (
        '<div class="header">'
        '<h1>📋 蘭老師 TX 週報</h1>'
        '<p>第 ' + str(week_num) + ' 週 · ' + TODAY + '（週六）'
        ' · 本週回顧 + 下週三關價預測</p>'
        '</div>'
    )

    # ── 一、環境判斷 ──
    html += '<div class="section"><h2>🌍 一、市場環境判斷</h2>'
    html += (
        '<table style="width:100%;border-collapse:collapse;">'
        '<tr>'
        '<td style="padding:12px;vertical-align:top;">'
        '<div style="font-size:13px;color:#7f8c8d;margin-bottom:6px;">TX 台指期</div>'
        '<div class="env-badge" style="background:' + tx_env_c + ';">' + tx_env + '環境</div>'
        '<div style="font-size:12px;color:#555;margin-top:6px;">' + tx_env_desc + '</div>'
        '</td>'
        '<td style="padding:12px;vertical-align:top;border-left:1px solid #eee;">'
        '<div style="font-size:13px;color:#7f8c8d;margin-bottom:6px;">T5F 台灣50</div>'
        '<div class="env-badge" style="background:' + t5f_env_c + ';">' + t5f_env + '環境</div>'
        '<div style="font-size:12px;color:#555;margin-top:6px;">' + t5f_env_desc + '</div>'
        '</td>'
        '</tr></table>'
        '<p style="font-size:12px;color:#95a5a6;margin:8px 0 0;">'
        '環境判斷依據：近8週M以上收盤週數佔比（≥65%多頭 / <50%空頭 / 其他震盪）</p>'
    )
    html += '</div>'

    # ── 二、TX 本週回顧 ──
    html += '<div class="section"><h2>📈 二、台指期（TX）本週回顧</h2>'
    if tx_this_week:
        html += week_summary_table(tx_this_week, tx_prev_w)
    html += '</div>'

    # ── 三、TX 本週訊號分析 ──
    html += '<div class="section"><h2>📡 三、TX 本週訊號分析</h2>'
    if tx_this_week:
        html += weekly_signal_analysis(tx_this_week, tx_next_gates, tx_prev_w, tx_env)
    html += '</div>'

    # ── 四、TX 下週三關價 ──
    html += '<div class="section"><h2>🚦 四、TX 下週三關價</h2>'
    if tx_this_week and tx_next_gates:
        html += '<p style="font-size:13px;color:#555;margin-bottom:12px;">依本週 OHLC 計算：開 {:,.0f} 高 {:,.0f} 低 {:,.0f} 收 {:,.0f}</p>'.format(
            tx_this_week['open'], tx_this_week['high'],
            tx_this_week['low'],  tx_this_week['close'])
        html += gate_table_weekly(tx_next_gates, tx_this_week['close'])
        html += '<h3>📌 下週操作展望</h3>'
        html += next_week_outlook(tx_next_gates, tx_this_week['close'], tx_env)
    html += '</div>'

    # ── 五、T5F 本週回顧 + 下週三關價 ──
    html += '<div class="section"><h2>🔷 五、台灣50（T5F）本週回顧 + 下週三關價</h2>'
    if t5f_this_week:
        html += week_summary_table(t5f_this_week, t5f_prev_w)
        html += '<h3 style="margin-top:18px;">T5F 下週三關價（依本週OHLC計算）</h3>'
        html += '<p style="font-size:12px;color:#7f8c8d;">開 {:.2f} 高 {:.2f} 低 {:.2f} 收 {:.2f}</p>'.format(
            t5f_this_week['open'], t5f_this_week['high'],
            t5f_this_week['low'],  t5f_this_week['close'])
        if t5f_next_gates:
            html += gate_table_weekly(t5f_next_gates, t5f_this_week['close'])
    html += '</div>'

    # ── 六、近8週歷史 ──
    html += '<div class="section"><h2>📅 六、TX 近8週週線歷史</h2>'
    html += weekly_history_table(tx_weekly, n=8)
    html += '</div>'

    # ── 七、三關價統計框架提醒 ──
    html += (
        '<div class="section"><h2>📚 七、本週框架對照</h2>'
        '<table style="border-collapse:collapse;width:100%;font-size:13px;">'
        '<tr style="background:#f8f9fa;">'
        '<th style="padding:8px 12px;text-align:left;">環境</th>'
        '<th style="padding:8px 12px;">B2突破（≥1.5%）</th>'
        '<th style="padding:8px 12px;">S2守回</th>'
        '<th style="padding:8px 12px;">M以上週數</th>'
        '</tr>'
        '<tr style="background:#e8f5e9;">'
        '<td style="padding:8px 12px;font-weight:bold;color:#27ae60;">多頭年</td>'
        '<td style="padding:8px 12px;">第4週漲81%，假突破僅26%</td>'
        '<td style="padding:8px 12px;">第1週反彈65-77%</td>'
        '<td style="padding:8px 12px;">≥65%</td></tr>'
        '<tr style="background:#fffbf0;">'
        '<td style="padding:8px 12px;font-weight:bold;color:#f39c12;">震盪年</td>'
        '<td style="padding:8px 12px;">假突破33-65%，謹慎</td>'
        '<td style="padding:8px 12px;">第1週反彈71%</td>'
        '<td style="padding:8px 12px;">59%</td></tr>'
        '<tr style="background:#fff0f0;">'
        '<td style="padding:8px 12px;font-weight:bold;color:#e74c3c;">空頭年</td>'
        '<td style="padding:8px 12px;">假突破45-86%，不可信</td>'
        '<td style="padding:8px 12px;">第1週僅42%（失效）</td>'
        '<td style="padding:8px 12px;"><50%</td></tr>'
        '</table>'
        '<p style="font-size:12px;color:#95a5a6;margin-top:10px;">'
        '資料來源：台指期週線 2,038週（1987-2026）統計</p>'
        '</div>'
    )

    html += (
        '<div class="footer">'
        '<p>📌 <strong style="color:#fff;">投資決策請自行判斷，本報告僅供技術分析參考。</strong></p>'
        '<p>三關價週報 · 自動產生 · ' + TODAY + ' 週六</p>'
        '</div>'
        '</div></body></html>'
    )
    return html


def send_email(html_body):
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASS', '')
    mail_to   = os.environ.get('MAIL_TO', '')
    if not smtp_user or not smtp_pass or not mail_to:
        print('ERROR: SMTP env not set')
        sys.exit(1)
    msg = MIMEMultipart('alternative')
    now = datetime.now(TW)
    week_num = now.isocalendar()[1]
    msg['Subject'] = '📋 蘭老師週報 第{}週 {} 下週三關價出爐'.format(week_num, TODAY)
    msg['From']    = smtp_user
    msg['To']      = mail_to
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, mail_to.split(','), msg.as_string())
    print('Weekly report sent to', mail_to)


def main():
    tx_daily   = read_csv_all(TX_CSV)
    t5f_daily  = read_csv_all(T5F_CSV)
    tx_weekly  = read_csv_all(TX_WEEKLY)
    t5f_weekly = read_csv_all(T5F_WEEKLY)

    html = build_weekly_html(tx_daily, t5f_daily, tx_weekly, t5f_weekly)

    report_dir = BASE / 'three_gate' / 'reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / ('weekly_report_' + TODAY + '.html')
    out.write_text(html, encoding='utf-8')
    print('Weekly HTML saved to', out)

    send_email(html)


if __name__ == '__main__':
    main()
