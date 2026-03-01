"""
run_pipeline.py — 전체 파이프라인 진입점

실행 순서:
  1. 환경 설정 및 로깅 초기화
  2. 시장 데이터 수집 (collect_data.py)
  3. 백테스트 (전일 예측 vs 실제, Moderator 선정)
  4. 4인 에이전트 토론 (Phase 1 → Phase 2)
  5. Moderator 최종 판단 (Phase 3)
  6. 결과 저장 (docs/data/daily_report.json, data/history/)
  7. Telegram 알림 발송 (선택)
"""
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

# 프로젝트 루트를 파이썬 경로에 추가
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import anthropic

from agents import QuantAgent, MacroAgent, SectorAgent, ValueAgent
from orchestrator import DebateEngine, Moderator, Backtester
from scripts.collect_data import collect_market_data

# ─── 환경 설정 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
DATA_DIR   = ROOT / "data"
DOCS_DIR   = ROOT / "docs" / "data"
REPORT_JSON = DOCS_DIR / "daily_report.json"


# ─── 설정 로드 ────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = {
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "telegram_token":    os.environ.get("TELEGRAM_TOKEN", ""),
        "telegram_chat_id":  os.environ.get("TELEGRAM_CHAT_ID", ""),
    }
    config_path = ROOT / "config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if not cfg.get(k):
                    cfg[k] = v
    if not cfg["anthropic_api_key"]:
        raise ValueError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    return cfg


# ─── Telegram 알림 ────────────────────────────────────────────────────────────

def send_telegram(verdict: dict, date_str: str, token: str, chat_id: str):
    try:
        import requests
        stance_emoji = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(
            verdict.get("final_stance", "HOLD"), "⚪"
        )
        weather = verdict.get("investment_weather_icon", "⛅")
        msg = (
            f"📊 <b>Korean Stock Agent — {date_str}</b>\n\n"
            f"{weather} 투자 기온: <b>{verdict.get('investment_weather_kr', '중립')}</b>\n"
            f"{stance_emoji} 최종 판단: <b>{verdict.get('final_stance', 'HOLD')}</b> "
            f"(확신도 {verdict.get('confidence_score', 50)}%)\n\n"
            f"📌 <b>요약</b>\n{verdict.get('summary', '')[:300]}\n\n"
            f"🏭 주목 섹터: {', '.join(verdict.get('top_sectors', []))}\n"
            f"⚠️ 리스크: {', '.join(verdict.get('risk_factors', []))}\n\n"
            f"📎 대시보드: https://jinhae8971.github.io/korean-stock-agent/"
        )
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=20)
        logger.info("Telegram 알림 발송 완료")
    except Exception as e:
        logger.warning(f"Telegram 발송 실패 (무시): {e}")


# ─── 메인 파이프라인 ──────────────────────────────────────────────────────────

def main():
    today_str = date.today().strftime("%Y-%m-%d")
    logger.info(f"===== Korean Stock Agent 파이프라인 시작 [{today_str}] =====")

    # 1) 설정 로드
    cfg = load_config()
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])

    # 2) 시장 데이터 수집
    logger.info("[Step 1] 시장 데이터 수집 중...")
    try:
        market_data = collect_market_data()
    except Exception as e:
        logger.error(f"데이터 수집 실패: {e}")
        raise

    # 3) 백테스트 + Moderator 선정
    logger.info("[Step 2] 백테스트 실행 중...")
    backtester = Backtester(data_dir=str(DATA_DIR))
    kospi_change = market_data.get("kospi", {}).get("change_pct", 0.0)
    backtest_result = backtester.run(kospi_change)
    today_moderator = backtest_result.get("today_moderator", "중재자")
    logger.info(f"오늘의 Moderator: {today_moderator}")

    # 4) 에이전트 초기화
    agents = [
        QuantAgent(client, MODEL),
        MacroAgent(client, MODEL),
        SectorAgent(client, MODEL),
        ValueAgent(client, MODEL),
    ]

    # 5) 토론 (Phase 1 + Phase 2)
    logger.info("[Step 3] 에이전트 토론 진행 중...")
    engine = DebateEngine(agents)
    debate_result = engine.run(market_data)

    # 6) Moderator 최종 판단 (Phase 3)
    logger.info("[Step 4] Moderator 최종 판단 중...")
    moderator = Moderator(client, MODEL, today_moderator_agent=today_moderator)
    verdict = moderator.synthesize(
        reports=debate_result["phase1_reports"],
        critiques=debate_result["phase2_critiques"],
        market_data=market_data,
    )

    # 7) 최종 보고서 조립
    report = {
        "date": today_str,
        "generated_at": market_data.get("collected_at", today_str),
        "market_data": market_data,
        "debate": {
            "moderator_agent": today_moderator,
            "phase1_reports": debate_result["phase1_reports"],
            "phase2_critiques": debate_result["phase2_critiques"],
        },
        "verdict": verdict,
        "backtest": backtest_result,
    }

    # 8) 저장
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"보고서 저장: {REPORT_JSON}")

    # 9) 히스토리 아카이브
    backtester.archive_report(report, today_str)

    # 10) Telegram 알림
    if cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
        send_telegram(verdict, today_str, cfg["telegram_token"], cfg["telegram_chat_id"])

    logger.info("===== 파이프라인 완료 =====")
    logger.info(f"최종 판단: {verdict.get('final_stance')} (확신도 {verdict.get('confidence_score')}%)")
    return report


if __name__ == "__main__":
    main()
