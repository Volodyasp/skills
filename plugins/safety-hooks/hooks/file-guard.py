#!/usr/bin/env python3
"""file-guard — PreToolUse hook that blocks access to secret files.

Protocol (Claude Code PreToolUse):
- stdin: JSON with fields {"tool_name": str, "tool_input": dict, ...}
- exit 0: allow the tool call (silent)
- exit 2: block, stderr shown to the model as the reason

Covered tools:
- Read / Edit / Write / MultiEdit / NotebookEdit — file_path glob-matched against
  PROTECTED_PATTERNS, with ALLOWED_PATTERNS as escape hatch (e.g. .env.example).
  Matches BOTH the literal path AND its symlink-resolved real path,
  so `ln -s .env /tmp/x` cannot be used to bypass the rule.
  Matching is case-insensitive (handles .Env, .ENV, Secret.json).
- Bash — regex-matched against DANGEROUS_BASH_PATTERNS for exfiltration
  attempts. Whitespace-tolerant: `cat  .env` (double space) still blocked.
  Each pattern carries a human reason surfaced in the block message.

Fails open on:
- malformed JSON stdin
- payload that isn't an object
- tool_input that isn't a dict
- file_path / command of unexpected type
A buggy hook must never block normal work — exit 2 is reserved for
deliberately-matched policy violations.

Extend by editing the lists below. They are source-of-truth.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys

# Glob patterns matched against the file path (full path OR basename).
# Both pattern and path are lowered before fnmatch, so case is irrelevant —
# convention is to write patterns lowercase for readability.
PROTECTED_PATTERNS: list[str] = [
    # env files — ALLOWED_PATTERNS overrides .env.example etc.
    ".env",
    ".env.*",  # catches .local / .production / .bak / .swp / arbitrary suffix
    ".env~",  # editor backup (tilde isn't a dot, so .env.* misses it)
    ".envrc",
    # private keys and certificates
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "*_rsa",
    "*_ed25519",
    "*_ecdsa",
    "*_dsa",
    # cloud credentials
    "credentials",  # AWS ~/.aws/credentials
    "service-account*.json",  # GCP
    "gha-creds-*.json",  # GCP GH Actions
    "*-credentials*.json",
    # kubernetes
    "kubeconfig",
    ".kube/config",
    # terraform
    "*.tfvars",
    "*.tfvars.json",
    "terraform.tfstate",
    "terraform.tfstate.backup",
    ".terraform/terraform.tfstate*",
    # secrets manifests — `*secret*` already matches `secrets` (substring),
    # so plural variants would be dead patterns shadowed by these.
    "*secret*.json",
    "*secret*.yaml",
    "*secret*.yml",
    # version-control / package registries / git
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "git-credentials",
    "auth.json",  # composer / docker registry auth
]

# Safe-override patterns: explicitly allowed even if they match PROTECTED_PATTERNS.
ALLOWED_PATTERNS: list[str] = [
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.test",
    ".env.dist",
    "secrets.example.json",
    "secrets.example.yaml",
    "secrets.example.yml",
]

# Negative lookahead — these `.env.*` suffixes mark template files.
# The end-of-token assertion `(?:\s|$|/|[\"')`;|&])` is critical: without it
# `.env.test.local` would be treated as allowed because `\b` matches the
# `.` after `test`, but `.test.local` is a real env variant that must
# block (consistent with the path-side `.env.*` glob).
# Shell separators (`;`, `&`, `|`) also end the filename, so
# `cat .env.example; echo ok` stays allowed while `.env.example.bak` blocks.
_ENV_ALLOW = r"(?!\.(?:example|sample|template|test|dist)(?:\s|$|/|[\"')`;|&]))"
# Tail group — what comes after `.env`. Must match:
# - `rc\b` so `.envrc` matches
# - `\.` so `.env.local` matches
# - whitespace / EOL / `/` so `cat .env` and `cat .env/` match
# - quotes/parens/backtick so `cat ".env"`, `echo $(cat .env)` match
# - shell separators `;|&` so `cat .env;echo ok`, `cat .env|base64`,
#   `cat .env&&echo ok` block (without these, the bypass closes them).
# Without matching `.envoy/x` (the `o` after `.env` doesn't fit).
_ENV_TAIL = r"(?:rc\b|\.|\s|$|/|[\"')`;|&])"

# Verbs that can read or relocate a file's contents — anything in this set
# touching `.env` is treated as exfiltration. Includes: pure readers (cat,
# head, …); copy/move (cp, mv) which clone the secret to a new path; archive
# tools (tar, zip, gzip, bzip2) which embed it; remote movers (rsync, scp);
# encoders (base64); network (curl, wget) where the file is a CLI argument.
_BASH_EXFIL_VERBS = (
    r"cat|head|tail|less|more|nl|tac|od|xxd|strings|hexdump|hd"
    r"|cp|mv|rsync|scp|tar|zip|gzip|bzip2|base64"
    r"|curl|wget"
)
# Text-search verbs are kept separate because they're commonly used on
# non-secret files; matching them inside the exfil set would inflate
# false-positive risk for unrelated commands. They still block on `.env`
# directly. `rg|ack|ag` (modern grep alternatives) are essential — `rg`
# is the default search tool in many setups and would otherwise be a
# trivial bypass.
_BASH_TEXT_VERBS = r"awk|sed|grep|rg|ack|ag"
# Readers limited to private-key / cert files — narrower verb set because
# binary tools like `xxd` make sense for keys but not for archive flows.
_BASH_KEY_VERBS = r"cat|head|tail|less|more|od|xxd|strings|cp|mv|rsync|scp|tar|base64"
# Destructive / mutating verbs — Read/Edit/Write block these on the path
# side, so Bash must mirror to keep the policy consistent. `tee` writes
# stdin to its file argument; `ln` creates a symlink TO the target (which
# is itself a secret leak in the wrong direction).
_BASH_DESTROY_VERBS = r"rm|tee|touch|chmod|chown|truncate|shred|ln|mv"
# Interpreter one-liners that bypass the file-tool path: `python -c`,
# `node -e`, `perl -ne`, `ruby -e`, `php -r`, etc. Pattern matches
# `<interp> -<flag>` (any short flag) followed by code that mentions `.env`.
_BASH_INTERPRETERS = r"python3?|node|perl|ruby|php"

# Token boundaries inside a Bash command: chars that delimit a filename
# token from surrounding shell syntax. Used by the unified protected-token
# matcher below so `cat ~/.kube/config` matches `.kube/config` after `/`.
# `@` is included so `curl -F file=@.npmrc` and `wget --attach=@auth.json`
# (curl multipart `@FILE` syntax — read content from FILE) recognize the
# filename right after `@` as a protected token.
_TOKEN_END = r"(?:\s|$|/|[\"')`;|&])"  # noqa: S105
_TOKEN_BOUNDARY = r"(?:^|[/\s='\"@])"  # noqa: S105

# Verb set used by the unified protected-token read/copy rule. Broader than
# `_BASH_KEY_VERBS` because protected files are exfiltrated by the same set
# of tools that read .env (curl/wget upload, archive tools, text searchers,
# structured-data extractors). Without this, `zip out.zip .npmrc`,
# `jq . service-account-key.json`, `yq . k8s/db-secret.yaml`,
# `curl -F file=@.npmrc`, `rg token auth.json` all bypass.
_BASH_PROTECTED_READ_VERBS = _BASH_EXFIL_VERBS + "|" + _BASH_TEXT_VERBS + "|jq|yq"


def _glob_to_token_regex(glob: str) -> str:
    """Convert an fnmatch glob into a regex that matches the same filename
    AS A SHELL TOKEN. `*` matches token characters (not `/`, whitespace, or
    shell separators); `?` matches one such character. Path separators in
    the glob are kept literal (so `.kube/config` matches as a path).
    """
    out: list[str] = []
    for ch in glob:
        if ch == "*":
            out.append(r"[^/\s|;&\"')`<>]*")
        elif ch == "?":
            out.append(r"[^/\s|;&\"')`<>]")
        elif ch in r".+()[]{}^$|\\":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


# Patterns whose Bash-side semantics are handled by dedicated rules with
# allow-list awareness. Excluded from the unified protected-token matcher
# because the .env family carries template-allowlist semantics
# (`_ENV_ALLOW`/`_ENV_TAIL`) that the generic matcher can't express.
# Keys/certs/credentials are NOT excluded — the unified rule must cover
# them so destroy/redirect verbs (rm/chmod/echo>) and broader read verbs
# (zip/curl/jq/rg) all block consistently with PROTECTED_PATTERNS. The
# narrower dedicated key-cert read rule still fires first on common reads
# (cat/head/...) for a clearer error message.
_BASH_HANDLED_ELSEWHERE: set[str] = {
    ".env",
    ".env.*",
    ".envrc",
    ".env~",
}


def _build_bash_patterns() -> list[tuple[str, str]]:
    """Compose the DANGEROUS_BASH_PATTERNS list. Done as a function so the
    unified protected-token alternations can reference PROTECTED_PATTERNS /
    ALLOWED_PATTERNS defined above without polluting module scope."""

    protected_token = (
        "(?:"
        + "|".join(
            _glob_to_token_regex(p) for p in PROTECTED_PATTERNS if p not in _BASH_HANDLED_ELSEWHERE
        )
        + ")"
    )
    allowed_token = "(?:" + "|".join(_glob_to_token_regex(p) for p in ALLOWED_PATTERNS) + ")"
    # Negative-lookahead form: refuses to treat allowed-template tokens
    # (secrets.example.json, .env.sample, …) as protected matches.
    not_allowed = rf"(?!{allowed_token}{_TOKEN_END})"

    return [
        # ---------- .env-specific rules (with template-allow handling) ----------
        (
            rf"\b({_BASH_EXFIL_VERBS})\b[^|;&]*\.env{_ENV_ALLOW}{_ENV_TAIL}",
            "reads/copies/uploads .env",
        ),
        (
            rf"\b({_BASH_TEXT_VERBS})\b[^|;&]*\.env{_ENV_ALLOW}{_ENV_TAIL}",
            "extracts text from .env (rg/grep/awk/sed)",
        ),
        # write/destroy on .env — printf X > .env, rm .env, chmod 600 .env, etc.
        (
            rf"\b({_BASH_DESTROY_VERBS})\b[^|;&]*\.env{_ENV_ALLOW}{_ENV_TAIL}",
            "writes/destroys .env",
        ),
        (
            rf">>?\s*[^\s|;&<>]*\.env{_ENV_ALLOW}{_ENV_TAIL}",
            "redirects shell output to .env",
        ),
        # sourcing .env exposes secrets to the current shell environment
        (
            rf"\bsource\s+[^\s|;&]*\.env{_ENV_ALLOW}(?:rc\b|\b)",
            "sources .env into current shell environment",
        ),
        (
            rf"(?:^|[;&|(])\s*\.\s+[^\s|;&]*\.env{_ENV_ALLOW}(?:rc\b|\b)",
            "dot-sources .env into current shell",
        ),
        (
            rf"\bdd\s+if=[^\s|;&]*\.env{_ENV_ALLOW}",
            "dd-reads .env",
        ),
        # interpreter one-liners reading .env (python/node/perl/ruby/php)
        (
            rf"\b({_BASH_INTERPRETERS})\b[^|;&]*-[a-z]+\b[^|;&]*\.env{_ENV_ALLOW}",
            "interpreter one-liner reads .env",
        ),
        # ---------- private keys / certs (own verb set + tail) ----------
        (
            rf"\b({_BASH_KEY_VERBS})\b[^|;&]*\.(pem|key|p12|pfx){_TOKEN_END}",
            "reads/copies private key or certificate",
        ),
        (
            rf"\b({_BASH_KEY_VERBS})\b[^|;&]*id_(rsa|ed25519|ecdsa|dsa){_TOKEN_END}",
            "reads/copies SSH private key",
        ),
        # ---------- AWS creds (file + directory) ----------
        (
            r"\.aws/credentials",
            "reads AWS credentials file",
        ),
        (
            rf"\b({_BASH_KEY_VERBS})\b[^|;&]*~?/?\.aws{_TOKEN_END}",
            "operates on ~/.aws directory (dumps credentials)",
        ),
        (
            r"\baws\s+configure\s+get\b",
            "reads AWS credential via aws configure get",
        ),
        (
            r"\bgcloud\s+auth\s+(print-access-token|application-default\s+print-access-token)\b",
            "prints GCP access token",
        ),
        # ---------- k8s secrets ----------
        (
            r"\bkubectl\s+(get|describe)\s+secrets?\b",
            "reads k8s secret resource",
        ),
        (
            r"\bkubectl\s+(get|describe)\b[^|;&]*-o\s+(yaml|json)\b",
            "k8s get/describe -o yaml/json may include secret data",
        ),
        # ---------- UNIFIED protected-path matcher ------------------------
        # Catches any PROTECTED_PATTERNS entry (kubeconfig, terraform
        # state/tfvars, registry creds, service-accounts, secret manifests,
        # auth.json, AWS `credentials`, keys/certs, …) when touched by a
        # read/copy verb, destroy verb, or output redirection. Generated
        # from PROTECTED_PATTERNS so adding a new path glob automatically
        # extends Bash coverage too. The negative lookahead refuses ALLOWED
        # template tokens. Read verbs use `_BASH_PROTECTED_READ_VERBS`
        # (broad — covers cat/cp/zip/curl/jq/rg/wget/yq/…) so file
        # exfiltration via archive/upload/structured-data tools also blocks.
        (
            rf"\b({_BASH_PROTECTED_READ_VERBS})\b[^|;&]*{_TOKEN_BOUNDARY}{not_allowed}{protected_token}{_TOKEN_END}",
            "reads/copies a protected secret file",
        ),
        (
            rf"\b({_BASH_DESTROY_VERBS})\b[^|;&]*{_TOKEN_BOUNDARY}{not_allowed}{protected_token}{_TOKEN_END}",
            "writes/destroys a protected secret file",
        ),
        (
            rf">>?\s*[^\s|;&<>]*{not_allowed}{protected_token}{_TOKEN_END}",
            "redirects shell output to a protected secret file",
        ),
    ]


DANGEROUS_BASH_PATTERNS: list[tuple[str, str]] = _build_bash_patterns()

# IGNORECASE because shell paths are case-sensitive on POSIX but secret
# filenames in the wild appear in any case (.ENV, ID_RSA, cert.PEM on
# Windows-shared filesystems). The path-side glob is already case-folded;
# without IGNORECASE here, Bash leaks would slip through `cat .ENV`.
_COMPILED_BASH: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), reason) for p, reason in DANGEROUS_BASH_PATTERNS
]


def _resolve(path: str) -> str:
    """Resolve symlinks. Returns input on empty paths or rare realpath errors.

    `os.path.realpath` does NOT raise on missing files (it returns a
    best-effort resolved path), so the except clause covers only edge
    cases like permission errors on intermediate dirs or pathological
    symlink loops on platforms where realpath does raise.
    """
    if not path:
        return path
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return path


def _glob_match(path_low: str, base_low: str, patterns: list[str]) -> str | None:
    """Match a single (lowered) path against a glob list. Returns first hit."""
    for pat in patterns:
        pat_low = pat.lower()
        if (
            fnmatch.fnmatch(path_low, pat_low)
            or fnmatch.fnmatch(path_low, "*/" + pat_low)
            or fnmatch.fnmatch(base_low, pat_low)
        ):
            return pat
    return None


def _classify(path: str) -> tuple[str, str | None]:
    """Decide whether `path` should be blocked, allowed, or is irrelevant.

    Per-candidate semantics: the input path AND its symlink-resolved
    real path are each checked independently. A candidate is "protected"
    only if it matches PROTECTED_PATTERNS and NOT ALLOWED_PATTERNS. If
    any candidate is protected, we block — even if the OTHER candidate
    matches ALLOWED. This closes the symlink hijack where a file named
    `.env.example` is symlinked to a real `.env`: the literal name is
    allowed, but the resolved target is purely protected, so we block.

    Returns:
        ("protected", pattern) — at least one candidate is purely protected
        ("allowed", None)      — at least one candidate matches ALLOWED and
                                  no candidate is purely protected
        ("unmatched", None)    — neither pattern set hit any candidate
    """
    candidates = {path, _resolve(path)}
    saw_allowed = False
    for c in candidates:
        c_low = c.lower()
        b_low = os.path.basename(c_low)
        prot = _glob_match(c_low, b_low, PROTECTED_PATTERNS)
        allow = _glob_match(c_low, b_low, ALLOWED_PATTERNS)
        if prot and not allow:
            return ("protected", prot)
        if allow:
            saw_allowed = True
    return ("allowed", None) if saw_allowed else ("unmatched", None)


def _block(message: str) -> int:
    print(f"file-guard: {message}", file=sys.stderr)
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # fail open on malformed stdin
    if not isinstance(payload, dict):
        return 0  # fail open on non-object payload

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0  # fail open on malformed tool_input

    if tool_name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if not isinstance(path, str) or not path:
            return 0

        verdict, pattern = _classify(path)
        if verdict == "protected":
            return _block(
                f"{tool_name} blocked on {path!r} "
                f"(matches protected pattern {pattern!r}). "
                f"If you need this file, ask the user to paste contents into chat. "
                f"To adjust rules: {__file__}."
            )
        return 0

    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if not isinstance(cmd, str):
            return 0
        cmd = cmd.strip()
        if not cmd:
            return 0

        for compiled, reason in _COMPILED_BASH:
            m = compiled.search(cmd)
            if m:
                return _block(
                    f"Bash blocked: {reason}. "
                    f"Cmd: {cmd[:200]!r}. "
                    f"If you need this file, ask the user to paste contents into chat. "
                    f"To adjust rules: {__file__}."
                )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
