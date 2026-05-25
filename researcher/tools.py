"""
Research tools — web search, page fetch, Wikipedia, eBay (rich product data + sold research)
All tools return serializable dicts/lists for the agent loop.
"""
import base64
import logging
import os
import time
from typing import Any
from urllib.parse import quote as url_quote

import requests

logger = logging.getLogger(__name__)

# ── Ollama tool schemas ────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "thingiverse_search",
            "description": (
                "Search Thingiverse for existing 3D printable models. "
                "Returns model names, thumbnails, creator info, like/collect counts, and direct URLs. "
                "Use this to find existing 3D models related to a product or topic and assess "
                "recreation feasibility — high like counts mean the design is proven and in demand."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query for 3D models"},
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (1-20)",
                        "default": 8,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information, news, articles, or product data. "
                "Use this to find up-to-date facts and sources."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (1-10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Fetch the full text content of a specific web page by URL. "
                "Use this to read articles, product pages, or any URL found in search results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia_search",
            "description": (
                "Look up a topic on Wikipedia for background knowledge, definitions, or history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The topic to search on Wikipedia"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ebay_search",
            "description": (
                "Search eBay for product listings with full details: images, prices, "
                "categories, seller ratings, and availability. "
                "Use for market research, pricing intelligence, and product discovery."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Product search query"},
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (1-20)",
                        "default": 12,
                    },
                    "condition": {
                        "type": "string",
                        "description": "Filter by condition: 'new', 'used', or 'all'",
                        "default": "all",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ebay_sold_research",
            "description": (
                "Research eBay sold/completed listings and market demand for a product. "
                "Returns sales velocity signals, price trends, and demand indicators. "
                "Use this after ebay_search to understand how well products actually sell."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Product to research sold data for"},
                },
                "required": ["query"],
            },
        },
    },
]


# ── Tool implementations ───────────────────────────────────────────────────────

class ResearchTools:
    def __init__(self):
        self.ebay_app_id  = os.getenv("EBAY_APP_ID",  "").strip()
        self.ebay_cert_id = os.getenv("EBAY_CERT_ID", "").strip()
        self.ebay_env     = os.getenv("EBAY_ENV", "production").lower()
        self._ebay_token: str  = ""
        self._ebay_token_expiry: float = 0.0

        self.thingiverse_token = os.getenv("THINGIVERSE_TOKEN", "").strip()

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        })

    # ── Web search ────────────────────────────────────────────────────────────

    def web_search(self, query: str, num_results: int = 5) -> list[dict]:
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=min(max(1, num_results), 10)))
            return [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("href",  ""),
                    "snippet": r.get("body",  ""),
                }
                for r in raw
            ]
        except Exception as e:
            logger.error("web_search error: %s", e)
            return [{"error": str(e)}]

    # ── Page fetch ────────────────────────────────────────────────────────────

    def fetch_page(self, url: str) -> dict:
        try:
            from bs4 import BeautifulSoup
            resp = self._session.get(url, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            lines   = [ln.strip() for ln in soup.get_text(separator="\n").splitlines() if ln.strip()]
            content = "\n".join(lines)[:5000]
            return {"url": url, "content": content, "chars": len(content)}
        except Exception as e:
            logger.error("fetch_page error for %s: %s", url, e)
            return {"url": url, "error": str(e)}

    # ── Wikipedia ─────────────────────────────────────────────────────────────

    def wikipedia_search(self, topic: str) -> dict:
        try:
            search = self._session.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": topic, "limit": 3, "format": "json"},
                timeout=10,
            )
            data = search.json()
            if not data[1]:
                return {"topic": topic, "error": "No Wikipedia article found"}

            title   = data[1][0]
            summary = self._session.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{url_quote(title)}",
                timeout=10,
            )
            s = summary.json()
            return {
                "title":       s.get("title", title),
                "description": s.get("description", ""),
                "summary":     s.get("extract", ""),
                "url": s.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
        except Exception as e:
            logger.error("wikipedia_search error: %s", e)
            return {"topic": topic, "error": str(e)}

    # ── Thingiverse ──────────────────────────────────────────────────────

    def thingiverse_search(self, query: str, limit: int = 8) -> dict:
        if not self.thingiverse_token:
            return {
                "error": "Thingiverse token not configured",
                "hint":  "Set THINGIVERSE_TOKEN in .env — get it at https://www.thingiverse.com/developers",
            }
        try:
            resp = self._session.get(
                f"https://api.thingiverse.com/search/{url_quote(query)}",
                headers={"Authorization": f"Bearer {self.thingiverse_token}"},
                params={"per_page": min(max(1, limit), 20), "page": 1, "type": "things", "sort": "popular"},
                timeout=15,
            )
            if resp.status_code == 401:
                return {"error": "Thingiverse token invalid or expired — regenerate at thingiverse.com/developers"}
            if resp.status_code == 403:
                return {"error": "Thingiverse rate-limited or forbidden", "detail": resp.text[:200]}
            if resp.status_code != 200:
                return {"error": f"Thingiverse API returned {resp.status_code}", "detail": resp.text[:300]}

            raw = resp.json()
            things = raw if isinstance(raw, list) else raw.get("hits", raw.get("things", []))

            parsed: list[dict] = []
            for t in things[:limit]:
                creator = t.get("creator") or {}
                tags    = [tg.get("name", "") for tg in (t.get("tags") or [])[:8] if tg.get("name")]
                parsed.append({
                    "id":           t.get("id"),
                    "name":         t.get("name", ""),
                    "thumbnail":    t.get("thumbnail", ""),
                    "url":          t.get("public_url") or f"https://www.thingiverse.com/thing:{t.get('id')}",
                    "creator":      creator.get("name", ""),
                    "likes":        int(t.get("like_count", 0) or 0),
                    "collects":     int(t.get("collect_count", 0) or 0),
                    "comments":     int(t.get("comment_count", 0) or 0),
                    "tags":         tags,
                    "is_printable": bool(t.get("is_printable", True)),
                })

            return {
                "query":   query,
                "total":   len(things),
                "showing": len(parsed),
                "things":  parsed,
            }
        except Exception as e:
            logger.error("thingiverse_search error: %s", e)
            return {"error": str(e)}

    # ── eBay search (rich) ────────────────────────────────────────────────────

    def ebay_search(self, query: str, limit: int = 12, condition: str = "all") -> dict:
        if not self.ebay_app_id or not self.ebay_cert_id:
            return {
                "error": "eBay credentials not configured",
                "hint":  "Set EBAY_APP_ID and EBAY_CERT_ID in .env to enable eBay research",
                "docs":  "https://developer.ebay.com/api-docs/static/oauth-client-credentials-grant.html",
            }

        token = self._get_ebay_token()
        if not token:
            return {"error": "Failed to obtain eBay OAuth token — check EBAY_APP_ID and EBAY_CERT_ID"}

        try:
            base   = "https://api.sandbox.ebay.com" if self.ebay_env == "sandbox" else "https://api.ebay.com"
            params: dict[str, Any] = {
                "q":           query,
                "limit":       min(max(1, limit), 20),
                "fieldgroups": "MATCHING_ITEMS,EXTENDED",
            }
            if condition == "new":
                params["filter"] = "conditionIds:{1000}"
            elif condition == "used":
                params["filter"] = "conditionIds:{3000|4000|5000|6000}"

            resp = self._session.get(
                f"{base}/buy/browse/v1/item_summary/search",
                headers={
                    "Authorization":          f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                },
                params=params,
                timeout=15,
            )

            if resp.status_code != 200:
                return {"error": f"eBay API returned {resp.status_code}", "detail": resp.text[:300]}

            data   = resp.json()
            items  = data.get("itemSummaries", [])
            parsed: list[dict] = []
            prices: list[float] = []

            for item in items:
                price_obj   = item.get("price", {})
                price_float = _safe_float(price_obj.get("value", 0))
                prices.append(price_float)

                # Images — prefer high-res, fall back to thumbnail
                main_image = (
                    item.get("image", {}).get("imageUrl")
                    or _first(item.get("thumbnailImages"), "imageUrl")
                    or ""
                )
                thumbnails = [
                    t.get("imageUrl", "")
                    for t in (item.get("additionalImages") or [])
                    if t.get("imageUrl")
                ]

                # Category
                categories = item.get("categories") or []
                category   = categories[0].get("categoryName", "") if categories else ""

                # Seller
                seller      = item.get("seller", {})
                seller_name = seller.get("username", "")
                feedback_pct = seller.get("feedbackPercentage", "")
                feedback_score = seller.get("feedbackScore", 0)

                # Availability (from estimatedAvailabilities if present)
                avail_list = item.get("estimatedAvailabilities") or []
                avail_qty  = None
                if avail_list:
                    avail_qty = avail_list[0].get("estimatedAvailableQuantity")

                parsed.append({
                    "item_id":          item.get("itemId", ""),
                    "title":            item.get("title", ""),
                    "price":            f"{price_obj.get('currency','USD')} {price_obj.get('value','?')}",
                    "price_value":      price_float,
                    "currency":         price_obj.get("currency", "USD"),
                    "condition":        item.get("condition", ""),
                    "category":         category,
                    "image_url":        main_image,
                    "extra_images":     thumbnails[:3],
                    "short_description": item.get("shortDescription", ""),
                    "seller":           seller_name,
                    "seller_feedback":  f"{feedback_pct}% ({feedback_score})",
                    "available_qty":    avail_qty,
                    "buying_options":   item.get("buyingOptions", []),
                    "top_rated":        item.get("topRatedBuyingExperience", False),
                    "location":         item.get("itemLocation", {}).get("country", ""),
                    "url":              item.get("itemWebUrl", ""),
                })

            price_range: dict = {}
            if prices:
                currency = (items[0].get("price", {}).get("currency", "USD") if items else "USD")
                price_range = {
                    "min":      f"{min(prices):.2f}",
                    "max":      f"{max(prices):.2f}",
                    "avg":      f"{sum(prices)/len(prices):.2f}",
                    "median":   f"{sorted(prices)[len(prices)//2]:.2f}",
                    "currency": currency,
                }

            return {
                "query":         query,
                "total_results": data.get("total", len(parsed)),
                "showing":       len(parsed),
                "price_range":   price_range,
                "items":         parsed,
            }
        except Exception as e:
            logger.error("ebay_search error: %s", e)
            return {"error": str(e)}

    # ── eBay sold / demand research ───────────────────────────────────────────

    def ebay_sold_research(self, query: str) -> dict:
        """
        Estimate sales velocity and demand by scraping web results for
        eBay sold/completed listings. No extra API credentials needed.
        """
        sold_results  = self.web_search(f'ebay sold completed "{query}" price', num_results=6)
        trend_results = self.web_search(f'"{query}" how many sold ebay demand popularity 2025', num_results=4)

        # Heuristic demand signal from result count & snippets
        demand_words = {"sold", "popular", "trending", "high demand", "selling fast", "best seller", "hot item"}
        supply_words = {"overstocked", "slow", "low demand", "clearance", "unsold"}

        demand_hits  = 0
        supply_hits  = 0
        price_mentions: list[float] = []

        import re
        for r in sold_results + trend_results:
            snippet = (r.get("snippet") or "").lower()
            demand_hits += sum(1 for w in demand_words if w in snippet)
            supply_hits += sum(1 for w in supply_words if w in snippet)
            for m in re.findall(r'\$\s*(\d+(?:\.\d{1,2})?)', snippet):
                try:
                    price_mentions.append(float(m))
                except ValueError:
                    pass

        if demand_hits > supply_hits + 1:
            demand_level = "high"
        elif supply_hits > demand_hits:
            demand_level = "low"
        else:
            demand_level = "medium"

        sold_price_range: dict = {}
        if price_mentions:
            sold_price_range = {
                "min": f"{min(price_mentions):.2f}",
                "max": f"{max(price_mentions):.2f}",
                "avg": f"{sum(price_mentions)/len(price_mentions):.2f}",
            }

        return {
            "query":           query,
            "demand_level":    demand_level,
            "demand_signals":  demand_hits,
            "supply_signals":  supply_hits,
            "sold_price_range": sold_price_range,
            "sources":         sold_results[:4],
        }

    # ── eBay token ────────────────────────────────────────────────────────────

    def _get_ebay_token(self) -> str:
        if self._ebay_token and time.time() < self._ebay_token_expiry:
            return self._ebay_token
        try:
            creds = base64.b64encode(f"{self.ebay_app_id}:{self.ebay_cert_id}".encode()).decode()
            base  = "https://api.sandbox.ebay.com" if self.ebay_env == "sandbox" else "https://api.ebay.com"
            resp  = requests.post(
                f"{base}/identity/v1/oauth2/token",
                headers={
                    "Content-Type":  "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {creds}",
                },
                data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
                timeout=10,
            )
            if resp.status_code == 200:
                d = resp.json()
                self._ebay_token        = d.get("access_token", "")
                self._ebay_token_expiry = time.time() + d.get("expires_in", 7200) - 300
                return self._ebay_token
        except Exception as e:
            logger.error("eBay token error: %s", e)
        return ""

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def dispatch(self, name: str, args: dict) -> Any:
        if name == "web_search":
            return self.web_search(args.get("query", ""), int(args.get("num_results", 5)))
        if name == "fetch_page":
            return self.fetch_page(args.get("url", ""))
        if name == "wikipedia_search":
            return self.wikipedia_search(args.get("topic", ""))
        if name == "thingiverse_search":
            return self.thingiverse_search(args.get("query", ""), int(args.get("limit", 8)))
        if name == "ebay_search":
            return self.ebay_search(
                args.get("query", ""),
                int(args.get("limit", 12)),
                args.get("condition", "all"),
            )
        if name == "ebay_sold_research":
            return self.ebay_sold_research(args.get("query", ""))
        return {"error": f"Unknown tool: {name}"}


# ── Module helpers ─────────────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(lst: list | None, key: str) -> str:
    if lst:
        return (lst[0] or {}).get(key, "")
    return ""
