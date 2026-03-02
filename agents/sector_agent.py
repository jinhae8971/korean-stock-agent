"""
섹터 매니저(Sector) 에이전트 — 반도체·이차전지 등 주도 섹터 전문가
"""
from .base_agent import BaseAgent, AgentReport, AgentCritique

SYSTEM_PROMPT = """당신은 '섹터 매니저'라는 이름의 산업 특화 분석가입니다.

[페르소나]
- 반도체, 이차전지, 바이오, 방산, 조선, 자동차, 금융 등 국내 주도 섹터의 흐름을 추적합니다.
- 공급망 뉴스, 수출입 현황, 기업 실적 예고, 산업 리포트를 종합해 bottom-up 분석을 수행합니다.
- 삼성전자·SK하이닉스·TSMC·엔비디아의 반도체 사이클 연동성을 항상 점검합니다.
- 이차전지(LG에너지솔루션·삼성SDI·에코프로)의 유럽·미국 수요 변화에 예민합니다.
- 어떤 섹터에 자금이 쏠리고 있는지, 로테이션 방향은 어디인지를 명확히 제시합니다.

[출력 언어] 한국어 (섹터 전문 용어 사용)
[JSON만 반환] 분석 시 반드시 지정된 JSON 형식으로만 응답"""


class SectorAgent(BaseAgent):

    def __init__(self, client, model):
        super().__init__(client, model)
        self.name = "섹터매니저"
        self.role = "주도 섹터·산업 분석가"
        self.avatar = "🔬"
        self.system_prompt = SYSTEM_PROMPT

    # ─── Phase 1: 개별 분석 ─────────────────────────────────────────────────

    def analyze(self, market_data: dict) -> AgentReport:
        summary = self._market_summary(market_data)
        stocks = market_data.get("top_stocks", [])
        stock_info = "\n".join(
            f"  {s.get('name','?')}: {s.get('close','N/A')}원 ({s.get('change_pct','N/A'):+.1f}%)"
            for s in stocks[:8]
        )
        prompt = f"""아래 시장 데이터를 기반으로 섹터 특화 분석 보고서를 작성하세요.

{summary}

[주요 종목 현황]
{stock_info}

[분석 가이드]
- 오늘 가장 강한 섹터와 약한 섹터를 특정하고 이유 설명
- 반도체(삼성전자·SK하이닉스) 사이클: 현재 고점·저점 판단
- 이차전지 수요 및 글로벌 EV 보조금 정책 변화 영향
- 바이오·방산·조선 중 주목 섹터와 근거
- 섹터 로테이션 방향 (성장→가치 or 반대) 판단

반드시 아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{{
  "analysis": "300자 이상 섹터 분석 (구체적 섹터명과 근거 포함)",
  "key_points": [
    "오늘의 주도 섹터와 근거",
    "회피해야 할 섹터와 이유",
    "주목할 섹터 로테이션 신호"
  ],
  "confidence_score": 72,
  "stance": "BUY"
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
            key_points=data.get("key_points", ["섹터 분석 완료"]),
            confidence_score=max(0, min(100, int(data.get("confidence_score", 50)))),
            stance=data.get("stance", "HOLD").upper(),
        )

    # ─── Phase 2: 반론 ──────────────────────────────────────────────────────

    def critique(self, other_report: AgentReport, market_data: dict) -> AgentCritique:
        stocks = market_data.get("top_stocks", [])
        stock_str = ", ".join(f"{s.get('name','?')} {s.get('change_pct','N/A'):+.1f}%" for s in stocks[:4])
        prompt = f"""섹터 전문가로서 아래 에이전트 분석의 산업 관점 취약점을 지적하세요.

[{other_report.agent_name} — {other_report.role}의 분석]
의견: {other_report.stance} (확신도: {other_report.confidence_score})
주장: {other_report.analysis[:300]}

[주요 종목 동향]
{stock_str}

[반론 가이드]
- 상대방이 간과한 섹터별 공급망 리스크나 수요 변화를 지적
- 반도체·이차전지 사이클 관점에서 상대 주장의 한계를 제시
- 150~250자 이내로 날카롭게 작성"""

        result = self._call_llm([{"role": "user", "content": prompt}])
        return AgentCritique(
            from_agent=self.name,
            to_agent=other_report.agent_name,
            critique=result.strip(),
        )
