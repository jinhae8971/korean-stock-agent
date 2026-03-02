"""
KoreanNewsAgent — 최근 24시간 글로벌 뉴스 기반 한국 증시 이벤트 리스크 분석 에이전트

페르소나:
  "뉴스 리스크 헌터" — 기술적 지표나 펀더멘털이 아닌 실시간 뉴스 이벤트를 통해
  한국 증시에 영향을 미칠 수 있는 서프라이즈 리스크와 기회를 포착한다.

반론 특징:
  - "당신의 분석이 전제하는 현실은 오늘의 뉴스가 이미 바꿨습니다."
  - 지정학적 리스크, 규제 변화, 공급망 이벤트, 중앙은행 서프라이즈 등을 근거로
    다른 에이전트의 기존 전제를 공격한다.

교차 반론 대상:
  Phase 2에서 퀀트 에이전트(0)에 반론: "기술적 패턴이 간과한 뉴스 촉매가 있습니다."
"""
import logging
from agents.base_agent import BaseAgent, AgentReport, AgentCritique
from scripts.collect_news import format_news_for_prompt

logger = logging.getLogger(__name__)

# ─── 페르소나 시스템 프롬프트 ────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 '뉴스 리스크 헌터(News Risk Hunter)'라는 이름의 이벤트 드리븐 리스크 분석가입니다.

[페르소나]
- 오직 최신 뉴스 이벤트에서만 한국 증시의 리스크와 기회를 포착합니다.
- RSI, PBR 같은 지표는 과거 데이터이며, 당신이 보는 것은 "지금 이 순간 세상에서 벌어지는 일"입니다.
- 지정학적 긴장, 중앙은행 서프라이즈, 공급망 충격, 기술 규제, 외교 이슈 등을
  한국 증시 및 주요 섹터에 즉각 연결지어 분석합니다.
- 반론 시에는 "당신의 분석이 전제하는 시장 환경이 오늘의 뉴스로 인해 변했습니다"라는
  프레임으로 상대 논리를 공격합니다.

[분석 우선순위]
1. 한국에 직접 영향을 미치는 뉴스 (한미관계, 한중관계, 반도체 수출규제 등)
2. 글로벌 경제 서프라이즈 (Fed, ECB 발언, 고용/물가 쇼크)
3. 기술 이벤트 (AI/반도체 공급망, 주요 기업 실적 서프라이즈)
4. 지정학 (대만해협, 중동, 러-우, 북한 리스크)

[출력 규칙]
- 반드시 JSON 형식으로만 응답
- 감정적 표현 없이 인과관계 중심 서술
- 뉴스 제목/소스를 근거로 직접 인용"""


class KoreanNewsAgent(BaseAgent):
    """24시간 글로벌 뉴스 기반 한국 증시 이벤트 리스크 에이전트"""

    def __init__(self, client, model):
        super().__init__(client, model)
        self.name = "뉴스 리스크 헌터"
        self.role = "이벤트 드리븐 리스크 & 촉매 분석가"
        self.avatar = "📡"
        self.system_prompt = SYSTEM_PROMPT

    # ─── Phase 1: 독립 분석 ───────────────────────────────────────────────────

    def analyze(self, market_data: dict) -> AgentReport:
        """최근 24h 뉴스 이벤트를 한국 증시 관점에서 종합 분석"""
        news_data = market_data.get("news", {})
        news_text = format_news_for_prompt(news_data, max_per_category=8)
        market_context = self._market_summary(market_data)

        prompt = f"""[현재 시장 컨텍스트]
{market_context}

[최근 24시간 글로벌 뉴스]
{news_text}

[분석 지시]
위 뉴스들을 한국 증시(KOSPI/KOSDAQ) 관점에서 분석하세요.

다음 항목을 평가하세요:
1. 한국 증시에 직접 영향을 줄 뉴스 이벤트 (상위 3~5건)
2. 각 이벤트의 시장 영향 방향 (긍정/부정/중립)
3. 특히 주목할 섹터 또는 종목 (반도체, 배터리, 자동차, 금융 등)
4. 기존 기술적·펀더멘털 분석이 간과할 수 있는 뉴스 촉매
5. 오늘 뉴스 흐름의 전체적인 증시 방향성 (매수/보유/매도)

반드시 아래 JSON으로만 응답:
{{
  "analysis": "250자 이상의 분석 텍스트 (뉴스 출처 및 한국 증시 연결 포함)",
  "key_points": [
    "핵심 뉴스 이벤트 1 (출처 포함)",
    "핵심 뉴스 이벤트 2 (출처 포함)",
    "핵심 뉴스 이벤트 3 (출처 포함)"
  ],
  "high_impact_news": [
    {{
      "headline": "뉴스 제목",
      "source": "출처",
      "impact": "긍정/부정/중립",
      "affected_sectors": ["반도체", "배터리"],
      "rationale": "영향 이유 (50자 이내)"
    }}
  ],
  "confidence_score": 70,
  "stance": "BUY"
}}"""

        logger.info(f"[{self.name}] 뉴스 분석 시작 ({news_data.get('total_count', 0)}건 입력)")
        result = self._call_llm([{"role": "user", "content": prompt}])
        data = self._parse_json_response(result)

        return AgentReport(
            agent_name=self.name,
            role=self.role,
            avatar=self.avatar,
            analysis=data.get("analysis", result[:600]),
            key_points=data.get("key_points", []),
            confidence_score=max(0, min(100, int(data.get("confidence_score", 55)))),
            stance=data.get("stance", "HOLD").upper(),
        )

    # ─── Phase 2: 교차 반론 ───────────────────────────────────────────────────

    def critique(self, other_report: AgentReport, market_data: dict) -> AgentCritique:
        """
        다른 에이전트 분석에 뉴스 근거로 반론.
        "당신의 분석이 전제하는 시장 환경이 최신 뉴스로 인해 달라졌습니다."
        """
        news_data = market_data.get("news", {})
        news_text = format_news_for_prompt(news_data, max_per_category=5)

        prompt = f"""당신은 뉴스 리스크 헌터입니다.
아래 에이전트의 분석에 최신 뉴스 이벤트를 근거로 핵심 반론을 제시하세요.

[{other_report.agent_name}의 분석]
역할: {other_report.role}
판단: {other_report.stance} (확신도: {other_report.confidence_score}%)
주요 주장: {other_report.analysis[:350]}

[최근 24시간 뉴스 (참조용)]
{news_text[:800]}

[반론 가이드]
- 상대 분석의 전제 조건을 뒤집는 뉴스 이벤트를 구체적으로 언급하세요.
- "이 뉴스가 발표된 이후 상대방의 [특정 주장]은 재검토가 필요합니다" 형식을 사용하세요.
- 200~280자, 뉴스 출처 명시, 논리적 인과관계 중심으로 작성하세요.
- 감정적 표현 없이 팩트 기반으로 작성하세요."""

        result = self._call_llm([{"role": "user", "content": prompt}])
        return AgentCritique(
            from_agent=self.name,
            to_agent=other_report.agent_name,
            critique=result.strip()[:400],
        )
