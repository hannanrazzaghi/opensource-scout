from opensource_scout.llm.context import build_context_bundle


def test_selects_files_with_query_term_overlap() -> None:
    files = {
        "src/ranking.py": "def rank_results(query): return bm25_score(query)",
        "README.md": "This project is a general purpose utility.",
    }
    bundle = build_context_bundle("abc123", files, ["rank_results", "bm25_score"])
    selected_paths = [f.path for f in bundle.selected_files]
    assert "src/ranking.py" in selected_paths
    assert "README.md" not in selected_paths


def test_zero_overlap_files_are_excluded_not_selected() -> None:
    files = {"unrelated.py": "def totally_unrelated_function(): pass"}
    bundle = build_context_bundle("abc123", files, ["ranking", "bm25"])
    assert bundle.selected_files == ()
    assert "unrelated.py" in bundle.excluded_files


def test_respects_max_files_limit() -> None:
    files = {f"file_{i}.py": "def rank(): pass" for i in range(10)}
    bundle = build_context_bundle("abc123", files, ["rank"], max_files=3)
    assert len(bundle.selected_files) == 3


def test_respects_max_token_budget() -> None:
    files = {f"file_{i}.py": ("def rank(): pass\n" * 1000) for i in range(5)}
    bundle = build_context_bundle("abc123", files, ["rank"], max_files=10, max_tokens=500)
    assert bundle.approx_token_count <= 500


def test_relevant_tests_are_identified_by_path() -> None:
    files = {
        "src/ranking.py": "def rank(): pass",
        "tests/test_ranking.py": "def test_rank(): assert rank() is not None",
    }
    bundle = build_context_bundle("abc123", files, ["rank"])
    assert "tests/test_ranking.py" in bundle.relevant_tests


def test_base_commit_sha_is_preserved() -> None:
    bundle = build_context_bundle("deadbeef", {}, ["x"])
    assert bundle.base_commit_sha == "deadbeef"


def test_higher_overlap_files_are_ranked_first() -> None:
    files = {
        "high.py": "rank rank rank bm25 bm25 bm25",
        "low.py": "rank",
    }
    bundle = build_context_bundle("abc123", files, ["rank", "bm25"])
    assert bundle.selected_files[0].path == "high.py"
