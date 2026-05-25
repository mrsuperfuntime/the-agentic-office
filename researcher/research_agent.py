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

_CROSS_REF_PROMPT = """\
You are a product recreation analyst specializing in 3D printing opportunities.

Your job: cross-reference what SELLS on eBay with what can be 3D PRINTED on Thingiverse
to identify the highest-value recreation opportunities using Meshy AI.

The best opportunity = HIGH eBay demand × HIGH Thingiverse feasibility.

Score each opportunity 1-10 using:
  • eBay demand      — sold count, GMV, price point (higher = more market)
  • Print feasibility — Thingiverse downloads/makes/likes (higher = proven printable)
  • Meshy AI fit     — figurines, props, decor, toys, helmets score HIGH; electronics, fabric score LOW
  • Margin potential — custom/improved version vs commodity price

Tier definitions:
  HIGH   (7-10): proven market + proven printability + good Meshy fit
  MEDIUM (4-6):  one signal strong, other moderate
  LOW    (1-3):  weak demand or not printable

For the meshy_prompt field: use the eBay listing's short_description and image context to write a
specific, detailed Meshy AI prompt. Reference the actual object's shape, texture, color, style, and
key visual details seen in the listing. More specific = better 3D model output.

Respond ONLY with a valid JSON array, highest score first — no markdown, no text outside JSON:
[
  {
    "opportunity": "Short product category name (3-6 words max)",
    "score": 9,
    "tier": "high",
    "ebay_indices": [2, 5],
    "thingiverse_indices": [1, 3],
    "reasons": ["234 eBay sold in 30 days", "15K Thingiverse downloads proves print demand"],
    "meshy_prompt": "3D model of [specific shape/texture/colors from listing description], [art style], detailed surface normals, game-ready mesh, physically based rendering",
    "redesign_ideas": "Specific improvements: variant colorways, LED cavity, modular parts"
  }
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
          1. LLM expands query into 3 focused eBay search terms
          2. Multi-term eBay search — deduped results across all terms
          3. Thingiverse search — multiple angles on the topic
          4. Real eBay sold data via Finding API
          5. LLM batch recreation scoring with Meshy AI prompts
          6. Ranked product cards + summary
        """
        started_at   = datetime.now(timezone.utc).isoformat()
        search_query = _extract_search_query(query)
        if search_query != query:
            logger.info("Query cleaned: %r -> %r", query, search_query)

        # Step 1: Expand into specific product search terms
        search_terms = self._expand_product_queries(search_query)
        logger.info("eBay search terms: %s", search_terms)

        # Step 2: eBay active listings — search each term, dedupe by item_id
        all_items:  list[dict] = []
        seen_ids:   set[str]   = set()
        ebay_error: str | None = None
        all_price_ranges: list[dict] = []
        total_ebay_results = 0

        per_term_limit = max(6, limit // len(search_terms) + 2)
        for term in search_terms:
            result = self.tools.ebay_search(term, limit=per_term_limit)
            if result.get("error"):
                ebay_error = result["error"]
                logger.warning("eBay error for %r: %s", term, ebay_error)
                break
            for item in result.get("items", []):
                iid = item.get("item_id", "")
                if iid and iid not in seen_ids:
                    seen_ids.add(iid)
                    all_items.append(item)
            if result.get("price_range"):
                all_price_ranges.append(result["price_range"])
            total_ebay_results += result.get("total_results", 0)

        items = all_items[:limit]

        # Merged price range across all search terms
        price_range: dict = {}
        if all_price_ranges:
            all_vals = [float(pr["min"]) for pr in all_price_ranges if pr.get("min")]
            all_vals += [float(pr["max"]) for pr in all_price_ranges if pr.get("max")]
            all_avgs  = [float(pr["avg"]) for pr in all_price_ranges if pr.get("avg")]
            if all_vals:
                cur = all_price_ranges[0].get("currency", "USD")
                price_range = {
                    "min":      f"{min(all_vals):.2f}",
                    "max":      f"{max(all_vals):.2f}",
                    "avg":      f"{sum(all_avgs)/len(all_avgs):.2f}" if all_avgs else "?",
                    "currency": cur,
                }

        # Step 3: Thingiverse — context-aware terms focused on 3D printable items
        tv_terms = self._expand_thingiverse_queries(search_query, search_terms)
        logger.info("Thingiverse search terms: %s", tv_terms)
        tv_per_term = max(4, limit // max(len(tv_terms), 1) + 3)
        thingiverse_things: list[dict] = []
        thingiverse_error:  str | None = None
        tv_seen: set = set()
        for tv_term in tv_terms:
            tv_result = self.tools.thingiverse_search(tv_term, limit=tv_per_term, sort="popular")
            if tv_result.get("error"):
                thingiverse_error = tv_result["error"]
                logger.info("Thingiverse error for %r: %s", tv_term, thingiverse_error)
                break
            for t in tv_result.get("things", []):
                tid = t.get("id")
                if tid and tid not in tv_seen:
                    tv_seen.add(tid)
                    thingiverse_things.append(t)
        thingiverse_things.sort(key=lambda t: t.get("likes", 0) + t.get("downloads", 0) // 10, reverse=True)
        thingiverse_things = thingiverse_things[:limit]  # honour the slider

        # Step 4: Real eBay sold data (Finding API on primary term)
        sold_data = self.tools.ebay_sold_data(search_query, timeframe_days=timeframe_days)

        # Step 5: Cross-reference eBay demand × Thingiverse feasibility
        scored_items = self._cross_reference_score(items, thingiverse_things, sold_data)
        scored_items.sort(key=lambda x: x.get("recreation_score", 0), reverse=True)

        # Step 6: LLM summary
        summary = self._generate_product_summary(
            query, scored_items, sold_data, thingiverse_things, timeframe_days,
            ebay_error=ebay_error, search_query=search_query,
            search_terms=search_terms, tv_terms=tv_terms,
        )

        # Step 7: Action plan — top 3 concrete "what to make" recommendations
        action_plan = _build_action_plan(scored_items, sold_data)

        return {
            "query":               query,
            "search_query":        search_query,
            "search_terms":        search_terms,
            "tv_terms":            tv_terms,
            "timeframe_days":      timeframe_days,
            "summary":             summary,
            "action_plan":         action_plan,
            "ranked_products":     scored_items,
            "total_results":       total_ebay_results,
            "price_range":         price_range,
            "demand_data":         sold_data,
            "thingiverse":         thingiverse_things,
            "thingiverse_total":   len(thingiverse_things),
            "ebay_error":          ebay_error,
            "thingiverse_error":   thingiverse_error,
            "started_at":          started_at,
            "completed_at":        datetime.now(timezone.utc).isoformat(),
        }

    async def research_and_rank_async(self, query: str, limit: int = 12, timeframe_days: int = 30) -> dict:
        return await asyncio.to_thread(self.research_and_rank, query, limit, timeframe_days)

    # ── Query expansion ───────────────────────────────────────────────────────

    def _expand_product_queries(self, query: str, n: int = 3) -> list[str]:
        """Ask the LLM to generate n focused eBay search terms from a broad query."""
        resp = self._call_ollama(
            [
                {
                    "role": "system",
                    "content": (
                        "You generate specific eBay product search keywords. "
                        "Return ONLY a valid JSON array of strings — no explanation, no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Generate {n} specific eBay search terms for the topic: '{query}'\n"
                        f"Focus on physical collectibles, figures, replicas, props, and toys "
                        f"that could be 3D printed or recreated with Meshy AI.\n"
                        f"Example for 'star wars': [\"star wars action figure\", \"star wars helmet replica\", \"star wars funko pop\"]\n"
                        f"Return JSON array only."
                    ),
                },
            ],
            use_tools=False,
        )
        content = (resp or {}).get("message", {}).get("content", "")
        # Try direct parse
        try:
            terms = json.loads(content.strip())
            if isinstance(terms, list):
                clean = [str(t).strip() for t in terms if str(t).strip()]
                if clean:
                    return clean[:n]
        except Exception:
            pass
        # Fall back to extracting the first JSON array found
        arr = _extract_json_array(content)
        if arr:
            clean = [str(t).strip() for t in arr if str(t).strip()]
            if clean:
                return clean[:n]
        # Last resort: just use the original query
        logger.warning("Query expansion failed for %r, using original", query)
        return [query]

    def _expand_thingiverse_queries(self, query: str, ebay_terms: list[str], n: int = 3) -> list[str]:
        """
        Generate Thingiverse search terms focused on 3D PRINTABLE items in the same
        category/theme as the query — NOT just repeating the eBay product terms.
        E.g. 'shohei ohtani' → ['baseball card display stand', 'baseball helmet replica', 'baseball trophy']
        """
        resp = self._call_ollama(
            [
                {
                    "role": "system",
                    "content": (
                        "You generate Thingiverse search keywords for 3D printable items. "
                        "Return ONLY a valid JSON array of strings — no explanation, no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: '{query}'\n"
                        f"eBay context (what people buy): {ebay_terms}\n\n"
                        f"Generate {n} Thingiverse search terms for 3D PRINTABLE items a fan or collector "
                        f"would want to make related to this topic.\n"
                        f"Think about the SPORT, FRANCHISE, or THEME — not just the specific person or item.\n"
                        f"Focus on: display stands, holders, organizers, helmets, busts, figurines, props, "
                        f"trophies, wall mounts, and accessories.\n"
                        f"Examples:\n"
                        f"  'shohei ohtani' → [\"baseball card display stand\", \"baseball helmet replica\", \"baseball bat wall mount\"]\n"
                        f"  'mandalorian'   → [\"mandalorian helmet\", \"star wars figurine\", \"beskar armor prop\"]\n"
                        f"  'pokemon'       → [\"pokemon figure\", \"pokeball display case\", \"pokedex prop\"]\n"
                        f"Return JSON array only."
                    ),
                },
            ],
            use_tools=False,
        )
        content = (resp or {}).get("message", {}).get("content", "")
        try:
            terms = json.loads(content.strip())
            if isinstance(terms, list):
                clean = [str(t).strip() for t in terms if str(t).strip()]
                if clean:
                    return clean[:n]
        except Exception:
            pass
        arr = _extract_json_array(content)
        if arr:
            clean = [str(t).strip() for t in arr if str(t).strip()]
            if clean:
                return clean[:n]
        logger.warning("Thingiverse query expansion failed for %r, using original", query)
        return [query]

    # ── Cross-platform opportunity scoring ───────────────────────────────────

    def _cross_reference_score(
        self,
        ebay_items: list[dict],
        thingiverse_things: list[dict],
        sold_data: dict,
    ) -> list[dict]:
        """
        Cross-reference eBay demand with Thingiverse feasibility to produce a
        ranked list of recreation opportunities. Each opportunity links the
        best matching eBay listing and Thingiverse model as evidence.
        """
        ebay_list = [
            {
                "index":             i + 1,
                "title":             item.get("title", "")[:100],
                "price":             item.get("price", ""),
                "category":          item.get("category", ""),
                "short_description": (item.get("short_description") or "")[:200],
                "image_url":         item.get("image_url", ""),
            }
            for i, item in enumerate(ebay_items)
        ]
        tv_list = [
            {
                "index":     i + 1,
                "name":      t.get("name", "")[:80],
                "likes":     t.get("likes", 0),
                "downloads": t.get("downloads", 0),
                "makes":     t.get("makes", 0),
                "tags":      t.get("tags", [])[:4],
            }
            for i, t in enumerate(thingiverse_things)
        ]

        sold_context = ""
        if sold_data.get("sold_count", 0) > 0:
            sold_context = (
                f"\neBay sold data ({sold_data.get('timeframe_days', 30)} days): "
                f"{sold_data['sold_count']} units sold — "
                f"avg ${sold_data.get('avg_sold_price', '?')} — "
                f"GMV ${sold_data.get('total_gmv', '?')}"
            )

        prompt = (
            f"eBay listings (market demand):\n{json.dumps(ebay_list, indent=2)}\n\n"
            f"Thingiverse models (print feasibility):\n{json.dumps(tv_list, indent=2)}"
            f"{sold_context}\n\n"
            "Identify and return the top recreation opportunities, highest score first."
        )

        resp = self._call_ollama(
            [
                {"role": "system", "content": _CROSS_REF_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            use_tools=False,
        )
        content      = (resp or {}).get("message", {}).get("content", "")
        opportunities = _extract_json_array(content)

        result: list[dict] = []
        covered_ebay: set[int] = set()

        for opp in opportunities:
            if not isinstance(opp, dict):
                continue
            # Resolve eBay listing reference
            ebay_idxs = [i - 1 for i in (opp.get("ebay_indices") or []) if isinstance(i, int)]
            ebay_item = ebay_items[ebay_idxs[0]] if ebay_idxs and ebay_idxs[0] < len(ebay_items) else {}
            for idx in ebay_idxs:
                covered_ebay.add(idx)

            # Resolve Thingiverse model reference
            tv_idxs = [i - 1 for i in (opp.get("thingiverse_indices") or []) if isinstance(i, int)]
            tv_item = thingiverse_things[tv_idxs[0]] if tv_idxs and tv_idxs[0] < len(thingiverse_things) else {}

            result.append({
                **ebay_item,
                "opportunity":        opp.get("opportunity", ebay_item.get("title", "")[:60]),
                "recreation_score":   int(opp.get("score", 5)),
                "recreation_tier":    opp.get("tier", "medium"),
                "recreation_reasons": opp.get("reasons", []),
                "meshy_prompt":       opp.get("meshy_prompt", ""),
                "redesign_ideas":     opp.get("redesign_ideas", ""),
                "tv_name":            tv_item.get("name", ""),
                "tv_url":             tv_item.get("url", ""),
                "tv_thumbnail":       tv_item.get("thumbnail", ""),
                "tv_likes":           tv_item.get("likes", 0),
                "tv_downloads":       tv_item.get("downloads", 0),
                "tv_makes":           tv_item.get("makes", 0),
            })

        # Fallback: add any eBay items not referenced by the LLM
        for i, item in enumerate(ebay_items):
            if i not in covered_ebay and len(result) < max(len(ebay_items), 8):
                s = _rule_score(item)
                result.append({
                    **item,
                    "opportunity":        item.get("title", "")[:60],
                    "recreation_score":   s["score"],
                    "recreation_tier":    s["tier"],
                    "recreation_reasons": s["reasons"],
                    "meshy_prompt":       s["meshy_prompt"],
                    "redesign_ideas":     "",
                    "tv_name": "", "tv_url": "", "tv_thumbnail": "",
                    "tv_likes": 0, "tv_downloads": 0, "tv_makes": 0,
                })

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
        search_terms: list[str] | None = None,
        tv_terms: list[str] | None = None,
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

        top5 = products[:5]
        top_titles = "\n".join(
            f"  {i+1}. {p['title'][:80]} — Score {p['recreation_score']}/10 — {p['price']}"
            for i, p in enumerate(top5)
        )
        demand = sold_data.get("demand_level", "unknown")

        terms_note = ""
        if search_terms and len(search_terms) > 1:
            terms_note = f"\nSearched eBay for: {', '.join(search_terms)}"

        sold_note = ""
        sold_count = sold_data.get("sold_count", 0)
        if sold_count > 0:
            sold_note = (
                f"\neBay sold data (last {timeframe_days} days): "
                f"{sold_count} units sold — "
                f"avg ${sold_data.get('avg_sold_price', '?')} — "
                f"total GMV ${sold_data.get('total_gmv', '?')} {sold_data.get('currency', 'USD')}"
            )
        else:
            sold_note = f"\neBay sold data: no completed sales found in last {timeframe_days} days"

        tv_note = ""
        if thingiverse_things:
            tv_note = "\nThingiverse models found:\n" + "\n".join(
                f"  • {t.get('name','')[:60]} — "
                f"{t.get('likes', 0):,} likes, {t.get('downloads', 0):,} downloads, {t.get('makes', 0)} makes"
                for t in thingiverse_things[:5]
            )
        else:
            tv_note = "\nThingiverse: no models found for this query"

        prompt = (
            f"You are THE RESEARCHER. Write a concise 3-paragraph market analysis for: '{query}'"
            f"{terms_note}\n"
            f"Market demand: {demand}{sold_note}\n"
            f"Top recreation candidates:\n{top_titles}\n"
            f"{tv_note}\n\n"
            f"Cover: (1) market size and demand using real sold numbers, "
            f"(2) Thingiverse evidence with specific like/download counts for recreation feasibility, "
            f"(3) top 2-3 specific recommendations for Meshy AI recreation. "
            f"Be direct and use the actual numbers provided."
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


def _build_action_plan(scored_items: list[dict], sold_data: dict) -> list[dict]:
    """
    Build a top-3 action plan from already-scored products.
    Returns structured dicts suitable for the UI ACTION PLAN section.
    No extra LLM call — derived from cross-reference scoring output.
    """
    candidates = [p for p in scored_items if p.get("recreation_score", 0) >= 4]
    if not candidates:
        candidates = scored_items  # fall back to all if none score high enough
    top3 = candidates[:3]

    sold_count = sold_data.get("sold_count", 0)
    avg_price  = sold_data.get("avg_sold_price")
    gmv        = sold_data.get("total_gmv")
    tf         = sold_data.get("timeframe_days", 30)

    market_note = ""
    if sold_count > 0 and avg_price:
        market_note = f"{sold_count} sold in {tf}d @ avg ${avg_price}"
        if gmv:
            market_note += f" (${gmv} GMV)"

    plan: list[dict] = []
    for i, item in enumerate(top3):
        reasons = item.get("recreation_reasons") or []
        reason_str = "; ".join(str(r) for r in reasons[:2]) if reasons else ""
        if market_note and i == 0:
            reason_str = (market_note + " — " + reason_str) if reason_str else market_note

        plan.append({
            "rank":          i + 1,
            "make":          item.get("opportunity") or item.get("title", "Unknown")[:60],
            "why":           reason_str or f"Recreation score {item.get('recreation_score', 0)}/10",
            "score":         item.get("recreation_score", 0),
            "tier":          item.get("recreation_tier", "medium"),
            "price_ref":     item.get("price", ""),
            "meshy_prompt":  item.get("meshy_prompt", ""),
            "redesign_ideas": item.get("redesign_ideas", ""),
            "ebay_url":      item.get("url", ""),
            "tv_url":        item.get("tv_url", ""),
            "tv_name":       item.get("tv_name", ""),
            "image_url":     item.get("image_url", ""),
        })
    return plan


def _dedupe_sources(sources: list) -> list:
    seen: set[str] = set()
    out:  list[dict] = []
    for s in sources:
        key = s.get("url") or s.get("query") or str(s)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out
