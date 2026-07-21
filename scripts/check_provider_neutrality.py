"""Bounded fail-closed pre-publication scanner for provider-specific residue."""
# ruff: noqa: E501, E701, E702

from __future__ import annotations

# fmt: off
import argparse
import codecs
import fnmatch
import ipaddress
import json
import re
import stat
import subprocess
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any, Iterable, Sequence
from urllib.parse import urlsplit

CHUNK_BYTES, OVERLAP_CHARACTERS, MAX_ARCHIVE_MEMBERS, MAX_ARTIFACTS = 65_536, 512, 4096, 16
MAX_POLICY_BYTES, MAX_RULES_PER_KIND = 65_536, 64
_ALLOWED_BINARY_SUFFIXES = {".png"}; _ARCHIVE_SUFFIXES = (".zip", ".whl", ".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz"); _ALLOWED_HIDDEN = {".git", ".github"}
_ALLOWED_PUBLIC_HOSTS = frozenset("astral.sh baseballsavant.mlb.com blogs.fangraphs.com creativecommons.org en.wikipedia.org example.com files.pythonhosted.org github.com huggingface.co img.shields.io modelcontextprotocol.io opencollective.com pypi.org raw.githubusercontent.com registry.npmjs.org sabr.org stathead.com statsapi.mlb.com svelte.dev tidelift.com www.example.com www.fangraphs.com www.mlb.com www.retrosheet.org www.statmuse.com www.w3.org".split())  # noqa: E501  # fmt: skip
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PERSONAL_PATH = re.compile(r"/(?:Users|Volumes)/[^/\s\"']+")
_NAME_SEGMENTS = r"(?:[A-Za-z0-9]+[_-])*"
_NAME_SUFFIX = r"(?:[_-][A-Za-z0-9]+)*"
_SENSITIVE_ASSIGNMENT = re.compile(rf"(?i)\b(?P<name>{_NAME_SEGMENTS}(?:credential|api[_-]?key|secret|token|password|authorization|request[_-]?identity|user[_-]?agent|client[_-]?ip){_NAME_SUFFIX})\s*[:=]")  # noqa: E501
_RESOURCE_ASSIGNMENT = re.compile(rf"(?i)\b(?P<name>{_NAME_SEGMENTS}(?:account|organization|org|project|store|deployment)[_-]id{_NAME_SUFFIX})\s*[:=]")  # noqa: E501
_LEXEME = re.compile(r"[A-Za-z0-9_@./:+-]+")
_RULE_ID = re.compile(r"[a-z][a-z0-9.-]{0,63}")

@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    rule_id: str
    excerpt: str

def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")  # noqa: E501

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
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid deny policy") from error
    if not raw or len(raw) > MAX_POLICY_BYTES or not isinstance(data, dict) or set(data) != {"schema_version", "exact_rules", "glob_rules"}:
        raise ValueError("invalid deny policy")
    try:
        canonical = _canonical_json(data)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid deny policy") from error
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or canonical != raw:
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
    rules: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"rule_id", field}:
            raise ValueError("invalid deny policy")
        rule_id, pattern = item["rule_id"], item[field]
        if not isinstance(rule_id, str) or not _RULE_ID.fullmatch(rule_id):
            raise ValueError("invalid deny policy")
        if not isinstance(pattern, str) or not pattern or len(pattern) > 256 or any(ord(char) < 32 for char in pattern):
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
        top = subprocess.run([*command, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
            return None
        result = subprocess.run([*command, "ls-files", "-z"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    paths: list[Path] = []
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        try:
            candidate = root / raw_name.decode("utf-8")
            if candidate.exists() or candidate.is_symlink():
                paths.append(candidate)
        except UnicodeDecodeError:
            paths.append(root / "<invalid-git-path>")
    return paths

def _tree_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if ".git" not in path.relative_to(root).parts and (path.is_file() or path.is_symlink())]

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

def _url_allowed(value: str) -> bool:
    parsed = urlsplit(value.rstrip(".,);]"))
    if parsed.username is not None or parsed.password is not None or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in _ALLOWED_PUBLIC_HOSTS

def _line_findings(relative: str, number: int, line: str, exact: list[dict[str, str]], globs: list[dict[str, str]], *, incomplete: bool = False) -> list[Finding]:
    if not exact and not globs and not any(marker in line for marker in ("/", "=", ":")):
        return []
    found: list[Finding] = []
    if _PERSONAL_PATH.search(line):
        found.append(Finding(relative, number, "personal-absolute-path", "<redacted>"))
    for match in _URL.finditer(line):
        if incomplete and match.end() == len(line):
            continue
        if not _url_allowed(match.group()):
            found.append(Finding(relative, number, "nonpublic-url", "<redacted>"))
    resource_match = _RESOURCE_ASSIGNMENT.search(line)
    assignment_match = _SENSITIVE_ASSIGNMENT.search(line)
    if resource_match:
        found.append(Finding(relative, number, "resource-identifier-assignment", f"{resource_match.group('name')}=<redacted>"[-120:]))
    elif assignment_match:
        found.append(Finding(relative, number, "sensitive-assignment", f"{assignment_match.group('name')}=<redacted>"[-120:]))
    for rule in exact:
        if rule["value"] in line:
            found.append(Finding(relative, number, rule["rule_id"], "<redacted>"))
    lexemes = _LEXEME.findall(line)
    for rule in globs:
        if fnmatch.fnmatchcase(line, rule["pattern"]) or any(fnmatch.fnmatchcase(item, rule["pattern"]) for item in lexemes):
            found.append(Finding(relative, number, rule["rule_id"], "<redacted>"))
    return found

def _scan_stream(stream: IO[bytes], relative: str, exact: list[dict[str, str]], globs: list[dict[str, str]]) -> list[Finding]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    overlap = ""
    newlines = 0
    findings: list[Finding] = []
    try:
        while raw := stream.read(CHUNK_BYTES):
            if b"\0" in raw:
                raise UnicodeError
            chunk = decoder.decode(raw)
            window = overlap + chunk
            base_line = 1 + newlines - overlap.count("\n")
            scannable = window[:-OVERLAP_CHARACTERS]
            lines = scannable.splitlines() or [scannable]
            for index, line in enumerate(lines):
                incomplete = index == len(lines) - 1 and not scannable.endswith(("\n", "\r"))
                findings.extend(_line_findings(relative, base_line + index, line, exact, globs, incomplete=incomplete))
            newlines += chunk.count("\n")
            overlap = window[-OVERLAP_CHARACTERS:]
        decoder.decode(b"", final=True)
        base_line = 1 + newlines - overlap.count("\n")
        for index, line in enumerate(overlap.splitlines() or [overlap]):
            findings.extend(_line_findings(relative, base_line + index, line, exact, globs))
    except (OSError, UnicodeError):
        return [Finding(relative, 1, "unscanned-content", "<redacted>")]
    return findings

def _is_archive(name: str) -> bool: return name.lower().endswith(_ARCHIVE_SUFFIXES)

def _scan_archive(path: Path, relative: str, exact: list[dict[str, str]], globs: list[dict[str, str]]) -> list[Finding]:
    found: list[Finding] = []
    try:
        if path.suffix.lower() in {".zip", ".whl"}:
            with zipfile.ZipFile(path) as archive:
                zip_members = archive.infolist()
                if len(zip_members) > MAX_ARCHIVE_MEMBERS:
                    raise ValueError
                for zip_member in zip_members:
                    label = f"{relative}!{zip_member.filename}"
                    mode = zip_member.external_attr >> 16
                    if zip_member.is_dir():
                        continue
                    if stat.S_ISLNK(mode) or _is_archive(zip_member.filename):
                        found.append(Finding(label, 1, "unscanned-content", "<redacted>"))
                    elif Path(zip_member.filename).suffix.lower() not in _ALLOWED_BINARY_SUFFIXES:
                        with archive.open(zip_member) as stream:
                            found.extend(_scan_stream(stream, label, exact, globs))
        else:
            with tarfile.open(path, "r:*") as archive:
                tar_members = archive.getmembers()
                if len(tar_members) > MAX_ARCHIVE_MEMBERS:
                    raise ValueError
                for tar_member in tar_members:
                    if tar_member.isdir():
                        continue
                    label = f"{relative}!{tar_member.name}"
                    if not tar_member.isfile() or _is_archive(tar_member.name):
                        found.append(Finding(label, 1, "unscanned-content", "<redacted>"))
                    elif Path(tar_member.name).suffix.lower() not in _ALLOWED_BINARY_SUFFIXES:
                        tar_stream = archive.extractfile(tar_member)
                        if tar_stream is None:
                            raise OSError
                        with tar_stream:
                            found.extend(_scan_stream(tar_stream, label, exact, globs))
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile):
        return [Finding(relative, 1, "unscanned-content", "<redacted>")]
    return found

def _deployment_finding(path: Path, relative: str) -> list[Finding]:
    if Path(relative).name.lower() not in {"deployment.yaml", "deployment.yml"}:
        return []
    try:
        raw = path.read_bytes(); text = raw.decode("utf-8") if len(raw) <= MAX_POLICY_BYTES else ""
    except (OSError, UnicodeError):
        return []
    required = (r"(?m)^services:\s*$", r"(?m)^\s+image:\s*\S+", r"(?m)^\s+ports:\s*(?:$|\[)"); return [Finding(relative, 1, "deployment-manifest", "<redacted>")] if all(re.search(item, text) for item in required) else []

def _scan_path(path: Path, relative: str, exact: list[dict[str, str]], globs: list[dict[str, str]]) -> list[Finding]:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            return [Finding(relative, 1, "unscanned-content", "<redacted>")]
        if path.suffix.lower() in _ALLOWED_BINARY_SUFFIXES:
            return []
        if _is_archive(relative):
            return _scan_archive(path, relative, exact, globs)
        with path.open("rb") as stream:
            return _scan_stream(stream, relative, exact, globs) + _deployment_finding(path, relative)
    except OSError:
        return [Finding(relative, 1, "unscanned-content", "<redacted>")]

def scan(root: str | Path, *, artifacts: Sequence[str | Path] = (), deny_policy: str | Path | None = None) -> tuple[Finding, ...]:
    return _scan(root, artifacts, deny_policy, None)

def _scan(root: str | Path, artifacts: Sequence[str | Path], deny_policy: str | Path | None, exclude: Path | None) -> tuple[Finding, ...]:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ValueError("root must be a directory")
    root_path = root_path.resolve()
    policy_path = Path(deny_policy).resolve() if deny_policy is not None else None
    exact, globs = _load_policy(policy_path)
    tracked = _git_files(root_path)
    files = _tree_files(root_path) if tracked is None else tracked
    hidden: Iterable[Path] = root_path.iterdir() if tracked is None else {root_path / path.relative_to(root_path).parts[0] for path in tracked}
    files.extend(_artifact_files(root_path, artifacts))
    findings: list[Finding] = []
    for child in sorted(hidden, key=lambda item: item.name):
        if child.name.startswith(".") and child.name not in _ALLOWED_HIDDEN and child.is_dir() and not child.is_symlink():
            findings.append(Finding(child.name + "/", 1, "unknown-hidden-config", "<redacted>"))
    for path in sorted(set(files), key=lambda item: item.relative_to(root_path).as_posix()):
        try:
            relative = path.relative_to(root_path).as_posix()
            resolved = path.resolve()
        except (OSError, ValueError):
            findings.append(Finding("<invalid-path>", 1, "unscanned-content", "<redacted>"))
            continue
        if resolved not in {policy_path, exclude}:
            findings.extend(_scan_path(path, relative, exact, globs))
    return tuple(sorted(set(findings)))

def _report(findings: tuple[Finding, ...]) -> bytes:
    return _canonical_json({"findings": [asdict(finding) for finding in findings], "schema_version": 1, "tool": "provider-neutrality"})

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
