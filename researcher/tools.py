"""
Research tools — web search, page fetch, Wikipedia, eBay (rich product data + sold research)
All tools return serializable dicts/lists for the agent loop.
"""
import base64
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote as url_quote

import requests
from pathlib import Path

logger = logging.getLogger(__name__)

# Re-load .env by explicit path in case this module is imported before main.py
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(dotenv_path=Path(__file__).parent / ".env")
except Exception:
    pass

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
                    "sort": {
                        "type": "string",
                        "description": "Sort order: 'popular' (default), 'newest', 'makes', 'derivatives'",
                        "default": "popular",
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
            "name": "ebay_sold_data",
            "description": (
                "Fetch real eBay completed/sold listing data via the eBay Finding API. "
                "Returns actual sold count, average sold price, min/max prices, and total GMV "
                "for a given timeframe. Use this after ebay_search to understand true sales velocity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Product to look up sold data for"},
                    "timeframe_days": {
                        "type": "integer",
                        "description": "How many days back to search for sold listings (7, 30, 90, 180)",
                        "default": 30,
                    },
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

    def _thingiverse_thing_detail(self, thing_id: int) -> dict:
        """Fetch full detail for one Thingiverse thing — dates + all stats."""
        try:
            resp = self._session.get(
                f"https://api.thingiverse.com/things/{thing_id}",
                headers={"Authorization": f"Bearer {self.thingiverse_token}"},
                timeout=8,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def thingiverse_enrich_dates(self, things: list[dict], max_workers: int = 8) -> list[dict]:
        """
        Batch-fetch full thing details for all results concurrently.
        Populates: added date, view_count, remix_count, comment_count, and
        verifies like/download/makes counts from the authoritative detail endpoint.
        """
        if not things:
            return things

        logger.info("Enriching %d things with full details (concurrent)", len(things))
        detail_map: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._thingiverse_thing_detail, t["id"]): t["id"]
                       for t in things if t.get("id")}
            for future in as_completed(futures):
                tid = futures[future]
                try:
                    detail_map[tid] = future.result()
                except Exception:
                    detail_map[tid] = {}

        for t in things:
            d = detail_map.get(t.get("id"), {})
            if not d:
                continue
            # Dates
            raw_date = d.get("added") or d.get("created_at") or d.get("published_at") or ""
            t["added"] = raw_date[:10]
            # Richer stats from authoritative source
            t["likes"]     = int(d.get("like_count",     t.get("likes",     0)) or 0)
            t["downloads"] = int(d.get("download_count", t.get("downloads", 0)) or 0)
            t["makes"]     = int(d.get("makes_count",    t.get("makes",     0)) or 0)
            t["comments"]  = int(d.get("comment_count",  t.get("comments",  0)) or 0)
            t["views"]     = int(d.get("view_count",     0) or 0)
            t["remixes"]   = int(d.get("remix_count",    0) or 0)
            t["collects"]  = int(d.get("collect_count",  t.get("collects",  0)) or 0)

        found = sum(1 for d in detail_map.values() if d)
        logger.info("Enrichment complete: %d/%d things returned detail", found, len(things))
        return things

    def thingiverse_search(self, query: str, limit: int = 8, sort: str = "relevant", page: int = 1) -> dict:
        if not self.thingiverse_token:
            return {
                "error": "Thingiverse token not configured",
                "hint":  "Set THINGIVERSE_TOKEN in .env — get it at https://www.thingiverse.com/developers",
            }
        # Fetch by relevance from the API — caller handles sorting client-side.
        # Sending sort=popular/makes to Thingiverse overrides relevance entirely and
        # returns globally trending models (benchie etc.) regardless of the search query.
        # Exception: "newest" is passed through because it controls chronological order.
        api_sort = "newest" if sort == "newest" else None
        params: dict = {"per_page": min(max(1, limit), 20), "page": page, "type": "things"}
        if api_sort:
            params["sort"] = api_sort
        try:
            resp = self._session.get(
                f"https://api.thingiverse.com/search/{url_quote(query)}",
                headers={"Authorization": f"Bearer {self.thingiverse_token}"},
                params=params,
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
                    "id":            t.get("id"),
                    "name":          t.get("name", ""),
                    "thumbnail":     t.get("thumbnail", ""),
                    "url":           t.get("public_url") or f"https://www.thingiverse.com/thing:{t.get('id')}",
                    "creator":       creator.get("name", ""),
                    "likes":         int(t.get("like_count", 0) or 0),
                    "collects":      int(t.get("collect_count", 0) or 0),
                    "downloads":     int(t.get("download_count", 0) or 0),
                    "makes":         int(t.get("makes_count", 0) or 0),
                    "comments":      int(t.get("comment_count", 0) or 0),
                    "tags":          tags,
                    "is_printable":  bool(t.get("is_printable", True)),
                    "added":         (
                        t.get("added") or t.get("created_at") or
                        t.get("published_at") or t.get("modified") or ""
                    )[:10],
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
                "q":     query,
                "limit": min(max(1, limit), 20),
            }
            if condition == "new":
                params["filter"] = "conditionIds:{1000}"
            elif condition == "used":
                params["filter"] = "conditionIds:{3000|4000|5000|6000}"

            resp = self._session.get(
                f"{base}/buy/browse/v1/item_summary/search",
                headers={
                    "Authorization":           f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                    "Content-Type":            "application/json",
                },
                params=params,
                timeout=15,
            )

            if resp.status_code != 200:
                logger.error("eBay Browse API %s for %r: %s", resp.status_code, query, resp.text[:400])
                return {"error": f"eBay Browse API returned HTTP {resp.status_code}", "detail": resp.text[:300]}

            data = resp.json()

            # eBay sometimes returns 200 with an errors array instead of results
            api_errors = data.get("errors") or []
            if api_errors:
                msg = api_errors[0].get("message", str(api_errors[0]))
                logger.error("eBay Browse API error in 200 response for %r: %s", query, msg)
                return {"error": f"eBay Browse API: {msg}", "detail": str(api_errors[:2])}

            items  = data.get("itemSummaries", [])
            if not items:
                logger.info("eBay Browse API returned 0 items for %r (total=%s)", query, data.get("total", 0))
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

    # ── eBay sold data (Finding API) ──────────────────────────────────────────

    def ebay_sold_data(self, query: str, timeframe_days: int = 30) -> dict:
        """
        Real eBay completed/sold listing data via the eBay Finding API.
        Uses App ID directly — no OAuth needed.
        Returns sold count, avg/min/max price, total GMV for the given timeframe.
        """
        if not self.ebay_app_id:
            return {
                "error": "eBay App ID not configured",
                "hint":  "Set EBAY_APP_ID in .env",
            }

        from datetime import datetime, timedelta, timezone as _tz
        timeframe_days = max(1, min(int(timeframe_days), 365))
        end_time_from  = (
            datetime.now(_tz.utc) - timedelta(days=timeframe_days)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        try:
            resp = self._session.get(
                "https://svcs.ebay.com/services/search/FindingService/v1",
                params={
                    "OPERATION-NAME":               "findCompletedItems",
                    "SERVICE-VERSION":              "1.0.0",
                    "SECURITY-APPNAME":             self.ebay_app_id,
                    "RESPONSE-DATA-FORMAT":         "JSON",
                    "REST-PAYLOAD":                 "",
                    "keywords":                     query,
                    "itemFilter(0).name":           "SoldItemsOnly",
                    "itemFilter(0).value":          "true",
                    "itemFilter(1).name":           "EndTimeFrom",
                    "itemFilter(1).value":          end_time_from,
                    "paginationInput.entriesPerPage": 100,
                    "sortOrder":                    "EndTimeSoonest",
                },
                timeout=20,
            )

            if resp.status_code != 200:
                return {"error": f"eBay Finding API returned {resp.status_code}", "detail": resp.text[:300]}

            data    = resp.json()
            wrapper = (data.get("findCompletedItemsResponse") or [{}])[0]
            ack     = (wrapper.get("ack") or [""])[0]

            if ack not in ("Success", "Warning"):
                err = (wrapper.get("errorMessage") or [{}])[0]
                return {"error": f"eBay Finding API: {ack}", "detail": str(err)[:200]}

            pagination    = (wrapper.get("paginationOutput") or [{}])[0]
            total_entries = int((pagination.get("totalEntries") or ["0"])[0])

            search_result = (wrapper.get("searchResult") or [{}])[0]
            items         = search_result.get("item") or []

            prices:      list[float] = []
            recent_sold: list[dict]  = []
            currency = "USD"

            for item in items:
                selling   = (item.get("sellingStatus") or [{}])[0]
                state     = (selling.get("sellingState") or [""])[0]
                if state != "EndedWithSales":
                    continue

                price_obj = (selling.get("currentPrice") or [{}])[0]
                price_val = _safe_float(price_obj.get("__value__", 0))
                currency  = price_obj.get("@currencyId", "USD")

                if price_val <= 0:
                    continue

                prices.append(price_val)
                listing  = (item.get("listingInfo") or [{}])[0]
                end_time = (listing.get("endTime") or [""])[0]
                title    = (item.get("title") or [""])[0]
                url      = (item.get("viewItemURL") or [""])[0]

                recent_sold.append({
                    "title":   title[:100],
                    "price":   f"{currency} {price_val:.2f}",
                    "sold_at": end_time[:10] if end_time else "",
                    "url":     url,
                })

            result: dict = {
                "query":          query,
                "timeframe_days": timeframe_days,
                "start_date":     end_time_from[:10],
                "total_in_timeframe": total_entries,
            }

            if prices:
                sold_count = len(prices)
                total_gmv  = sum(prices)
                avg_price  = total_gmv / sold_count
                demand_level = (
                    "high"   if sold_count >= 50 else
                    "medium" if sold_count >= 10 else
                    "low"
                )
                result.update({
                    "sold_count":     sold_count,
                    "avg_sold_price": f"{avg_price:.2f}",
                    "min_sold_price": f"{min(prices):.2f}",
                    "max_sold_price": f"{max(prices):.2f}",
                    "total_gmv":      f"{total_gmv:.2f}",
                    "currency":       currency,
                    "demand_level":   demand_level,
                    "recent_sold":    recent_sold[:10],
                })
            else:
                result.update({
                    "sold_count":    0,
                    "demand_level":  "low",
                    "recent_sold":   [],
                    "note": "No sold items found in this timeframe — try a broader query or longer timeframe",
                })

            return result

        except Exception as e:
            logger.error("ebay_sold_data error: %s", e)
            return {"error": str(e)}

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
            return self.thingiverse_search(
                args.get("query", ""),
                int(args.get("limit", 8)),
                args.get("sort", "popular"),
            )
        if name == "ebay_search":
            return self.ebay_search(
                args.get("query", ""),
                int(args.get("limit", 12)),
                args.get("condition", "all"),
            )
        if name == "ebay_sold_data":
            return self.ebay_sold_data(
                args.get("query", ""),
                int(args.get("timeframe_days", 30)),
            )
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
