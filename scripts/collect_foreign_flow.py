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


_ETF_PREFIXES = (
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "SOL", "ACE",
    "KOSEF", "KINDEX", "TIMEFOLIO", "PLUS", "BNK", "WOORI", "RISE",
    "FOCUS", "MASTERL", "파워", "마이티", "히어로",
)


def _is_etf(name: str) -> bool:
    upper = name.upper()
    return any(upper.startswith(p.upper()) for p in _ETF_PREFIXES)


def fetch_naver_foreign_detail() -> dict:
    """
    네이버 금융 외국인 순매수/순매도 상위 종목
    한 페이지에 순매수(Table 0)·순매도(Table 1) 테이블이 모두 포함됨
    ETF는 제외
    """
    result = {"buy_top": [], "sell_top": []}
    url = "https://finance.naver.com/sise/sise_deal_rank.naver"
    params = {"sosok": "01", "investor_gubun": "9000"}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.encoding = "euc-kr"
        html = resp.text

        # 테이블별로 분리하여 파싱
        tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
        keys = ["buy_top", "sell_top"]

        for idx, table in enumerate(tables):
            if idx >= 2:
                break
            stocks = []
            matches = re.findall(
                r'<a\s+href="/item/main\.naver\?code=\d+"[^>]*>(.*?)</a>.*?'
                r'<td[^>]*>([\d,]+)</td>', table, re.DOTALL,
            )
            for name, amount in matches:
                name = re.sub(r'<[^>]+>', '', name).strip()
                amount = int(amount.replace(',', ''))
                if name and not _is_etf(name):
                    stocks.append({"name": name, "amount": amount})
            result[keys[idx]] = stocks[:10]

    except Exception as e:
        print(f"  [WARN] Foreign detail failed: {e}")

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


# ─── HTML 리포트 생성 ──────────────────────────────────────────────────────

def generate_html_report(result: dict) -> str:
    """실행 결과를 시각화한 HTML 리포트 생성"""
    a = result.get("analysis", {})
    rows = result.get("daily_trend", [])
    detail = result.get("foreign_detail", {})
    buy_top = detail.get("buy_top", [])[:5]
    sell_top = detail.get("sell_top", [])[:5]

    signal = a.get("signal", "NEUTRAL")
    signal_config = {
        "BUY_TURN":    {"color": "#1565C0", "bg": "#E3F2FD", "border": "#90CAF9", "icon": "🔵🔄", "label": "매수 전환"},
        "SELL_TURN":   {"color": "#C62828", "bg": "#FFEBEE", "border": "#EF9A9A", "icon": "🔴🔄", "label": "매도 전환"},
        "STRONG_BUY":  {"color": "#1565C0", "bg": "#E3F2FD", "border": "#90CAF9", "icon": "🔵🔥", "label": "강한 매수"},
        "STRONG_SELL": {"color": "#C62828", "bg": "#FFEBEE", "border": "#EF9A9A", "icon": "🔴🔥", "label": "강한 매도"},
        "BUY":         {"color": "#1565C0", "bg": "#E8F5E9", "border": "#A5D6A7", "icon": "🔵",   "label": "순매수"},
        "SELL":        {"color": "#C62828", "bg": "#FFF3E0", "border": "#FFCC80", "icon": "🔴",   "label": "순매도"},
        "NEUTRAL":     {"color": "#616161", "bg": "#F5F5F5", "border": "#E0E0E0", "icon": "⚪",   "label": "중립"},
    }
    sc = signal_config.get(signal, signal_config["NEUTRAL"])

    # 바 차트 데이터
    bar_rows_html = ""
    if rows:
        max_abs = max(abs(r.get("foreign", 0)) for r in rows[:7]) or 1
        for r in rows[:7]:
            f = r.get("foreign", 0)
            pct = abs(f) / max_abs * 100
            color = "#1565C0" if f >= 0 else "#C62828"
            sign = "+" if f > 0 else ""
            bar_rows_html += f"""
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
              <span style="width:80px;font-size:12px;color:#666;font-family:monospace">{r.get('date','')}</span>
              <div style="flex:1;display:flex;align-items:center;height:28px">
                {"<div style='flex:1'></div><div style='flex:1;display:flex;align-items:center'><div style=" + repr(f"background:{color};height:22px;border-radius:0 4px 4px 0;width:{pct/2}%;min-width:2px") + "></div><span style='font-size:12px;margin-left:6px;color:" + color + f";font-family:monospace;font-weight:600'>{sign}{f:,}</span></div>" if f >= 0 else "<div style='flex:1;display:flex;align-items:center;justify-content:flex-end'><span style='font-size:12px;margin-right:6px;color:" + color + f";font-family:monospace;font-weight:600'>{f:,}</span><div style=" + repr(f"background:{color};height:22px;border-radius:4px 0 0 4px;width:{pct/2}%;min-width:2px") + "></div></div><div style='flex:1'></div>"}
              </div>
            </div>"""

    # 투자자별 카드
    investors = [
        ("🌐 외국인", a.get("today_foreign", 0), "#1565C0"),
        ("🏦 기관",   a.get("today_institution", 0), "#7B1FA2"),
        ("👤 개인",   a.get("today_individual", 0), "#E65100"),
    ]
    investor_cards = ""
    for label, val, accent in investors:
        val_color = "#2E7D32" if val > 0 else "#C62828" if val < 0 else "#666"
        sign = "+" if val > 0 else ""
        arrow = "▲ 순매수" if val > 0 else "▼ 순매도" if val < 0 else "— 보합"
        investor_cards += f"""
        <div style="background:#F5F7FA;border-radius:10px;padding:16px;text-align:center;border:1px solid #E0E0E0">
          <div style="font-size:13px;color:#555;margin-bottom:6px">{label}</div>
          <div style="font-size:22px;font-weight:700;color:{val_color};font-family:monospace">{sign}{val:,}억</div>
          <div style="font-size:11px;color:{val_color};margin-top:4px">{arrow}</div>
        </div>"""

    # 순매수/매도 TOP 5 테이블
    def _stock_table(stocks, title, color):
        if not stocks:
            return ""
        rows_html = ""
        for i, s in enumerate(stocks):
            bg = "#F8F9FA" if i % 2 == 0 else "#FFF"
            rows_html += f"""
            <tr style="background:{bg}">
              <td style="padding:6px 10px;font-size:13px;color:#333">{i+1}</td>
              <td style="padding:6px 10px;font-size:13px;color:#333">{s.get('name','')}</td>
              <td style="padding:6px 10px;font-size:13px;color:{color};font-family:monospace;text-align:right;font-weight:600">{s.get('amount',0):,}</td>
            </tr>"""
        return f"""
        <div style="flex:1">
          <div style="font-size:13px;font-weight:700;color:{color};margin-bottom:8px">{title}</div>
          <table style="width:100%;border-collapse:collapse;border:1px solid #E0E0E0;border-radius:8px;overflow:hidden">
            <thead><tr style="background:#F0F0F0">
              <th style="padding:6px 10px;font-size:11px;color:#666;text-align:left;width:30px">#</th>
              <th style="padding:6px 10px;font-size:11px;color:#666;text-align:left">종목</th>
              <th style="padding:6px 10px;font-size:11px;color:#666;text-align:right">금액(백만원)</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>"""

    buy_table = _stock_table(buy_top, "🔵 외국인 순매수 TOP 5", "#1565C0")
    sell_table = _stock_table(sell_top, "🔴 외국인 순매도 TOP 5", "#C62828")

    five_day = a.get("five_day_total", 0)
    five_color = "#2E7D32" if five_day > 0 else "#C62828"
    five_sign = "+" if five_day > 0 else ""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KOSPI 외국인 수급 리포트 — {result.get('date','')}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; font-family:'Noto Sans KR',sans-serif; }}
  body {{ background:#FFFFFF; color:#212121; }}
</style>
</head>
<body>
<div style="max-width:720px;margin:0 auto;padding:24px 16px">

  <!-- 헤더 -->
  <div style="text-align:center;margin-bottom:28px">
    <div style="font-size:14px;color:#999;letter-spacing:2px;margin-bottom:6px">KOSPI FOREIGN INVESTOR FLOW</div>
    <h1 style="font-size:24px;font-weight:900;color:#1A1A2E;margin-bottom:4px">🌐 외국인 수급 리포트</h1>
    <div style="font-size:13px;color:#888">📅 {a.get('date', result.get('date',''))} 기준 · {result.get('source','').replace('_',' ').upper()}</div>
  </div>

  <!-- 시그널 배너 -->
  <div style="background:{sc['bg']};border:2px solid {sc['border']};border-radius:14px;padding:20px 24px;margin-bottom:24px;display:flex;align-items:center;gap:16px">
    <span style="font-size:42px">{sc['icon']}</span>
    <div>
      <div style="font-size:20px;font-weight:800;color:{sc['color']}">{a.get('signal_kr', sc['label'])}</div>
      <div style="font-size:14px;color:#555;margin-top:4px">{a.get('message','')}</div>
    </div>
  </div>

  <!-- 투자자별 수급 -->
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px">
    {investor_cards}
  </div>

  <!-- 지표 카드 -->
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:28px">
    <div style="background:#F5F7FA;border-radius:10px;padding:12px;text-align:center;border:1px solid #E0E0E0">
      <div style="font-size:11px;color:#888">연속 매수</div>
      <div style="font-size:18px;font-weight:700;color:#1565C0;font-family:monospace">{a.get('consecutive_buy_days',0)}일</div>
    </div>
    <div style="background:#F5F7FA;border-radius:10px;padding:12px;text-align:center;border:1px solid #E0E0E0">
      <div style="font-size:11px;color:#888">연속 매도</div>
      <div style="font-size:18px;font-weight:700;color:#C62828;font-family:monospace">{a.get('consecutive_sell_days',0)}일</div>
    </div>
    <div style="background:#F5F7FA;border-radius:10px;padding:12px;text-align:center;border:1px solid #E0E0E0">
      <div style="font-size:11px;color:#888">5일 누적</div>
      <div style="font-size:18px;font-weight:700;color:{five_color};font-family:monospace">{five_sign}{five_day:,}억</div>
    </div>
  </div>

  <!-- 수급 추이 바 차트 -->
  <div style="background:#FFFFFF;border:1px solid #E0E0E0;border-radius:12px;padding:20px;margin-bottom:24px">
    <div style="font-size:14px;font-weight:700;color:#333;margin-bottom:14px">📊 최근 외국인 수급 추이 <span style="font-size:11px;color:#999;font-weight:400">(단위: 억원)</span></div>
    {bar_rows_html}
  </div>

  <!-- 순매수/매도 TOP 5 -->
  <div style="display:flex;gap:16px;margin-bottom:24px">
    {buy_table}
    {sell_table}
  </div>

  <!-- 푸터 -->
  <div style="text-align:center;padding:16px 0;border-top:1px solid #EEE;margin-top:12px">
    <div style="font-size:11px;color:#AAA">Korean Stock Agent — KOSPI Foreign Flow Monitor</div>
    <div style="font-size:10px;color:#CCC;margin-top:4px">수집: {result.get('collected_at','')[:19]} · ⚠️ 본 데이터는 참고용이며 투자 결정의 책임은 투자자 본인에게 있습니다.</div>
  </div>

</div>
</body>
</html>"""

    return html


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

    # 5) HTML 리포트 생성
    print("\n[5] HTML 리포트 생성...")
    html = generate_html_report(result)
    html_path = DOCS_DATA / "foreign_flow_report.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    Saved: {html_path}")

    # 6) 텔레그램 알림
    print("\n[6] Telegram 알림 전송...")
    send_telegram(analysis, rows, detail)

    print(f"\n=== 완료 ===")
    return result


if __name__ == "__main__":
    main()
