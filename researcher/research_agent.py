"""
THE RESEARCHER — agentic loop + product recreation scoring.

Two modes:
  run()                    — general research with multi-step tool calling
  research_and_rank()      — product-focused pipeline: eBay data → sold signals
                             → LLM recreation scoring → ranked cards
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from tools import ResearchTools, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

# ── System prompts ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are THE RESEARCHER, an advanced autonomous research agent.
Your mission: conduct thorough, accurate research on any topic using your tools.

Available tools
───────────────
• web_search          — search the web for current information
• fetch_page          — read the full text of a specific URL
• wikipedia_search    — look up background knowledge and definitions
• thingiverse_search  — find existing 3D printable models on Thingiverse (like/download counts = demand signal)
• ebay_search         — search eBay for product listings with images and pricing
• ebay_sold_data      — real eBay completed/sold data: sold count, avg price, GMV for a timeframe

Research process
────────────────
1. Break the request into specific searches
2. Use ebay_search to find active products — it returns images, categories, and pricing
3. Use ebay_sold_data to get real sold counts, average sold prices, and GMV
4. Use thingiverse_search to find existing 3D models — likes and download counts confirm demand
5. Use web_search for broader market context
6. Synthesize everything into a structured, cited report with real numbers

Always cite sources. Be thorough, factual, and concise.
"""

_SCORER_PROMPT = """\
You are an expert in 3D design, Meshy AI, and 3D printing markets.

Score each product for its potential to be recreated and redesigned as a 3D model
using Meshy AI (a text-to-3D AI generator) and sold or distributed as a custom product.

Scoring criteria (1-10):
  • 3D modelability    — can its shape be accurately reproduced as a 3D mesh?
  • Meshy AI fit       — does it match what Meshy excels at? (figures, props, decor, toys)
  • Market opportunity — is there demand for custom or improved versions?
  • Printability       — can it be 3D printed with standard PLA/resin?
  • Thingiverse signal — if similar models exist on Thingiverse with high like counts,
                         that confirms feasibility and demand — boost the score accordingly

Tier definitions:
  HIGH   (7-10): figurines, statues, busts, action figures, props, cosplay items,
                 decorative objects, vases, miniatures, game pieces, jewelry pendants
  MEDIUM (4-6):  functional parts with some printable components, accessories,
                 mixed-material products, simple tools/cases
  LOW    (1-3):  electronics, clothing/fabric, paper goods, food, complex machinery,
                 transparent/glass items

Respond ONLY with a valid JSON array — no markdown, no explanation outside the JSON:
[
  {
    "index": 1,
    "score": 8,
    "tier": "high",
    "reasons": ["solid figurine shape", "high collector demand", "1200+ likes on Thingiverse confirms demand"],
    "meshy_prompt": "3D model of [specific description], detailed surface, game-ready mesh, stylized art style",
    "redesign_ideas": "Could add articulated joints, LED cavity in base, variant colorways"
  },
  ...
]
"""


class ResearchAgent:
    def __init__(self) -> None:
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.model      = os.getenv("RESEARCHER_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:7b"))
        self.timeout    = int(os.getenv("LLM_TIMEOUT", "90"))
        self.tools      = ResearchTools()

    # ── General research loop ─────────────────────────────────────────────────

    def run(self, query: str, max_steps: int = 10) -> dict:
        started_at = datetime.now(timezone.utc).isoformat()
        messages: list[dict] = [
            {"role": "system",  "content": _SYSTEM_PROMPT},
            {"role": "user",    "content": query},
        ]
        steps:   list[dict] = []
        sources: list[dict] = []

        for step_num in range(max_steps):
            response   = self._call_ollama(messages, use_tools=True)
            if not response:
                break
            msg        = response.get("message", {})
            tool_calls = msg.get("tool_calls") or []
            content    = msg.get("content") or ""

            if not tool_calls:
                return self._build_result(query, content, steps, sources, started_at, step_num + 1)

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            for call in tool_calls:
                fn   = call.get("function", {})
                name = fn.get("name", "")
                args = _safe_json(fn.get("arguments", {}))

                result = self.tools.dispatch(name, args)
                steps.append({
                    "step":    step_num + 1,
                    "tool":    name,
                    "args":    args,
                    "summary": _summarize(name, result),
                })
                _collect_sources(name, args, result, sources)
                messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)})

        messages.append({
            "role":    "user",
            "content": "Synthesize everything you have gathered into a comprehensive report.",
        })
        final   = self._call_ollama(messages, use_tools=False)
        content = (final or {}).get("message", {}).get("content", "Research complete.")
        return self._build_result(query, content, steps, sources, started_at, max_steps)

    async def run_async(self, query: str, max_steps: int = 10) -> dict:
        return await asyncio.to_thread(self.run, query, max_steps)

    # ── Single-shot Q&A ───────────────────────────────────────────────────────

    def quick_answer(self, question: str) -> str:
        resp = self._call_ollama(
            [
                {"role": "system", "content": "You are a concise research assistant. Answer accurately."},
                {"role": "user",   "content": question},
            ],
            use_tools=False,
        )
        return (resp or {}).get("message", {}).get("content", "")

    async def quick_answer_async(self, question: str) -> str:
        return await asyncio.to_thread(self.quick_answer, question)

    # ── Product research + recreation ranking ─────────────────────────────────

    def research_and_rank(self, query: str, limit: int = 12, timeframe_days: int = 30) -> dict:
        """
        Full product research pipeline:
          1. eBay active listings (images, prices, categories)
          2. Thingiverse models (likes, downloads, makes — demand signal)
          3. Real eBay sold data via Finding API (sold count, avg price, GMV)
          4. LLM batch recreation scoring with Meshy AI prompts
          5. Ranked product cards + summary
        """
        started_at   = datetime.now(timezone.utc).isoformat()
        search_query = _extract_search_query(query)
        if search_query != query:
            logger.info("Query cleaned: %r → %r", query, search_query)

        # Step 1: eBay active listings (use cleaned keyword query)
        ebay_result = self.tools.ebay_search(search_query, limit=limit)
        items       = ebay_result.get("items", [])
        ebay_error  = ebay_result.get("error")
        if ebay_error:
            logger.warning("eBay search error for %r: %s", search_query, ebay_error)

        # Step 2: Thingiverse models
        thingiverse_result = self.tools.thingiverse_search(search_query, limit=8, sort="popular")
        thingiverse_things = thingiverse_result.get("things", [])
        thingiverse_error  = thingiverse_result.get("error")
        if thingiverse_error:
            logger.info("Thingiverse: %s", thingiverse_error)

        # Step 3: Real eBay sold data (Finding API, same cleaned query)
        sold_data: dict = {}
        sold_data = self.tools.ebay_sold_data(search_query, timeframe_days=timeframe_days)

        # Step 4: Web context
        web_context = self.tools.web_search(
            f"{query} popular 3D print figurine market demand 2025",
            num_results=4,
        )

        # Step 5: Score each product for recreation potential
        scored_items: list[dict] = []
        if items:
            scores = self._score_products_for_recreation(items, thingiverse_things, sold_data)
            for i, item in enumerate(items):
                score_data = scores.get(i + 1, {})
                scored_items.append({
                    **item,
                    "recreation_score":   score_data.get("score", 0),
                    "recreation_tier":    score_data.get("tier", "unknown"),
                    "recreation_reasons": score_data.get("reasons", []),
                    "meshy_prompt":       score_data.get("meshy_prompt", ""),
                    "redesign_ideas":     score_data.get("redesign_ideas", ""),
                })

        scored_items.sort(key=lambda x: x.get("recreation_score", 0), reverse=True)

        # Step 6: LLM summary with real metrics
        summary = self._generate_product_summary(
            query, scored_items, sold_data, thingiverse_things, timeframe_days,
            ebay_error=ebay_error, search_query=search_query,
        )

        return {
            "query":             query,
            "search_query":      search_query,
            "timeframe_days":    timeframe_days,
            "summary":           summary,
            "ranked_products":   scored_items,
            "total_results":     ebay_result.get("total_results", len(items)),
            "price_range":       ebay_result.get("price_range", {}),
            "demand_data":       sold_data,
            "thingiverse":       thingiverse_things,
            "thingiverse_total": thingiverse_result.get("total", 0),
            "web_context":       web_context,
            "ebay_error":        ebay_error,
            "started_at":        started_at,
            "completed_at":      datetime.now(timezone.utc).isoformat(),
        }

    async def research_and_rank_async(self, query: str, limit: int = 12, timeframe_days: int = 30) -> dict:
        return await asyncio.to_thread(self.research_and_rank, query, limit, timeframe_days)

    # ── Recreation scoring ────────────────────────────────────────────────────

    def _score_products_for_recreation(
        self,
        items: list[dict],
        thingiverse_things: list[dict] | None = None,
        sold_data: dict | None = None,
    ) -> dict[int, dict]:
        """
        Batch-score all items in a single LLM call.
        Returns a dict keyed by 1-based index.
        """
        product_list = [
            {
                "index":     i + 1,
                "title":     item.get("title", "")[:120],
                "category":  item.get("category", ""),
                "price":     item.get("price", ""),
                "condition": item.get("condition", ""),
            }
            for i, item in enumerate(items)
        ]

        thingiverse_context = ""
        if thingiverse_things:
            tv_summary = [
                {
                    "name":      t.get("name", "")[:80],
                    "likes":     t.get("likes", 0),
                    "downloads": t.get("downloads", 0),
                    "makes":     t.get("makes", 0),
                    "collects":  t.get("collects", 0),
                    "tags":      t.get("tags", [])[:5],
                }
                for t in thingiverse_things[:6]
            ]
            thingiverse_context = (
                f"\n\nThingiverse models for this category:\n"
                f"{json.dumps(tv_summary, indent=2)}\n"
                f"Use likes, downloads, and makes as evidence of 3D print demand and feasibility."
            )

        sold_context = ""
        if sold_data and sold_data.get("sold_count", 0) > 0:
            sold_context = (
                f"\n\neBay sold data ({sold_data.get('timeframe_days', 30)} days): "
                f"{sold_data['sold_count']} units sold — "
                f"avg ${sold_data.get('avg_sold_price', '?')} — "
                f"GMV ${sold_data.get('total_gmv', '?')}. "
                f"Factor this demand signal into your market opportunity score."
            )

        prompt = (
            f"Products to score:\n{json.dumps(product_list, indent=2)}"
            f"{thingiverse_context}"
            f"{sold_context}\n\n"
            "Return the JSON array of scores as specified."
        )

        resp = self._call_ollama(
            [
                {"role": "system", "content": _SCORER_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            use_tools=False,
        )
        content = (resp or {}).get("message", {}).get("content", "")
        raw     = _extract_json_array(content)

        result: dict[int, dict] = {}
        for entry in raw:
            idx = entry.get("index")
            if isinstance(idx, int):
                result[idx] = entry

        # Fallback: rule-based score for any items the LLM missed
        for i, item in enumerate(items):
            if (i + 1) not in result:
                result[i + 1] = _rule_score(item)

        return result

    def _generate_product_summary(
        self,
        query: str,
        products: list[dict],
        sold_data: dict,
        thingiverse_things: list[dict] | None = None,
        timeframe_days: int = 30,
        ebay_error: str | None = None,
        search_query: str | None = None,
    ) -> str:
        if not products:
            sq = search_query or query
            if ebay_error:
                return (
                    f"eBay API error for '{sq}': {ebay_error}\n\n"
                    f"Check that EBAY_APP_ID and EBAY_CERT_ID are set correctly in .env on Chauncy, "
                    f"then run: `sudo systemctl restart researcher`"
                )
            return (
                f"No eBay listings found for '{sq}'. "
                f"Try a more specific product name (e.g. 'mandalorian figure' instead of a full sentence)."
            )

        top3 = products[:3]
        top_titles = "\n".join(
            f"  {i+1}. {p['title'][:80]} — Score {p['recreation_score']}/10 — {p['price']}"
            for i, p in enumerate(top3)
        )
        demand = sold_data.get("demand_level", "unknown")

        sold_note = ""
        sold_count = sold_data.get("sold_count", 0)
        if sold_count > 0:
            sold_note = (
                f"\neBay sold data (last {timeframe_days} days): "
                f"{sold_count} units sold — "
                f"avg ${sold_data.get('avg_sold_price', '?')} — "
                f"GMV ${sold_data.get('total_gmv', '?')} {sold_data.get('currency', 'USD')}"
            )
        elif sold_data.get("total_in_timeframe", 0) == 0:
            sold_note = f"\neBay sold data: no completed sales found in the last {timeframe_days} days"

        tv_note = ""
        if thingiverse_things:
            top_tv = thingiverse_things[:3]
            tv_note = "\nTop Thingiverse models:\n" + "\n".join(
                f"  • {t.get('name','')[:60]} — {t.get('likes', 0)} likes, "
                f"{t.get('downloads', 0):,} downloads, {t.get('makes', 0)} makes"
                for t in top_tv
            )

        prompt = (
            f"You are THE RESEARCHER. Write a concise 3-paragraph market analysis for:\n"
            f"Query: {query}\n"
            f"Market demand: {demand}"
            f"{sold_note}\n"
            f"Top recreation candidates:\n{top_titles}"
            f"{tv_note}\n\n"
            f"Cover: (1) market overview with real sales numbers, "
            f"(2) Thingiverse evidence and download/like counts for feasibility, "
            f"(3) recommended Meshy AI approach. Be direct, use the actual numbers provided."
        )
        resp = self._call_ollama(
            [{"role": "user", "content": prompt}],
            use_tools=False,
        )
        return (resp or {}).get("message", {}).get("content", "")

    # ── Model info ────────────────────────────────────────────────────────────

    def get_model_info(self) -> dict:
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=8)
            if resp.status_code != 200:
                return {"status": "offline", "model": self.model, "model_ready": False}
            available = [m.get("name", "") for m in resp.json().get("models", [])]
            ready     = any(
                m == self.model or m.startswith(f"{self.model}:")
                for m in available
            )
            return {
                "status":           "online",
                "model":            self.model,
                "model_ready":      ready,
                "available_models": available,
                "pull_hint":        f"ollama pull {self.model}" if not ready else None,
            }
        except Exception as e:
            return {"status": "offline", "model": self.model, "model_ready": False, "error": str(e)}

    # ── Ollama API ────────────────────────────────────────────────────────────

    def _call_ollama(self, messages: list[dict], use_tools: bool = True) -> Optional[dict]:
        try:
            payload: dict[str, Any] = {
                "model":    self.model,
                "messages": messages,
                "stream":   False,
                "options":  {"temperature": 0.1, "num_predict": 2048},
            }
            if use_tools:
                payload["tools"] = TOOL_SCHEMAS
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.error("Ollama %s: %s", resp.status_code, resp.text[:300])
            return None
        except Exception as e:
            logger.error("Ollama call failed: %s", e)
            return None

    # ── Result builders ───────────────────────────────────────────────────────

    @staticmethod
    def _build_result(
        query: str, report: str, steps: list, sources: list,
        started_at: str, step_count: int,
    ) -> dict:
        return {
            "query":        query,
            "report":       report,
            "step_count":   step_count,
            "steps":        steps,
            "sources":      _dedupe_sources(sources),
            "started_at":   started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }


# ── Module helpers ─────────────────────────────────────────────────────────────

def _safe_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        r = json.loads(value)
        return r if isinstance(r, dict) else {}
    except Exception:
        return {}


def _extract_json_array(content: str) -> list:
    """Extract a JSON array from an LLM response that may contain markdown fences."""
    for attempt in [content, _strip_fence(content)]:
        try:
            r = json.loads(attempt)
            if isinstance(r, list):
                return r
        except Exception:
            pass
    # Fall back: find first [...] block
    m = re.search(r'\[[\s\S]*\]', content)
    if m:
        try:
            r = json.loads(m.group(0))
            if isinstance(r, list):
                return r
        except Exception:
            pass
    return []


def _strip_fence(text: str) -> str:
    m = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    return m.group(1) if m else text


def _rule_score(item: dict) -> dict:
    """Fast rule-based fallback when LLM scoring fails."""
    title    = (item.get("title",    "") or "").lower()
    category = (item.get("category", "") or "").lower()

    HIGH_KEYWORDS = {
        "figurine", "figure", "statue", "bust", "miniature", "mini", "diorama",
        "prop", "cosplay", "replica", "toy", "doll", "plush", "puppet",
        "pendant", "charm", "jewelry", "keychain", "decoration", "decor",
        "model", "sculpture", "ornament", "collectible", "action figure",
    }
    LOW_KEYWORDS  = {
        "shirt", "tshirt", "hoodie", "jacket", "clothing", "fabric",
        "phone", "tablet", "laptop", "electronic", "circuit", "battery",
        "book", "magazine", "poster", "print", "food", "snack", "drink",
    }

    score = 5  # default medium
    if any(k in title or k in category for k in HIGH_KEYWORDS):
        score = 8
    elif any(k in title or k in category for k in LOW_KEYWORDS):
        score = 2

    tier = "high" if score >= 7 else "medium" if score >= 4 else "low"
    return {
        "score":         score,
        "tier":          tier,
        "reasons":       ["rule-based estimate"],
        "meshy_prompt":  f"3D model of {item.get('title','product')[:60]}, detailed, game-ready",
        "redesign_ideas": "",
    }


def _summarize(tool_name: str, result: Any) -> str:
    if isinstance(result, list):
        return f"{len(result)} result(s)"
    if isinstance(result, dict):
        if result.get("error"):
            return f"error: {result['error']}"
        if tool_name == "thingiverse_search":
            return f"{result.get('showing', 0)}/{result.get('total', 0)} models found"
        if tool_name == "ebay_search":
            pr = result.get("price_range", {})
            return (
                f"{result.get('showing', 0)}/{result.get('total_results', 0)} listings — "
                f"avg {pr.get('currency','USD')} {pr.get('avg','?')}"
            )
        if tool_name == "ebay_sold_data":
            sc = result.get("sold_count", 0)
            gmv = result.get("total_gmv", "?")
            tf  = result.get("timeframe_days", 30)
            return f"{sc} sold in {tf}d — GMV ${gmv} — demand: {result.get('demand_level','?')}"
        if tool_name == "wikipedia_search":
            return f"article: {result.get('title','')} ({len(result.get('summary',''))} chars)"
        if tool_name == "fetch_page":
            return f"fetched {result.get('chars', 0)} chars"
    return str(result)[:120]


def _collect_sources(name: str, args: dict, result: Any, sources: list) -> None:
    if name == "web_search" and isinstance(result, list):
        for r in result:
            if r.get("url"):
                sources.append({"type": "web", "url": r["url"], "title": r.get("title", "")})
    elif name == "fetch_page" and isinstance(result, dict) and not result.get("error"):
        sources.append({"type": "page", "url": result.get("url", "")})
    elif name == "wikipedia_search" and isinstance(result, dict) and not result.get("error"):
        sources.append({"type": "wikipedia", "url": result.get("url", ""), "title": result.get("title", "")})
    elif name == "thingiverse_search" and isinstance(result, dict) and not result.get("error"):
        sources.append({"type": "thingiverse", "query": args.get("query", ""), "url": "https://www.thingiverse.com"})
    elif name in ("ebay_search", "ebay_sold_data") and isinstance(result, dict) and not result.get("error"):
        sources.append({"type": "ebay", "query": args.get("query", "")})


def _extract_search_query(query: str) -> str:
    """Strip conversational framing to get a clean product keyword search."""
    q = query.strip()
    # Remove leading instruction phrases
    q = re.sub(
        r'^(?:tell me(?: about)?|find me|show me|give me|what are|what is|list|find|'
        r'search for|look for|look up|research|get me|i want to see)\s+',
        '', q, flags=re.IGNORECASE,
    ).strip()
    # Remove "top N" / "best N" prefix
    q = re.sub(
        r'^(?:the\s+)?(?:top|best|popular|trending|most popular)\s+\d+\s+',
        '', q, flags=re.IGNORECASE,
    ).strip()
    q = re.sub(
        r'^(?:the\s+)?(?:top|best|popular|trending|hottest|newest)\s+',
        '', q, flags=re.IGNORECASE,
    ).strip()
    # Remove trailing filler words
    q = re.sub(
        r'\s+(?:for me|please|items?|products?|things?|listings?|on ebay|available)\.?$',
        '', q, flags=re.IGNORECASE,
    ).strip()
    return q if len(q) >= 3 else query


def _dedupe_sources(sources: list) -> list:
    seen: set[str] = set()
    out:  list[dict] = []
    for s in sources:
        key = s.get("url") or s.get("query") or str(s)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out
