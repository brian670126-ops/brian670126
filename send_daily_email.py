# -*- coding: utf-8 -*-
"""
send_daily_email.py
====================
每天 daily_pipeline.py 跑完之後接著執行：把當天的重點(極端訊號、均線二次確認後
的「留意/警示」名單)整理成一封信件內文，並把當天的好讀版看板(dashboard_日期.html)
當附件，一起寄到信箱。

跟 three_gate/src/monthly_report.py 用的是同一套寄信方式(Gmail SMTP)，
也重複使用同一組 GitHub Secrets，不用再另外申請：
    SMTP_USER  寄件 Gmail 帳號
    SMTP_PASS  Gmail 應用程式密碼 (App Password，不是登入密碼)
    MAIL_TO    收件信箱（不設定則預設寄給 SMTP_USER 自己）

沒有設定這三個 Secrets 時，會印出提示、直接跳過寄信，不會讓整個排程失敗。
"""

from __future__ import annotations
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
REPORT_DIR = BASE_DIR / "reports"
RELATION_MAP_PATH = BASE_DIR / "relation_map_v2.csv"

TAIWAN_TZ = timezone(timedelta(hours=8))


def today_taiwan() -> str:
    return datetime.now(TAIWAN_TZ).strftime("%Y-%m-%d")


def build_email_body(summary: pd.DataFrame, today: str) -> str:
    if RELATION_MAP_PATH.exists():
        rm = pd.read_csv(RELATION_MAP_PATH, encoding="utf-8-sig")
        name_map = (
            rm.drop_duplicates(subset="yfinance_ticker")
            .set_index("yfinance_ticker")["公司名稱"]
            .to_dict()
        )
    else:
        name_map = {}

    summary = summary.copy()
    summary["公司名稱"] = summary["目標股"].map(name_map)

    lines = [f"{today} 每日追蹤摘要（系統自動寄送）", ""]
    lines.append(f"今天共分析 {len(summary)} 檔目標股。")
    lines.append("")

    extreme = summary[
        (summary["趨勢延續分數_100"] >= 90) | (summary["趨勢延續分數_100"] <= -90)
    ].sort_values("趨勢延續分數_100")
    lines.append(f"【極端訊號 分數>=90 或 <=-90，共 {len(extreme)} 檔】")
    if len(extreme):
        for _, row in extreme.iterrows():
            lines.append(
                f"　{row['目標股']} {row['公司名稱'] or ''}　{row['趨勢延續分數_100']:.1f}分"
                f"　均線濾網：{row.get('均線濾網') or '（非強烈訊號區間，不套用）'}"
            )
    else:
        lines.append("　今天沒有任何一檔進入極端訊號區間。")
    lines.append("")

    if "均線濾網" in summary.columns:
        watch = summary[summary["均線濾網"] == "留意/警示"].sort_values(
            "趨勢延續分數_100"
        )
        lines.append(f"【均線二次確認後，列入「留意/警示」的名單，共 {len(watch)} 檔】")
        if len(watch):
            for _, row in watch.iterrows():
                lines.append(
                    f"　{row['目標股']} {row['公司名稱'] or ''}　{row['趨勢延續分數_100']:.1f}分"
                    f"　收盤價 {row.get('收盤價')}"
                )
        else:
            lines.append("　今天沒有股票進入這份名單。")
        lines.append("")

    lines.append("附件是今天的好讀版看板(html)，下載後用瀏覽器打開即可看到完整97檔的排版畫面。")
    lines.append("（本信件由 GitHub Actions 排程自動寄送，不需回覆）")

    return "\n".join(lines)


def send_email(subject: str, body: str, attachment_path: Path | None):
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    mail_to = os.environ.get("MAIL_TO") or smtp_user

    if not smtp_user or not smtp_pass:
        print("未設定 SMTP_USER / SMTP_PASS，略過寄信（報表仍會正常產出並提交到 repo）")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = mail_to
    msg.set_content(body)

    if attachment_path and attachment_path.exists():
        with open(attachment_path, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="text",
            subtype="html",
            filename=attachment_path.name,
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    print(f"已寄出 email 給 {mail_to}")


def main():
    today = today_taiwan()
    summary_path = REPORT_DIR / f"summary_{today}.csv"
    dashboard_path = REPORT_DIR / f"dashboard_{today}.html"

    if not summary_path.exists():
        print(f"找不到 {summary_path}，可能今天 daily_pipeline.py 沒有跑出結果，略過寄信")
        return

    summary = pd.read_csv(summary_path, encoding="utf-8-sig")
    body = build_email_body(summary, today)
    subject = f"產業關聯追蹤 每日摘要 {today}"

    send_email(subject, body, dashboard_path if dashboard_path.exists() else None)


if __name__ == "__main__":
    main()
