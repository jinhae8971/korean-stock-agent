"""
collect_news.py — 최근 24시간 국제·경제·기술 뉴스 수집 모듈

수집 소스 (RSS 기반 — API 키 불필요):
  [국제]  BBC World, Google News World, Reuters World
  [경제]  BBC Business, Google News Business, Reuters Finance
  [기술]  BBC Tech, TechCrunch, Google News Technology
  [한국]  연합뉴스 경제, 네이버 금융 주요뉴스

출력 구조:
  {
    "international": [{"title", "source", "summary", "published_at"}, ...],
    "economic":      [...],
    "technology":    [...],
    "korean":        [...],
    "collected_at":  ISO timestamp,
    "total_count":   int,
    "collection_errors": [str, ...]
  }
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from email.utils import parsedate_to_datetime

import requests

logger = logging.getLogger(__name__)

# ─── RSS 소스 정의 ──────────────────────────────────────────────────────────

RSS_SOURCES: Dict[str, List[Dict]] = {
    "international": [
        {
            "name": "BBC World",
            "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        },
        {
            "name": "NYT World",
            "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        },
        {
            "name": "Google News World",
            "url": (
                "https://news.google.com/rss/headlines/section/topic/WORLD"
                "?hl=en-US&gl=US&ceid=US:en"
            ),
        },
    ],
    "economic": [
        {
            "name": "BBC Business",
            "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        },
        {
            "name": "NYT Business",
            "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        },
        {
            "name": "Google News Business",
            "url": (
                "https://news.google.com/rss/headlines/section/topic/BUSINESS"
                "?hl=en-US&gl=US&ceid=US:en"
            ),
        },
        {
            "name": "Reuters Markets",
            "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        },
    ],
    "technology": [
        {
            "name": "BBC Technology",
            "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        },
        {
            "name": "NYT Technology",
            "url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        },
        {
            "name": "Google News Technology",
            "url": (
                "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY"
                "?hl=en-US&gl=US&ceid=US:en"
            ),
        },
        {
            "name": "TechCrunch",
            "url": "https://techcrunch.com/feed/",
        },
    ],
    "korean": [
        {
            "name": "연합뉴스 경제",
            "url": "https://www.yna.co.kr/rss/economy.xml",
        },
        {
            "name": "연합뉴스 산업",
            "url": "https://www.yna.co.kr/rss/industry.xml",
        },
        {
            "name": "연합뉴스 금융",
            "url": "https://www.yna.co.kr/rss/market.xml",
        },
        {
            "name": "연합뉴스 국제",
            "url": "https://www.yna.co.kr/rss/international.xml",
        },
    ],
}

# 수집 설정
MAX_ITEMS_PER_SOURCE = 15       # 소스당 최대 기사 수
MAX_ITEMS_PER_CATEGORY = 20     # 카테고리당 최대 기사 수 (중복 제거 후)
HOURS_WINDOW = 24               # 최근 N시간 이내만 수집
REQUEST_TIMEOUT = 12            # 소스 요청 타임아웃 (초)
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NewsBot/1.0; +https://github.com/jinhae8971)"
    )
}


# ─── 파서 헬퍼 ─────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """HTML 태그 및 CDATA 제거 후 텍스트 정제"""
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#\d+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_rss_xml(xml_text: str) -> List[Dict]:
    """
    간단한 정규식 기반 RSS 파서.
    feedparser 의존성 없이 <item> 블록에서 title/description/pubDate 추출.
    """
    items = []
    # <item> 블록 추출
    for item_match in re.finditer(r"<item>(.*?)</item>", xml_text, re.DOTALL):
        raw = item_match.group(1)
        title = ""
        description = ""
        pub_date = ""

        tm = re.search(r"<title[^>]*>(.*?)</title>", raw, re.DOTALL)
        if tm:
            title = _strip_html(tm.group(1))

        dm = re.search(r"<description[^>]*>(.*?)</description>", raw, re.DOTALL)
        if dm:
            description = _strip_html(dm.group(1))

        pm = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", raw, re.DOTALL)
        if pm:
            pub_date = pm.group(1).strip()

        if title:
            items.append({
                "title": title,
                "description": description,
                "pub_date_raw": pub_date,
            })
    return items


def _parse_pub_date(pub_date_raw: str) -> Optional[datetime]:
    """RFC 822 / ISO 8601 날짜 문자열 → datetime(UTC)"""
    if not pub_date_raw:
        return None
    try:
        dt = parsedate_to_datetime(pub_date_raw)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    # ISO 8601 폴백
    try:
        dt = datetime.fromisoformat(pub_date_raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    return None


def _dedup_by_title(items: List[Dict]) -> List[Dict]:
    """제목 앞 40자 해시 기준 중복 제거"""
    seen: set = set()
    result = []
    for item in items:
        key = hashlib.md5(item["title"][:40].lower().encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# ─── 단일 소스 수집 ────────────────────────────────────────────────────────

def _fetch_source(source: Dict, cutoff: datetime) -> List[Dict]:
    """단일 RSS 소스에서 24h 이내 기사 반환"""
    name = source["name"]
    url = source["url"]
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw_items = _parse_rss_xml(resp.text)

        result = []
        for raw in raw_items[:MAX_ITEMS_PER_SOURCE]:
            pub_dt = _parse_pub_date(raw.get("pub_date_raw", ""))

            # 날짜 파싱 실패 시 → 최신 기사로 간주 (포함)
            if pub_dt is not None and pub_dt < cutoff:
                continue

            published_str = pub_dt.strftime("%Y-%m-%d %H:%M UTC") if pub_dt else "Unknown"
            summary = raw.get("description", "")[:300]

            result.append({
                "title": raw["title"],
                "source": name,
                "summary": summary,
                "published_at": published_str,
            })
        logger.debug(f"  [{name}] {len(result)}건 수집")
        return result

    except requests.exceptions.Timeout:
        logger.warning(f"  [{name}] 타임아웃")
        return []
    except requests.exceptions.RequestException as e:
        logger.warning(f"  [{name}] 요청 실패: {e}")
        return []
    except Exception as e:
        logger.warning(f"  [{name}] 파싱 오류: {e}")
        return []


# ─── 메인 수집 함수 ────────────────────────────────────────────────────────

def collect_news(hours: int = HOURS_WINDOW) -> Dict:
    """
    최근 `hours` 시간 내 국제·경제·기술·한국 뉴스 수집

    Parameters
    ----------
    hours : int
        수집 기간 (기본 24시간)

    Returns
    -------
    dict
        {
          "international": [...],
          "economic": [...],
          "technology": [...],
          "korean": [...],
          "collected_at": str,
          "total_count": int,
          "collection_errors": [str]
        }
    """
    logger.info(f"뉴스 수집 시작 (최근 {hours}시간)")
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=hours)

    collected: Dict[str, List[Dict]] = {
        "international": [],
        "economic": [],
        "technology": [],
        "korean": [],
    }
    errors: List[str] = []

    for category, sources in RSS_SOURCES.items():
        logger.info(f"  카테고리: {category} ({len(sources)}개 소스)")
        all_items: List[Dict] = []
        for source in sources:
            try:
                items = _fetch_source(source, cutoff)
                all_items.extend(items)
            except Exception as e:
                msg = f"{source['name']}: {str(e)[:80]}"
                errors.append(msg)
                logger.warning(f"  수집 오류 — {msg}")

        # 중복 제거 + 상위 N건만 유지
        deduped = _dedup_by_title(all_items)[:MAX_ITEMS_PER_CATEGORY]
        collected[category] = deduped
        logger.info(f"  {category}: {len(deduped)}건 (중복 제거 후)")

    total = sum(len(v) for v in collected.values())
    logger.info(f"뉴스 수집 완료 — 총 {total}건")

    return {
        **collected,
        "collected_at": now_utc.isoformat(),
        "total_count": total,
        "collection_window_hours": hours,
        "collection_errors": errors,
    }


def format_news_for_prompt(news_data: Dict, max_per_category: int = 8) -> str:
    """
    LLM 프롬프트 주입용 뉴스 텍스트 포맷터.
    카테고리별 최신 뉴스 제목 + 요약을 구조화된 문자열로 반환.
    """
    lines = []
    category_labels = {
        "international": "🌐 국제 뉴스",
        "economic": "💰 경제 뉴스",
        "technology": "⚡ 기술 뉴스",
        "korean": "🇰🇷 한국 경제·금융 뉴스",
    }
    collected_at = news_data.get("collected_at", "")
    if collected_at:
        lines.append(f"[뉴스 수집 시각] {collected_at[:19]} UTC")
        lines.append(f"[수집 기간] 최근 {news_data.get('collection_window_hours', 24)}시간")
        lines.append("")

    for cat, label in category_labels.items():
        items = news_data.get(cat, [])[:max_per_category]
        if not items:
            continue
        lines.append(f"{'─' * 50}")
        lines.append(f"{label} ({len(items)}건)")
        lines.append(f"{'─' * 50}")
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. [{item['source']}] {item['title']}")
            if item.get("summary"):
                # 요약 앞 120자만 출력
                lines.append(f"   {item['summary'][:120]}")
        lines.append("")

    total = news_data.get("total_count", 0)
    errors = news_data.get("collection_errors", [])
    lines.append(f"※ 총 {total}건 수집" + (f" | 오류 {len(errors)}건" if errors else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = collect_news()
    print(format_news_for_prompt(data))
    print("\n--- RAW JSON (요약) ---")
    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in data.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
