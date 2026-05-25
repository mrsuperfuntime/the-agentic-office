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
• thingiverse_search  — find existing 3D printable models on Thingiverse (like counts = demand signal)
• ebay_search         — search eBay for product listings with images and pricing
• ebay_sold_research  — research actual sales velocity and demand signals

Research process
────────────────
1. Break the request into specific searches
2. Use ebay_search to find products — it returns images, categories, and pricing
3. Use ebay_sold_research to understand demand and sales history
4. Use thingiverse_search to find existing 3D models — high like counts confirm recreation feasibility
5. Use web_search for broader market context
6. Synthesize everything into a structured, cited report

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

    def research_and_rank(self, query: str, limit: int = 12) -> dict:
        """
        Full product research pipeline:
          1. eBay search for rich product data (images, prices, categories)
          2. Thingiverse search for existing 3D models (feasibility + demand signal)
          3. Sold-demand research for market signals
          4. LLM batch recreation scoring with Meshy AI prompts
          5. Ranked product cards
        """
        started_at = datetime.now(timezone.utc).isoformat()

        # Step 1: eBay listings
        ebay_result = self.tools.ebay_search(query, limit=limit)
        items       = ebay_result.get("items", [])
        ebay_error  = ebay_result.get("error")

        # Step 2: Thingiverse models for this query
        thingiverse_result = self.tools.thingiverse_search(query, limit=8)
        thingiverse_things = thingiverse_result.get("things", [])
        thingiverse_error  = thingiverse_result.get("error")
        if thingiverse_error:
            logger.info("Thingiverse: %s", thingiverse_error)

        # Step 3: Sold / demand signals
        sold_data = {}
        if items:
            sold_data = self.tools.ebay_sold_research(query)

        # Step 4: Web context
        web_context = self.tools.web_search(
            f"{query} popular 3D print figurine market 2025",
            num_results=4,
        )

        # Step 5: Score each product for recreation potential (with Thingiverse context)
        scored_items: list[dict] = []
        if items:
            scores = self._score_products_for_recreation(items, thingiverse_things)
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

        # Step 6: LLM summary
        summary = self._generate_product_summary(query, scored_items, sold_data, thingiverse_things)

        return {
            "query":             query,
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

    async def research_and_rank_async(self, query: str, limit: int = 12) -> dict:
        return await asyncio.to_thread(self.research_and_rank, query, limit)

    # ── Recreation scoring ────────────────────────────────────────────────────

    def _score_products_for_recreation(
        self, items: list[dict], thingiverse_things: list[dict] | None = None
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
                    "name":     t.get("name", "")[:80],
                    "likes":    t.get("likes", 0),
                    "collects": t.get("collects", 0),
                    "tags":     t.get("tags", [])[:5],
                }
                for t in thingiverse_things[:6]
            ]
            thingiverse_context = (
                f"\n\nThingiverse models already available for this product category:\n"
                f"{json.dumps(tv_summary, indent=2)}\n"
                f"Use like/collect counts as evidence of 3D print demand and feasibility."
            )

        prompt = (
            f"Products to score:\n{json.dumps(product_list, indent=2)}"
            f"{thingiverse_context}\n\n"
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
    ) -> str:
        if not products:
            return f"No eBay listings found for '{query}'. Try a different search term or check eBay API credentials."

        top3 = products[:3]
        top_titles = "\n".join(
            f"  {i+1}. {p['title'][:80]} — Score {p['recreation_score']}/10 — {p['price']}"
            for i, p in enumerate(top3)
        )
        demand = sold_data.get("demand_level", "unknown")

        tv_note = ""
        if thingiverse_things:
            top_tv = thingiverse_things[:3]
            tv_note = "\nTop Thingiverse models found:\n" + "\n".join(
                f"  • {t.get('name','')[:60]} — {t.get('likes', 0)} likes"
                for t in top_tv
            )

        prompt = (
            f"You are THE RESEARCHER. Write a concise 3-paragraph analysis for:\n"
            f"Query: {query}\n"
            f"Demand level: {demand}\n"
            f"Top recreation candidates:\n{top_titles}"
            f"{tv_note}\n\n"
            f"Cover: market overview, Thingiverse evidence for recreation feasibility, "
            f"and recommended approach using Meshy AI. Be direct and actionable."
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
        if tool_name == "ebay_sold_research":
            return f"demand: {result.get('demand_level','?')}"
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
    elif name in ("ebay_search", "ebay_sold_research") and isinstance(result, dict) and not result.get("error"):
        sources.append({"type": "ebay", "query": args.get("query", "")})


def _dedupe_sources(sources: list) -> list:
    seen: set[str] = set()
    out:  list[dict] = []
    for s in sources:
        key = s.get("url") or s.get("query") or str(s)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out
