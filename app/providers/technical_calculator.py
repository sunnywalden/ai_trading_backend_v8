"""技术指标计算引擎"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple
import pandas_ta as ta


class TechnicalIndicatorCalculator:
    """技术指标计算器"""
    
    @staticmethod
    def calculate_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
        """计算移动平均线"""
        df['MA_5'] = df['Close'].rolling(window=5).mean()
        df['MA_10'] = df['Close'].rolling(window=10).mean()
        df['MA_20'] = df['Close'].rolling(window=20).mean()
        df['MA_50'] = df['Close'].rolling(window=50).mean()
        df['MA_200'] = df['Close'].rolling(window=200).mean()
        return df
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算RSI指标"""
        df['RSI_14'] = ta.rsi(df['Close'], length=period)
        return df
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame) -> pd.DataFrame:
        """计算MACD指标"""
        macd = ta.macd(df['Close'])
        if macd is not None:
            df['MACD'] = macd['MACD_12_26_9']
            df['MACD_signal'] = macd['MACDs_12_26_9']
            df['MACD_histogram'] = macd['MACDh_12_26_9']
        return df
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """计算布林带"""
        bb = ta.bbands(df['Close'], length=period)
        if bb is not None:
            # pandas-ta 新版本列名格式: BBU_20_2.0_2.0
            # 尝试新格式,如果不存在则尝试旧格式
            cols = bb.columns.tolist()
            upper_col = next((c for c in cols if c.startswith(f'BBU_{period}')), None)
            middle_col = next((c for c in cols if c.startswith(f'BBM_{period}')), None)
            lower_col = next((c for c in cols if c.startswith(f'BBL_{period}')), None)
            
            if upper_col:
                df['BB_upper'] = bb[upper_col]
            if middle_col:
                df['BB_middle'] = bb[middle_col]
            if lower_col:
                df['BB_lower'] = bb[lower_col]
        return df
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算ATR（平均真实波幅）"""
        df['ATR_14'] = ta.atr(df['High'], df['Low'], df['Close'], length=period)
        return df
    
    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.DataFrame:
        """计算OBV（能量潮）"""
        df['OBV'] = ta.obv(df['Close'], df['Volume'])
        return df
    
    @staticmethod
    def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标"""
        calc = TechnicalIndicatorCalculator
        
        df = calc.calculate_moving_averages(df)
        df = calc.calculate_rsi(df)
        df = calc.calculate_macd(df)
        df = calc.calculate_bollinger_bands(df)
        df = calc.calculate_atr(df)
        df = calc.calculate_obv(df)
        
        # 计算成交量均线
        df['Volume_SMA_20'] = df['Volume'].rolling(window=20).mean()
        
        return df
    
    @staticmethod
    def identify_trend(df: pd.DataFrame) -> Tuple[str, int]:
        """识别趋势方向和强度
        
        Returns:
            (trend_direction, trend_strength)
            trend_direction: BULLISH, BEARISH, SIDEWAYS
            trend_strength: 0-100
        """
        latest = df.iloc[-1]
        
        # 使用MA均线判断趋势
        ma_5 = latest.get('MA_5', 0)
        ma_20 = latest.get('MA_20', 0)
        ma_50 = latest.get('MA_50', 0)
        ma_200 = latest.get('MA_200', 0)
        current_price = latest['Close']
        
        # 金叉/死叉判断
        bullish_signals = 0
        bearish_signals = 0
        
        if ma_5 > ma_20:
            bullish_signals += 1
        else:
            bearish_signals += 1
            
        if ma_20 > ma_50:
            bullish_signals += 1
        else:
            bearish_signals += 1
            
        if ma_50 > ma_200:
            bullish_signals += 1
        else:
            bearish_signals += 1
            
        if current_price > ma_50:
            bullish_signals += 1
        else:
            bearish_signals += 1
        
        # 判断趋势
        if bullish_signals >= 3:
            direction = "BULLISH"
            strength = int((bullish_signals / 4) * 100)
        elif bearish_signals >= 3:
            direction = "BEARISH"
            strength = int((bearish_signals / 4) * 100)
        else:
            direction = "SIDEWAYS"
            strength = 50
        
        return direction, strength
    
    @staticmethod
    def identify_rsi_status(rsi_value: float) -> Tuple[str, str]:
        """识别RSI状态和信号
        
        Returns:
            (status, signal)
            status: OVERSOLD, NEUTRAL, OVERBOUGHT
            signal: BUY, HOLD, SELL
        """
        if rsi_value < 30:
            return "OVERSOLD", "BUY"
        elif rsi_value > 70:
            return "OVERBOUGHT", "SELL"
        else:
            return "NEUTRAL", "HOLD"
    
    @staticmethod
    def identify_macd_signal(df: pd.DataFrame) -> str:
        """识别MACD信号
        
        Returns:
            BULLISH_CROSSOVER, BEARISH_CROSSOVER, NEUTRAL
        """
        if len(df) < 2:
            return "NEUTRAL"
        
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        
        macd_current = latest.get('MACD', 0)
        signal_current = latest.get('MACD_signal', 0)
        macd_prev = previous.get('MACD', 0)
        signal_prev = previous.get('MACD_signal', 0)
        
        # 检测金叉/死叉
        if macd_prev <= signal_prev and macd_current > signal_current:
            return "BULLISH_CROSSOVER"
        elif macd_prev >= signal_prev and macd_current < signal_current:
            return "BEARISH_CROSSOVER"
        else:
            return "NEUTRAL"
    
    @staticmethod
    def identify_support_resistance(df: pd.DataFrame, n_levels: int = 3) -> Tuple[List[float], List[float]]:
        """识别支撑位和阻力位
        
        Returns:
            (support_levels, resistance_levels)
        """
        # 使用最近的高点和低点
        recent_data = df.tail(60)  # 最近60个交易日
        
        # 寻找局部极值
        highs = recent_data[recent_data['High'] == recent_data['High'].rolling(5, center=True).max()]['High']
        lows = recent_data[recent_data['Low'] == recent_data['Low'].rolling(5, center=True).min()]['Low']
        
        # 取最近的几个支撑和阻力位
        resistance_levels = sorted(highs.tail(n_levels).tolist(), reverse=True)
        support_levels = sorted(lows.tail(n_levels).tolist(), reverse=True)
        
        return support_levels, resistance_levels
    
    @staticmethod
    def calculate_bollinger_position(current_price: float, bb_upper: float, bb_middle: float, bb_lower: float) -> str:
        """计算价格在布林带中的位置"""
        if current_price >= bb_upper:
            return "ABOVE_UPPER"
        elif current_price >= bb_middle:
            return "MIDDLE_TO_UPPER"
        elif current_price >= bb_lower:
            return "LOWER_TO_MIDDLE"
        else:
            return "BELOW_LOWER"
