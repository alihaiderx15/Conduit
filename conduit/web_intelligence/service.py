"""Provider-neutral live web intelligence with Gemini grounding and no-key fallback."""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any

import httpx

from .models import SearchResponse, SearchResult


class UnsafeSearchQueryError(ValueError):
    """Raised when a search would facilitate age-restricted or dangerous content."""


_BLOCKED_QUERY_PATTERNS = (
    r"\bbuy\s+(?:a\s+)?(?:gun|firearm|ammo|ammunition)\b",
    r"\bwhere\s+to\s+(?:buy|get)\s+(?:drugs?|weed|cannabis|vape|cigarettes?)\b",
    r"\b(?:best|top)\s+(?:betting|gambling|casino)\s+(?:site|app|platform)",
    r"\bhow\s+to\s+(?:make|build)\s+(?:a\s+)?(?:bomb|explosive|weapon)\b",
)


# Hard output safety gate. These results must never be surfaced by normal
# information/research searches, even when a public search provider returns
# badly corrupted or unrelated rankings.
_UNSAFE_RESULT_MARKERS = (
    "porn", "xxx", "adult video", "sex video", "pornhub", "youporn",
    "redtube", "xvideos", "xnxx", "naughtyamerica", "adulttime",
    "fullporner", "iporntv", "onlyfans",
)

_UNSAFE_RESULT_DOMAINS = (
    "pornhub.com", "youporn.com", "redtube.com", "xvideos.com",
    "xnxx.com", "naughtyamerica.com", "adulttime.com", "fullporner.com",
    "iporntv.net",
)

_PRICE_RE = re.compile(
    r"(?<!\w)(?:US\$|USD|PKR|Rs\.?|£|€|\$)\s?"
    r"\d[\d,]*(?:\.\d{1,2})?(?:\s?(?:USD|PKR))?",
    re.IGNORECASE,
)


class _DuckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "url": attrs_dict.get("href") or "", "snippet": ""}
            self._capture = "title"
            self._parts = []
        elif self._current is not None and tag in {"a", "div"} and (
            "result__snippet" in classes or "result__body" in classes
        ):
            self._capture = "snippet"
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current is None or self._capture is None:
            return
        if tag in {"a", "div"}:
            value = " ".join("".join(self._parts).split())
            self._current[self._capture] = value
            if self._capture == "snippet" or (self._capture == "title" and self._current["snippet"]):
                if self._current["title"] and self._current["url"]:
                    self.results.append(self._current)
                    self._current = None
            self._capture = None
            self._parts = []


class _TextParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


class WebIntelligenceService:
    """Search the live web through Gemini grounding or public fallback endpoints."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        gemini_api_key: str | None = None,
        gemini_model: str = "gemini-flash-latest",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                )
            },
        )
        self.gemini_api_key = (gemini_api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self.gemini_model = gemini_model
        self.timeout_seconds = timeout_seconds

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        use_grounding: bool = True,
        region: str = "wt-wt",
        query_variants: Iterable[str] = (),
        exclude_terms: Iterable[str] = (),
    ) -> SearchResponse:
        query = self._validate_query(query)
        grounding_error: str | None = None

        if use_grounding:
            if not self.gemini_api_key:
                grounding_error = "GEMINI_API_KEY is not set in this process."
            else:
                try:
                    grounded = await self._gemini_grounded(query, mode="search")
                    if grounded.answer or grounded.results:
                        return grounded
                    grounding_error = "Gemini returned no grounded answer or sources."
                except Exception as exc:
                    grounding_error = f"{type(exc).__name__}: {exc}"

        variants = self._clean_variants(query, query_variants)
        batches = await asyncio.gather(
            *(
                self._public_search(item, limit=limit, region=region)
                for item in variants
            ),
            return_exceptions=True,
        )
        combined: list[SearchResult] = []
        providers: list[str] = []
        fallback_errors: list[str] = []
        for batch in batches:
            if isinstance(batch, Exception):
                fallback_errors.append(str(batch))
                continue
            batch_results, batch_provider, batch_errors = batch
            combined.extend(batch_results)
            providers.append(batch_provider)
            fallback_errors.extend(batch_errors)
        candidates = self._filter_exclusions(
            self._dedupe(combined),
            exclude_terms,
        )
        results = self._topically_filter_results(query, candidates)[:limit]

        recovery_queries: list[str] = []
        query_token_count = len(self._topic_tokens(query))
        if not results or (
            query_token_count >= 2
            and len(results) < min(3, limit)
        ):
            recovery_queries = [
                f'"{query}"',
                f"{query} official source",
                f"{query} statistics records",
            ]
            recovery_batches = await asyncio.gather(
                *(
                    self._public_search(item, limit=max(limit, 8), region=region)
                    for item in recovery_queries
                ),
                return_exceptions=True,
            )
            recovered: list[SearchResult] = []
            for batch in recovery_batches:
                if isinstance(batch, Exception):
                    continue
                batch_results, batch_provider, batch_errors = batch
                recovered.extend(batch_results)
                providers.append(batch_provider)
                fallback_errors.extend(batch_errors)
            merged = self._filter_exclusions(
                self._dedupe([*results, *recovered]),
                exclude_terms,
            )
            results = self._topically_filter_results(query, merged)[:limit]

        provider = "+".join(dict.fromkeys(providers)) if providers else "unavailable"
        return SearchResponse(
            query=query,
            mode="search",
            provider=provider,
            results=tuple(results),
            sources=tuple(results),
            metadata={
                "grounding_requested": use_grounding,
                "grounding_available": bool(self.gemini_api_key),
                "grounding_error": grounding_error,
                "fallback_errors": fallback_errors,
                "count": len(results),
                "query_variants": variants,
                "exclude_terms": list(exclude_terms),
                "recovery_queries": recovery_queries,
                "safety_filtered": True,
                "topic_filtered": True,
            },
        )

    async def news(
        self,
        query: str,
        *,
        limit: int = 12,
        parallel_queries: int = 3,
        query_variants: Iterable[str] = (),
        exclude_terms: Iterable[str] = (),
    ) -> SearchResponse:
        query = self._validate_query(query)
        variants = self._clean_variants(
            query,
            query_variants or self._news_variants(query),
        )[:max(1, min(parallel_queries, 5))]
        batches = await asyncio.gather(
            *(self._google_news_rss(item, limit=limit) for item in variants),
            return_exceptions=True,
        )
        combined: list[SearchResult] = []
        for batch in batches:
            if isinstance(batch, Exception):
                continue
            combined.extend(batch)
        results = self._topically_filter_results(
            query,
            self._filter_exclusions(
                self._dedupe(combined),
                exclude_terms,
            ),
        )[:limit]
        if not results:
            fallback = await self._duckduckgo(f"{query} latest news", limit=limit)
            results = self._topically_filter_results(
                query,
                [
                    SearchResult(item.title, item.url, item.snippet, item.source or "DuckDuckGo")
                    for item in fallback
                ],
            )[:limit]
        return SearchResponse(
            query=query,
            mode="news",
            provider="google-news-rss" if combined else "duckduckgo",
            results=tuple(results),
            sources=tuple(results),
            metadata={
                "parallel_queries": variants,
                "exclude_terms": list(exclude_terms),
                "count": len(results),
            },
        )

    async def research(
        self,
        query: str,
        *,
        depth: int = 2,
        sources_per_query: int = 5,
        use_grounding: bool = True,
        query_variants: Iterable[str] = (),
        exclude_terms: Iterable[str] = (),
        source_preferences: Iterable[str] = (),
    ) -> SearchResponse:
        query = self._validate_query(query)
        if use_grounding and self.gemini_api_key:
            prompt = (
                "Research the following question using live Google Search. Produce a balanced, "
                "well-structured answer, distinguish confirmed facts from uncertainty, and include "
                f"source links. Question: {query}"
            )
            try:
                grounded = await self._gemini_grounded(prompt, mode="research")
                if grounded.answer:
                    return grounded
            except Exception:
                pass

        subqueries = self._clean_variants(
            query,
            query_variants or self._research_queries(query, depth),
        )
        batches = await asyncio.gather(
            *(
                self._public_search(
                    item,
                    limit=sources_per_query,
                    region="wt-wt",
                )
                for item in subqueries
            ),
            return_exceptions=True,
        )
        candidates: list[SearchResult] = []
        fallback_diagnostics: list[dict[str, object]] = []
        for batch in batches:
            if isinstance(batch, Exception):
                fallback_diagnostics.append({"error": str(batch)})
                continue
            results, provider, errors = batch
            candidates.extend(results)
            fallback_diagnostics.append(
                {"provider": provider, "errors": errors, "count": len(results)}
            )
        filtered_candidates = [
            item
            for item in self._safe_results(
                self._filter_exclusions(self._dedupe(candidates), exclude_terms)
            )
            if self._result_topic_relevant(query, item)
            and self._research_source_quality(item, source_preferences)
        ]

        recovery_queries: list[str] = []
        if len(filtered_candidates) < 3 and source_preferences:
            recovery_queries = [
                f'{query} site:pubmed.ncbi.nlm.nih.gov',
                f'{query} site:nih.gov',
                f'{query} systematic review',
                f'{query} university study',
            ]
            recovery_batches = await asyncio.gather(
                *(
                    self._public_search(
                        item,
                        limit=max(4, sources_per_query),
                        region="wt-wt",
                    )
                    for item in recovery_queries
                ),
                return_exceptions=True,
            )
            recovered: list[SearchResult] = []
            for batch in recovery_batches:
                if isinstance(batch, Exception):
                    continue
                results, _, _ = batch
                recovered.extend(results)
            filtered_candidates = [
                item
                for item in self._safe_results(
                    self._dedupe([*filtered_candidates, *recovered])
                )
                if self._result_topic_relevant(query, item)
                and self._research_source_quality(item, source_preferences)
            ]

        sources = self._rank_sources(
            filtered_candidates,
            source_preferences,
        )[: max(6, depth * sources_per_query)]

        page_tasks = [self._fetch_page_text(item.url, 6000) for item in sources[:8]]
        page_texts = await asyncio.gather(*page_tasks, return_exceptions=True)
        evidence: list[str] = []
        for source, page in zip(sources[:8], page_texts):
            if isinstance(page, Exception) or not page:
                excerpt = source.snippet
            else:
                excerpt = str(page)[:1200]
            if excerpt:
                evidence.append(f"{source.title}: {excerpt}")

        answer = self._evidence_summary(query, evidence, sources)
        return SearchResponse(
            query=query,
            mode="research",
            provider="duckduckgo+page-fetch",
            answer=answer,
            results=tuple(sources),
            sources=tuple(sources),
            metadata={
                "subqueries": subqueries,
                "pages_fetched": len(evidence),
                "fallback_diagnostics": fallback_diagnostics,
                "exclude_terms": list(exclude_terms),
                "source_preferences": list(source_preferences),
                "recovery_queries": recovery_queries,
                "quality_filtered": True,
            },
        )

    @staticmethod
    def _region_tokens(region: str) -> list[str]:
        clean = " ".join(str(region).casefold().split())
        if not clean:
            return []
        aliases = {
            "pakistan": ["pakistan", "pakistani", ".pk", " pkr", " rs"],
            "united states": ["united states", "usa", "u.s.", ".com"],
            "uk": ["united kingdom", " uk ", ".co.uk", "£"],
        }
        tokens = [clean]
        for key, values in aliases.items():
            if key in clean or clean == key:
                tokens.extend(values)
        return list(dict.fromkeys(tokens))

    @classmethod
    def _result_matches_region(cls, region: str, result: SearchResult) -> bool:
        tokens = cls._region_tokens(region)
        if not tokens:
            return True
        haystack = f" {result.title} {result.snippet} {result.url} {result.source} ".casefold()
        return any(token in haystack for token in tokens)

    async def price_search(
        self,
        item: str,
        *,
        region: str = "",
        currency: str = "",
        limit: int = 10,
        query_variants: Iterable[str] = (),
        exclude_terms: Iterable[str] = (),
    ) -> SearchResponse:
        item = self._validate_query(item)
        suffix = " ".join(part for part in ("price", region, currency) if part).strip()
        query = f"{item} {suffix}".strip()
        variants = self._clean_variants(
            query,
            query_variants or (
                query,
                f"{item} {region} price",
                f"{item} buy {region}",
            ),
        )
        base = await self.search(
            query,
            limit=max(limit * 3, 15),
            use_grounding=False,
            query_variants=variants,
            exclude_terms=exclude_terms,
        )
        relevant_results = [
            result
            for result in self._safe_results(base.results)
            if self._result_matches_item(item, result)
            and self._result_matches_region(region, result)
        ]

        # Retrieval recovery: if the first pass drifted to the wrong country or
        # generic global pages, retry with stronger market-specific formulations.
        recovery_queries: list[str] = []
        if region and len(relevant_results) < 2:
            recovery_queries = [
                f'"{item}" price in {region} {currency}'.strip(),
                f'"{item}" {region} retailer {currency}'.strip(),
                f'"{item}" buy online {region} {currency}'.strip(),
            ]
            if "pakistan" in region.casefold():
                recovery_queries.extend(
                    [
                        f'"{item}" Pakistan PKR',
                        f'"{item}" site:.pk price',
                    ]
                )
            recovery = await self.search(
                recovery_queries[0],
                limit=max(limit * 4, 20),
                use_grounding=False,
                query_variants=recovery_queries,
                exclude_terms=exclude_terms,
            )
            recovered = [
                result
                for result in recovery.results
                if self._result_matches_item(item, result)
                and self._result_matches_region(region, result)
            ]
            relevant_results = self._dedupe([*relevant_results, *recovered])

        priced: list[SearchResult] = []
        for result in relevant_results:
            price = self._extract_price(f"{result.title} {result.snippet}")
            if price:
                priced.append(
                    SearchResult(
                        result.title,
                        result.url,
                        result.snippet,
                        result.source,
                        result.published_at,
                        price,
                    )
                )
        results = priced[:limit] or relevant_results[:limit]
        return SearchResponse(
            query=query,
            mode="price_search",
            provider=base.provider,
            results=tuple(results),
            sources=tuple(results),
            metadata={
                "item": item,
                "region": region,
                "currency": currency,
                "priced_results": len(priced),
                "query_variants": variants,
                "exclude_terms": list(exclude_terms),
                "recovery_queries": recovery_queries,
                "region_filtered": bool(region),
            },
        )

    async def compare(
        self,
        items: Iterable[str],
        *,
        criteria: Iterable[str] = (),
        region: str = "",
        include_prices: bool = True,
    ) -> SearchResponse:
        clean_items = [self._validate_query(item) for item in items if str(item).strip()]
        if len(clean_items) < 2:
            raise ValueError("web.compare requires at least two items.")
        clean_items = clean_items[:6]
        criteria_list = [str(item).strip() for item in criteria if str(item).strip()][:8]

        async def collect(item: str) -> tuple[str, SearchResponse, SearchResponse | None]:
            facts_query = f"{item} {' '.join(criteria_list)} specifications".strip()
            fact_variants = (
                facts_query,
                f'"{item}" official specifications',
                f'"{item}" technical specifications memory power',
                f'"{item}" memory bus power ray tracing hardware',
            )
            facts, prices = await asyncio.gather(
                self.search(
                    facts_query,
                    limit=12,
                    use_grounding=False,
                    query_variants=fact_variants,
                ),
                self.price_search(item, region=region, limit=5) if include_prices else _none(),
            )
            return item, facts, prices

        groups = await asyncio.gather(*(collect(item) for item in clean_items))
        all_sources: list[SearchResult] = []
        comparison: dict[str, Any] = {}
        discarded_irrelevant: dict[str, int] = {}
        for item, facts, prices in groups:
            relevant_facts = [
                entry
                for entry in self._safe_results(facts.results)
                if self._result_matches_item(item, entry)
            ]
            if relevant_facts:
                pages = await asyncio.gather(
                    *(self._fetch_page_text(entry.url, 5000) for entry in relevant_facts[:6]),
                    return_exceptions=True,
                )
                enriched: list[SearchResult] = []
                for entry, page in zip(relevant_facts[:6], pages):
                    excerpt = (
                        entry.snippet
                        if isinstance(page, Exception) or not page
                        else str(page)[:1800]
                    )
                    enriched.append(
                        SearchResult(
                            entry.title,
                            entry.url,
                            excerpt,
                            entry.source,
                            entry.published_at,
                            entry.price,
                        )
                    )
                relevant_facts = enriched
            relevant_prices = [
                entry
                for entry in self._safe_results(prices.results if prices else ())
                if self._result_matches_item(item, entry)
            ]
            discarded_irrelevant[item] = (
                len(facts.results) - len(relevant_facts)
            )
            all_sources.extend(relevant_facts)
            all_sources.extend(relevant_prices)
            comparison[item] = {
                "evidence": [
                    entry.to_dict()
                    for entry in relevant_facts[:6]
                ],
                "prices": [
                    entry.to_dict()
                    for entry in relevant_prices[:6]
                ],
            }

        answer = self._comparison_summary(comparison, criteria_list)
        sources = self._dedupe(all_sources)
        return SearchResponse(
            query=" vs ".join(clean_items),
            mode="compare",
            provider="parallel-web-search",
            answer=answer,
            results=tuple(sources),
            sources=tuple(sources),
            metadata={
                "items": clean_items,
                "criteria": criteria_list,
                "comparison": comparison,
                "parallel": True,
                "discarded_irrelevant": discarded_irrelevant,
            },
        )

    async def _gemini_grounded(self, query: str, *, mode: str) -> SearchResponse:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.gemini_api_key)

        def request() -> Any:
            grounding_tool = types.Tool(
                google_search=types.GoogleSearch()
            )
            config = types.GenerateContentConfig(
                tools=[grounding_tool]
            )
            return client.models.generate_content(
                model=self.gemini_model,
                contents=query,
                config=config,
            )

        response = await asyncio.to_thread(request)
        answer = str(getattr(response, "text", "") or "")
        raw = _model_dump(response)
        sources = _extract_grounding_sources(raw)
        search_queries = _extract_grounding_queries(raw)
        return SearchResponse(
            query=query,
            mode=mode,
            provider="gemini-google-search",
            answer=answer,
            results=tuple(sources),
            sources=tuple(sources),
            metadata={
                "grounded": bool(sources or search_queries),
                "model": self.gemini_model,
                "search_queries": search_queries,
                "source_count": len(sources),
            },
        )

    async def _public_search(
        self,
        query: str,
        *,
        limit: int,
        region: str,
    ) -> tuple[list[SearchResult], str, list[str]]:
        """Try independent public search paths and report every fallback failure."""
        errors: list[str] = []

        for attempt in range(2):
            try:
                results = await self._duckduckgo(
                    query,
                    limit=limit,
                    region=region,
                )
                if results:
                    return results, "duckduckgo", errors
                errors.append(
                    f"DuckDuckGo attempt {attempt + 1} returned zero results."
                )
            except Exception as exc:
                errors.append(
                    f"DuckDuckGo attempt {attempt + 1}: "
                    f"{type(exc).__name__}: {exc}"
                )
            if attempt == 0:
                await asyncio.sleep(0.8)

        try:
            results = await self._bing_rss(query, limit=limit)
            if results:
                return results, "bing-rss", errors
            errors.append("Bing RSS returned zero results.")
        except Exception as exc:
            errors.append(f"Bing RSS: {type(exc).__name__}: {exc}")

        try:
            results = await self._wikipedia_search(query, limit=limit)
            if results:
                return results, "wikipedia", errors
            errors.append("Wikipedia returned zero results.")
        except Exception as exc:
            errors.append(f"Wikipedia: {type(exc).__name__}: {exc}")

        return [], "unavailable", errors


    async def _duckduckgo(
        self,
        query: str,
        *,
        limit: int,
        region: str = "wt-wt",
    ) -> list[SearchResult]:
        response = await self.client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": region},
        )
        response.raise_for_status()
        parser = _DuckParser()
        parser.feed(response.text)
        results: list[SearchResult] = []
        for raw in parser.results:
            url = _decode_duck_url(raw["url"])
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                SearchResult(
                    title=html.unescape(raw["title"]),
                    url=url,
                    snippet=html.unescape(raw["snippet"]),
                    source=_hostname(url),
                )
            )
            if len(results) >= limit:
                break
        return results

    async def _google_news_rss(self, query: str, *, limit: int) -> list[SearchResult]:
        encoded = urllib.parse.quote_plus(query)
        response = await self.client.get(
            f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        results: list[SearchResult] = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", default="")
            link = item.findtext("link", default="")
            description = _strip_html(item.findtext("description", default=""))
            published = item.findtext("pubDate")
            source_node = item.find("source")
            source = source_node.text if source_node is not None else _hostname(link)
            if title and link:
                results.append(
                    SearchResult(title, link, description, source or "", published)
                )
        return results

    async def _bing_rss(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[SearchResult]:
        encoded = urllib.parse.quote_plus(query)
        response = await self.client.get(
            f"https://www.bing.com/search?format=rss&q={encoded}"
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        results: list[SearchResult] = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", default="")
            link = item.findtext("link", default="")
            description = _strip_html(
                item.findtext("description", default="")
            )
            if title and link:
                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        snippet=description,
                        source=_hostname(link),
                    )
                )
        return results

    async def _wikipedia_search(
        self,
        query: str,
        *,
        limit: int,
    ) -> list[SearchResult]:
        response = await self.client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
                "origin": "*",
            },
        )
        response.raise_for_status()
        payload = response.json()
        results: list[SearchResult] = []
        for item in payload.get("query", {}).get("search", []):
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            url = (
                "https://en.wikipedia.org/wiki/"
                + urllib.parse.quote(title.replace(" ", "_"))
            )
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=_strip_html(str(item.get("snippet", ""))),
                    source="wikipedia.org",
                )
            )
        return results

    async def _fetch_page_text(self, url: str, max_chars: int) -> str:
        response = await self.client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            return ""
        parser = _TextParser()
        parser.feed(response.text[:1_000_000])
        return " ".join(parser.parts)[:max_chars]

    @staticmethod
    def _validate_query(query: str) -> str:
        clean = " ".join(str(query).split())
        if not clean:
            raise ValueError("Search query cannot be empty.")
        lowered = clean.casefold()
        if any(re.search(pattern, lowered) for pattern in _BLOCKED_QUERY_PATTERNS):
            raise UnsafeSearchQueryError(
                "This search request is blocked because it could help locate dangerous or age-restricted content."
            )
        return clean[:1000]

    @staticmethod
    def _result_matches_item(
        item: str,
        result: SearchResult,
    ) -> bool:
        """Reject unrelated results such as Lexus RX pages for an RX 6700 XT."""

        item_tokens = re.findall(r"[a-z0-9]+", item.casefold())
        text = f"{result.title} {result.snippet}".casefold()

        model_tokens = [
            token
            for token in item_tokens
            if any(character.isdigit() for character in token)
        ]
        if model_tokens:
            return all(token in text for token in model_tokens)

        meaningful = [
            token
            for token in item_tokens
            if len(token) >= 3
            and token not in {
                "the",
                "and",
                "with",
                "for",
                "review",
                "specifications",
            }
        ]
        if not meaningful:
            return True

        required = 1 if len(meaningful) == 1 else 2
        overlap = sum(token in text for token in meaningful)
        return overlap >= required

    @staticmethod
    def _result_is_safe(result: SearchResult) -> bool:
        text = f"{result.title} {result.snippet} {result.url} {result.source}".casefold()
        if any(marker in text for marker in _UNSAFE_RESULT_MARKERS):
            return False
        try:
            host = urllib.parse.urlparse(result.url).netloc.casefold()
        except Exception:
            host = ""
        return not any(host == domain or host.endswith("." + domain) for domain in _UNSAFE_RESULT_DOMAINS)

    @classmethod
    def _safe_results(cls, results: Iterable[SearchResult]) -> list[SearchResult]:
        return [item for item in results if cls._result_is_safe(item)]

    @classmethod
    def _topically_filter_results(
        cls,
        query: str,
        results: Iterable[SearchResult],
    ) -> list[SearchResult]:
        safe = cls._safe_results(results)
        topical = [
            item for item in safe
            if cls._result_topic_relevant(query, item)
        ]
        # If token extraction is too strict for a weird but legitimate query,
        # prefer safe results over returning nothing. Never relax the safety gate.
        return topical if topical else safe

    @staticmethod
    def _clean_variants(primary: str, variants: Iterable[str]) -> list[str]:
        output: list[str] = []
        for item in (primary, *tuple(variants)):
            clean = " ".join(str(item).split())
            if clean and clean.casefold() not in {value.casefold() for value in output}:
                output.append(clean)
        return output[:6]

    @staticmethod
    def _filter_exclusions(
        results: Iterable[SearchResult],
        exclude_terms: Iterable[str],
    ) -> list[SearchResult]:
        exclusions = [
            " ".join(str(item).casefold().split())
            for item in exclude_terms
            if str(item).strip()
        ]
        if not exclusions:
            return list(results)
        output = []
        for result in results:
            haystack = f"{result.title} {result.snippet}".casefold()
            if any(term in haystack for term in exclusions):
                continue
            output.append(result)
        return output

    @staticmethod
    def _topic_tokens(query: str) -> set[str]:
        stop = {
            "research", "study", "studies", "evidence", "benefit", "benefits",
            "health", "scientific", "science", "source", "sources", "review",
            "reviews", "effect", "effects", "advantage", "advantages",
            "current", "latest", "information", "using", "about", "from",
        }
        tokens = set()
        for token in re.findall(r"[a-z0-9]+", query.casefold()):
            root = token[:-1] if token.endswith("s") and len(token) > 4 else token
            if len(root) >= 4 and root not in stop:
                tokens.add(root)
        return tokens

    @classmethod
    def _result_topic_relevant(cls, query: str, result: SearchResult) -> bool:
        tokens = cls._topic_tokens(query)
        if not tokens:
            return True
        haystack = f"{result.title} {result.snippet} {result.url}".casefold()
        normalized = {
            token[:-1] if token.endswith("s") and len(token) > 4 else token
            for token in re.findall(r"[a-z0-9]+", haystack)
        }
        return bool(tokens & normalized)

    @staticmethod
    def _research_source_quality(
        result: SearchResult,
        source_preferences: Iterable[str],
    ) -> bool:
        prefs = " ".join(str(item).casefold() for item in source_preferences)
        wants_strong_sources = any(
            term in prefs
            for term in ("academic", "medical", "journal", "study", "review", "official")
        )
        if not wants_strong_sources:
            return True

        text = f"{result.title} {result.url} {result.source}".casefold()
        low_signal = (
            "dictionary", "wikipedia.org", "reddit.com", "quora.com",
            "facebook.com", "instagram.com", "tiktok.com", "pinterest.com",
            "merriam-webster", "cambridge.org/dictionary", "thefreedictionary",
        )
        if any(marker in text for marker in low_signal):
            return False

        strong = (
            ".gov", ".edu", "pubmed", "ncbi.nlm.nih.gov", "nih.gov",
            "who.int", "nature.com", "sciencedirect", "springer",
            "wiley", "bmj", "jamanetwork", "thelancet", "frontiersin",
            "mdpi.com", "oup.com", "academic.oup.com",
        )
        return any(marker in text for marker in strong) or any(
            word in text for word in ("journal", "university", "institute", "study", "review")
        )

    @staticmethod
    def _rank_sources(
        results: Iterable[SearchResult],
        source_preferences: Iterable[str],
    ) -> list[SearchResult]:
        preferences = [str(item).casefold() for item in source_preferences]
        trusted_markers = (
            ".gov", ".edu", "who.int", "nih.gov", "pubmed", "nature.com",
            "sciencedirect", "springer", "wiley", "bmj", "jamanetwork",
        )
        def score(item: SearchResult) -> tuple[int, int]:
            text = f"{item.source} {item.title} {item.url}".casefold()
            trusted = sum(marker in text for marker in trusted_markers)
            preferred = sum(pref in text for pref in preferences)
            return (trusted + preferred, len(item.snippet or ""))
        return sorted(results, key=score, reverse=True)

    @staticmethod
    def _extract_price(text: str) -> str | None:
        match = _PRICE_RE.search(text)
        return match.group(0).strip() if match else None

    @staticmethod
    def _dedupe(results: Iterable[SearchResult]) -> list[SearchResult]:
        seen: set[str] = set()
        output: list[SearchResult] = []
        for item in results:
            key = item.url.split("#", 1)[0].rstrip("/").casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

    @staticmethod
    def _news_variants(query: str) -> list[str]:
        return [query, f"{query} latest", f"{query} update"]

    @staticmethod
    def _research_queries(query: str, depth: int) -> list[str]:
        variants = [
            query,
            f"{query} key facts evidence",
            f"{query} recent developments",
            f"{query} criticism limitations",
            f"{query} expert analysis",
            f"{query} statistics report",
        ]
        return variants[: max(2, min(6, depth * 2 + 1))]

    @staticmethod
    def _evidence_summary(
        query: str,
        evidence: list[str],
        sources: list[SearchResult],
    ) -> str:
        if not evidence:
            return f"No sufficiently detailed live evidence was retrieved for: {query}"
        lines = [
            f"Research evidence collected for: {query}",
            "",
            "Key source evidence:",
        ]
        for index, item in enumerate(evidence[:8], 1):
            lines.append(f"{index}. {item[:900]}")
        lines.append("")
        lines.append(
            "Use the linked sources to verify important claims; this fallback synthesis does not invent facts beyond retrieved evidence."
        )
        return "\n".join(lines)

    @staticmethod
    def _comparison_summary(
        comparison: dict[str, Any],
        criteria: list[str],
    ) -> str:
        lines = ["Comparison evidence summary"]
        if criteria:
            lines.append("Requested criteria: " + ", ".join(criteria))
        for item, data in comparison.items():
            lines.append(f"\n{item}:")
            prices = [
                result.get("price")
                for result in data["prices"]
                if result.get("price")
            ]
            if prices:
                lines.append("Observed prices: " + ", ".join(prices[:4]))
            for evidence in data["evidence"][:3]:
                snippet = evidence.get("snippet") or evidence.get("title")
                if snippet:
                    lines.append(f"- {snippet[:350]}")
        lines.append(
            "\nNo winner is declared automatically; the agent should weigh the retrieved evidence against the user's criteria."
        )
        return "\n".join(lines)


async def _none() -> None:
    return None


def _decode_duck_url(url: str) -> str:
    parsed = urllib.parse.urlparse(html.unescape(url))
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query:
        return urllib.parse.unquote(query["uddg"][0])
    if url.startswith("//"):
        return "https:" + url
    return url


def _hostname(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.removeprefix("www.")


def _strip_html(value: str) -> str:
    parser = _TextParser()
    parser.feed(value)
    return " ".join(parser.parts)


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_json_dict"):
        return value.to_json_dict()
    try:
        return json.loads(json.dumps(value, default=lambda obj: vars(obj)))
    except Exception:
        return {}


def _extract_grounding_sources(raw: Any) -> list[SearchResult]:
    found: list[SearchResult] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            uri = value.get("uri") or value.get("url")
            title = value.get("title") or value.get("name")
            if isinstance(uri, str) and uri.startswith(("http://", "https://")):
                found.append(
                    SearchResult(
                        title=str(title or _hostname(uri)),
                        url=uri,
                        snippet=str(value.get("snippet") or ""),
                        source=_hostname(uri),
                    )
                )
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(raw)
    return WebIntelligenceService._dedupe(found)


def _extract_grounding_queries(raw: Any) -> list[str]:
    queries: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"webSearchQueries", "web_search_queries"} and isinstance(child, list):
                    queries.extend(str(item) for item in child if str(item).strip())
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(raw)
    return list(dict.fromkeys(queries))
