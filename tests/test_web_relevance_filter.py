
from conduit.web_intelligence.models import SearchResult
from conduit.web_intelligence.service import WebIntelligenceService


def test_gpu_model_filter_rejects_lexus_rx_result():
    lexus = SearchResult(
        title="2026 Lexus RX review",
        url="https://example.com/lexus",
        snippet="Luxury SUV comparison",
    )
    gpu = SearchResult(
        title="AMD Radeon RX 6700 XT review",
        url="https://example.com/gpu",
        snippet="6700 XT gaming performance",
    )
    assert not WebIntelligenceService._result_matches_item("RX 6700 XT", lexus)
    assert WebIntelligenceService._result_matches_item("RX 6700 XT", gpu)
