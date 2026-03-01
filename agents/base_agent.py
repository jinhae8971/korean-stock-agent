"""
Base Agent: 모든 에이전트의 공통 인터페이스 및 데이터 구조 정의
"""
from dataclasses import dataclass, field
from typing import Optional, List
import json
import re
import anthropic


@dataclass
class AgentReport:
    agent_name: str
    role: str
    avatar: str
    analysis: str
    key_points: List[str]
    confidence_score: int   # 0~100
    stance: str             # "BUY" | "HOLD" | "SELL"

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "avatar": self.avatar,
            "analysis": self.analysis,
            "key_points": self.key_points,
            "confidence_score": self.confidence_score,
            "stance": self.stance,
        }


@dataclass
class AgentCritique:
    from_agent: str
    to_agent: str
    critique: str

    def to_dict(self) -> dict:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "critique": self.critique,
        }


class BaseAgent:
    """모든 에이전트가 상속받는 베이스 클래스"""

    def __init__(self, client: anthropic.Anthropic, model: str = "claude-sonnet-4-5-20250929"):
        self.client = client
        self.model = model
        self.name: str = ""
        self.role: str = ""
        self.avatar: str = "🤖"
        self.system_prompt: str = ""

    # ─── 공개 인터페이스 ────────────────────────────────────────────────────────

    def analyze(self, market_data: dict) -> AgentReport:
        """Phase 1: 시장 데이터를 받아 개별 분석 보고서 작성"""
        raise NotImplementedError

    def critique(self, other_report: AgentReport, market_data: dict) -> AgentCritique:
        """Phase 2: 다른 에이전트의 보고서에 반론 제시"""
        raise NotImplementedError

    # ─── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _call_llm(self, messages: list, system: Optional[str] = None) -> str:
        """Claude API 호출 공통 메서드"""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system or self.system_prompt,
            messages=messages,
        )
        return response.content[0].text

    def _parse_json_response(self, text: str) -> dict:
        """LLM 응답에서 JSON 추출"""
        # 마크다운 코드블록 제거
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        # JSON 블록 탐색
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}

    def _market_summary(self, market_data: dict) -> str:
        """시장 데이터를 간결한 문자열로 변환 (프롬프트 주입용)"""
        lines = []
        kospi = market_data.get("kospi", {})
        kosdaq = market_data.get("kosdaq", {})
        lines.append(f"[지수] KOSPI {kospi.get('close','N/A')} ({kospi.get('change_pct','N/A'):+.2f}%) "
                     f"/ KOSDAQ {kosdaq.get('close','N/A')} ({kosdaq.get('change_pct','N/A'):+.2f}%)")
        lines.append(f"[환율] USD/KRW {market_data.get('usdkrw','N/A')}")
        lines.append(f"[금리] 미국 10Y {market_data.get('us10y','N/A')}%")
        nasdaq = market_data.get("nasdaq", {})
        lines.append(f"[미국] 나스닥 {nasdaq.get('close','N/A')} ({nasdaq.get('change_pct','N/A'):+.2f}%)")
        lines.append(f"[수급] 외국인 {market_data.get('foreigners_net','N/A')}억 / "
                     f"기관 {market_data.get('institutions_net','N/A')}억")
        ti = market_data.get("technical_indicators", {})
        if ti:
            lines.append(f"[기술] KOSPI RSI {ti.get('rsi','N/A'):.1f} / "
                         f"MACD {ti.get('macd','N/A'):.2f} / "
                         f"볼린저 위치 {ti.get('bb_position','N/A'):.1%}")
        return "\n".join(lines)
