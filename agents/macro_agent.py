"""
매크로(Macro) 에이전트 — 거시경제·대외 변수 전문가
"""
from .base_agent import BaseAgent, AgentReport, AgentCritique

SYSTEM_PROMPT = """당신은 '매크로(Macro)'라는 이름의 거시경제 전문가입니다.

[페르소나]
- 금리·환율·유가·글로벌 자금 흐름·연준(Fed) 정책을 중심으로 국내 증시를 분석합니다.
- "나무보다 숲을 본다"는 원칙으로 개별 종목보다 대외 환경의 변화를 중시합니다.
- 미국 증시(나스닥·S&P500)와 국내 증시의 연동성, 달러 인덱스 방향을 항상 체크합니다.
- 중국 경기와 반도체 수출 지표 등 한국 경제와 직결된 대외 변수를 반드시 언급합니다.

[출력 언어] 한국어 (거시경제 전문 용어 사용, 명확한 인과관계 제시)
[JSON만 반환] 분석 시 반드시 지정된 JSON 형식으로만 응답"""


class MacroAgent(BaseAgent):

    def __init__(self, client, model):
        super().__init__(client, model)
        self.name = "매크로"
        self.role = "거시경제·대외변수 전문가"
        self.avatar = "🌐"
        self.system_prompt = SYSTEM_PROMPT

    # ─── Phase 1: 개별 분석 ─────────────────────────────────────────────────

    def analyze(self, market_data: dict) -> AgentReport:
        summary = self._market_summary(market_data)
        prompt = f"""아래 시장 데이터를 기반으로 거시경제 관점의 분석 보고서를 작성하세요.

{summary}

[분석 가이드]
- 달러/원 환율 방향이 외국인 수급에 미치는 영향 분석
- 미국 10년물 국채금리 레벨과 성장주 밸류에이션 압력
- 나스닥·S&P500과 KOSPI의 상관관계 및 동조화 여부
- 원자재(유가, 구리) 흐름과 인플레이션 기대치
- 연준 정책 방향과 한국은행 통화정책 여파

반드시 아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{{
  "analysis": "300자 이상 거시경제 분석 (인과관계 명확히 제시)",
  "key_points": [
    "핵심 매크로 포인트 1 (구체적 수치·사실 포함)",
    "핵심 매크로 포인트 2",
    "핵심 매크로 포인트 3"
  ],
  "confidence_score": 70,
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
            key_points=data.get("key_points", ["거시경제 분석 완료"]),
            confidence_score=max(0, min(100, int(data.get("confidence_score", 50)))),
            stance=data.get("stance", "HOLD").upper(),
        )

    # ─── Phase 2: 반론 ──────────────────────────────────────────────────────

    def critique(self, other_report: AgentReport, market_data: dict) -> AgentCritique:
        prompt = f"""거시경제 전문가로서 아래 에이전트 분석의 매크로 취약점을 지적하세요.

[{other_report.agent_name} — {other_report.role}의 분석]
의견: {other_report.stance} (확신도: {other_report.confidence_score})
주장: {other_report.analysis[:300]}

[현재 매크로 변수]
USD/KRW: {market_data.get('usdkrw','N/A')} / 미국 10Y: {market_data.get('us10y','N/A')}%
나스닥 등락: {market_data.get('nasdaq',{}).get('change_pct','N/A')}%

[반론 가이드]
- 상대방이 놓친 대외 변수나 매크로 리스크를 구체적으로 지적
- 글로벌 자금 흐름·환율·금리 관점에서 상대방 주장의 한계를 제시
- 150~250자 이내로 날카롭게 작성"""

        result = self._call_llm([{"role": "user", "content": prompt}])
        return AgentCritique(
            from_agent=self.name,
            to_agent=other_report.agent_name,
            critique=result.strip(),
        )
