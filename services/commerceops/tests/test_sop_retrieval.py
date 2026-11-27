from pathlib import Path

from commerceops.sop.retrieval import get_index, load_package_documents, search_sops


def test_control_codes_cite_the_exact_section_and_quote():
    expectations = {
        "profitrefundspike": ("sop-profit-drop", "Refund Spike Check"),
        "acossevere": ("sop-acos-optimization", "Budget Cut Ladder"),
        "stockoutreorder": ("sop-stockout-supplier", "Reorder Point"),
        "competitorpricedrop": ("sop-competitor-response", "Price Drop Response"),
    }
    documents = {document.doc_id: Path(document.path).read_text(encoding="utf-8") for document in load_package_documents()}
    for code, (doc_id, section) in expectations.items():
        first = search_sops(code, limit=3)
        second = search_sops(code, limit=3)
        assert first == second
        hit = first["hits"][0]
        assert hit.doc_id == doc_id
        assert hit.section == section
        assert code in hit.quote
        if code == "acossevere":
            assert "0.80" in hit.quote
        assert hit.quote in documents[doc_id]
        assert hit.source_sha256
        assert first["formula_version"] == "sop.bm25.v1"


def test_chinese_refund_query_and_natural_stockout_query():
    refund = search_sops("退款尖峰", limit=3)["hits"][0]
    assert refund.doc_id == "sop-profit-drop"
    assert refund.section == "Refund Spike Check"
    assert "退款尖峰核对" in refund.quote
    stock = search_sops("reorder point safety stock MOQ lead time days of cover", limit=3)["hits"][0]
    assert stock.doc_id == "sop-stockout-supplier"


def test_empty_query_and_limit():
    assert search_sops("   ", limit=5)["hits"] == []
    assert len(search_sops("refund", limit=1)["hits"]) == 1
    assert get_index().search("zzznomatchtoken", 5) == []
