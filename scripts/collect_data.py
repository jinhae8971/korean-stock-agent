"""
collect_data.py — 국내외 증시 데이터 수집 및 기술적 지표 계산

수집 항목:
  - KOSPI, KOSDAQ 지수 (yfinance)
  - 주요 종목: 삼성전자, SK하이닉스, LG에너지솔루션, NAVER, 카카오, POSCO홀딩스 등
  - USD/KRW 환율, 미국 10년물 국채금리
  - 나스닥, S&P500, 엔비디아

기술적 지표 (KOSPI 기준):
  - RSI(14), MACD(12,26,9), 볼린저밴드(20,2)
  - 이동평균: 5일, 20일, 60일
  - 거래량 변화율 (5일 평균 대비)
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ─── 종목 매핑 ───────────────────────────────────────────────────────────────
TICKERS = {
    # 지수
    "kospi":  "^KS11",
    "kosdaq": "^KQ11",
    "nasdaq": "^IXIC",
    "sp500":  "^GSPC",
    # 환율·금리
    "usdkrw": "KRW=X",
    "us10y":  "^TNX",
    # 국내 주요 종목
    "samsung":   "005930.KS",   # 삼성전자
    "skhynix":   "000660.KS",   # SK하이닉스
    "lges":      "373220.KS",   # LG에너지솔루션
    "naver":     "035420.KS",   # NAVER
    "kakao":     "035720.KS",   # 카카오
    "posco":     "005490.KS",   # POSCO홀딩스
    "hyundai":   "005380.KS",   # 현대차
    "celltrion": "068270.KS",   # 셀트리온
    # 미국 반도체
    "nvidia":    "NVDA",
    "tsmc":      "TSM",
}

STOCK_NAMES = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "373220.KS": "LG에너지솔루션",
    "035420.KS": "NAVER",
    "035720.KS": "카카오",
    "005490.KS": "POSCO홀딩스",
    "005380.KS": "현대차",
    "068270.KS": "셀트리온",
    "NVDA":      "엔비디아",
    "TSM":       "TSMC",
}


# ─── 기술적 지표 계산 ─────────────────────────────────────────────────────────

def calculate_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not np.isnan(val) else 50.0


def calculate_macd(series: pd.Series) -> Dict:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return {
        "macd":      round(float(macd.iloc[-1]), 2),
        "signal":    round(float(signal.iloc[-1]), 2),
        "histogram": round(float(hist.iloc[-1]), 2),
    }


def calculate_bollinger(series: pd.Series, window: int = 20, num_std: int = 2) -> Dict:
    ma = series.rolling(window).mean()
    std = series.rolling(window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    current = series.iloc[-1]
    band_range = float(upper.iloc[-1] - lower.iloc[-1])
    position = (float(current - lower.iloc[-1]) / band_range) if band_range > 0 else 0.5
    return {
        "upper":    round(float(upper.iloc[-1]), 2),
        "middle":   round(float(ma.iloc[-1]), 2),
        "lower":    round(float(lower.iloc[-1]), 2),
        "position": round(position, 4),   # 0=하단, 1=상단
    }


def calculate_moving_averages(series: pd.Series) -> Dict:
    current = float(series.iloc[-1])
    result = {}
    for period in [5, 20, 60]:
        if len(series) >= period:
            ma = float(series.rolling(period).mean().iloc[-1])
            result[f"ma{period}"] = round(ma, 2)
            result[f"ma{period}_diff_pct"] = round((current - ma) / ma * 100, 2)
    return result


# ─── 단일 종목 데이터 수집 ─────────────────────────────────────────────────────

def fetch_ticker(symbol: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            logger.warning(f"{symbol}: 데이터 없음")
            return None
        return df
    except Exception as e:
        logger.error(f"{symbol} 수집 실패: {e}")
        return None


def get_latest_info(df: pd.DataFrame) -> Dict:
    """종가·등락률·거래량 추출"""
    if df is None or df.empty:
        return {}
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    close = float(last["Close"])
    prev_close = float(prev["Close"])
    change = close - prev_close
    change_pct = (change / prev_close * 100) if prev_close != 0 else 0.0
    vol = float(last["Volume"]) if "Volume" in last else 0
    avg_vol5 = float(df["Volume"].rolling(5).mean().iloc[-1]) if "Volume" in df.columns else 0
    vol_change_pct = ((vol - avg_vol5) / avg_vol5 * 100) if avg_vol5 > 0 else 0.0
    return {
        "close":           round(close, 2),
        "change":          round(change, 2),
        "change_pct":      round(change_pct, 2),
        "volume":          int(vol),
        "volume_change_pct": round(vol_change_pct, 2),
    }


# ─── 메인 수집 함수 ───────────────────────────────────────────────────────────

def collect_market_data() -> Dict:
    logger.info("시장 데이터 수집 시작...")
    result: Dict = {}

    # 1) 지수
    for key in ["kospi", "kosdaq", "nasdaq", "sp500"]:
        df = fetch_ticker(TICKERS[key])
        result[key] = get_latest_info(df) or {"close": 0, "change_pct": 0}
        if key == "kospi" and df is not None and len(df) >= 26:
            # 기술적 지표 계산 (KOSPI 기준)
            close_series = df["Close"]
            bb = calculate_bollinger(close_series)
            macd_data = calculate_macd(close_series)
            mas = calculate_moving_averages(close_series)
            result["technical_indicators"] = {
                "rsi": calculate_rsi(close_series),
                **macd_data,
                "bb_upper":   bb["upper"],
                "bb_middle":  bb["middle"],
                "bb_lower":   bb["lower"],
                "bb_position": bb["position"],
                **mas,
            }

    # 2) 환율·금리
    for key in ["usdkrw", "us10y"]:
        df = fetch_ticker(TICKERS[key], period="1mo")
        info = get_latest_info(df)
        result[key] = info.get("close", 0)

    # 3) 주요 종목
    top_stocks = []
    stock_symbols = {
        "samsung": "005930.KS", "skhynix": "000660.KS",
        "lges": "373220.KS",    "naver": "035420.KS",
        "kakao": "035720.KS",   "posco": "005490.KS",
        "hyundai": "005380.KS", "celltrion": "068270.KS",
        "nvidia": "NVDA",       "tsmc": "TSM",
    }
    for _, symbol in stock_symbols.items():
        df = fetch_ticker(symbol, period="1mo")
        if df is not None:
            info = get_latest_info(df)
            info["ticker"] = symbol
            info["name"] = STOCK_NAMES.get(symbol, symbol)
            # 간단 밸류에이션 (yfinance fast_info)
            try:
                t = yf.Ticker(symbol)
                fi = t.fast_info
                info["per"] = round(float(fi.get("trailingPE", 0) or 0), 1)
                info["pbr"] = round(float(fi.get("priceToBook", 0) or 0), 2)
            except Exception:
                info["per"] = None
                info["pbr"] = None
            top_stocks.append(info)
    result["top_stocks"] = top_stocks

    # 4) 수급 정보 (시뮬레이션 — 실제 KRX API 연동 시 교체)
    # 실제 배포 시 FinanceDataReader의 KRX 데이터 또는 KRX 데이터포털 API로 교체
    result["foreigners_net"] = _estimate_foreign_net(result.get("kospi", {}))
    result["institutions_net"] = _estimate_institution_net(result.get("kospi", {}))

    # 5) 최근 24시간 글로벌 뉴스 수집 [NEW]
    logger.info("뉴스 데이터 수집 중...")
    try:
        from scripts.collect_news import collect_news
        result["news"] = collect_news(hours=24)
        logger.info(f"뉴스 수집 완료: {result['news'].get('total_count', 0)}건")
    except Exception as e:
        logger.warning(f"뉴스 수집 실패 (파이프라인 계속 진행): {e}")
        result["news"] = {
            "international": [], "economic": [], "technology": [], "korean": [],
            "collected_at": datetime.now().isoformat(),
            "total_count": 0,
            "collection_errors": [str(e)],
        }

    result["collected_at"] = datetime.now().isoformat()
    logger.info("데이터 수집 완료")
    return result


def _estimate_foreign_net(kospi_info: Dict) -> float:
    """
    외국인 순매수 추정 (실제 KRX 데이터 대신 임시 계산값)
    실제 운영 시 FinanceDataReader.DataReader('KRX/전체/외국인', ...) 으로 교체
    """
    change = kospi_info.get("change_pct", 0)
    vol_change = kospi_info.get("volume_change_pct", 0)
    # 외국인은 지수 상승 + 거래량 증가 시 매수 경향
    estimate = change * 800 + vol_change * 50
    return round(estimate, 0)


def _estimate_institution_net(kospi_info: Dict) -> float:
    change = kospi_info.get("change_pct", 0)
    estimate = -change * 400   # 기관은 역추세 경향 반영
    return round(estimate, 0)


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = collect_market_data()
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
