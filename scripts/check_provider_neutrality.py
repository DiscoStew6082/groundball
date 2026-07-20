"""Bounded pre-publication scanner for provider-specific residue."""

from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

MAX_TEXT_BYTES = 1_048_576
MAX_ARTIFACTS = 16
MAX_POLICY_BYTES = 65_536
MAX_RULES_PER_KIND = 64
_ALLOWED_HIDDEN = {".git", ".github"}
_ALLOWED_PUBLIC_HOSTS = frozenset("astral.sh baseballsavant.mlb.com blogs.fangraphs.com creativecommons.org en.wikipedia.org example.com files.pythonhosted.org github.com huggingface.co img.shields.io modelcontextprotocol.io opencollective.com pypi.org raw.githubusercontent.com registry.npmjs.org sabr.org smithery.ai stathead.com statsapi.mlb.com svelte.dev tidelift.com www.example.com www.fangraphs.com www.mlb.com www.retrosheet.org www.statmuse.com www.w3.org".split())  # noqa: E501  # fmt: skip
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PERSONAL_PATH = re.compile(r"/(?:Users|Volumes)/[^/\s\"']+")
_NAME_SEGMENTS = r"(?:[A-Za-z0-9]+[_-])*"
_NAME_SUFFIX = r"(?:[_-][A-Za-z0-9]+)*"
_SENSITIVE_ASSIGNMENT = re.compile(
    rf"(?i)\b(?P<name>{_NAME_SEGMENTS}(?:credential|api[_-]?key|secret|token|password|"
    rf"authorization|request[_-]?identity|user[_-]?agent|client[_-]?ip){_NAME_SUFFIX})\s*[:=]"
)
_RESOURCE_ASSIGNMENT = re.compile(
    rf"(?i)\b(?P<name>{_NAME_SEGMENTS}(?:account|organization|org|project|store|deployment)"
    rf"[_-]id{_NAME_SUFFIX})\s*[:=]"
)
_LEXEME = re.compile(r"[A-Za-z0-9_@./:+-]+")
_RULE_ID = re.compile(r"[a-z][a-z0-9.-]{0,63}")


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    rule_id: str
    excerpt: str


def _canonical_json(value: Any) -> bytes:
    text = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return (text + "\n").encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid deny policy")
        result[key] = value
    return result


def _load_policy(path: Path | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if path is None:
        return [], []
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid deny policy")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError("invalid deny policy") from error
    if not raw or len(raw) > MAX_POLICY_BYTES:
        raise ValueError("invalid deny policy")
    try:
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid deny policy") from error
    if not isinstance(data, dict) or set(data) != {"schema_version", "exact_rules", "glob_rules"}:
        raise ValueError("invalid deny policy")
    try:
        canonical = _canonical_json(data)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid deny policy") from error
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("invalid deny policy")
    if canonical != raw:
        raise ValueError("invalid deny policy")
    exact = _validate_rules(data["exact_rules"], "value", glob=False)
    globs = _validate_rules(data["glob_rules"], "pattern", glob=True)
    ids = [rule["rule_id"] for rule in exact + globs]
    if len(ids) != len(set(ids)):
        raise ValueError("invalid deny policy")
    return exact, globs


def _validate_rules(value: Any, field: str, *, glob: bool) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_RULES_PER_KIND:
        raise ValueError("invalid deny policy")
    expected_keys = {"rule_id", field}
    rules: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ValueError("invalid deny policy")
        rule_id, pattern = item["rule_id"], item[field]
        if not isinstance(rule_id, str) or not _RULE_ID.fullmatch(rule_id):
            raise ValueError("invalid deny policy")
        if not isinstance(pattern, str) or not pattern or len(pattern) > 256:
            raise ValueError("invalid deny policy")
        if any(ord(char) < 32 for char in pattern):
            raise ValueError("invalid deny policy")
        if glob and (len(pattern) > 128 or pattern.count("*") + pattern.count("?") > 8):
            raise ValueError("invalid deny policy")
        rules.append(item)
    keys = [(item["rule_id"], item[field]) for item in rules]
    patterns = [item[field] for item in rules]
    if keys != sorted(keys) or len(keys) != len(set(keys)) or len(patterns) != len(set(patterns)):
        raise ValueError("invalid deny policy")
    return rules


def _git_files(root: Path) -> list[Path] | None:
    command = ["git", "-C", str(root)]
    try:
        top = subprocess.run(
            [*command, "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
            return None
        result = subprocess.run(
            [*command, "ls-files", "-z"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    paths = []
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        try:
            name = raw_name.decode("utf-8")
        except UnicodeDecodeError:
            continue
        candidate = root / name
        if candidate.is_file() and not candidate.is_symlink():
            paths.append(candidate)
    return paths


def _tree_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if ".git" not in path.relative_to(root).parts and path.is_file() and not path.is_symlink()
    ]


def _artifact_files(root: Path, artifacts: Sequence[str | Path]) -> list[Path]:
    if len(artifacts) > MAX_ARTIFACTS:
        raise ValueError("at most 16 artifacts are allowed")
    selected: list[Path] = []
    for supplied in artifacts:
        candidate = Path(supplied)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_symlink() or not candidate.exists():
            raise ValueError("invalid artifact")
        try:
            candidate.resolve().relative_to(root)
        except (OSError, ValueError) as error:
            raise ValueError("invalid artifact") from error
        if candidate.is_file():
            selected.append(candidate)
        elif candidate.is_dir():
            selected.extend(_tree_files(candidate))
        else:
            raise ValueError("invalid artifact")
    return selected


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        raw = path.read_bytes()
        if len(raw) > MAX_TEXT_BYTES or b"\0" in raw:
            return None
        return raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _url_allowed(value: str) -> bool:
    parsed = urlsplit(value.rstrip(".,);]"))
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname
    if not host:
        return False
    host = host.lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in _ALLOWED_PUBLIC_HOSTS


def _line_findings(
    relative: str,
    number: int,
    line: str,
    exact: list[dict[str, str]],
    globs: list[dict[str, str]],
) -> list[Finding]:
    found: list[Finding] = []
    if _PERSONAL_PATH.search(line):
        found.append(Finding(relative, number, "personal-absolute-path", "<redacted>"))
    for match in _URL.finditer(line):
        if not _url_allowed(match.group()):
            found.append(Finding(relative, number, "nonpublic-url", "<redacted>"))
    resource_match = _RESOURCE_ASSIGNMENT.search(line)
    assignment_match = _SENSITIVE_ASSIGNMENT.search(line)
    if resource_match:
        excerpt = f"{resource_match.group('name')}=<redacted>"[-120:]
        found.append(Finding(relative, number, "resource-identifier-assignment", excerpt))
    elif assignment_match:
        excerpt = f"{assignment_match.group('name')}=<redacted>"[-120:]
        found.append(Finding(relative, number, "sensitive-assignment", excerpt))
    for rule in exact:
        if rule["value"] in line:
            found.append(Finding(relative, number, rule["rule_id"], "<redacted>"))
    lexemes = _LEXEME.findall(line)
    for rule in globs:
        pattern = rule["pattern"]
        if fnmatch.fnmatchcase(line, pattern) or any(
            fnmatch.fnmatchcase(lexeme, pattern) for lexeme in lexemes
        ):
            found.append(Finding(relative, number, rule["rule_id"], "<redacted>"))
    return found


def scan(
    root: str | Path,
    *,
    artifacts: Sequence[str | Path] = (),
    deny_policy: str | Path | None = None,
) -> tuple[Finding, ...]:
    return _scan(root, artifacts, deny_policy, None)


def _scan(
    root: str | Path,
    artifacts: Sequence[str | Path],
    deny_policy: str | Path | None,
    exclude: Path | None,
) -> tuple[Finding, ...]:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ValueError("root must be a directory")
    root_path = root_path.resolve()
    policy_path = Path(deny_policy).resolve() if deny_policy is not None else None
    exact, globs = _load_policy(policy_path)
    tracked = _git_files(root_path)
    files = _tree_files(root_path) if tracked is None else tracked
    hidden: Iterable[Path] = root_path.iterdir()
    if tracked is not None:
        hidden = {root_path / path.relative_to(root_path).parts[0] for path in tracked}
    files.extend(_artifact_files(root_path, artifacts))
    findings: list[Finding] = []
    for child in sorted(hidden, key=lambda item: item.name):
        if (
            child.name.startswith(".")
            and child.name not in _ALLOWED_HIDDEN
            and child.is_dir()
            and not child.is_symlink()
        ):
            findings.append(Finding(child.name + "/", 1, "unknown-hidden-config", "<redacted>"))
    for path in sorted(set(files), key=lambda item: item.relative_to(root_path).as_posix()):
        resolved = path.resolve()
        if resolved == policy_path or resolved == exclude:
            continue
        text = _read_text(path)
        if text is None:
            continue
        relative = path.relative_to(root_path).as_posix()
        for number, line in enumerate(text.splitlines(), 1):
            findings.extend(_line_findings(relative, number, line, exact, globs))
    return tuple(sorted(set(findings)))


def _report(findings: tuple[Finding, ...]) -> bytes:
    return _canonical_json(
        {
            "findings": [asdict(finding) for finding in findings],
            "schema_version": 1,
            "tool": "provider-neutrality",
        }
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--deny-policy")
    parser.add_argument("--report-json")
    args = parser.parse_args(argv)
    try:
        report_path = Path(args.report_json).resolve() if args.report_json else None
        findings = _scan(args.root, args.artifact, args.deny_policy, report_path)
        if report_path:
            report_path.write_bytes(_report(findings))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
