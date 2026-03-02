"""
가치투자자(Value) 에이전트 — 밸류에이션·실적 중심 역발상 전략가
"""
from .base_agent import BaseAgent, AgentReport, AgentCritique

SYSTEM_PROMPT = """당신은 '가치투자자'라는 이름의 역발상 전략가이자 가치투자 전문가입니다.

[페르소나]
- PBR, PER, ROE, 배당수익률, EV/EBITDA 등 밸류에이션 지표를 핵심 근거로 사용합니다.
- 시장이 공포에 빠졌을 때 기회를 보고, 과열됐을 때 경고를 발합니다.
- 군중 심리와 반대 방향을 자주 제안하며, 단기 주가 변동보다 내재 가치를 중시합니다.
- 공매도 잔고, 투자자별 순매수, 공포탐욕지수 등 센티멘트 지표도 활용합니다.
- "싸게 사서 비싸게 팔라"는 원칙 아래, 현재 시장이 고평가인지 저평가인지 명확히 판단합니다.

[출력 언어] 한국어 (가치투자 철학을 반영한 냉정하고 장기적 시각)
[JSON만 반환] 분석 시 반드시 지정된 JSON 형식으로만 응답"""


class ValueAgent(BaseAgent):

    def __init__(self, client, model):
        super().__init__(client, model)
        self.name = "가치투자자"
        self.role = "밸류에이션·역발상 전략가"
        self.avatar = "💰"
        self.system_prompt = SYSTEM_PROMPT

    # ─── Phase 1: 개별 분석 ─────────────────────────────────────────────────

    def analyze(self, market_data: dict) -> AgentReport:
        summary = self._market_summary(market_data)
        stocks = market_data.get("top_stocks", [])
        valuation_info = "\n".join(
            f"  {s.get('name','?')}: PER {s.get('per','N/A')}x / PBR {s.get('pbr','N/A')}x"
            for s in stocks[:5] if s.get("per")
        )
        prompt = f"""아래 시장 데이터를 기반으로 밸류에이션 관점의 분석 보고서를 작성하세요.

{summary}

[밸류에이션 현황]
{valuation_info if valuation_info else "밸류에이션 데이터 제한적"}

[분석 가이드]
- KOSPI 전체 PER·PBR 수준이 역사적 평균 대비 고평가/저평가인지 판단
- 현재 시장 센티멘트(과공포/과탐욕)와 역발상 기회 탐색
- 배당수익률이 높은 가치주 섹터의 매력도 분석
- 최근 급등 종목의 실적 대비 밸류에이션 과열 여부 경고
- 장기 투자자 관점에서 현재 시점이 Buy Zone인지 판단

반드시 아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{{
  "analysis": "300자 이상 밸류에이션·역발상 분석 (구체적 지표 수치 포함)",
  "key_points": [
    "현재 시장 밸류에이션 레벨 판단 (PER/PBR 기준)",
    "역발상 관점의 투자 기회 또는 경고",
    "장기 투자자를 위한 포지션 조언"
  ],
  "confidence_score": 65,
  "stance": "HOLD"
}}

stance: BUY / HOLD / SELL 중 하나
confidence_score: 0~100 정수"""

        result = self._call_llm([{"role": "user", "content": prompt}])
        data = self._parse_json_response(result)
        return AgentReport(
            agent_name=self.name,
            role=self.role,
            avatar=self.avatar,
            analysis=data.get("analysis", result[:600]),
            key_points=data.get("key_points", ["밸류에이션 분석 완료"]),
            confidence_score=max(0, min(100, int(data.get("confidence_score", 50)))),
            stance=data.get("stance", "HOLD").upper(),
        )

    # ─── Phase 2: 반론 ──────────────────────────────────────────────────────

    def critique(self, other_report: AgentReport, market_data: dict) -> AgentCritique:
        prompt = f"""가치투자 관점에서 아래 에이전트 분석의 밸류에이션·심리적 맹점을 지적하세요.

[{other_report.agent_name} — {other_report.role}의 분석]
의견: {other_report.stance} (확신도: {other_report.confidence_score})
주장: {other_report.analysis[:300]}

[현재 시장 상황]
KOSPI: {market_data.get('kospi',{}).get('close','N/A')} / 외국인 수급: {market_data.get('foreigners_net','N/A')}억

[반론 가이드]
- 군중 심리 편향이나 단기 노이즈에 휘둘린 부분을 지적
- 밸류에이션 관점에서 과열 또는 과매도 신호를 근거로 반박
- 역발상 투자자 시각에서 상대방 주장의 한계를 150~250자로 날카롭게 작성"""

        result = self._call_llm([{"role": "user", "content": prompt}])
        return AgentCritique(
            from_agent=self.name,
            to_agent=other_report.agent_name,
            critique=result.strip(),
        )
