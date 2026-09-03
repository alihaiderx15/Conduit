"""Live smoke test for Conduit's Web Intelligence Pack."""
from __future__ import annotations

import argparse
import asyncio
import os

from conduit.web_intelligence import WebIntelligenceService


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="Python programming language latest news")
    parser.add_argument("--grounded", action="store_true")
    parser.add_argument("--model", default=os.getenv("CONDUIT_GEMINI_SEARCH_MODEL", "gemini-flash-latest"))
    args = parser.parse_args()

    service = WebIntelligenceService(gemini_model=args.model)
    try:
        print("CONFIGURATION")
        print(" Gemini key detected:", bool(service.gemini_api_key))
        print(" Gemini search model:", service.gemini_model)
        print(" Grounding requested:", args.grounded)
        if args.grounded and not service.gemini_api_key:
            print(
                " WARNING: --grounded was requested, but GEMINI_API_KEY "
                "is not set in this CMD window."
            )

        print("\n1) WEB SEARCH")
        search = await service.search(args.query, limit=5, use_grounding=args.grounded)
        print(" provider:", search.provider)
        print(" results:", len(search.results))
        if search.metadata.get("grounding_error"):
            print(" grounding fallback reason:", search.metadata["grounding_error"])
        if search.metadata.get("fallback_errors"):
            print(" fallback diagnostics:")
            for error in search.metadata["fallback_errors"]:
                print("   *", error)
        for item in search.results[:3]:
            print("  -", item.title, "|", item.url)

        print("\n2) CURRENT NEWS (PARALLEL)")
        news = await service.news(args.query, limit=5, parallel_queries=3)
        print(" provider:", news.provider)
        print(" results:", len(news.results))
        for item in news.results[:3]:
            print("  -", item.title, "|", item.source)

        print("\n3) PRICE SEARCH")
        prices = await service.price_search("Logitech G305 mouse", region="Pakistan", currency="PKR", limit=5)
        print(" priced results:", prices.metadata.get("priced_results"))
        for item in prices.results[:3]:
            print("  -", item.price or "price not parsed", "|", item.title)

        print("\n4) ITEM COMPARISON")
        comparison = await service.compare(
            ["Logitech G305", "Razer Orochi V2"],
            criteria=["battery life", "weight", "wireless latency"],
            region="Pakistan",
        )
        print(" compared:", ", ".join(comparison.metadata["items"]))
        print(" sources:", len(comparison.sources))

        print("\n5) DEEP RESEARCH")
        research = await service.research(
            "How does retrieval augmented generation improve factual reliability?",
            depth=1,
            sources_per_query=3,
            use_grounding=args.grounded,
        )
        print(" provider:", research.provider)
        print(" sources:", len(research.sources))
        print(" answer preview:", research.answer[:300].replace("\n", " "))
        diagnostics = research.metadata.get("fallback_diagnostics", [])
        if diagnostics:
            print(" research fallback diagnostics:", diagnostics[:3])

        if not search.results:
            raise SystemExit("web.search returned no results.")
        if not news.results:
            raise SystemExit("web.news returned no results.")
        if not comparison.sources:
            raise SystemExit("web.compare returned no sources.")
        if not research.sources and not research.answer:
            raise SystemExit("web.research returned no evidence.")

        print("\nWEB INTELLIGENCE PACK SMOKE TEST: PASS")
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(main())
