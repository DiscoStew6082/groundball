import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path("scripts/check_provider_neutrality.py")
_SPEC = importlib.util.spec_from_file_location("provider_neutrality", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("scanner module could not be loaded")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
CHUNK_BYTES = _MODULE.CHUNK_BYTES
Finding = _MODULE.Finding
main = _MODULE.main
scan = _MODULE.scan


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _policy(exact=(), globs=()):
    return {
        "exact_rules": [{"rule_id": rule_id, "value": value} for rule_id, value in exact],
        "glob_rules": [{"pattern": pattern, "rule_id": rule_id} for rule_id, pattern in globs],
        "schema_version": 1,
    }


def test_clean_tree_allows_generic_prose(tmp_path):
    (tmp_path / "notes.txt").write_text(
        "A provider adapter can use blob hosting during deployment.\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == ()


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("/Us" + "ers/alice/My Work/release.txt", "personal-absolute-path"),
        ("API_" + "TO" + "KEN" + "=" + "'not-" + "real'", "sensitive-assignment"),
        ("project_" + "id = 'sample-123'", "resource-identifier-assignment"),
    ],
)
def test_generic_findings_are_redacted(tmp_path, text, rule_id):
    (tmp_path / "input.txt").write_text(text + "\n", encoding="utf-8")

    finding = scan(tmp_path)[0]

    assert (finding.path, finding.line, finding.rule_id) == ("input.txt", 1, rule_id)
    assert finding.excerpt.endswith("<redacted>")
    assert "not-real" not in finding.excerpt
    assert "sample-123" not in finding.excerpt
    assert "alice" not in finding.excerpt
    assert len(finding.excerpt) <= 120


def test_unknown_root_hidden_configuration_directory_is_reported(tmp_path):
    (tmp_path / ".github").mkdir()
    hidden = ".cache" + "tool"
    (tmp_path / hidden).mkdir()

    assert scan(tmp_path) == (Finding(hidden + "/", 1, "unknown-hidden-config", "<redacted>"),)


@pytest.mark.parametrize(
    ("text", "expected_lines"),
    [
        (
            "https://example.com/spec\nhttp://localhost:8000/ok\n"
            + "https://"
            + "private.invalid/v1/jobs\n",
            [3],
        ),
        ("https://" + "user@example.com/spec\n", [1]),
        ("http://" + "user:pass@localhost:8000/ok\n", [1]),
    ],
)
def test_public_and_loopback_urls_are_allowed_but_unknown_url_is_not(
    tmp_path, text, expected_lines
):
    (tmp_path / "links.txt").write_text(text, encoding="utf-8")

    findings = scan(tmp_path)

    assert [(item.line, item.rule_id) for item in findings] == [
        (line, "nonpublic-url") for line in expected_lines
    ]
    assert all(item.excerpt == "<redacted>" for item in findings)


def test_source_and_artifacts_are_ordered_and_fail_closed_on_unscanned_content(tmp_path):
    (tmp_path / "b.txt").write_text("API_" + "KEY=x\n", encoding="utf-8")
    build = tmp_path / "build"
    build.mkdir()
    (build / "a.txt").write_text("store_" + "id=y\n", encoding="utf-8")
    (build / "binary.dat").write_bytes(b"bad\x00data")
    (build / "invalid.txt").write_bytes(b"\xff")
    (build / "link.txt").symlink_to(build / "a.txt")

    findings = scan(tmp_path, artifacts=(build,))

    assert [(item.path, item.rule_id) for item in findings] == [
        ("b.txt", "sensitive-assignment"),
        ("build/a.txt", "resource-identifier-assignment"),
        ("build/binary.dat", "unscanned-content"),
        ("build/invalid.txt", "unscanned-content"),
        ("build/link.txt", "unscanned-content"),
    ]


def test_git_checkout_scans_only_tracked_regular_files(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("deployment_" + "id=x\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("API_" + "TO" + "KEN" + "=" + "y\n", encoding="utf-8")
    (tmp_path / ".untracked").mkdir()
    (tmp_path / ".ignored").mkdir()
    (tmp_path / ".gitignore").write_text(".ignored/\n", encoding="utf-8")
    tracked_hidden = tmp_path / ".tracked-config"
    tracked_hidden.mkdir()
    (tracked_hidden / "settings.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "tracked.txt", ".gitignore", ".tracked-config"],
        check=True,
    )

    assert [item.path for item in scan(tmp_path)] == [".tracked-config/", "tracked.txt"]


def test_canonical_exact_and_glob_policy_rules_are_applied_and_redacted(tmp_path):
    denied = "acme" + "-host"
    prefixed = "ACME" + "_REGION"
    (tmp_path / "input.txt").write_text(f"service={denied}\n{prefixed}=demo\n", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_bytes(
        _canonical(
            _policy(
                (("policy.exact-host", denied),),
                (("policy.env-prefix", "ACME_" + "*"),),
            )
        )
    )

    findings = scan(tmp_path, deny_policy=policy)

    assert [(item.line, item.rule_id) for item in findings] == [
        (1, "policy.exact-host"),
        (2, "policy.env-prefix"),
    ]
    assert all(item.excerpt == "<redacted>" for item in findings)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"exact_rules":[],"exact_rules":[],"glob_rules":[],"schema_version":1}\n',
        _canonical(
            {
                **_policy(),
                "unexpected": True,
            }
        ),
        json.dumps(_policy()).encode(),
    ],
)
def test_invalid_or_noncanonical_policy_is_rejected(tmp_path, payload):
    policy = tmp_path / "policy.json"
    policy.write_bytes(payload)

    with pytest.raises(ValueError, match="deny policy"):
        scan(tmp_path, deny_policy=policy)


def test_cli_exit_codes_and_canonical_report(tmp_path):
    source = tmp_path / "input.txt"
    report = tmp_path / "report.json"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source.write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "input.txt"], check=True)
    assert main(["--root", str(tmp_path), "--report-json", str(report)]) == 0
    assert report.read_bytes() == _canonical(
        {"findings": [], "schema_version": 1, "tool": "provider-neutrality"}
    )

    subprocess.run(["git", "-C", str(tmp_path), "add", "report.json"], check=True)
    source.write_text("account_" + "id=demo\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--report-json", str(report)]) == 1
    first_report = report.read_bytes()
    assert json.loads(first_report)["findings"][0]["rule_id"] == ("resource-identifier-assignment")
    assert main(["--root", str(tmp_path), "--report-json", str(report)]) == 1
    assert report.read_bytes() == first_report

    with pytest.raises(SystemExit) as exc:
        main(["--root", str(tmp_path / "missing")])
    assert exc.value.code == 2


def test_large_text_is_stream_scanned_across_chunk_boundaries(tmp_path):
    prefix = b"x" * (CHUNK_BYTES - 4)
    (tmp_path / "large.txt").write_bytes(
        prefix + b"https://" + b"concrete-host.invalid/container\n" + b"x" * CHUNK_BYTES
    )

    assert [(item.path, item.rule_id) for item in scan(tmp_path)] == [
        ("large.txt", "nonpublic-url")
    ]


def test_generic_hosted_container_manifest_is_rejected_without_provider_policy(tmp_path):
    (tmp_path / "deployment.json").write_text(
        '{"container":{"health":"https://' + "concrete-host.invalid/health" + '"}}\n',
        encoding="utf-8",
    )

    assert scan(tmp_path) == (Finding("deployment.json", 1, "nonpublic-url", "<redacted>"),)


def test_artifact_count_and_path_bounds(tmp_path):
    large = tmp_path / "large.txt"
    large.write_text("clean\n", encoding="utf-8")
    with pytest.raises(ValueError, match="at most 16"):
        scan(tmp_path, artifacts=tuple(tmp_path / f"a-{index}" for index in range(17)))
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="invalid artifact"):
        scan(tmp_path, artifacts=(missing,))
    missing.symlink_to(large)
    with pytest.raises(ValueError, match="invalid artifact"):
        scan(tmp_path, artifacts=(missing,))


def test_scanner_tests_and_current_tree_scan_clean_without_exclusions(tmp_path):
    for relative in (
        Path("scripts/check_provider_neutrality.py"),
        Path("tests/test_provider_neutrality.py"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(relative.read_bytes())

    assert scan(tmp_path) == ()
    assert scan(Path.cwd()) == ()
