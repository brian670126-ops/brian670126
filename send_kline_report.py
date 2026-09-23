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

# ── 時區 ──────────────────────────────────────────────────────────────────────
TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")
WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
TODAY_WEEKDAY = WEEKDAY_CN[datetime.now(TW).weekday()]

# ── 檔案路徑 ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
STRATEGY_DIR = BASE / "three_gate" / "strategy"
TX_DAILY   = STRATEGY_DIR / "TX_daily.md"
TX_WEEKLY  = STRATEGY_DIR / "TX_weekly.md"
T5F_DAILY  = STRATEGY_DIR / "T5F_daily.md"
LATEST_MD  = STRATEGY_DIR / "latest.md"

# ── 工具函式 ──────────────────────────────────────────────────────────────────

def read_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""

def parse_value(text: str, key: str, default: str = "—") -> str:
    m = re.search(rf"\*\*{re.escape(key)}\*\*[：:]\s*(.+)", text)
    if m:
        return m.group(1).strip()
    m = re.search(rf"{re.escape(key)}[：:]\s*(.+)", text)
    return m.group(1).strip() if m else default

def parse_gates(text: str) -> dict:
    gates = {}
    for key in ["B3", "B2", "B1", "M", "S1", "S2", "S3"]:
        m = re.search(rf"\b{key}\b[^0-9]*([0-9,]+)", text)
        if m:
            gates[key] = m.group(1).replace(",", "")
    return gates

def direction_badge(direction: str) -> str:
    if "多" in direction:
        return f'<span style="background:#16a34a;color:#fff;padding:3px 12px;border-radius:12px;font-size:13px;">▲ {direction}</span>'
    if "空" in direction:
        return f'<span style="background:#dc2626;color:#fff;padding:3px 12px;border-radius:12px;font-size:13px;">▼ {direction}</span>'
    return f'<span style="background:#d97706;color:#fff;padding:3px 12px;border-radius:12px;font-size:13px;">◆ {direction}</span>'

def alert_badge(alert: str) -> str:
    if "強" in alert:
        return f'<span style="color:#dc2626;font-weight:bold;">🔴 {alert}</span>'
    if "中" in alert:
        return f'<span style="color:#d97706;font-weight:bold;">🟡 {alert}</span>'
    if "弱" in alert:
        return f'<span style="color:#ca8a04;">🟡 {alert}</span>'
    if alert and alert != "—":
        return f'<span style="color:#6b7280;">{alert}</span>'
    return '<span style="color:#16a34a;">✓ 無警訊</span>'

def gate_bar_html(gates: dict, close_str: str) -> str:
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
        diff_str = f"+{diff:,.0f}" if diff >= 0 else f"{diff:,.0f}"
        rows += f"""
        <tr style="background:{bg};">
          <td
