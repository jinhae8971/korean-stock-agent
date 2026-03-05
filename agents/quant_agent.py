"""
퀀트(Quant) 에이전트 — 기술적 지표·수급 중심 냉철한 정량 분석가
"""
from .base_agent import BaseAgent, AgentReport, AgentCritique

SYSTEM_PROMPT = """당신은 '퀀트(Quant)'라는 이름의 냉철한 정량 분석가입니다.

[페르소나]
- 오직 숫자·통계·기술적 지표만 신뢰합니다. 뉴스나 감정은 노이즈로 취급합니다.
- RSI, MACD, 볼린저밴드, 거래량 변화율, 이동평균선 수치를 구체적으로 언급합니다.
- 문장은 짧고 직접적이며, 숫자가 없는 주장은 하지 않습니다.
- 반론할 때는 상대방 논리의 데이터 취약점을 정확히 집어냅니다.

[출력 언어] 한국어 (전문적이고 간결하게)
[JSON만 반환] 분석 시 반드시 지정된 JSON 형식으로만 응답"""


class QuantAgent(BaseAgent):

    def __init__(self, client, model):
        super().__init__(client, model)
        self.name = "퀀트"
        self.role = "기술적 지표·수급 분석가"
        self.avatar = "📊"
        self.system_prompt = SYSTEM_PROMPT

    # ─── Phase 1: 개별 분석 ─────────────────────────────────────────────────

    def analyze(self, market_data: dict) -> AgentReport:
        summary = self._market_summary(market_data)
        prompt = f"""아래 시장 데이터를 기반으로 기술적 분석 보고서를 작성하세요.

{summary}

[분석 가이드]
- RSI가 과매수(>70) / 과매도(<30) 구간인지 판단
- MACD 골든크로스 / 데드크로스 여부 확인
- 볼린저밴드 상단 돌파 / 하단 지지 확인
- 5일, 20일 이동평균선 배열 상태
- 거래량 증감 (5일 평균 대비) 수급 해석
- 외국인·기관 순매수 방향과 시장 함의

반드시 아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{{
  "analysis": "300자 이상 기술적 분석 (구체적 수치 반드시 포함)",
  "key_points": [
    "핵심 기술적 포인트 1 (수치 포함)",
    "핵심 기술적 포인트 2",
    "핵심 기술적 포인트 3"
  ],
  "confidence_score": 75,
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
            key_points=data.get("key_points", ["기술적 분석 완료"]),
            confidence_score=max(0, min(100, int(data.get("confidence_score", 50)))),
            stance=data.get("stance", "HOLD").upper(),
        )

    # ─── Phase 2: 반론 ──────────────────────────────────────────────────────

    def critique(self, other_report: AgentReport, market_data: dict) -> AgentCritique:
        ti = market_data.get("technical_indicators", {})
        prompt = f"""퀀트 분석가로서 아래 에이전트 분석에 날카로운 반론을 제시하세요.

[{other_report.agent_name} — {other_report.role}의 분석]
의견: {other_report.stance} (확신도: {other_report.confidence_score})
주장: {other_report.analysis[:300]}

[현재 기술적 수치]
RSI: {self._fmt(ti.get('rsi', 'N/A'), '.1f')} / MACD: {self._fmt(ti.get('macd', 'N/A'), '.2f')} / 볼린저 위치: {ti.get('bb_position', 'N/A')}

[반론 가이드]
- 상대방 주장의 데이터적 허점을 구체적 수치로 반박
- 감정적 표현 금지, 수치 기반 논리만 사용
- 150~250자 이내로 날카롭고 간결하게 작성"""

        result = self._call_llm([{"role": "user", "content": prompt}])
        return AgentCritique(
            from_agent=self.name,
            to_agent=other_report.agent_name,
            critique=self._clean_critique(result),
        )
