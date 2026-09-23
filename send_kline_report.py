#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 蘭老師 TX 日K線分析報告 v3 - 深度分析版（修正中文表格解析）

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
STRATEGY_DIR = BASE / 'three_gate' / 'strategy'
DATA_DIR     = BASE / 'three_gate'

TX_DAILY_MD  = STRATEGY_DIR / 'TX_daily.md'
TX_WEEKLY_MD = STRATEGY_DIR / 'TX_weekly.md'
T5F_DAILY_MD = STRATEGY_DIR / 'T5F_daily.md'
LATEST_MD    = STRATEGY_DIR / 'latest.md'
TX_CSV       = DATA_DIR / 'TX_daily.csv'
T5F_CSV      = DATA_DIR / 'T5F_daily.csv'


def read_md(path):
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def read_csv_last_n(path, n=6):
    rows = []
    try:
        with open(path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        pass
    return rows[-n:] if len(rows) >= n else rows


def fv(text, *patterns):
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            v = m.group(1).replace(',', '').strip()
            try:
                return float(v)
            except Exception:
                return v
    return None


def fstr(text, *patterns):
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return '-'


def parse_tx(text):
    # 收盤：中文表格格式 | 收盤 | 48497.00 |
    close = fv(text,
        r'\|\s*收盤\s*\|\s*([\d,\.]+)',
        r'closed at ([\d,\.]+)',
        r'收盤[|：:]\s*([\d,\.]+)')
    # 明日預測三關價：在 > 引用區塊裡
    quote_lines = '\n'.join(l for l in text.split('\n') if l.strip().startswith('>'))
    b3_n = fv(quote_lines, r'>?\s*\|\s*B3\s*\|\s*([\d,\.]+)')
    b2_n = fv(quote_lines, r'>?\s*\|\s*B2\s*\|\s*([\d,\.]+)')
    b1_n = fv(quote_lines, r'>?\s*\|\s*B1\s*\|\s*([\d,\.]+)')
    m_n  = fv(quote_lines, r'>?\s*\|\s*M\s*\|\s*([\d,\.]+)')
    s1_n = fv(quote_lines, r'>?\s*\|\s*S1\s*\|\s*([\d,\.]+)')
    s2_n = fv(quote_lines, r'>?\s*\|\s*S2\s*\|\s*([\d,\.]+)')
    s3_n = fv(quote_lines, r'>?\s*\|\s*S3\s*\|\s*([\d,\.]+)')
    # 當前三關價：非引用行
    noq = '\n'.join(l for l in text.split('\n') if not l.strip().startswith('>'))
    b3_c = fv(noq, r'\|\s*B3\s*\|\s*([\d,\.]+)')
    b2_c = fv(noq, r'\|\s*B2\s*\|\s*([\d,\.]+)')
    b1_c = fv(noq, r'\|\s*B1\s*\|\s*([\d,\.]+)')
    m_c  = fv(noq, r'\|\s*M\s*\|\s*([\d,\.]+)')
    s1_c = fv(noq, r'\|\s*S1\s*\|\s*([\d,\.]+)')
    s2_c = fv(noq, r'\|\s*S2\s*\|\s*([\d,\.]+)')
    s3_c = fv(noq, r'\|\s*S3\s*\|\s*([\d,\.]+)')
    date    = fstr(text, r'(\d{4}-\d{2}-\d{2})')
    bull    = '多方' in text or 'bullish' in text.lower()
    bear    = '空方' in text or 'bearish' in text.lower()
    strong  = '強警訊' in text or 'strong warning' in text.lower()
    mid_w   = '中警訊' in text or 'moderate warning' in text.lower()
    weak_w  = '弱警訊' in text or 'weak warning' in text.lower()
    chg     = fv(text, r'\|\s*日漲跌\s*\|\s*([\-\d,\.]+)', r'漲跌[|：:\s]+([\-\d,\.]+)')
    amp     = fv(text, r'\|\s*振幅\s*\|\s*([\d,\.]+)', r'振幅[|：:\s]+([\d,\.]+)')
    return dict(
        close=close,
        b3=b3_n or b3_c, b2=b2_n or b2_c, b1=b1_n or b1_c,
        m=m_n or m_c, s1=s1_n or s1_c, s2=s2_n or s2_c, s3=s3_n or s3_c,
        b3_cur=b3_c, b2_cur=b2_c, b1_cur=b1_c, m_cur=m_c,
        s1_cur=s1_c, s2_cur=s2_c, s3_cur=s3_c,
        b3_next=b3_n, b2_next=b2_n, b1_next=b1_n, m_next=m_n,
        s1_next=s1_n, s2_next=s2_n, s3_next=s3_n,
        date=date, bull=bull, bear=bear, strong=strong, mid_w=mid_w, weak_w=weak_w,
        chg=chg, amp=amp)


def direction_badge(bull):
    if bull:
        return '<span style="background:#e74c3c;color:#fff;padding:2px 10px;border-radius:4px;font-weight:bold;">🟢 多方</span>'
    return '<span style="background:#27ae60;color:#fff;padding:2px 10px;border-radius:4px;font-weight:bold;">🔴 空方</span>'


def alert_badge(strong, mid_w, weak_w):
    if strong:
        return '<span style="color:#e74c3c;font-weight:bold;">🔴🔴🔴 強警訊</span>'
    if mid_w:
        return '<span style="color:#f39c12;font-weight:bold;">🟠🟠 中警訊</span>'
    if weak_w:
        return '<span style="color:#f1c40f;font-weight:bold;">🟡 弱警訊</span>'
    return '<span style="color:#27ae60;">✅ 無警訊</span>'


def pct(a, b):
    if a and b and b != 0:
        return round((a - b) / b * 100, 2)
    return 0.0


def gate_table(d, label='明日預測三關價'):
    close = d.get('close') or 0
    rows = [
        ('B3', '壓3', '#c0392b', d.get('b3')),
        ('B2', '壓2', '#e74c3c', d.get('b2')),
        ('B1', '壓1', '#e67e22', d.get('b1')),
        ('M',  '中樞M', '#f39c12', d.get('m')),
        ('S1', '撐1', '#27ae60', d.get('s1')),
        ('S2', '撐2', '#1abc9c', d.get('s2')),
        ('S3', '撐3', '#16a085', d.get('s3')),
    ]
    html = '<table style="border-collapse:collapse;width:100%;">'
    html += ('<tr style="background:#f8f9fa;">'
             '<th style="padding:6px 10px;text-align:left;color:#7f8c8d;font-size:12px;">關卡</th>'
             '<th style="padding:6px 10px;text-align:left;color:#7f8c8d;font-size:12px;">數值</th>'
             '<th style="padding:6px 10px;text-align:left;color:#7f8c8d;font-size:12px;">距收盤</th>'
             '<th style="padding:6px 10px;font-size:12px;color:#7f8c8d;">位置</th></tr>')
    for key, lbl, color, val in rows:
        if not val:
            continue
        diff = round(val - close, 2) if close else 0
        diff_str = ('+' if diff >= 0 else '') + '{:,.0f}'.format(diff)
        near = abs(diff) < 200 if close else False
        bg = '#fffde7' if near else '#fff'
        bar_pct = min(max(int((val - (close * 0.97)) / (close * 0.06) * 100), 0), 100) if close else 60
        html += (
            '<tr style="background:' + bg + ';border-bottom:1px solid #f0f0f0;">'
            '<td style="padding:6px 10px;font-weight:bold;color:' + color + ';">' + lbl + '</td>'
            '<td style="padding:6px 10px;font-family:monospace;font-size:15px;font-weight:bold;">'
            + '{:,.2f}'.format(val) + '</td>'
            '<td style="padding:6px 10px;color:' + ('#e74c3c' if diff > 0 else '#27ae60')
            + ';font-size:13px;">' + diff_str + '</td>'
            '<td style="padding:6px 10px;width:120px;">'
            '<div style="background:#ecf0f1;border-radius:3px;height:10px;">'
            '<div style="background:' + color + ';height:100%;width:' + str(bar_pct)
            + '%;border-radius:3px;"></div></div></td></tr>'
        )
    html += '</table>'
    return html


def five_day_table(rows):
    if not rows:
        return '<p style="color:#95a5a6;">歷史資料暫無</p>'
    html = '<table style="border-collapse:collapse;width:100%;font-size:13px;">'
    html += ('<tr style="background:#f8f9fa;">'
             '<th style="padding:5px 8px;text-align:left;">日期</th>'
             '<th style="padding:5px 8px;">開</th><th style="padding:5px 8px;">高</th>'
             '<th style="padding:5px 8px;">低</th><th style="padding:5px 8px;">收</th>'
             '<th style="padding:5px 8px;">漲跌</th><th style="padding:5px 8px;">量</th></tr>')
    prev_close = None
    for r in rows:
        try:
            o = float(r.get('open', 0))
            h = float(r.get('high', 0))
            l = float(r.get('low', 0))
            c = float(r.get('close', 0))
            v = int(float(r.get('volume', 0)))
            date = r.get('date', '')
            if prev_close and prev_close > 0:
                chg = c - prev_close
                chg_pct = chg / prev_close * 100
                chg_str = ('+' if chg >= 0 else '') + '{:.0f}'.format(chg) + ' ({:.1f}%)'.format(chg_pct)
                chg_color = '#e74c3c' if chg >= 0 else '#27ae60'
            else:
                chg_str = '-'
                chg_color = '#95a5a6'
            candle = '🟥' if c < o else '🟩'
            html += (
                '<tr style="border-bottom:1px solid #f0f0f0;">'
                '<td style="padding:5px 8px;color:#7f8c8d;">' + date + ' ' + candle + '</td>'
                '<td style="padding:5px 8px;font-family:monospace;">' + '{:,.0f}'.format(o) + '</td>'
                '<td style="padding:5px 8px;font-family:monospace;color:#e74c3c;">' + '{:,.0f}'.format(h) + '</td>'
                '<td style="padding:5px 8px;font-family:monospace;color:#27ae60;">' + '{:,.0f}'.format(l) + '</td>'
                '<td style="padding:5px 8px;font-family:monospace;font-weight:bold;">' + '{:,.0f}'.format(c) + '</td>'
                '<td style="padding:5px 8px;color:' + chg_color + ';font-weight:bold;">' + chg_str + '</td>'
                '<td style="padding:5px 8px;color:#7f8c8d;">' + '{:,}'.format(v) + '</td>'
                '</tr>'
            )
            prev_close = c
        except Exception:
            pass
    html += '</table>'
    return html


def trend_analysis(rows):
    if len(rows) < 3:
        return '資料不足'
    closes = []
    for r in rows:
        try:
            closes.append(float(r['close']))
        except Exception:
            pass
    if len(closes) < 3:
        return '資料不足'
    up_days = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    down_days = len(closes) - 1 - up_days
    total_chg = pct(closes[-1], closes[0])
    recent_3 = closes[-3:]
    if all(recent_3[i] > recent_3[i-1] for i in range(1, 3)):
        recent_trend = '持續上漲'
    elif all(recent_3[i] < recent_3[i-1] for i in range(1, 3)):
        recent_trend = '持續下跌'
    else:
        recent_trend = '震盪整理'
    return '近5日：上漲{}天 / 下跌{}天，累積漲跌 {}{:.1f}%，近3日走勢：{}'.format(
        up_days, down_days, '+' if total_chg >= 0 else '', total_chg, recent_trend)


def bull_prob(tx, tx_rows):
    score = 50
    if tx.get('bull'):
        score += 15
    if tx.get('weak_w'):
        score -= 5
    if tx.get('mid_w'):
        score -= 10
    if tx.get('strong'):
        score -= 20
    if len(tx_rows) >= 2:
        try:
            c1 = float(tx_rows[-1]['close'])
            c2 = float(tx_rows[-2]['close'])
            if c1 > c2:
                score += 5
            else:
                score -= 5
        except Exception:
            pass
    close = tx.get('close') or 0
    m_val = tx.get('m') or 0
    b1    = tx.get('b1') or 0
    if close and m_val and b1:
        if close > m_val:
            score += 8
        if close > b1:
            score += 5
    return max(20, min(85, score))


def strategies_html(tx, prob):
    close = tx.get('close') or 0
    m_val = tx.get('m') or 0
    b1    = tx.get('b1') or 0
    s2    = tx.get('s2') or 0
    s1    = tx.get('s1') or 0
    b2    = tx.get('b2') or 0

    all_strategies = [
        ('S01', 'M附近做多→目標B1', '多方M~B1主戰場策略',
         bool(close and m_val and abs(close - m_val) < 200 and tx.get('bull'))),
        ('S02', 'B1附近反彈失敗做空→目標M', 'B1壓力反轉策略',
         bool(close and b1 and abs(close - b1) < 200)),
        ('S03', '突破B1後拉回做多→目標B2', 'B1突破後回測進場',
         bool(close and b1 and close > b1)),
        ('S04', '收盤守S1觀察次日再多', 'S1支撐確認多',
         bool(close and s1 and close > s1 and abs(close - s1) < 300)),
        ('S05', '破S2立即清空多單', 'S2止損守則',
         bool(close and s2 and close < s2)),
        ('S06', '連續上漲後M附近減碼', '趨勢過熱降倉',
         bool(tx.get('weak_w') or tx.get('mid_w'))),
        ('S07', '量縮守M整理等待', '低量整理等噴出',
         bool(tx.get('amp') and tx.get('amp', 1000) < 500)),
        ('S08', '強警訊出現先觀望', '警訊先蹲再跳',
         bool(tx.get('strong') or tx.get('mid_w'))),
        ('S09', '週線多方+日線拉回做多', '周日共振進場',
         bool(tx.get('bull'))),
        ('S10', '弱警訊+多方：半倉試多', '弱警訊輕倉策略',
         bool(tx.get('weak_w') and tx.get('bull'))),
        ('S11', '早盤高開B1以上 → 空手', '高開不追多',
         bool(close and b1 and close > b1)),
        ('S12', '跌破M首日觀望不做空', 'M失守等確認',
         bool(close and m_val and close < m_val)),
        ('S13', 'B2以上不追多，等回M', '強多不追高守則',
         bool(close and b2 and close > b2)),
        ('S14', '多商品同步多方加碼', '國際共振加碼',
         bool(tx.get('bull'))),
        ('S15', '美股夜盤大漲→次日縮小漲幅觀察', '外資套利效應', True),
        ('S16', '融資增加+量增→確認多方延續', '籌碼確認策略',
         bool(tx.get('bull'))),
        ('S17', 'M~B1區間來回當沖', '箱型操作策略',
         bool(close and m_val and b1 and m_val < close < b1)),
        ('S18', '前高突破後回測支撐做多', '突破回測經典型態',
         bool(tx.get('bull') and not tx.get('strong'))),
        ('S19', '三連陰後守M反彈做多', '情緒K線反轉',
         bool(not tx.get('bull'))),
        ('S20', '原油大跌觀察台股供應鏈', '跨商品聯動觀察', True),
        ('S21', '盤整末期量縮S1附近做多', '量縮整理末升段',
         bool(tx.get('amp') and tx.get('amp', 1000) < 600)),
        ('S22', '強警訊後次日量增是否守M定多空', '警訊後量能確認',
         bool(tx.get('strong') or tx.get('mid_w'))),
    ]

    matched   = [(c, n, d) for c, n, d, cond in all_strategies if cond]
    unmatched = [(c, n, d) for c, n, d, cond in all_strategies if not cond]

    html = '<table style="border-collapse:collapse;width:100%;font-size:13px;">'
    html += ('<tr style="background:#f8f9fa;">'
             '<th style="padding:6px 8px;text-align:left;width:50px;">代碼</th>'
             '<th style="padding:6px 8px;text-align:left;">策略名稱</th>'
             '<th style="padding:6px 8px;text-align:left;">說明</th>'
             '<th style="padding:6px 8px;width:70px;">適用</th></tr>')
    for code, name, desc in matched:
        html += (
            '<tr style="background:#e8f5e9;border-bottom:1px solid #c8e6c9;">'
            '<td style="padding:6px 8px;font-weight:bold;color:#1b5e20;">' + code + '</td>'
            '<td style="padding:6px 8px;font-weight:bold;color:#2e7d32;">' + name + '</td>'
            '<td style="padding:6px 8px;color:#555;">' + desc + '</td>'
            '<td style="padding:6px 8px;text-align:center;">✅ 適合</td></tr>'
        )
    for code, name, desc in unmatched:
        html += (
            '<tr style="border-bottom:1px solid #f0f0f0;">'
            '<td style="padding:6px 8px;color:#bbb;">' + code + '</td>'
            '<td style="padding:6px 8px;color:#bbb;">' + name + '</td>'
            '<td style="padding:6px 8px;color:#ddd;">' + desc + '</td>'
            '<td style="padding:6px 8px;text-align:center;color:#bbb;">—</td></tr>'
        )
    html += '</table>'
    return html, len(matched)


def teacher_notes(tx):
    close  = tx.get('close') or 0
    m_val  = tx.get('m') or 0
    b1     = tx.get('b1') or 0
    s2     = tx.get('s2') or 0
    bull   = tx.get('bull')
    strong = tx.get('strong')
    mid_w  = tx.get('mid_w')
    weak_w = tx.get('weak_w')

    notes = []
    notes.append(('D-01', '靜態規則是基礎，動態判斷是核心',
        '三關價是結構框架，請依今日實際走勢調整，不要死守靜態數字。'))
    if close and m_val and b1 and m_val < close < b1:
        zone = 'M~B1 核心安全區（多方主戰場）'
    elif b1 and close and close > b1:
        zone = 'B1以上（警戒區，勿追多）'
    elif m_val and close and close < m_val:
        zone = 'M以下（需等確認再進場）'
    else:
        zone = '整理區'
    notes.append(('D-02', '位置決定意義，同一根K線在不同位置意義完全不同',
        '目前收盤在 {} 區間，進場前先確認位置再論多空。'.format(zone)))
    notes.append(('D-03', '趨勢比反轉大，順勢做趨勢容易賺',
        '日線{}，順勢操作勝率較高，{}。'.format(
            '多方' if bull else '空方',
            '不宜逆勢放空' if bull else '反彈做空機率較高')))
    if strong:
        notes.append(('KN-03', '強警訊出現，反轉一半原則',
            '目前出現強警訊，建議先觀望或減半倉位，等量能確認方向再動作。'))
    elif mid_w:
        notes.append(('KN-03', '中警訊出現，需提高警覺',
            '中警訊訊號，多單建議縮小至半倉，等守住關鍵支撐再加碼。'))
    elif weak_w:
        notes.append(('KN-03', '弱警訊，輕倉試多為主',
            '弱警訊不代表反轉，但要注意是否連續出現。目前可輕倉持多，守住 M 值。'))
    notes.append(('V-03', '量是因，價是果；先看量，再看價',
        '今日開盤前請確認夜盤量能，若量縮守M，做多信心較足；量增跌破M需謹慎。'))
    notes.append(('SYS-02', '指標衝突時，回歸價的系統',
        '若今日消息面與技術面有衝突，以三關價位置（收盤 vs S2/B2）為最終判斷依據。'))
    if close and s2 and close < s2:
        notes.append(('MA-03', '破S2清空多單，不做空S2以下',
            '收盤已破 S2 ({})，依規則應清空多單，不在此區做空，等待止跌訊號。'.format(
                '{:,.0f}'.format(s2))))
    elif close and m_val and close < m_val:
        notes.append(('MA-02', '失守M需等確認，不急著進場',
            '收盤跌破 M ({})，建議等隔日收盤確認方向，不在盤中急著接刀。'.format(
                '{:,.0f}'.format(m_val))))
    else:
        notes.append(('MA-02', '守住M是多方最低條件',
            '只要收盤持續守住 M ({})，多方格局維持，拉回視為買點。'.format(
                '{:,.0f}'.format(m_val) if m_val else '-')))
    notes.append(('EM-05', '賺錢的人利用對面的情緒賺錢',
        '當大家都恐慌殺出或興奮追多，往往是反向訊號。保持冷靜，讓數字說話。'))
    notes.append(('M-01', '失去平常心，什麼都做不好',
        '不管今天盤勢如何，先回歸生活規律，清醒的頭腦比任何指標都重要。'))
    notes.append(('F-03', '多空格局衝突時以價格為主',
        '基本面再好，若收盤跌破S2，技術面優先；反之亦然。數據反映過去，價格反映未來。'))

    html = ''
    for code, rule, remind in notes:
        html += (
            '<div style="border-left:3px solid #f39c12;padding:10px 14px;margin-bottom:12px;'
            'background:#fffbf0;border-radius:0 6px 6px 0;">'
            '<div style="font-size:12px;color:#e67e22;font-weight:bold;margin-bottom:4px;">'
            '依據 ' + code + '</div>'
            '<div style="font-size:13px;color:#7f8c8d;font-style:italic;margin-bottom:6px;">'
            '「' + rule + '」</div>'
            '<div style="font-size:14px;color:#2c3e50;">→ ' + remind + '</div>'
            '</div>'
        )
    return html


def build_html(tx_text, tx_w_text, t5f_text, latest_text, tx_rows, t5f_rows):
    tx   = parse_tx(tx_text)
    t5f  = parse_tx(t5f_text)
    tx_w = parse_tx(tx_w_text)

    prob      = bull_prob(tx, tx_rows)
    bear_prob = 100 - prob

    strat_html, matched_count = strategies_html(tx, prob)
    teacher_html = teacher_notes(tx)

    five_days_tx  = tx_rows[-6:]  if len(tx_rows)  >= 6 else tx_rows
    five_days_t5f = t5f_rows[-6:] if len(t5f_rows) >= 6 else t5f_rows
    trend_tx  = trend_analysis(five_days_tx)
    trend_t5f = trend_analysis(five_days_t5f)

    close_str     = '{:,.0f}'.format(tx['close'])  if tx.get('close')  else '-'
    t5f_close_str = '{:.2f}'.format(t5f['close']) if t5f.get('close') else '-'

    # 全域商品概況
    latest_lines  = latest_text.split('\n')
    commodity_rows = []
    for line in latest_lines:
        if line.startswith('|') and '|' in line[1:]:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 5 and '---' not in parts[0] and '類別' not in parts[0]:
                commodity_rows.append(parts)

    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>蘭老師 TX 深度日報</title>'
        '<style>'
        'body{font-family:"Helvetica Neue",Arial,"Microsoft JhengHei",sans-serif;'
        'background:#f0f2f5;margin:0;padding:16px 0;}'
        '.wrap{max-width:760px;margin:0 auto;background:#fff;border-radius:12px;'
        'overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.12);}'
        '.header{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);'
        'padding:32px 36px;color:#fff;}'
        '.header h1{margin:0 0 6px;font-size:24px;letter-spacing:2px;}'
        '.header p{margin:0;color:#aaa;font-size:13px;}'
        '.section{padding:22px 36px;border-bottom:2px solid #f0f0f0;}'
        '.section h2{margin:0 0 16px;font-size:17px;color:#1a1a2e;'
        'border-left:5px solid #e74c3c;padding-left:12px;font-weight:bold;}'
        '.section h3{margin:12px 0 8px;font-size:14px;color:#2c3e50;}'
        '.kv{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:14px;}'
        '.kv-item{background:#f8f9fa;border-radius:8px;padding:12px 18px;'
        'min-width:110px;border:1px solid #ecf0f1;}'
        '.kv-item .label{font-size:11px;color:#95a5a6;margin-bottom:5px;'
        'text-transform:uppercase;letter-spacing:.5px;}'
        '.kv-item .value{font-size:20px;font-weight:bold;color:#1a1a2e;}'
        '.prob-bar{background:#ecf0f1;border-radius:6px;height:20px;overflow:hidden;margin:6px 0;}'
        '.prob-fill-bull{background:linear-gradient(90deg,#e74c3c,#c0392b);height:100%;'
        'border-radius:6px;}'
        '.footer{background:#1a1a2e;padding:20px 36px;font-size:12px;'
        'color:#7f8c8d;text-align:center;}'
        '.footer p{margin:4px 0;}'
        '</style></head><body><div class="wrap">'
    )

    html += (
        '<div class="header">'
        '<h1>📊 蘭老師 TX 深度日報</h1>'
        '<p>' + TODAY + '（星期' + TODAY_WEEKDAY + '）'
        '｜台指期 · 台灣50 · 22策略 · 深度分析版</p>'
        '</div>'
    )

    # 一、TX 深度分析
    html += '<div class="section"><h2>📈 一、台指期（TX）深度分析</h2>'
    html += '<div class="kv">'
    html += ('<div class="kv-item"><div class="label">資料日期</div>'
             '<div class="value" style="font-size:14px;">' + tx.get('date', '-') + '</div></div>')
    html += ('<div class="kv-item"><div class="label">收盤價</div>'
             '<div class="value">' + close_str + '</div></div>')
    html += ('<div class="kv-item"><div class="label">日線方向</div>'
             '<div class="value" style="font-size:14px;">' + direction_badge(tx.get('bull')) + '</div></div>')
    html += ('<div class="kv-item"><div class="label">警訊</div>'
             '<div class="value" style="font-size:12px;">'
             + alert_badge(tx.get('strong'), tx.get('mid_w'), tx.get('weak_w')) + '</div></div>')
    html += ('<div class="kv-item"><div class="label">週線方向</div>'
             '<div class="value" style="font-size:14px;">' + direction_badge(tx_w.get('bull')) + '</div></div>')
    html += '</div>'
    html += (
        '<h3>📊 多空機率評估</h3>'
        '<div style="margin-bottom:16px;">'
        '<div style="display:flex;justify-content:space-between;font-size:13px;'
        'font-weight:bold;margin-bottom:4px;">'
        '<span style="color:#e74c3c;">偏多 ' + str(prob) + '%</span>'
        '<span style="color:#27ae60;">偏空 ' + str(bear_prob) + '%</span>'
        '</div>'
        '<div class="prob-bar">'
        '<div class="prob-fill-bull" style="width:' + str(prob) + '%;"></div>'
        '</div>'
        '<p style="font-size:12px;color:#95a5a6;margin:4px 0 0;">'
        '評分依據：日線方向、警訊強度、與M/B1/S2相對位置、近期走勢</p>'
        '</div>'
    )
    html += '<h3>🚦 明日預測三關價</h3>'
    html += gate_table(tx)
    html += '</div>'

    # 二、T5F 深度分析
    t5f_prob = 65 if t5f.get('bull') else 40
    if t5f.get('weak_w'):
        t5f_prob -= 5
    if t5f.get('mid_w'):
        t5f_prob -= 12
    t5f_bear = 100 - t5f_prob

    html += '<div class="section"><h2>🔷 二、台灣50期貨（T5F）深度分析</h2>'
    html += '<div class="kv">'
    html += ('<div class="kv-item"><div class="label">收盤價</div>'
             '<div class="value">' + t5f_close_str + '</div></div>')
    html += ('<div class="kv-item"><div class="label">日線方向</div>'
             '<div class="value" style="font-size:14px;">' + direction_badge(t5f.get('bull')) + '</div></div>')
    html += ('<div class="kv-item"><div class="label">警訊</div>'
             '<div class="value" style="font-size:12px;">'
             + alert_badge(t5f.get('strong'), t5f.get('mid_w'), t5f.get('weak_w')) + '</div></div>')
    html += '</div>'
    html += (
        '<h3>📊 T5F 多空機率</h3>'
        '<div style="margin-bottom:12px;">'
        '<div style="display:flex;justify-content:space-between;font-size:13px;'
        'font-weight:bold;margin-bottom:4px;">'
        '<span style="color:#e74c3c;">偏多 ' + str(t5f_prob) + '%</span>'
        '<span style="color:#27ae60;">偏空 ' + str(t5f_bear) + '%</span>'
        '</div>'
        '<div class="prob-bar">'
        '<div class="prob-fill-bull" style="width:' + str(t5f_prob) + '%;"></div>'
        '</div></div>'
    )
    html += '<h3>🚦 T5F 明日預測三關價</h3>'
    html += gate_table(t5f)
    html += '</div>'

    # 三、近5日盤勢
    html += '<div class="section"><h2>📅 三、近5日盤勢連動分析</h2>'
    html += '<h3>台指期（TX）近5日 K 線</h3>'
    html += five_day_table(five_days_tx[-5:])
    html += ('<p style="font-size:13px;color:#555;margin-top:10px;padding:10px;'
             'background:#f8f9fa;border-radius:6px;">' + trend_tx + '</p>')
    html += '<h3 style="margin-top:16px;">台灣50期貨（T5F）近5日 K 線</h3>'
    html += five_day_table(five_days_t5f[-5:])
    html += ('<p style="font-size:13px;color:#555;margin-top:10px;padding:10px;'
             'background:#f8f9fa;border-radius:6px;">' + trend_t5f + '</p>')
    html += '</div>'

    # 四、22策略
    html += ('<div class="section"><h2>🎯 四、22大策略框架 — 今日適合策略（'
             + str(matched_count) + '個符合）</h2>')
    html += ('<p style="font-size:13px;color:#7f8c8d;margin:0 0 12px;">'
             '依當前盤勢條件自動篩選，綠色底色為今日適合操作策略：</p>')
    html += strat_html
    html += '</div>'

    # 五、全球18商品
    if commodity_rows:
        html += '<div class="section"><h2>🌐 五、全球18商品方向掃瞄</h2>'
        html += ('<table><tr><th>商品</th><th>收盤</th><th>漲%</th>'
                 '<th>方向</th><th>警訊</th><th>區間</th></tr>')
        for row in commodity_rows[:18]:
            if len(row) >= 5:
                name_txt  = row[1] if len(row) > 1 else '-'
                close_txt = row[3] if len(row) > 3 else '-'
                chg_txt   = row[2] if len(row) > 2 else '-'
                dir_txt   = row[4] if len(row) > 4 else '-'
                alert_txt = row[5] if len(row) > 5 else '-'
                zone_txt  = row[6] if len(row) > 6 else '-'
                dir_color   = '#e74c3c' if '多方' in dir_txt else '#27ae60'
                alert_color = ('#e74c3c' if '強' in alert_txt else
                               '#f39c12' if '中' in alert_txt else
                               '#f1c40f' if '弱' in alert_txt else '#27ae60')
                html += (
                    '<tr style="border-bottom:1px solid #f0f0f0;">'
                    '<td style="font-weight:bold;">' + name_txt + '</td>'
                    '<td style="font-family:monospace;">' + close_txt + '</td>'
                    '<td>' + chg_txt + '</td>'
                    '<td style="color:' + dir_color + ';font-weight:bold;">' + dir_txt + '</td>'
                    '<td style="color:' + alert_color + ';">' + alert_txt + '</td>'
                    '<td style="font-size:11px;color:#7f8c8d;">' + zone_txt[:20] + '</td>'
                    '</tr>'
                )
        html += '</table></div>'

    # 六、蘭老師叮嚀
    html += '<div class="section"><h2>🎓 六、蘭老師叮嚀（規則引用）</h2>'
    html += teacher_html
    html += '</div>'

    html += (
        '<div class="footer">'
        '<p>📌 <strong style="color:#fff;">投資的最終決策權在您自己。</strong></p>'
        '<p>本報告依三關價系統自動產生，僅供技術面參考。'
        '新資訊進來時，判斷需動態調整（貝葉斯思維）。</p>'
        '<p>—— 蘭老師 AI 分身 · ' + TODAY + '</p>'
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
    msg['Subject'] = '📊 蘭老師 TX 深度日報 ' + TODAY + '（' + TODAY_WEEKDAY + '）'
    msg['From']    = smtp_user
    msg['To']      = mail_to
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, mail_to.split(','), msg.as_string())
    print('Mail sent to', mail_to)


def main():
    tx_text  = read_md(TX_DAILY_MD)
    tx_w     = read_md(TX_WEEKLY_MD)
    t5f_text = read_md(T5F_DAILY_MD)
    latest   = read_md(LATEST_MD)
    tx_rows  = read_csv_last_n(TX_CSV, 8)
    t5f_rows = read_csv_last_n(T5F_CSV, 8)

    html = build_html(tx_text, tx_w, t5f_text, latest, tx_rows, t5f_rows)

    report_dir = BASE / 'three_gate' / 'reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / ('kline_report_' + TODAY + '.html')
    out.write_text(html, encoding='utf-8')
    print('HTML saved to', out)

    send_email(html)


if __name__ == '__main__':
    main()
