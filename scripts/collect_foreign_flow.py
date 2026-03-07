"""
KOSPI 외국인 수급 모니터링
- 평일 17:00 KST 실행 (장 마감 후)
- 당일 외국인 순매수/매도 수집
- 매수 전환 여부 판단
- docs/data/foreign_flow.json 으로 저장
"""
import json, os, sys, re, datetime as dt
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DATA = BASE_DIR / "docs" / "data"
HISTORY_DIR = BASE_DIR / "data" / "history_flow"

DOCS_DATA.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


# ─── 데이터 수집 ──────────────────────────────────────────────────────────

def _parse_naver_value(s: str) -> int:
    """네이버 API 값 파싱: '+29,488' / '-19,418' / '0' → int"""
    if not s:
        return 0
    s = str(s).replace(",", "").replace("+", "").strip()
    try:
        return int(s)
    except ValueError:
        return 0


def _get_business_days(end_date: dt.date, count: int = 10) -> list:
    """최근 N 영업일 날짜 리스트 반환 (최신→과거 순)"""
    days = []
    d = end_date
    while len(days) < count:
        if d.weekday() < 5:  # 월~금
            days.append(d)
        d -= dt.timedelta(days=1)
    return days


def fetch_naver_mobile_trend(end_date: dt.date) -> dict:
    """
    네이버 모바일 증권 API로 투자자별 매매동향 수집 (KOSPI)
    https://m.stock.naver.com/api/index/KOSPI/trend?bizdate=YYYYMMDD
    최근 10영업일 데이터를 개별 요청으로 수집
    """
    url = "https://m.stock.naver.com/api/index/KOSPI/trend"
    biz_days = _get_business_days(end_date, 10)
    rows = []

    for d in biz_days:
        bizdate = d.strftime("%Y%m%d")
        try:
            resp = requests.get(
                url, params={"bizdate": bizdate},
                headers=HEADERS, timeout=10,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            actual_date = data.get("bizdate", bizdate)
            foreign = _parse_naver_value(data.get("foreignValue", "0"))
            institution = _parse_naver_value(data.get("institutionalValue", "0"))
            individual = _parse_naver_value(data.get("personalValue", "0"))

            # 주말/공휴일은 0값 → 건너뛰기
            if foreign == 0 and institution == 0 and individual == 0:
                continue

            rows.append({
                "date": f"{actual_date[:4]}.{actual_date[4:6]}.{actual_date[6:8]}",
                "foreign": foreign,
                "institution": institution,
                "individual": individual,
            })
        except Exception as e:
            print(f"  [WARN] Naver mobile trend {bizdate} failed: {e}")
            continue

    return {"source": "naver_mobile", "rows": rows}


def fetch_naver_foreign_detail() -> dict:
    """
    네이버 금융 외국인 순매수 상위/하위 종목
    """
    result = {"buy_top": [], "sell_top": []}
    for buy_sell in ["buy", "sell"]:
        url = "https://finance.naver.com/sise/sise_deal_rank.naver"
        params = {
            "sosok": "01",  # 코스피
            "investor_gubun": "9000",  # 외국인
            "type": buy_sell,
        }
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            resp.encoding = "euc-kr"
            html = resp.text

            stocks = []
            matches = re.findall(
                r'<a\s+href="/item/main\.naver\?code=\d+"[^>]*>(.*?)</a>.*?'
                r'<td[^>]*>([\d,]+)</td>', html, re.DOTALL,
            )
            for name, amount in matches[:10]:
                name = re.sub(r'<[^>]+>', '', name).strip()
                amount = int(amount.replace(',', ''))
                if name:
                    stocks.append({"name": name, "amount": amount})

            result[f"{buy_sell}_top"] = stocks[:10]
        except Exception as e:
            print(f"  [WARN] Foreign {buy_sell} detail failed: {e}")

    return result


# ─── 분석 ──────────────────────────────────────────────────────────────────

def analyze_flow(rows: list) -> dict:
    """
    외국인 수급 분석
    - 당일 순매수/순매도 판단
    - 매수 전환 여부 (전일 대비)
    - 연속 매수/매도일 계산
    """
    if not rows:
        return {
            "status": "NO_DATA",
            "message": "수급 데이터를 수집하지 못했습니다.",
            "signal": "NEUTRAL",
        }

    today = rows[0]
    today_foreign = today.get("foreign", 0)

    # 매수/매도 판단
    if today_foreign > 0:
        direction = "NET_BUY"
        direction_kr = "순매수"
    elif today_foreign < 0:
        direction = "NET_SELL"
        direction_kr = "순매도"
    else:
        direction = "FLAT"
        direction_kr = "보합"

    # 전일 대비 전환 여부
    turned_to_buy = False
    turned_to_sell = False
    if len(rows) >= 2:
        yesterday_foreign = rows[1].get("foreign", 0)
        if yesterday_foreign <= 0 and today_foreign > 0:
            turned_to_buy = True
        elif yesterday_foreign >= 0 and today_foreign < 0:
            turned_to_sell = True

    # 연속 매수/매도일 계산
    consecutive_buy = 0
    consecutive_sell = 0
    for r in rows:
        f = r.get("foreign", 0)
        if f > 0:
            consecutive_buy += 1
        else:
            break
    for r in rows:
        f = r.get("foreign", 0)
        if f < 0:
            consecutive_sell += 1
        else:
            break

    # 5일 누적
    five_day_total = sum(r.get("foreign", 0) for r in rows[:5])

    # 시그널 판단
    signal = "NEUTRAL"
    signal_kr = "중립"
    if turned_to_buy:
        signal = "BUY_TURN"
        signal_kr = "매수 전환"
    elif turned_to_sell:
        signal = "SELL_TURN"
        signal_kr = "매도 전환"
    elif consecutive_buy >= 3:
        signal = "STRONG_BUY"
        signal_kr = f"{consecutive_buy}일 연속 순매수"
    elif consecutive_sell >= 3:
        signal = "STRONG_SELL"
        signal_kr = f"{consecutive_sell}일 연속 순매도"
    elif direction == "NET_BUY":
        signal = "BUY"
        signal_kr = "순매수"
    elif direction == "NET_SELL":
        signal = "SELL"
        signal_kr = "순매도"

    # 메시지 생성
    amount_str = f"{abs(today_foreign):,}"
    if direction == "NET_BUY":
        message = f"외국인 {amount_str}억원 순매수"
    elif direction == "NET_SELL":
        message = f"외국인 {amount_str}억원 순매도"
    else:
        message = "외국인 매매 보합"

    if turned_to_buy:
        message += " (매수 전환!)"
    elif turned_to_sell:
        message += " (매도 전환!)"

    return {
        "status": "OK",
        "date": today.get("date", ""),
        "today_foreign": today_foreign,
        "today_institution": today.get("institution", 0),
        "today_individual": today.get("individual", 0),
        "direction": direction,
        "direction_kr": direction_kr,
        "turned_to_buy": turned_to_buy,
        "turned_to_sell": turned_to_sell,
        "consecutive_buy_days": consecutive_buy,
        "consecutive_sell_days": consecutive_sell,
        "five_day_total": five_day_total,
        "signal": signal,
        "signal_kr": signal_kr,
        "message": message,
    }


# ─── 텔레그램 알림 ─────────────────────────────────────────────────────────

def send_telegram(analysis: dict, rows: list, detail: dict):
    """텔레그램으로 외국인 수급 알림 전송"""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [SKIP] Telegram credentials not set")
        return

    signal = analysis.get("signal", "")
    emoji_map = {
        "BUY_TURN": "🔵🔄",
        "SELL_TURN": "🔴🔄",
        "STRONG_BUY": "🔵🔥",
        "STRONG_SELL": "🔴🔥",
        "BUY": "🔵",
        "SELL": "🔴",
        "NEUTRAL": "⚪",
    }
    emoji = emoji_map.get(signal, "⚪")

    lines = [
        f"{emoji} <b>KOSPI 외국인 수급 리포트</b>",
        f"",
        f"📅 {analysis.get('date', 'N/A')}",
        f"",
        f"<b>{analysis.get('message', '')}</b>",
        f"",
        f"👤 개인: {analysis.get('today_individual', 0):+,}억원",
        f"🏦 기관: {analysis.get('today_institution', 0):+,}억원",
        f"🌐 외국인: {analysis.get('today_foreign', 0):+,}억원",
        f"",
        f"📊 시그널: <b>{analysis.get('signal_kr', '')}</b>",
    ]

    if analysis.get("consecutive_buy_days", 0) > 1:
        lines.append(f"🔥 {analysis['consecutive_buy_days']}일 연속 순매수")
    if analysis.get("consecutive_sell_days", 0) > 1:
        lines.append(f"🔥 {analysis['consecutive_sell_days']}일 연속 순매도")

    lines.append(f"📈 5일 누적: {analysis.get('five_day_total', 0):+,}억원")

    # 최근 5일 추이
    if rows:
        lines.append("")
        lines.append("📋 <b>최근 5일 추이</b>")
        for r in rows[:5]:
            f = r.get("foreign", 0)
            icon = "🔵" if f > 0 else "🔴" if f < 0 else "⚪"
            lines.append(f"  {r.get('date', '')} {icon} {f:+,}억원")

    # 외국인 순매수 상위
    buy_top = detail.get("buy_top", [])
    if buy_top:
        lines.append("")
        lines.append("🔵 <b>외국인 순매수 TOP 5</b>")
        for s in buy_top[:5]:
            lines.append(f"  · {s['name']} ({s['amount']:,}백만원)")

    msg = "\n".join(lines)

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        print("  [OK] Telegram notification sent")
    except Exception as e:
        print(f"  [WARN] Telegram send failed: {e}")


# ─── 메인 ──────────────────────────────────────────────────────────────────

def main():
    today = dt.date.today()
    today_str = today.strftime("%Y-%m-%d")
    print(f"=== KOSPI 외국인 수급 모니터링 ({today_str} 17:00 KST) ===")

    # 1) 데이터 수집 (Naver 모바일 API)
    print("\n[1] 투자자별 매매동향 수집 (Naver Mobile API)...")
    trend = fetch_naver_mobile_trend(today)
    rows = trend.get("rows", [])

    print(f"  -> {len(rows)}일치 데이터 수집 (source: {trend.get('source', 'unknown')})")
    for r in rows[:5]:
        print(f"     {r.get('date')} | 외국인: {r.get('foreign', 0):+,} | 기관: {r.get('institution', 0):+,}")

    # 2) 외국인 순매수/매도 상위 종목
    print("\n[2] 외국인 매매 상위 종목 수집...")
    detail = fetch_naver_foreign_detail()
    print(f"  -> 순매수 TOP {len(detail.get('buy_top', []))}종목, 순매도 TOP {len(detail.get('sell_top', []))}종목")

    # 3) 분석
    print("\n[3] 수급 분석...")
    analysis = analyze_flow(rows)
    print(f"  -> 시그널: {analysis.get('signal', 'N/A')} ({analysis.get('signal_kr', '')})")
    print(f"  -> {analysis.get('message', '')}")

    # 4) 결과 저장
    result = {
        "date": today_str,
        "collected_at": dt.datetime.now().isoformat(),
        "source": trend.get("source", "unknown"),
        "analysis": analysis,
        "daily_trend": rows[:10],
        "foreign_detail": detail,
    }

    # docs/data/foreign_flow.json (대시보드용)
    out_path = DOCS_DATA / "foreign_flow.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[4] Saved: {out_path}")

    # data/history_flow/YYYY-MM-DD.json (아카이브)
    hist_path = HISTORY_DIR / f"{today_str}.json"
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"    Saved: {hist_path}")

    # 5) 텔레그램 알림
    print("\n[5] Telegram 알림 전송...")
    send_telegram(analysis, rows, detail)

    print(f"\n=== 완료 ===")
    return result


if __name__ == "__main__":
    main()
