"""
Backtester — 피드백 루프: 전일 예측 vs 실제 시장 비교

1. 전일 리포트 로드 → 각 에이전트의 stance 추출
2. 오늘의 KOSPI 실제 등락으로 정답 판정
3. 에이전트별 적중 통계 갱신 (data/agent_stats.json)
4. 누적 적중률 1위 에이전트 → 오늘의 Moderator 임명
"""
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# 경계값: ±0.3% 이내면 NEUTRAL
UP_THRESHOLD = 0.3
DOWN_THRESHOLD = -0.3


class Backtester:

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.history_dir = self.data_dir / "history"
        self.stats_file = self.data_dir / "agent_stats.json"
        self.history_dir.mkdir(parents=True, exist_ok=True)

    # ─── 메인 ───────────────────────────────────────────────────────────────

    def run(self, today_kospi_change_pct: float) -> Dict:
        """
        Parameters
        ----------
        today_kospi_change_pct : float
            오늘 KOSPI 실제 등락률 (%)

        Returns
        -------
        {
            "agent_rankings": [...],
            "yesterday_comparison": {...},
            "today_moderator": "퀀트"
        }
        """
        yesterday = date.today() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")

        # 전일 보고서 로드
        yesterday_report = self._load_yesterday(yesterday_str)

        # 실제 방향 판정
        actual_direction = self._classify_movement(today_kospi_change_pct)
        logger.info(f"오늘 KOSPI: {today_kospi_change_pct:+.2f}% → {actual_direction}")

        # 전일 비교 결과 산출
        yesterday_comparison = None
        if yesterday_report:
            yesterday_comparison = self._compare(yesterday_report, actual_direction, yesterday_str)
            self._update_stats(yesterday_comparison["predictions"])
        else:
            logger.warning(f"전일({yesterday_str}) 보고서 없음 — 백테스트 건너뜀")

        # 랭킹 조회 + 오늘의 Moderator 결정
        stats = self._load_stats()
        rankings = self._build_rankings(stats)
        today_moderator = rankings[0]["name"] if rankings else "중재자"

        return {
            "agent_rankings": rankings,
            "yesterday_comparison": yesterday_comparison,
            "today_moderator": today_moderator,
        }

    # ─── 보조 메서드 ────────────────────────────────────────────────────────

    def _load_yesterday(self, date_str: str) -> Optional[Dict]:
        path = self.history_dir / f"{date_str}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _classify_movement(self, change_pct: float) -> str:
        if change_pct >= UP_THRESHOLD:
            return "UP"
        if change_pct <= DOWN_THRESHOLD:
            return "DOWN"
        return "NEUTRAL"

    def _is_correct(self, stance: str, actual: str) -> bool:
        if actual == "UP" and stance == "BUY":
            return True
        if actual == "DOWN" and stance == "SELL":
            return True
        if actual == "NEUTRAL" and stance == "HOLD":
            return True
        return False

    def _compare(self, report: Dict, actual_direction: str, date_str: str) -> Dict:
        predictions = []
        agents = report.get("debate", {}).get("phase1_reports", [])
        for agent in agents:
            stance = agent.get("stance", "HOLD")
            correct = self._is_correct(stance, actual_direction)
            predictions.append({
                "agent": agent.get("agent_name"),
                "avatar": agent.get("avatar", "🤖"),
                "prediction": stance,
                "was_correct": correct,
            })
        return {
            "date": date_str,
            "actual_movement": actual_direction,
            "predictions": predictions,
        }

    def _update_stats(self, predictions: List[Dict]):
        stats = self._load_stats()
        for pred in predictions:
            name = pred["agent"]
            if name not in stats:
                stats[name] = {"total": 0, "correct": 0, "avatar": pred.get("avatar", "🤖")}
            stats[name]["total"] += 1
            if pred["was_correct"]:
                stats[name]["correct"] += 1
        self._save_stats(stats)

    def _build_rankings(self, stats: Dict) -> List[Dict]:
        rankings = []
        for name, s in stats.items():
            total = s.get("total", 0)
            correct = s.get("correct", 0)
            hit_rate = correct / total if total > 0 else 0.0
            rankings.append({
                "name": name,
                "avatar": s.get("avatar", "🤖"),
                "hit_rate": round(hit_rate, 4),
                "total_predictions": total,
                "correct": correct,
            })
        rankings.sort(key=lambda x: (x["hit_rate"], x["total_predictions"]), reverse=True)
        return rankings

    def _load_stats(self) -> Dict:
        if not self.stats_file.exists():
            return {}
        with open(self.stats_file, encoding="utf-8") as f:
            return json.load(f)

    def _save_stats(self, stats: Dict):
        with open(self.stats_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    # ─── 오늘 보고서 저장 ────────────────────────────────────────────────────

    def archive_report(self, report: Dict, date_str: str):
        """오늘 생성된 최종 보고서를 history 폴더에 백업"""
        path = self.history_dir / f"{date_str}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"보고서 아카이브 완료: {path}")
