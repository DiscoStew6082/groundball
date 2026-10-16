from baseball_rag.query.eval_matrix import run_matrix


def test_query_plan_and_query_run_eval_matrix_passes_without_llm() -> None:
    from baseball_rag.release_context import installed_release_context

    before = installed_release_context()
    report = run_matrix()
    assert installed_release_context() is before

    assert report["status"] == "passing"
    assert report["summary"] == {"passed": 26, "failed": 0, "total": 26}
