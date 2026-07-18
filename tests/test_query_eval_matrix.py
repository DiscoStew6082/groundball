from baseball_rag.query.eval_matrix import run_matrix


def test_query_plan_and_query_run_eval_matrix_passes_without_llm() -> None:
    report = run_matrix()

    assert report["status"] == "passing"
    assert report["summary"] == {"passed": 17, "failed": 0, "total": 17}
