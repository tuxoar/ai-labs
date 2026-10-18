"""SQL builder contract: legs, fusion, filters, bounds — no database."""

import pytest

from api.retrieval import SearchSpec, build_search_sql

VEC = [0.0] * 768


def test_hybrid_has_both_legs_and_rrf():
    sql, params = build_search_sql(SearchSpec(query="q", collection="c"), VEC)
    assert "dense AS" in sql and "lexical AS" in sql
    assert "FULL OUTER JOIN" in sql and "1.0 / (%(rrf_k)s + d.rnk)" in sql
    assert "SET" not in sql                       # knobs go through set_config
    assert params["collection"] == "c" and params["rrf_k"] == 60
    assert "hnsw" not in sql.lower()              # HNSW chosen by the planner via ORDER BY <=> LIMIT


def test_dense_uses_embedder_column_and_requires_vector():
    sql, _ = build_search_sql(SearchSpec(query="q", collection="c", mode="dense", embedder="embed-bge-m3"), [0.0] * 1024)
    assert "c.emb_bgem3 <=> %(qvec)s::vector" in sql and "lexical AS" not in sql
    with pytest.raises(ValueError):
        build_search_sql(SearchSpec(query="q", collection="c", mode="dense"), None)
    with pytest.raises(ValueError):
        build_search_sql(SearchSpec(query="q", collection="c", mode="dense"), [0.0] * 10)


def test_lexical_needs_no_vector():
    sql, params = build_search_sql(SearchSpec(query="exact phrase", collection="c", mode="lexical"), None)
    assert "websearch_to_tsquery" in sql and "dense AS" not in sql
    assert "qvec" not in params


def test_filters_apply_inside_each_leg():
    spec = SearchSpec(query="q", collection="c", book_id="00000000-0000-0000-0000-000000000001", author="Ann")
    sql, params = build_search_sql(spec, VEC)
    assert sql.count("c.book_id = %(book_id)s::uuid") == 2
    assert sql.count("fb.author ILIKE %(author)s") == 2
    assert params["author"] == "%Ann%"


def test_bad_mode_and_embedder_rejected():
    with pytest.raises(ValueError):
        build_search_sql(SearchSpec(query="q", collection="c", mode="magic"), VEC)
    with pytest.raises(ValueError):
        build_search_sql(SearchSpec(query="q", collection="c", embedder="embed-arctic2"), VEC)
