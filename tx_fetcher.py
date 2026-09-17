"""
tx_fetcher.py  v5
台指期（TX）資料自動抓取模組
來源：台灣期貨交易所（taifex.com.tw）
合併日盤＋夜盤：Open=日盤O, High=max(日H,夜H), Low=min(日L,夜L), Close=夜盤C

v5 修正重點（結算日換月問題）：
    每月第3個星期三是TX結算日，當天近月合約會在早盤結算後停止交易，
    成交量主力轉移到新的近月合約。若日盤、夜盤「各自」抓成交量最大的
    TX列，結算日當天可能日盤抓到舊合約、夜盤抓到新合約，開高低收會
    變成兩個不同合約拼起來，數字對不起來。
    v5 做法：日盤、夜盤都先抓「所有到期月份」的資料，再用「當天日盤+
    夜盤合計成交量最大」的那個月份為準，日盤、夜盤都固定抓同一個月份
    的資料，避免結算日拼錯合約。

台期所欄位順序（已確認）：
[0]=契約 [1]=到期月份 [2]=開盤價 [3]=最高價 [4]=最低價 [5]=最後成交價
[6]=漲跌值 [7]=漲跌% [8]=*成交量 [9]=結算價 [10]=*未沖銷契約量
[11]=最後最佳買價 [12]=最後最佳賣價 [13]=歷史最高 [14]=歷史最低
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import argparse
import os
import time

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "three_gate", "data", "auto")
DAILY_CSV  = os.path.join(DATA_DIR, "TX_daily.csv")
WEEKLY_CSV = os.path.join(DATA_DIR, "TX_weekly.csv")
os.makedirs(DATA_DIR, exist_ok=True)

TAIFEX_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":    "https://www.taifex.com.tw/",
    "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PRICE_MIN = 5000
PRICE_MAX = 100000


def to_float(s):
    try:
        return float(str(s).replace(",", "").strip())
    except:
        return None


def to_int(s):
    try:
        return int(str(s).replace(",", "").strip())
