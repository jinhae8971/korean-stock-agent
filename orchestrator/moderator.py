"""
Moderator — Phase 3: 에이전트 토론 전체를 종합해 최종 투자 판단 도출

- 4인의 stance + confidence_score를 가중 집계
- 최종 Buy/Hold/Sell 결정
- 투자 기온(weather) 산출: sunny / partly_cloudy / cloudy / rainy
- 상위 섹터, 리스크 요인, 실행 액션 제시
"""
import json
import logging
from typing import List, Dict

import anthropic

logger = logging.getLogger(__name__)

STANCE_SCORE = {"BUY": 1, "HOLD": 0, "SELL": -1}

WEATHER_MAP = {
    "strong_buy": ("☀️", "강세 — 맑음", "sunny"),
    "buy": ("🌤️", "매수 우위 — 구름 조금", "partly_sunny"),
    "hold": ("⛅", "중립 — 흐림", "cloudy"),
    "sell": ("🌧️", "매도 우위 — 비", "rainy"),
    "strong_sell": ("⛈️", "강세 하락 — 폭풍", "stormy"),
}

SYSTEM_PROMPT = """당신은 투자 토론의 중재자(Moderator)입니다.
4명의 전문 에이전트(퀀트, 매크로, 섹터매니저, 가치투자자)의 분석과 토론을 종합하여
최종 투자 판단을 내려야 합니다.

[역할]
- 각 에이전트의 논리적 강점과 약점을 객관적으로 평가합니다.
- 단순 다수결이 아니라 논리의 질과 데이터의 신뢰성을 기준으로 판단합니다.
- 반드시 JSON 형식으로만 응답합니다."""


class Moderator:

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str = "claude-sonnet-4-5-20250929",
        today_moderator_agent: str = "중재자",
    ):
        self.client = client
        self.model = model
        self.today_moderator_agent = today_moderator_agent

    # ─── 메인 ───────────────────────────────────────────────────────────────

    def synthesize(
        self,
        reports: List[Dict],
        critiques: List[Dict],
        market_data: dict,
    ) -> Dict:
        """Phase 3 최종 판단 수행"""

        # 1) 규칙 기반 가중 집계 (빠른 선행 판단)
        weighted_score, avg_confidence = self._weighted_vote(reports)
        rule_stance = self._score_to_stance(weighted_score)

        # 2) LLM 기반 종합 판단
        llm_result = self._llm_synthesis(reports, critiques, market_data, rule_stance)

        # 3) 투자 기온 산출
        final_stance = llm_result.get("final_stance", rule_stance)
        weather = self._determine_weather(final_stance, avg_confidence)

        return {
            "today_moderator_agent": self.today_moderator_agent,
            "final_stance": final_stance,
            "confidence_score": llm_result.get("confidence_score", int(avg_confidence)),
            "summary": llm_result.get("summary", "종합 판단 완료"),
            "investment_weather": weather[2],
            "investment_weather_icon": weather[0],
            "investment_weather_kr": weather[1],
            "top_sectors": llm_result.get("top_sectors", []),
            "risk_factors": llm_result.get("risk_factors", []),
            "action_items": llm_result.get("action_items", []),
            "stance_votes": {r["agent_name"]: r["stance"] for r in reports},
        }

    # ─── 내부 메서드 ────────────────────────────────────────────────────────

    def _weighted_vote(self, reports: List[Dict]):
        """confidence_score를 가중치로 사용한 stance 집계"""
        total_weight = 0
        weighted_sum = 0
        confidence_sum = 0
        for r in reports:
            w = r.get("confidence_score", 50)
            s = STANCE_SCORE.get(r.get("stance", "HOLD"), 0)
            weighted_sum += s * w
            total_weight += w
            confidence_sum += w
        if total_weight == 0:
            return 0, 50.0
        return weighted_sum / total_weight, confidence_sum / len(reports)

    def _score_to_stance(self, score: float) -> str:
        if score > 0.4:
            return "BUY"
        if score < -0.4:
            return "SELL"
        return "HOLD"

    def _determine_weather(self, stance: str, avg_conf: float) -> tuple:
        if stance == "BUY" and avg_conf >= 70:
            return WEATHER_MAP["strong_buy"]
        if stance == "BUY":
            return WEATHER_MAP["buy"]
        if stance == "SELL" and avg_conf >= 70:
            return WEATHER_MAP["strong_sell"]
        if stance == "SELL":
            return WEATHER_MAP["sell"]
        return WEATHER_MAP["hold"]

    def _llm_synthesis(
        self,
        reports: List[Dict],
        critiques: List[Dict],
        market_data: dict,
        rule_stance: str,
    ) -> Dict:
        debate_text = self._format_debate(reports, critiques)
        kospi = market_data.get("kospi", {})

        prompt = f"""아래는 4명의 에이전트 토론 내용입니다. 중재자로서 최종 판단을 내려주세요.

=== 오늘의 시장 ===
KOSPI: {kospi.get('close','N/A')} ({kospi.get('change_pct','N/A'):+.2f}%)
USD/KRW: {market_data.get('usdkrw','N/A')}

=== 에이전트 토론 ===
{debate_text}

=== 규칙 기반 선행 판단 ===
가중 투표 결과: {rule_stance}

반드시 아래 JSON 형식으로만 응답:
{{
  "final_stance": "BUY",
  "confidence_score": 68,
  "summary": "핵심 판단 근거 요약 (200자 이상, 한국어)",
  "top_sectors": ["반도체", "조선"],
  "risk_factors": ["환율 변동성", "Fed 불확실성"],
  "action_items": ["삼성전자 비중 점검", "이차전지 ETF 관망"]
}}

final_stance: BUY / HOLD / SELL
confidence_score: 0~100
top_sectors: 오늘 주목할 상위 2~3개 섹터
risk_factors: 핵심 리스크 2~3개
action_items: 투자자 실행 항목 2~3개"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            import re
            # 코드블록 제거
            text = re.sub(r"```(?:json)?\s*", "", text)
            text = re.sub(r"```\s*", "", text)
            text = text.strip()
            # JSON 객체 추출 (응답에 설명문이 섞여있어도 안전하게 파싱)
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                text = match.group(0)
            return json.loads(text)
        except Exception as e:
            logger.error(f"Moderator LLM 호출 실패: {e}")
            return {
                "final_stance": rule_stance,
                "confidence_score": 50,
                "summary": "에이전트 토론을 종합한 결과입니다.",
                "top_sectors": [],
                "risk_factors": [],
                "action_items": [],
            }

    def _format_debate(self, reports: List[Dict], critiques: List[Dict]) -> str:
        lines = []
        lines.append("[Phase 1 — 개별 분석]")
        for r in reports:
            lines.append(
                f"\n{r['avatar']} {r['agent_name']} ({r['role']})\n"
                f"의견: {r['stance']} | 확신도: {r['confidence_score']}\n"
                f"분석: {r['analysis'][:250]}\n"
                f"핵심: {' / '.join(r.get('key_points', []))}"
            )
        lines.append("\n[Phase 2 — 교차 반론]")
        for c in critiques:
            lines.append(f"\n{c['from_agent']} → {c['to_agent']}: {c['critique'][:200]}")
        return "\n".join(lines)
