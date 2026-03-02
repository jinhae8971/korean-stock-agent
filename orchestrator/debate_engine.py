"""
DebateEngine — 5인 에이전트 3-Phase 토론 오케스트레이터

에이전트 구성 (인덱스 순서):
  Quant(0)         — 기술적 지표 중심 단기 분석
  Macro(1)         — 거시경제·환율·금리 하향식 분석
  Sector(2)        — 섹터·수급·테마 상향식 분석
  Value(3)         — 펀더멘털·밸류에이션 중심 분석
  KoreanNews(4)    — 최근 24h 글로벌 뉴스 이벤트 드리븐 분석 [NEW]

Phase 1: 각 에이전트 개별 분석 보고서 작성
Phase 2: 5방향 순환 교차 반론 (체인 구조)
  Quant(0)      → Value(3)        : 기술 신호 vs 펀더멘털 가정
  Macro(1)      → KoreanNews(4)   : 거시 흐름 vs 뉴스 이벤트
  Sector(2)     → Quant(0)        : 섹터 수급 vs 기술적 패턴
  Value(3)      → Macro(1)        : 펀더멘털 vs 매크로 환경
  KoreanNews(4) → Sector(2)       : 뉴스 촉매 vs 섹터 로테이션
Phase 3: Moderator가 전체를 종합해 최종 판단 (moderator.py)
"""
import logging
from typing import List, Dict

from agents.base_agent import AgentReport, AgentCritique

logger = logging.getLogger(__name__)


# 반론 할당 테이블 (from_idx → to_idx) — 5인 체인 구조
# 대립 축: 기술(0)↔가치(3), 거시(1)↔뉴스(4), 섹터(2)↔기술(0)
# 순환 체인: 0→3→1→4→2→0 (5인 완전 순환)
CRITIQUE_PAIRS = [
    (0, 3),   # Quant      → Value        : 기술 지표 vs 펀더멘털 가정
    (1, 4),   # Macro      → KoreanNews   : 거시 흐름 vs 이벤트 노이즈
    (2, 0),   # Sector     → Quant        : 수급 시그널 vs 기술적 패턴
    (3, 1),   # Value      → Macro        : 내재가치 vs 매크로 환경
    (4, 2),   # KoreanNews → Sector       : 뉴스 촉매 vs 섹터 내러티브
]


class DebateEngine:

    def __init__(self, agents: list):
        """
        Parameters
        ----------
        agents : list
            [QuantAgent, MacroAgent, SectorAgent, ValueAgent] 순서
        """
        self.agents = agents

    # ─── 메인 진행 ──────────────────────────────────────────────────────────

    def run(self, market_data: dict) -> Dict:
        """
        토론 전체 실행 후 결과 딕셔너리 반환

        Returns
        -------
        {
            "phase1_reports": [AgentReport.to_dict(), ...],
            "phase2_critiques": [AgentCritique.to_dict(), ...]
        }
        """
        logger.info("=== Phase 1: 개별 분석 보고서 작성 ===")
        reports = self._run_phase1(market_data)

        logger.info("=== Phase 2: 교차 반론 ===")
        critiques = self._run_phase2(reports, market_data)

        return {
            "phase1_reports": [r.to_dict() for r in reports],
            "phase2_critiques": [c.to_dict() for c in critiques],
        }

    # ─── Phase 1 ────────────────────────────────────────────────────────────

    def _run_phase1(self, market_data: dict) -> List[AgentReport]:
        reports: List[AgentReport] = []
        for agent in self.agents:
            logger.info(f"  [{agent.name}] 분석 작성 중...")
            try:
                report = agent.analyze(market_data)
                reports.append(report)
                logger.info(f"  [{agent.name}] {report.stance} (확신도 {report.confidence_score})")
            except Exception as e:
                logger.error(f"  [{agent.name}] 분석 실패: {e}")
                # 실패 시 기본 보고서 삽입
                from agents.base_agent import AgentReport
                reports.append(AgentReport(
                    agent_name=agent.name,
                    role=agent.role,
                    avatar=agent.avatar,
                    analysis=f"분석 중 오류 발생: {str(e)[:100]}",
                    key_points=["분석 불가"],
                    confidence_score=0,
                    stance="HOLD",
                ))
        return reports

    # ─── Phase 2 ────────────────────────────────────────────────────────────

    def _run_phase2(
        self, reports: List[AgentReport], market_data: dict
    ) -> List[AgentCritique]:
        critiques: List[AgentCritique] = []
        for from_idx, to_idx in CRITIQUE_PAIRS:
            if from_idx >= len(self.agents) or to_idx >= len(reports):
                continue
            from_agent = self.agents[from_idx]
            target_report = reports[to_idx]
            logger.info(f"  [{from_agent.name}] → [{target_report.agent_name}] 반론 중...")
            try:
                critique = from_agent.critique(target_report, market_data)
                critiques.append(critique)
            except Exception as e:
                logger.error(f"  반론 실패 ({from_agent.name}→{target_report.agent_name}): {e}")
                critiques.append(AgentCritique(
                    from_agent=from_agent.name,
                    to_agent=target_report.agent_name,
                    critique=f"반론 생성 중 오류: {str(e)[:80]}",
                ))
        return critiques
