"""Run the checked-in Query Plan and Query Run deterministic eval matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from baseball_rag.query.adapters import _execution_payload, recipe_from_dict, run_query_input
from baseball_rag.query.contracts import ExecutionFailed, Ready
from baseball_rag.query.service import prepare

MATRIX_PATH = Path(__file__).with_name("eval_matrix.json")


def run_matrix(path: Path = MATRIX_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for case in manifest["cases"]:
        try:
            payload = _run_case(case)
            _assert_expected(payload, case["expect"])
            results.append({"id": case["id"], "status": "passing", "failures": []})
        except Exception as exc:  # noqa: BLE001 - collect the whole deterministic matrix
            results.append(
                {
                    "id": case["id"],
                    "status": "failing",
                    "failures": [f"{type(exc).__name__}: {exc}"],
                }
            )
    failed = [item for item in results if item["status"] != "passing"]
    return {
        "schema_version": manifest["schema_version"],
        "status": "passing" if not failed else "failing",
        "summary": {
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "total": len(results),
        },
        "cases": results,
    }


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    if case.get("fixture") == "execution_failed":
        recipe = recipe_from_dict({"source": "People", "selections": ["People.playerID"]})
        planned = prepare(recipe)
        if not isinstance(planned, Ready):
            raise AssertionError("failed-outcome fixture did not plan")
        return _execution_payload(
            recipe,
            planned,
            ExecutionFailed("deterministic failure fixture"),
        )
    if "question" in case:
        return run_query_input(question=case["question"])
    return run_query_input(recipe=case["recipe"])


def _assert_expected(payload: dict[str, Any], expected: dict[str, Any]) -> None:
    if payload.get("kind") != expected["kind"]:
        raise AssertionError(f"expected {expected['kind']}, observed {payload.get('kind')}")
    rows = payload.get("rows", [])
    if "row_count" in expected and len(rows) != expected["row_count"]:
        raise AssertionError(f"expected {expected['row_count']} rows, observed {len(rows)}")
    if "row_count_min" in expected and len(rows) < expected["row_count_min"]:
        raise AssertionError("result did not meet the minimum row count")
    for expected_row in expected.get("rows_include", []):
        if not any(
            all(row.get(key) == value for key, value in expected_row.items()) for row in rows
        ):
            raise AssertionError(f"missing expected row subset {expected_row}")
    if "text_contains" in expected:
        text = str(payload.get("question") or payload.get("reason") or "").casefold()
        if str(expected["text_contains"]).casefold() not in text:
            raise AssertionError(f"missing expected text {expected['text_contains']!r}")
    bound_values = payload.get("evidence", {}).get("bound_values", [])
    for value in expected.get("bound_values_include", []):
        if value not in bound_values:
            raise AssertionError(f"missing bound value {value!r}")
    if "export_contains" in expected:
        content = payload.get("export", {}).get("content", "")
        if expected["export_contains"] not in content:
            raise AssertionError("export content changed")
    if expected.get("calculation"):
        calculations = payload.get("evidence", {}).get("calculations", [])
        if expected["calculation"] not in {item.get("identity") for item in calculations}:
            raise AssertionError("calculation evidence is missing")
    if payload.get("kind") in {"rows", "no_data", "exported"}:
        if payload.get("verification", {}).get("status") != "verified":
            raise AssertionError("factual result is not bound to passing proof")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    report = run_matrix()
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.json_report:
        args.json_report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["status"] != "passing":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
