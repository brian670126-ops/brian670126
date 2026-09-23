#!/usr/bin/env python3
"""
蘭老師 TX 日K線分析報告
每日 07:00 Taiwan time 自動寄送
讀取 three_gate/strategy/ 的最新資料，產生 HTML 郵件並寄出
"""

import os
import re
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")
WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
TODAY_WEEKDAY = WEEKDAY_CN[datetime.now(TW).weekday()]

BASE = Path(__file__).parent
STRATEGY_DIR = BASE / "three_gate" / "strategy"
TX_DAILY  = STRATEGY_DIR / "TX_daily.md"
TX_WEEKLY = STRATEGY_DIR / "TX_weekly.md"
T5F_DAILY = STRATEGY_DIR / "T5F_daily.md"
LATEST_MD = STRATEGY_DIR / "latest.md"


def read_md(path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def parse_value(text, key, default="—"):
    m = re.search(rf"\*\*{re.escape(key)}\*\*[：:]\s*(.+)", text)
    if m:
        return m.group(1).strip()
    m = re.search(rf"{re.escape(key)}[：:]\s*(.+)", text)
    return m.group(1).strip() if m else default


def parse_gates(text):
    gates = {}
    for key in ["B3", "B2", "B1", "M", "S1", "S2", "S3"]:
        m = re.search(rf"\b{key}\b[^0-9]*([0-9,]+)", text)
        if m:
            gates[key] = m.group(1).replace(",", "")
    return gates


def direction_badge(d):
    if "多" in d:
        return '<span style="background:#16a34a;color:#fff;padding:3px 12px;border-radius:12px;font-size:13px;">▲ ' + d + '</span>'
    if "空" in d:
        return '<span style="background:#dc2626;color:#fff;padding:3px 12px;border-radius:12px;font-size:13px;">▼ ' + d + '</span>'
    return '<span style="background:#d97706;color:#fff;padding:3px 12px;border-radius:12px;font-size:13px;">◆ ' + d + '</span>'


def alert_badge(a):
    if "強" in a:
        return '<span style="color:#dc2626;font-weight:bold;">🔴 ' + a + '</span>'
    if "中" in a:
        return '<span style="color:#d97706;font-weight:bold;">🟡 ' + a + '</span>'
    if "弱" in a:
        return '<span style="color:#ca8a04;">🟡 ' + a + '</span>'
    if a and a != "—":
        return '<span style="color:#6b7280;">' + a + '</span>'
    return '<span style="color:#16a34a;">✓ 無警訊</span>'


def gate_bar_html(gates, close_str):
    try:
        close = float(close_str.replace(",", ""))
        b2 = float(gates.get("B2", 0))
        b1 = float(gates.get("B1", 0))
        m  = float(gates.get("M",  0))
        s1 = float(gates.get("S1", 0))
        s2 = float(gates.get("S2", 0))
    except (ValueError, TypeError):
        return ""
    levels = [
        ("B2", b2, "#16a34a", "#dcfce7"),
        ("B1", b1, "#22c55e", "#f0fdf4"),
        ("M",  m,  "#2563eb", "#eff6ff"),
        ("S1", s1, "#f97316", "#fff7ed"),
        ("S2", s2, "#dc2626", "#fef2f2"),
    ]
    rows = ""
    for name, val, color, bg in levels:
        diff = close - val
        diff_str = ("+{:,.0f}".format(diff)) if diff >= 0 else "{:,.0f}".format(diff)
        rows += (
            '<tr style="background:' + bg + ';">'
            '<td style="padding:6px 12px;font-weight:bold;color:' + color + ';width:40px;">' + name + '</td>'
            '<td style="padding:6px 12px;font-family:monospace;font-size:15px;">{:,.0f}</td>'.format(val) +
            '<td style="padding:6px 12px;color:#6b7280;font-size:12px;">距收盤 ' + diff_str + '</td>'
            '</tr>'
        )
    return '<table style="border-collapse:collapse;width:100%;">' + rows + '</table>'


def parse_latest(text):
    multi, short, warn = [], [], []
    for line in text.splitlines():
        if "多方" in line and "│" in line:
            code = re.search(r"│\s*(\w+)\s*│", line)
            if code:
                multi.append(code.group(1))
        elif "空方" in line and "│" in line:
            code = re.search(r"│\s*(\w+)\s*│", line)
            if code:
                short.append(code.group(1))
        if "強警訊" in line and "│" in line:
            code = re.search(r"│\s*(\w+)\s*│", line)
            if code:
                warn.append(code.group(1))
    return multi, short, warn


def chips_row(label, items, color):
    chips = "".join(
        '<span style="background:' + color + ';color:#fff;padding:2px 8px;border-radius:10px;margin:2px;font-size:12px;display:inline-block;">' + i + '</span>'
        for i in items
    )
    return '<div style="margin:4px 0;"><b style="font-size:12px;color:#6b7280;">' + label + '</b><br>' + chips + '</div>'


def build_html():
    tx_d   = read_md(TX_DAILY)
    tx_w   = read_md(TX_WEEKLY)
    t5f_d  = read_md(T5F_DAILY)
    latest = read_md(LATEST_MD)

    tx_close     = parse_value(tx_d, "收盤")
    tx_direction = parse_value(tx_d, "方向")
    tx_zone      = parse_value(tx_d, "所在區間")
    tx_alert     = parse_value(tx_d, "警訊")
    tx_date      = parse_value(tx_d, "日期", TODAY)
    tx_gates     = parse_gates(tx_d)
    pred = re.search(r"明[日天]預測三關價(.*?)(?:\n#|\Z)", tx_d, re.S)
    if pred:
        tx_gates = parse_gates(pred.group(1))

    tx_w_direction = parse_value(tx_w, "方向")
    tx_w_alert     = parse_value(tx_w, "警訊")
    tx_w_zone      = parse_value(tx_w, "所在區間")

    t5f_close     = parse_value(t5f_d, "收盤")
    t5f_direction = parse_value(t5f_d, "方向")
    t5f_alert     = parse_value(t5f_d, "警訊")

    multi, short, warn = parse_latest(latest)
    gate_bar = gate_bar_html(tx_gates, tx_close)

    gate_rows = ""
    gate_labels = {
        "B3": ("強壓", "#15803d"), "B2": ("壓力2", "#16a34a"), "B1": ("壓力1", "#22c55e"),
        "M":  ("樞軸M", "#2563eb"),
        "S1": ("支撐1", "#f97316"), "S2": ("支撐2", "#dc2626"), "S3": ("強支", "#991b1b"),
    }
    for key, (label, color) in gate_labels.items():
        val = tx_gates.get(key, "—")
        try:
            val_display = "{:,}".format(int(val))
        except (ValueError, TypeError):
            val_display = "—"
        gate_rows += (
            '<tr>'
            '<td style="padding:5px 10px;color:' + color + ';font-weight:bold;">' + key + '</td>'
            '<td style="padding:5px 10px;font-size:13px;color:#6b7280;">' + label + '</td>'
            '<td style="padding:5px 10px;font-family:monospace;font-size:15px;text-align:right;">' + val_display + '</td>'
            '</tr>'
        )

    multi_html = chips_row("多方商品", multi, "#16a34a") if multi else ""
    short_html = chips_row("空方商品", short, "#dc2626") if short else ""
    warn_html  = chips_row("警訊商品", warn, "#d97706") if warn else ""

    if "多" in tx_direction:
        teacher_note = "<b>今日蘭老師叮嚀：</b><br>依據 <b>D-01</b>：「趨勢比反轉大，順勢做趨勢容易賺。」<br>依據 <b>KN-03</b>：「消息面只是催化劑，K線形態才是主角。」<br>目前多方趨勢，操作上以回測支撐時的進場機會為主，不追高，設好停損。"
    elif "空" in tx_direction:
        teacher_note =
