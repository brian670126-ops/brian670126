"""
主分析流程

對每個商品:
1. 讀取日/週 OHLC (自動抓 or 手動輸入)
2. 計算三關價 (用前一週期 OHLC 推)
3. 計算觸碰、方向、警訊
4. 判斷所在區間與策略
5. 產出:
   - analysis/{code}_daily.xlsx
   - analysis/{code}_weekly.xlsx
   - strategy/latest.md (多商品對照)
   - strategy/{code}.md (單商品完整分析，表頭含「明日/下週三關價(預估)」)

v2 修正重點（明日/下週三關價(預估)顯示邏輯）：
    三關價公式是「用前一週期OHLC算當期關卡」，所以只要當期OHLC已經
    確定，下一期的關卡就已經可以精確算出來，不是用猜的，只是還沒有
    下一期的收盤價可以拿來判斷方向、位置而已。
    - 日線：只要當天資料已經抓進來，代表當天已經收盤，隔天的三關價
      可以馬上算出來，直接顯示。
    - 週線：weekly CSV 是用 W-FRI 每天重新彙總，平日執行時最後一筆
      其實是「本週尚在進行中」的暫時彙總（例如只到週三），不是完整
      的一週，這時候拿來推算「下週」關卡會不準。要等到週五夜盤結束、
      週六早上資料進來、那一週真正收盤後，才把「下週三關價(預估)」
      算出來顯示，平常日子這段就先不顯示。
    - 不論日/週，這個「(預估)」關卡都只放在 strategy/*.md 報告的表頭，
      不寫進 Excel 分析檔（Excel 維持只放已經發生、確定的資料）。
"""

import sys
import json
from datetime import datetime
from pathlib import Path

import yaml
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).parent))
from three_gate_calc import (
    OHLC, ThreeGate,
    calc_three_gate, determine_direction,
    calc_touch_symbols, calc_warning_signal, strategy_zones,
)
from read_manual import read_manual_daily, read_manual_weekly
from fetch_yfinance import DATA_DIR as AUTO_DIR


ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / 'config' / 'symbols.yaml'
ANALYSIS_DIR = ROOT / 'analysis'
STRATEGY_DIR = ROOT / 'strategy'


def load_symbols():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_ohlc_data(code: str, source: str, period: str) -> pd.DataFrame:
    """
    讀取 OHLC 資料

    Args:
        code: 商品代碼 (TX, ES, NQ, ...)
        source: 'manual' | 'auto'
        period: 'daily' | 'weekly'
    """
    if source == 'manual':
        if period == 'daily':
            return read_manual_daily(code)
        else:
            return read_manual_weekly(code)
    else:
        path = AUTO_DIR / f'{code}_{period}.csv'
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_csv(path)
        if 'date' not in df.columns and 'week_end' in df.columns:
            df = df.rename(columns={'week_end': 'date'})
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values('date').reset_index(drop=True)


def is_period_closed(period: str, last_date_str: str) -> bool:
    """
    判斷「最後一筆資料」是不是已經是「完整收盤」的一期，
    可以拿來推算下一期的(預估)三關價。

    - daily: 只要這筆資料存在，代表當天已經收盤，永遠算完整。
    - weekly: weekly CSV 用 W-FRI 逐日重算，平日執行時最後一筆
      常常是「本週還沒過完」的暫時彙總（標示的 week_end 是還沒到的
      週五）。只有當「今天」已經到達或超過那個週五，才代表那一週
      真正收完盤，才可以拿來推算下週的(預估)關卡。
    """
    if period == 'daily':
        return True

    week_end = datetime.strptime(last_date_str, '%Y-%m-%d').date()
    today = datetime.now().date()
    return today >= week_end


def analyze_one(code: str, name: str, source: str, period: str) -> dict:
    """
    分析單商品的單週期資料

    Returns: dict with 三關價、方向、觸碰、警訊、策略區間、下一期(預估)關卡
    """
    df = get_ohlc_data(code, source, period)

    if len(df) < 2:
        return None

    # 計算每個週期的三關價 (用前一週期 OHLC 推)
    rows = []
    prev_direction = '多方'

    for i in range(1, len(df)):
        prev = df.iloc[i-1]
        curr = df.iloc[i]

        prev_ohlc = OHLC(
            open=float(prev['open']), high=float(prev['high']),
            low=float(prev['low']), close=float(prev['close']),
        )
        curr_ohlc = OHLC(
            open=float(curr['open']), high=float(curr['high']),
            low=float(curr['low']), close=float(curr['close']),
        )

        # 當前週期的三關價
        gate = calc_three_gate(prev_ohlc)

        # 方向 (用當前週期的 S2/B2 判定)
        direction = determine_direction(curr_ohlc.close, gate, prev_direction)

        # 觸碰
        touches = calc_touch_symbols(curr_ohlc, gate)

        # 警訊
        warning = calc_warning_signal(curr_ohlc, prev_ohlc, direction, gate)

        rows.append({
            'date': curr['date'],
            'open': curr_ohlc.open, 'high': curr_ohlc.high,
            'low': curr_ohlc.low, 'close': curr_ohlc.close,
            'change': curr_ohlc.close - prev_ohlc.close,
            'change_pct': (curr_ohlc.close - prev_ohlc.close) / prev_ohlc.close,
            'range': curr_ohlc.range,
            'S3': gate.S3, 'S2': gate.S2, 'S1': gate.S1,
            'M': gate.M,
            'B1': gate.B1, 'B2': gate.B2, 'B3': gate.B3,
            'touch_S3': touches.get('S3'), 'touch_S2': touches.get('S2'),
            'touch_S1': touches.get('S1'), 'touch_M': touches.get('M'),
            'touch_B1': touches.get('B1'), 'touch_B2': touches.get('B2'),
            'touch_B3': touches.get('B3'),
            'direction': direction, 'warning': warning,
        })

        prev_direction = direction

    result_df = pd.DataFrame(rows)

    # 最後一筆的完整分析
    last = result_df.iloc[-1]
    last_gate = ThreeGate(
        S3=last['S3'], S2=last['S2'], S1=last['S1'],
        M=last['M'], B1=last['B1'], B2=last['B2'], B3=last['B3'],
    )
    strategy = strategy_zones(last_gate, last['close'], last['direction'])

    last_date_str = str(last['date'])[:10]

    # 明日/下週三關價(預估)：用「最後一期」的 OHLC 推算下一期
    # （公式本身就是拿前一期推當期，所以只要最後一期已經收盤確定，
    #   下一期的關卡就能精確算出來，不是預測猜測，只是還沒有下一期
    #   的收盤可以判斷方向而已）
    latest_ohlc = OHLC(
        open=last['open'], high=last['high'],
        low=last['low'], close=last['close'],
    )
    next_gate = calc_three_gate(latest_ohlc)
    next_gate_valid = is_period_closed(period, last_date_str)

    return {
        'code': code,
        'name': name,
        'period': period,
        'df': result_df,
        'last': last.to_dict(),
        'strategy': strategy,
        'next_gate': next_gate.to_dict(),
        'next_gate_valid': next_gate_valid,
        'last_date': last_date_str,
    }


def write_excel(analysis: dict, out_path: Path):
    """把單商品分析結果寫成 Excel（只放已確定發生的資料，不放(預估)關卡）"""
    wb = Workbook()
    ws = wb.active
    ws.title = f"{analysis['code']}_{analysis['period']}"

    # 樣式
    font_h = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    font_red = Font(name='Calibri', size=10, color='C00000', bold=True)
    font_green = Font(name='Calibri', size=10, color='006100', bold=True)
    align_c = Alignment(horizontal='center', vertical='center')

    HEADER_BG = '4472C4'
    S_BG = 'C6EFCE'
    B_BG = 'FFC7CE'
    M_BG = 'FFF2CC'

    # 標題
    headers = [
        '日期', '開', '高', '低', '收', '漲跌', '漲%', '振幅',
        'S3', 'S2', 'S1', 'M', 'B1', 'B2', 'B3',
        '觸S3', '觸S2', '觸S1', '觸M', '觸B1', '觸B2', '觸B3',
        '方向', '警訊',
    ]

    for c, h in enumerate(headers, 1):
        cell = ws.cell(1, c)
        cell.value = h
        cell.font = font_h
        cell.alignment = align_c
        if h.startswith('S') or h.startswith('觸S'): cell.fill = PatternFill('solid', start_color=S_BG)
        elif h.startswith('B') or h.startswith('觸B'): cell.fill = PatternFill('solid', start_color=B_BG)
        elif h in ['M', '觸M']: cell.fill = PatternFill('solid', start_color=M_BG)
        else: cell.fill = PatternFill('solid', start_color=HEADER_BG)

    # 資料
    df = analysis['df']
    for i, row in df.iterrows():
        r = i + 2
        ws.cell(r, 1).value = row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])[:10]
        for c, key in enumerate(['open','high','low','close','change'], 2):
            ws.cell(r, c).value = round(float(row[key]), 2)
        ws.cell(r, 7).value = round(float(row['change_pct']), 4)
        ws.cell(r, 7).number_format = '+0.00%;-0.00%;0.00%'
        ws.cell(r, 8).value = round(float(row['range']), 2)

        for c, key in enumerate(['S3','S2','S1','M','B1','B2','B3'], 9):
            ws.cell(r, c).value = round(float(row[key]), 2)

        for c, key in enumerate(['touch_S3','touch_S2','touch_S1','touch_M','touch_B1','touch_B2','touch_B3'], 16):
            v = row[key]
            cell = ws.cell(r, c)
            cell.value = v if v else ''
            if v and ('S' in key):
                cell.fill = PatternFill('solid', start_color=S_BG)
                cell.font = font_green
            elif v and ('B' in key):
                cell.fill = PatternFill('solid', start_color=B_BG)
                cell.font = font_red
            elif v and ('M' in key):
                cell.fill = PatternFill('solid', start_color=M_BG)
                if '↑' in str(v): cell.font = font_red
                elif '↓' in str(v): cell.font = font_green
            cell.alignment = align_c

        ws.cell(r, 23).value = row['direction']
        ws.cell(r, 23).font = font_red if row['direction'] == '多方' else font_green
        ws.cell(r, 24).value = row['warning']

    # 欄寬
    for c in range(1, len(headers)+1):
        ws.column_dimensions[get_column_letter(c)].width = 10
    ws.freeze_panes = 'B2'

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def write_strategy_md(analysis: dict, out_path: Path):
    """把單商品分析結果寫成 Markdown 策略報告（表頭放「明日/下週三關價(預估)」）"""
    a = analysis
    last = a['last']
    st = a['strategy']
    ng = a['next_gate']
    period_name = '日' if a['period'] == 'daily' else '週'
    next_period_name = '明日' if a['period'] == 'daily' else '下週'

    dir_emoji = '🟢' if last['direction'] == '多方' else '🔴'
    warn_emoji = {'強警訊': '🔴🔴🔴', '中警訊': '🟠🟠', '弱警訊': '🟡', '': ''}.get(last['warning'], '')

    lines = [
        f"# {a['name']} ({a['code']}) - {period_name}三關價分析",
        "",
    ]

    # ── 表頭：明日/下週三關價(預估) ──────────────────────────
    if a['next_gate_valid']:
        lines.extend([
            f"> ### 📌 {next_period_name}三關價（預估）— 依 {a['last_date']} 已收盤資料計算",
            f">",
            f"> | 關卡 | 值 |",
            f"> |------|-----|",
        ])
        for lbl in ['B3', 'B2', 'B1', 'M', 'S1', 'S2', 'S3']:
            lines.append(f"> | {lbl} | {ng[lbl]:.2f} |")
        lines.extend([
            f">",
            f"> ⚠️ 此為依目前已知資料試算的「預估」關卡，供{next_period_name}參考；"
            f"若之後 {a['last_date']} 的原始 OHLC 有校正，此處數字會跟著更新。",
            "",
        ])
    elif a['period'] == 'weekly':
        lines.extend([
            f"> ### 📌 下週三關價（預估）",
            f">",
            f"> ⏳ 本週尚未收盤（目前資料只到 {a['last_date']} 所在的這一週的進行中彙總），"
            f"下週(預估)關卡將於本週收盤（週五夜盤結束、週六資料到齊）後產出。",
            "",
        ])

    lines.extend([
        f"**最新資料日期**: {a['last_date']}",
        "",
        f"## 目前狀態",
        "",
        f"| 項目 | 值 |",
        f"|------|-----|",
        f"| 收盤 | {last['close']:.2f} |",
        f"| {period_name}漲跌 | {last['change']:+.2f} ({last['change_pct']*100:+.2f}%) |",
        f"| 振幅 | {last['range']:.2f} |",
        f"| **方向** | {dir_emoji} **{last['direction']}** |",
        f"| **警訊** | {warn_emoji} {last['warning']} |",
        f"| 所在區間 | {st['zone']} |",
        "",
        f"## 當前 {period_name}三關價",
        "",
        f"| 關卡 | 值 | 距收盤 | 觸碰 |",
        f"|------|-----|-------|------|",
    ])

    for lbl in ['B3', 'B2', 'B1', 'M', 'S1', 'S2', 'S3']:
        v = last[lbl]
        dist = v - last['close']
        touch = last.get(f'touch_{lbl}')
        if touch is None or (isinstance(touch, float) and pd.isna(touch)):
            touch = ''
        lines.append(f"| {lbl} | {v:.2f} | {dist:+.2f} | {touch} |")

    lines.extend([
        "",
        f"## 實戰參考 (M-B1 策略)",
        "",
        f"**主戰場**: M ({last['M']:.2f}) ~ B1 ({last['B1']:.2f})",
        "",
        f"- 短多進場: M 附近 → 目標 B1 → B2",
        f"- 短空進場: B1 附近反彈失敗 → 目標 M",
        f"- 停損: 破 S2 ({last['S2']:.2f}) 清空多單",
        f"- 不追多: 過 B2 ({last['B2']:.2f}) 以上",
        f"- 不做空: 破 S2 以下",
        "",
    ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')


def write_multi_summary(analyses: dict, out_path: Path):
    """
    多商品對照報告
    """
    lines = [
        "# 三關價系統 - 全球多商品每日對照",
        "",
        f"**執行時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 一、全商品方向對照 (日週期)",
        "",
        f"| 類別 | 商品 | 資料日 | 收盤 | 漲% | 方向 | 警訊 | 所在區間 |",
        f"|------|------|-------|-----|-----|-----|------|--------|",
    ]

    # 按類別分組
    cfg = load_symbols()
    all_items = cfg.get('manual', []) + cfg.get('auto', [])

    for item in all_items:
        code = item['code']
        name = item['name']
        cat = item.get('category', '-')
        key = f"{code}_daily"

        if key not in analyses or not analyses[key]:
            lines.append(f"| {cat} | {name} ({code}) | 無資料 | - | - | - | - | - |")
            continue

        a = analyses[key]
        last = a['last']
        st = a['strategy']
        dir_emoji = '🟢' if last['direction'] == '多方' else '🔴'
        warn = last['warning'] or '-'

        lines.append(
            f"| {cat} | {name} ({code}) | {a['last_date']} | "
            f"{last['close']:.2f} | {last['change_pct']*100:+.2f}% | "
            f"{dir_emoji} {last['direction']} | {warn} | {st['zone'][:20]} |"
        )

    lines.extend([
        "",
        "## 二、多方商品 (可能做多對象)",
        "",
    ])

    long_list = []
    short_list = []
    for key, a in analyses.items():
        if not a or not key.endswith('_daily'): continue
        if a['last']['direction'] == '多方':
            long_list.append(a)
        else:
            short_list.append(a)

    if long_list:
        lines.append(f"共 {len(long_list)} 個商品方向為多方:")
        lines.append("")
        for a in long_list:
            lines.append(f"- **{a['name']} ({a['code']})**: 收 {a['last']['close']:.2f}, {a['strategy']['zone']}")
    else:
        lines.append("_無多方商品_")

    lines.extend([
        "",
        "## 三、空方商品 (可能做空對象或避開)",
        "",
    ])

    if short_list:
        lines.append(f"共 {len(short_list)} 個商品方向為空方:")
        lines.append("")
        for a in short_list:
            lines.append(f"- **{a['name']} ({a['code']})**: 收 {a['last']['close']:.2f}, {a['strategy']['zone']}")
    else:
        lines.append("_無空方商品_")

    lines.extend([
        "",
        "## 四、警訊商品 (需注意)",
        "",
    ])

    warn_list = []
    for key, a in analyses.items():
        if not a or not key.endswith('_daily'): continue
        if a['last']['warning']:
            warn_list.append(a)

    if warn_list:
        lines.append(f"共 {len(warn_list)} 個商品出現警訊:")
        lines.append("")
        warn_priority = {'強警訊': 3, '中警訊': 2, '弱警訊': 1}
        warn_list.sort(key=lambda x: -warn_priority.get(x['last']['warning'], 0))
        for a in warn_list:
            emoji = {'強警訊': '🔴🔴🔴', '中警訊': '🟠🟠', '弱警訊': '🟡'}.get(a['last']['warning'], '')
            lines.append(f"- {emoji} **{a['name']} ({a['code']})**: {a['last']['warning']}, 方向 {a['last']['direction']}")
    else:
        lines.append("_無警訊商品_")

    lines.extend([
        "",
        "## 五、詳細資料",
        "",
        "各商品詳細分析請看 `strategy/{code}_daily.md` 或 `strategy/{code}_weekly.md`",
        "",
        "各商品完整 Excel 表格請看 `analysis/{code}_daily.xlsx` 或 `analysis/{code}_weekly.xlsx`",
        "",
    ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')


def run_all():
    """主流程: 分析所有商品的日週兩週期"""
    cfg = load_symbols()
    manual_items = cfg.get('manual', [])
    auto_items = cfg.get('auto', [])

    all_analyses = {}

    # 手動商品
    for item in manual_items:
        code = item['code']
        name = item['name']
        for period in ['daily', 'weekly']:
            key = f"{code}_{period}"
            print(f"\n分析 {key}...")
            a = analyze_one(code, name, 'manual', period)
            if a:
                all_analyses[key] = a
                write_excel(a, ANALYSIS_DIR / f'{key}.xlsx')
                write_strategy_md(a, STRATEGY_DIR / f'{key}.md')
                print(f"  ✓ 產出 {key}")
            else:
                print(f"  ✗ 資料不足或缺失")
                all_analyses[key] = None

    # 自動商品
    for item in auto_items:
        code = item['code']
        name = item['name']
        for period in ['daily', 'weekly']:
            key = f"{code}_{period}"
            print(f"\n分析 {key}...")
            a = analyze_one(code, name, 'auto', period)
            if a:
                all_analyses[key] = a
                write_excel(a, ANALYSIS_DIR / f'{key}.xlsx')
                write_strategy_md(a, STRATEGY_DIR / f'{key}.md')
                print(f"  ✓ 產出 {key}")
            else:
                print(f"  ✗ 資料不足或缺失")
                all_analyses[key] = None

    # 多商品對照
    write_multi_summary(all_analyses, STRATEGY_DIR / 'latest.md')
    print("\n✓ 多商品對照報告: strategy/latest.md")

    # 統計
    valid = sum(1 for a in all_analyses.values() if a)
    total = len(all_analyses)
    print(f"\n共 {valid}/{total} 個商品×週期成功分析")

    return all_analyses


if __name__ == '__main__':
    run_all()
