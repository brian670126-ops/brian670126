"""
三關價計算核心模組

公式:
    M = (H + L + 2C) / 4
    B1 = 2M - L
    B2 = 3M - 2L
    B3 = H + (H - L)
    S1 = 2M - H
    S2 = 3M - 2H
    S3 = L - (H - L)

方向 (以當前週期的 S2/B2 判定):
    if 當前C > 當前B2 → 多方
    elif 當前C < 當前S2 → 空方
    else → 延續前期方向

觸碰符號 (v8):
    B系列: H >= B → ✓
    S系列: L <= S → ✓
    M: C > M → ↑; C < M → ↓; C == M → =
    最靠近的關卡: △C 覆蓋 ✓ (M 加 C 變 ↑C/↓C)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ThreeGate:
    """三關價七個關卡"""
    S3: float
    S2: float
    S1: float
    M: float
    B1: float
    B2: float
    B3: float
    
    def to_dict(self):
        return {
            'S3': self.S3, 'S2': self.S2, 'S1': self.S1,
            'M': self.M,
            'B1': self.B1, 'B2': self.B2, 'B3': self.B3,
        }


@dataclass
class OHLC:
    """一根 K 棒"""
    open: float
    high: float
    low: float
    close: float
    
    @property
    def range(self):
        return self.high - self.low


def calc_three_gate(prev: OHLC) -> ThreeGate:
    """
    用前一週期的 OHLC 推算當前週期的三關價
    """
    H, L, C = prev.high, prev.low, prev.close
    M = (H + L + 2 * C) / 4
    return ThreeGate(
        S3=L - (H - L),
        S2=3 * M - 2 * H,
        S1=2 * M - H,
        M=M,
        B1=2 * M - L,
        B2=3 * M - 2 * L,
        B3=H + (H - L),
    )


def determine_direction(
    curr_close: float,
    curr_gate: ThreeGate,
    prev_direction: Optional[str] = None,
) -> str:
    """
    判定方向 - 用「當前週期的 B2/S2」對照「當前收盤」
    """
    if curr_close > curr_gate.B2:
        return '多方'
    elif curr_close < curr_gate.S2:
        return '空方'
    else:
        return prev_direction or '多方'


def calc_touch_symbols(
    curr_ohlc: OHLC,
    curr_gate: ThreeGate,
) -> dict:
    """
    計算觸碰符號 (v8 邏輯)
    
    Returns:
        {'S3': '✓', 'S2': '△C', 'S1': None, 'M': '↑C', 'B1': '✓', ...}
    """
    H, L, C = curr_ohlc.high, curr_ohlc.low, curr_ohlc.close
    gate_dict = curr_gate.to_dict()
    
    # 找收盤最靠近的關卡
    closest = min(gate_dict.keys(), key=lambda k: abs(C - gate_dict[k]))
    
    result = {}
    for lbl, lv in gate_dict.items():
        sym = None
        side = lbl[0]  # 'S', 'M', 'B'
        
        if side == 'B':
            if H >= lv:
                sym = '✓'
        elif side == 'S':
            if L <= lv:
                sym = '✓'
        elif side == 'M':
            if C > lv:
                sym = '↑'
            elif C < lv:
                sym = '↓'
            else:
                sym = '='
        
        # 收盤最靠近 → 覆蓋
        if closest == lbl:
            if side == 'M':
                sym = (sym or '') + 'C'
            else:
                sym = '△C'
        
        result[lbl] = sym
    
    return result


def calc_warning_signal(
    curr_ohlc: OHLC,
    prev_ohlc: OHLC,
    direction: str,
    curr_gate: ThreeGate,
) -> str:
    """
    反轉警訊系統
    
    多方時: 觀察 高/低/收 是否 3 個都變低 (反轉徵兆)
        3 個 True = 強警訊
        2 個 = 中警訊
        1 個 = 弱警訊
        0 個 = ''
    
    空方時反向 (3 個都變高)
    """
    if direction == '多方':
        conds = [
            curr_ohlc.high < prev_ohlc.high,
            curr_ohlc.low < prev_ohlc.low,
            curr_ohlc.close < prev_ohlc.close,
        ]
    elif direction == '空方':
        conds = [
            curr_ohlc.high > prev_ohlc.high,
            curr_ohlc.low > prev_ohlc.low,
            curr_ohlc.close > prev_ohlc.close,
        ]
    else:
        return ''
    
    n = sum(conds)
    if n == 3: return '強警訊'
    if n == 2: return '中警訊'
    if n == 1: return '弱警訊'
    return ''


def strategy_zones(gate: ThreeGate, current_close: float, direction: str) -> dict:
    """
    根據三關價 + 方向, 產出策略區間分析
    
    你的 M-B1 策略:
    - 核心安全區: M ~ B1
    - 短期擴大: S1 ~ M ~ B1
    - 避開: B2 以上、S2 以下
    - B3/S3 極限位
    """
    C = current_close
    
    # 判斷收盤在哪個區間
    if C > gate.B2:
        zone = "B2 以上 (強多方，不追多)"
        risk = "high"
    elif C > gate.B1:
        zone = "B1 ~ B2 (警戒區，短空回檔)"
        risk = "medium"
    elif C > gate.M:
        zone = "M ~ B1 (核心安全區，多方主戰場)"
        risk = "safe"
    elif C > gate.S1:
        zone = "S1 ~ M (短期擴大區，短空為主)"
        risk = "medium"
    elif C > gate.S2:
        zone = "S2 ~ S1 (警戒區，破 S2 清空多單)"
        risk = "high"
    else:
        zone = "S2 以下 (恐慌區，不做多)"
        risk = "extreme"
    
    # 距各關卡距離
    distances = {
        'to_B3': gate.B3 - C,
        'to_B2': gate.B2 - C,
        'to_B1': gate.B1 - C,
        'to_M': gate.M - C,
        'to_S1': gate.S1 - C,
        'to_S2': gate.S2 - C,
        'to_S3': gate.S3 - C,
    }
    
    return {
        'current_close': C,
        'zone': zone,
        'risk_level': risk,
        'direction': direction,
        'distances': distances,
        'main_battle_range': (gate.M, gate.B1) if direction == '多方' else (gate.S1, gate.M),
    }
