"""
DebateEngine — 4인 에이전트 3-Phase 토론 오케스트레이터

Phase 1: 각 에이전트 개별 분석 보고서 작성
Phase 2: 순환 방식으로 서로 다른 에이전트에게 반론 제기
         퀀트→가치투자자, 매크로→섹터매니저, 섹터매니저→매크로, 가치투자자→퀀트
Phase 3: Moderator가 전체를 종합해 최종 판단 (moderator.py)
"""
import logging
from typing import List, Dict

from agents.base_agent import AgentReport, AgentCritique

logger = logging.getLogger(__name__)


# 반론 할당 테이블 (from → to index)
# 퀀트(0)→가치투자자(3), 매크로(1)→섹터매니저(2),
# 섹터매니저(2)→매크로(1), 가치투자자(3)→퀀트(0)
CRITIQUE_PAIRS = [(0, 3), (1, 2), (2, 1), (3, 0)]


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
