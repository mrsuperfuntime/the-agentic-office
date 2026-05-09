"""
Trend Intelligence Agent - Sales Office
Manager: Leia Organa (Sales Office Manager)

Pipeline overview:
- Leia Organa coordinates five specialist sub-agents.
- Signal sources are fetched by source adapters (Reddit, YouTube, Google Trends, Etsy, MakerWorld).
- A trend scoring engine computes weighted keyword clusters.
- Lando Calrissian (Insight Writer) converts top clusters into IDEAS, ALERTS, and ACTIONS.

Credentials and API keys are read from environment variables.
Adapters fail gracefully when credentials are missing so the rest of the pipeline can still run.
"""

from __future__ import annotations

import os
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TrendSignal:
    """A single trend data point from any source."""
    source: str                        # "reddit" | "youtube" | "google_trends" | "etsy" | "makerworld"
    keyword: str
    score: float                       # normalised 0-100 engagement/interest score
    volume: int                        # raw count (posts, views, searches, listings, makes)
    velocity: float                    # % change over last 7 days (positive = growing)
    sample_titles: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "keyword": self.keyword,
            "score": round(self.score, 2),
            "volume": self.volume,
            "velocity": round(self.velocity, 2),
            "sample_titles": self.sample_titles[:5],
            "metadata": self.metadata,
            "fetched_at": self.fetched_at,
        }


@dataclass
class TrendCluster:
    """Aggregated signal across sources for one keyword cluster."""
    keyword: str
    composite_score: float
    signals: list[TrendSignal] = field(default_factory=list)
    source_coverage: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "composite_score": round(self.composite_score, 2),
            "source_coverage": self.source_coverage,
            "signal_count": len(self.signals),
            "signals": [s.to_dict() for s in self.signals],
        }


@dataclass
class TrendReport:
    """Final output of one agent run."""
    keywords: list[str]
    top_clusters: list[TrendCluster]
    ideas: list[str]
    alerts: list[str]
    recommended_actions: list[str]
    raw_signal_count: int
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    llm_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "keywords": self.keywords,
            "raw_signal_count": self.raw_signal_count,
            "top_clusters": [c.to_dict() for c in self.top_clusters],
            "ideas": self.ideas,
            "alerts": self.alerts,
            "recommended_actions": self.recommended_actions,
            "llm_summary": self.llm_summary,
        }


# ---------------------------------------------------------------------------
# Sub-agent base class
# ---------------------------------------------------------------------------

class SubAgent:
    """
    Base class for every specialist sub-agent on Sarah's trend team.
    Each concrete sub-agent declares its identity and implements fetch().
    """
    agent_name: str = "Unknown Agent"
    agent_role: str = "Signal collector"
    agent_description: str = ""
    source_id: str = ""          # matches SOURCE_WEIGHTS key

    def identity(self) -> dict:
        return {
            "name": self.agent_name,
            "role": self.agent_role,
            "description": self.agent_description,
            "source": self.source_id,
        }

    def fetch(self, keywords: list[str]) -> list[TrendSignal]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Signal source adapters  (each is now a named sub-agent)
# ---------------------------------------------------------------------------

class RedditAdapter(SubAgent):
    """
    Poe Dameron - Reddit Scout
    Monitors entrepreneurship, maker, and commerce subreddits for rising
    product ideas and community sentiment.
    """
    agent_name = "Poe Dameron"
    agent_role = "Reddit Scout"
    agent_description = (
        "Monitors subreddits like r/etsy, r/3dprinting, r/smallbusiness, and r/entrepreneur "
        "to surface rising community discussions, product ideas, and consumer sentiment."
    )
    source_id = "reddit"

    BASE_URL = "https://www.reddit.com"
    SUBREDDITS_BY_KEYWORD: dict[str, list[str]] = {
        "_default": ["entrepreneur", "smallbusiness", "etsy", "crafts",
                     "3dprinting", "makerspace", "Flipping", "ecommerce"],
    }

    def __init__(self) -> None:
        self.user_agent = os.getenv("REDDIT_USER_AGENT", "AgenTrendBot/1.0")
        self.client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self._bearer_token: str | None = None
        self._token_expiry: float = 0.0

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent}
        if self.client_id and self.client_secret:
            token = self._get_bearer()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_bearer(self) -> str | None:
        if self._bearer_token and time.time() < self._token_expiry - 60:
            return self._bearer_token
        try:
            resp = httpx.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                headers={"User-Agent": self.user_agent},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._bearer_token = data.get("access_token")
            self._token_expiry = time.time() + int(data.get("expires_in", 3600))
            return self._bearer_token
        except Exception as exc:
            logger.warning("Reddit OAuth failed: %s", exc)
            return None

    def fetch(self, keywords: list[str]) -> list[TrendSignal]:
        signals: list[TrendSignal] = []
        subreddits = self.SUBREDDITS_BY_KEYWORD.get("_default", [])
        base = "https://oauth.reddit.com" if self._bearer_token else self.BASE_URL

        for subreddit in subreddits[:6]:  # cap to avoid rate limits in dev
            try:
                url = f"{base}/r/{subreddit}/hot.json"
                resp = httpx.get(url, headers=self._headers(), params={"limit": 25}, timeout=10)
                if resp.status_code == 429:
                    logger.warning("Reddit rate-limited on r/%s", subreddit)
                    break
                resp.raise_for_status()
                posts = resp.json().get("data", {}).get("children", [])
                for kw in keywords:
                    matching = [
                        p["data"] for p in posts
                        if kw.lower() in (p["data"].get("title", "") + " " + p["data"].get("selftext", "")).lower()
                    ]
                    if not matching:
                        continue
                    total_score = sum(p.get("score", 0) for p in matching)
                    titles = [p.get("title", "") for p in matching]
                    # velocity proxy: upvote_ratio average above 0.8 -> positive
                    avg_ratio = sum(p.get("upvote_ratio", 0.5) for p in matching) / max(len(matching), 1)
                    velocity = round((avg_ratio - 0.5) * 200, 1)   # maps 0.5 -> 0, 1.0 -> +100
                    signals.append(TrendSignal(
                        source="reddit",
                        keyword=kw,
                        score=min(math.log1p(total_score) * 10, 100),
                        volume=len(matching),
                        velocity=velocity,
                        sample_titles=titles[:3],
                        metadata={"subreddit": subreddit, "raw_upvotes": total_score},
                    ))
            except Exception as exc:
                logger.warning("Reddit fetch error for r/%s: %s", subreddit, exc)
        return signals


class YouTubeAdapter(SubAgent):
    """
    Wedge Antilles - YouTube Analyst
    Tracks view counts, likes, and keyword search volumes on YouTube to
    identify product categories gaining video momentum.
    """
    agent_name = "Wedge Antilles"
    agent_role = "YouTube Analyst"
    agent_description = (
        "Queries the YouTube Data API v3 for high-performing videos related to target keywords. "
        "Identifies which product categories are attracting video content and viewer interest."
    )
    source_id = "youtube"

    SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(self) -> None:
        self.api_key = os.getenv("YOUTUBE_API_KEY", "")

    def fetch(self, keywords: list[str]) -> list[TrendSignal]:
        if not self.api_key:
            logger.warning("YOUTUBE_API_KEY not set - skipping YouTube adapter")
            return []
        signals: list[TrendSignal] = []
        for kw in keywords:
            try:
                search_resp = httpx.get(
                    self.SEARCH_URL,
                    params={
                        "part": "snippet",
                        "q": kw,
                        "type": "video",
                        "order": "viewCount",
                        "maxResults": 10,
                        "key": self.api_key,
                        "publishedAfter": "2024-01-01T00:00:00Z",
                    },
                    timeout=10,
                )
                search_resp.raise_for_status()
                items = search_resp.json().get("items", [])
                if not items:
                    continue

                video_ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
                stats_resp = httpx.get(
                    self.VIDEOS_URL,
                    params={
                        "part": "statistics",
                        "id": ",".join(video_ids),
                        "key": self.api_key,
                    },
                    timeout=10,
                )
                stats_resp.raise_for_status()
                stats = {v["id"]: v.get("statistics", {}) for v in stats_resp.json().get("items", [])}

                total_views = sum(int(stats.get(vid, {}).get("viewCount", 0)) for vid in video_ids)
                total_likes = sum(int(stats.get(vid, {}).get("likeCount", 0)) for vid in video_ids)
                titles = [i["snippet"]["title"] for i in items]

                signals.append(TrendSignal(
                    source="youtube",
                    keyword=kw,
                    score=min(math.log1p(total_views) * 5, 100),
                    volume=len(items),
                    velocity=round(math.log1p(total_likes) * 2, 1),
                    sample_titles=titles[:3],
                    metadata={"total_views": total_views, "total_likes": total_likes},
                ))
            except Exception as exc:
                logger.warning("YouTube fetch error for '%s': %s", kw, exc)
        return signals


class GoogleTrendsAdapter(SubAgent):
    """
    Cassian Andor - Trends Watcher
    Pulls Google Trends interest-over-time data to give the highest-signal
    view of what consumers are actually searching for right now.
    """
    agent_name = "Cassian Andor"
    agent_role = "Trends Watcher"
    agent_description = (
        "Uses Google Trends (via pytrends or public RSS) to measure search interest over time. "
        "Identifies velocity changes - keywords that are accelerating or peaking this week."
    )
    source_id = "google_trends"

    def __init__(self) -> None:
        self.geo = os.getenv("GOOGLE_TRENDS_GEO", "US")
        self.timeframe = os.getenv("GOOGLE_TRENDS_TIMEFRAME", "now 7-d")
        self._pytrends_available = self._check_pytrends()

    @staticmethod
    def _check_pytrends() -> bool:
        try:
            import pytrends  # noqa: F401
            return True
        except ImportError:
            return False

    def fetch(self, keywords: list[str]) -> list[TrendSignal]:
        if self._pytrends_available:
            return self._fetch_pytrends(keywords)
        return self._fetch_rss(keywords)

    def _fetch_pytrends(self, keywords: list[str]) -> list[TrendSignal]:
        from pytrends.request import TrendReq  # type: ignore
        signals: list[TrendSignal] = []
        try:
            pt = TrendReq(hl="en-US", tz=0)
            # Process in batches of 5 (Google Trends limit)
            for i in range(0, len(keywords), 5):
                batch = keywords[i:i + 5]
                pt.build_payload(batch, cat=0, timeframe=self.timeframe, geo=self.geo)
                interest = pt.interest_over_time()
                if interest.empty:
                    continue
                for kw in batch:
                    if kw not in interest.columns:
                        continue
                    series = interest[kw]
                    current = float(series.iloc[-1]) if len(series) else 0.0
                    week_ago = float(series.iloc[0]) if len(series) > 1 else current
                    velocity = round(((current - week_ago) / max(week_ago, 1)) * 100, 1)
                    signals.append(TrendSignal(
                        source="google_trends",
                        keyword=kw,
                        score=current,
                        volume=int(series.mean()),
                        velocity=velocity,
                        metadata={"geo": self.geo, "timeframe": self.timeframe},
                    ))
        except Exception as exc:
            logger.warning("pytrends error: %s", exc)
        return signals

    def _fetch_rss(self, keywords: list[str]) -> list[TrendSignal]:
        """Fallback: Google Trends daily RSS (no auth, coarser data)."""
        signals: list[TrendSignal] = []
        try:
            resp = httpx.get(
                "https://trends.google.com/trends/trendingsearches/daily/rss",
                params={"geo": self.geo},
                timeout=10,
            )
            resp.raise_for_status()
            xml = resp.text
            for kw in keywords:
                if kw.lower() in xml.lower():
                    signals.append(TrendSignal(
                        source="google_trends",
                        keyword=kw,
                        score=50.0,
                        volume=1,
                        velocity=0.0,
                        metadata={"method": "rss-fallback", "geo": self.geo},
                    ))
        except Exception as exc:
            logger.warning("Google Trends RSS error: %s", exc)
        return signals


class EtsyAdapter(SubAgent):
    """
    Hera Syndulla - Marketplace Spotter (Etsy channel)
    Scans live Etsy listings for favourite density and view counts to
    identify what handmade and custom products are selling right now.
    """
    agent_name = "Hera Syndulla"
    agent_role = "Marketplace Spotter"
    agent_description = (
        "Queries the Etsy Open API v3 to surface listings with high favourite density "
        "and view counts. Covers the handmade, custom, and maker-goods market segment."
    )
    source_id = "etsy"

    SEARCH_URL = "https://openapi.etsy.com/v3/application/listings/active"

    def __init__(self) -> None:
        self.api_key = os.getenv("ETSY_API_KEY", "")

    def fetch(self, keywords: list[str]) -> list[TrendSignal]:
        if not self.api_key:
            logger.warning("ETSY_API_KEY not set - skipping Etsy adapter")
            return []
        signals: list[TrendSignal] = []
        for kw in keywords:
            try:
                resp = httpx.get(
                    self.SEARCH_URL,
                    headers={"x-api-key": self.api_key},
                    params={
                        "keywords": kw,
                        "limit": 25,
                        "sort_on": "score",
                        "sort_order": "desc",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                listings = data.get("results", [])
                if not listings:
                    continue

                total_views = sum(l.get("views", 0) for l in listings)
                total_favs = sum(l.get("num_favorers", 0) for l in listings)
                titles = [l.get("title", "") for l in listings[:3]]
                # Etsy "score" = favourite density
                score = min(math.log1p(total_favs) * 8, 100)

                signals.append(TrendSignal(
                    source="etsy",
                    keyword=kw,
                    score=score,
                    volume=len(listings),
                    velocity=round(math.log1p(total_views) * 1.5, 1),
                    sample_titles=titles,
                    metadata={"total_views": total_views, "total_favs": total_favs},
                ))
            except Exception as exc:
                logger.warning("Etsy fetch error for '%s': %s", kw, exc)
        return signals


class MakerWorldAdapter(SubAgent):
    """
    Hera Syndulla - Marketplace Spotter (MakerWorld channel)
    Tracks download counts and make counts on MakerWorld (Bambu Lab) to
    spot 3-D printing and maker product trends before they cross over.
    """
    # Same agent as EtsyAdapter - Hera covers both marketplace signals.
    agent_name = "Hera Syndulla"
    agent_role = "Marketplace Spotter"
    agent_description = (
        "Queries MakerWorld for top downloaded and most-made 3D models, surfacing "
        "maker and physical-product trends that typically lead consumer markets by 2-4 weeks."
    )
    source_id = "makerworld"

    SEARCH_URL = "https://makerworld.com/api/v1/design-service/search"

    def __init__(self) -> None:
        self.api_key = os.getenv("MAKERWORLD_API_KEY", "")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "AgenTrendBot/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def fetch(self, keywords: list[str]) -> list[TrendSignal]:
        signals: list[TrendSignal] = []
        for kw in keywords:
            try:
                resp = httpx.get(
                    self.SEARCH_URL,
                    headers=self._headers(),
                    params={"keyword": kw, "limit": 20, "sortBy": "downloadCount"},
                    timeout=10,
                )
                if resp.status_code in (401, 403, 404):
                    logger.warning("MakerWorld returned %s for '%s'", resp.status_code, kw)
                    continue
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items") or data.get("data") or data.get("results") or []
                if not items:
                    continue

                total_downloads = sum(i.get("downloadCount", 0) for i in items)
                total_makes = sum(i.get("makeCount", 0) for i in items)
                titles = [i.get("title", "") or i.get("name", "") for i in items[:3]]

                signals.append(TrendSignal(
                    source="makerworld",
                    keyword=kw,
                    score=min(math.log1p(total_downloads) * 6, 100),
                    volume=total_downloads,
                    velocity=round(math.log1p(total_makes) * 3, 1),
                    sample_titles=titles,
                    metadata={"total_downloads": total_downloads, "total_makes": total_makes},
                ))
            except Exception as exc:
                logger.warning("MakerWorld fetch error for '%s': %s", kw, exc)
        return signals


# ---------------------------------------------------------------------------
# Trend Scoring Engine
# ---------------------------------------------------------------------------

# Source weights (must sum to 1.0)
SOURCE_WEIGHTS: dict[str, float] = {
    "reddit": 0.20,
    "youtube": 0.25,
    "google_trends": 0.30,
    "etsy": 0.15,
    "makerworld": 0.10,
}

# Velocity bonus multiplier - rewards rapidly growing signals
VELOCITY_BONUS_CAP = 15.0   # max bonus points added to composite score


def _velocity_bonus(velocity: float) -> float:
    """Map velocity (-100 .. +100) to a 0..VELOCITY_BONUS_CAP bonus."""
    if velocity <= 0:
        return 0.0
    return min(velocity / 100 * VELOCITY_BONUS_CAP, VELOCITY_BONUS_CAP)


def score_signals(signals: list[TrendSignal]) -> list[TrendCluster]:
    """
    Group signals by keyword, compute a weighted composite score, and
    return clusters sorted by composite score descending.
    """
    groups: dict[str, list[TrendSignal]] = {}
    for sig in signals:
        groups.setdefault(sig.keyword, []).append(sig)

    clusters: list[TrendCluster] = []
    for kw, group in groups.items():
        weighted_sum = 0.0
        total_weight = 0.0
        velocity_bonuses: list[float] = []
        covered_sources: list[str] = []

        for sig in group:
            w = SOURCE_WEIGHTS.get(sig.source, 0.05)
            weighted_sum += sig.score * w
            total_weight += w
            velocity_bonuses.append(_velocity_bonus(sig.velocity))
            if sig.source not in covered_sources:
                covered_sources.append(sig.source)

        base_score = weighted_sum / max(total_weight, 1e-9)
        # Coverage bonus: present in more sources = higher confidence
        coverage_bonus = len(covered_sources) * 2.0
        avg_velocity_bonus = sum(velocity_bonuses) / max(len(velocity_bonuses), 1)
        composite = min(base_score + coverage_bonus + avg_velocity_bonus, 100.0)

        clusters.append(TrendCluster(
            keyword=kw,
            composite_score=round(composite, 2),
            signals=group,
            source_coverage=covered_sources,
        ))

    clusters.sort(key=lambda c: c.composite_score, reverse=True)
    return clusters


# ---------------------------------------------------------------------------
# LLM Interpretation Agent - Lando Calrissian, Insight Writer
# ---------------------------------------------------------------------------

TREND_SYSTEM_PROMPT = """You are a Trend Intelligence Analyst for a sales and creative-products business.
You receive aggregated trend data from Reddit, YouTube, Google Trends, Etsy, and MakerWorld.
Your job is to:
1. Identify the most commercially promising opportunities.
2. Call out any fast-rising signals that require urgent attention (alerts).
3. Suggest concrete product ideas, content angles, or sales actions.
4. Be specific - reference the actual keywords and data provided.
5. Format your response as three labelled sections:
   IDEAS: <bullet list>
   ALERTS: <bullet list>
   ACTIONS: <bullet list>
Keep the total response under 400 words."""


def _build_trend_prompt(clusters: list[TrendCluster], keywords: list[str]) -> str:
    lines = [f"Trend analysis run for keywords: {', '.join(keywords)}", ""]
    for c in clusters[:8]:
        lines.append(f"[{c.keyword.upper()}]  composite_score={c.composite_score}  sources={','.join(c.source_coverage)}")
        for sig in c.signals:
            lines.append(
                f"  {sig.source}: score={sig.score} volume={sig.volume} velocity={sig.velocity:+.1f}%"
                + (f"  sample='{sig.sample_titles[0]}'" if sig.sample_titles else "")
            )
        lines.append("")
    return "\n".join(lines)


def _parse_llm_output(text: str) -> tuple[list[str], list[str], list[str]]:
    """Extract IDEAS / ALERTS / ACTIONS sections from the LLM response."""
    ideas, alerts, actions = [], [], []
    current: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("IDEAS"):
            current = ideas
        elif upper.startswith("ALERTS"):
            current = alerts
        elif upper.startswith("ACTIONS"):
            current = actions
        elif current is not None and stripped.lstrip("-* "):
            current.append(stripped.lstrip("-* "))
    return ideas, alerts, actions


class InsightWriterAgent:
    """
    Lando Calrissian - Insight Writer
    Receives scored trend clusters from Leia's team and uses the LLM to
    synthesise commercial opportunities, urgent alerts, and recommended actions.
    """

    agent_name = "Lando Calrissian"
    agent_role = "Insight Writer"
    agent_description = (
        "Interprets aggregated trend data from all signal sub-agents using the LLM. "
        "Produces structured IDEAS, ALERTS, and ACTIONS that the sales team can act on immediately."
    )

    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client

    def identity(self) -> dict:
        return {
            "name": self.agent_name,
            "role": self.agent_role,
            "description": self.agent_description,
            "source": "llm",
        }

    def interpret(
        self,
        keywords: list[str],
        clusters: list[TrendCluster],
    ) -> tuple[list[str], list[str], list[str], str]:
        if not clusters:
            return (
                ["No significant trend signals found for the given keywords."],
                [],
                ["Try broadening your keywords or check API credential configuration."],
                "",
            )
        prompt = _build_trend_prompt(clusters, keywords)
        try:
            raw = self.llm_client.generate(prompt, TREND_SYSTEM_PROMPT)
        except Exception as exc:
            logger.error("LLM interpretation failed: %s", exc)
            raw = ""

        ideas, alerts, actions = _parse_llm_output(raw)
        if not ideas:
            ideas = [f"Investigate growing interest in: {', '.join(c.keyword for c in clusters[:3])}"]
        if not actions:
            actions = ["Review top cluster data and brief the sales team."]

        return ideas, alerts, actions, raw


# ---------------------------------------------------------------------------
# Leia Organa - Sales Office Manager / Trend Intelligence Orchestrator
# ---------------------------------------------------------------------------

class TrendIntelligenceAgent:
    """
    Leia Organa - Sales Office Manager.

    Leia coordinates a team of five specialist sub-agents to run the full
    trend intelligence pipeline.  She assigns each source to the right agent,
    consolidates their signals through the Trend Scoring Engine, and hands
    the top clusters to Lando Calrissian (Insight Writer) for LLM interpretation.

    Call `run(keywords)` to execute the full pipeline.
    Call `roster()` to get the team directory.
    """

    manager_name = "Leia Organa"
    manager_role = "Sales Office Manager"
    manager_description = (
        "Oversees the Sales Office and coordinates the Trend Intelligence team. "
        "Leia assigns keyword research tasks to her sub-agents, reviews their signals, "
        "and synthesises the results into actionable sales strategy."
    )

    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client
        # Named signal-collection sub-agents
        self._reddit    = RedditAdapter()
        self._youtube   = YouTubeAdapter()
        self._trends    = GoogleTrendsAdapter()
        self._etsy      = EtsyAdapter()
        self._makerworld = MakerWorldAdapter()
        # LLM interpretation sub-agent
        self._casey     = InsightWriterAgent(llm_client)

        self.adapters: dict[str, SubAgent] = {
            "reddit":        self._reddit,
            "youtube":       self._youtube,
            "google_trends": self._trends,
            "etsy":          self._etsy,
            "makerworld":    self._makerworld,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def roster(self) -> dict:
        """Return the full team directory - manager + sub-agents (deduplicated by name)."""
        seen: set[str] = set()
        unique_agents: list[dict] = []
        # Collect identities and merge sources for agents covering multiple sources
        merged: dict[str, dict] = {}
        for source_id, agent in self.adapters.items():
            if not isinstance(agent, SubAgent):
                continue
            identity = agent.identity()
            name = identity["name"]
            if name in merged:
                # Append the extra source to the existing entry
                existing = merged[name]["source"]
                if source_id not in existing:
                    merged[name]["source"] = f"{existing}, {source_id}"
            else:
                merged[name] = identity
        for identity in merged.values():
            unique_agents.append(identity)
        unique_agents.append(self._casey.identity())
        return {
            "manager": {
                "name": self.manager_name,
                "role": self.manager_role,
                "description": self.manager_description,
            },
            "sub_agents": unique_agents,
        }

    def run(
        self,
        keywords: list[str],
        sources: list[str] | None = None,
        top_n: int = 5,
    ) -> TrendReport:
        """
        Full pipeline: ingest -> score -> interpret -> report.

        Args:
            keywords:  e.g. ["3d printed planter", "custom tumblers"]
            sources:   subset of adapters to run; None = all
            top_n:     how many top clusters to include in the report
        """
        active_sources = sources or list(self.adapters.keys())
        all_signals = self._ingest(keywords, active_sources)
        clusters = score_signals(all_signals)
        top_clusters = clusters[:top_n]
        ideas, alerts, actions, summary = self._casey.interpret(keywords, top_clusters)

        return TrendReport(
            keywords=keywords,
            top_clusters=top_clusters,
            ideas=ideas,
            alerts=alerts,
            recommended_actions=actions,
            raw_signal_count=len(all_signals),
            llm_summary=summary,
        )

    def get_source_health(self) -> dict[str, str]:
        """Return configured/missing status for each signal sub-agent."""
        env_map: dict[str, tuple[str, ...]] = {
            "reddit":        ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
            "youtube":       ("YOUTUBE_API_KEY",),
            "google_trends": (),
            "etsy":          ("ETSY_API_KEY",),
            "makerworld":    (),
        }
        status = {}
        for source, keys in env_map.items():
            agent = self.adapters.get(source)
            agent_name = agent.agent_name if isinstance(agent, SubAgent) else source
            if not keys:
                status[source] = f"{agent_name}: ready (public)"
            elif all(os.getenv(k) for k in keys):
                status[source] = f"{agent_name}: ready (credentials set)"
            else:
                missing = ", ".join(k for k in keys if not os.getenv(k))
                status[source] = f"{agent_name}: degraded (missing env: {missing})"
        return status

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ingest(self, keywords: list[str], active_sources: list[str]) -> list[TrendSignal]:
        signals: list[TrendSignal] = []
        for source in active_sources:
            agent = self.adapters.get(source)
            if agent is None:
                logger.warning("Unknown source '%s' - skipping", source)
                continue
            try:
                fetched = agent.fetch(keywords)
                agent_label = agent.agent_name if isinstance(agent, SubAgent) else source
                logger.info("%s (%s): %d signals fetched", agent_label, source, len(fetched))
                signals.extend(fetched)
            except Exception as exc:
                logger.error("Agent '%s' raised unexpectedly: %s", source, exc)
        return signals


