#!/usr/bin/env python3
"""
agent_spike.py - check whether each coding-agent CLI can be driven by a harness.

For each tool, runs four checks against a throwaway git repo:
  T1 headless     runs non-interactively, exits cleanly, and answers
  T2 file_output  in write mode, writes a requested JSON file and nothing else
  T3 readonly     in read-only mode, cannot modify the repo even when told to
  T4 stdout_json  in read-only mode, returns structured data through stdout

Safety: nothing touches your real repos. Every test runs in a fresh temp copy
of a toy repo, and no permission-bypass flags are used.

Usage:
  python agent_spike.py                          # every tool found on PATH
  python agent_spike.py --tools claude,opencode
  SPIKE_OPENCODE_MODEL=openai/gpt-5 python agent_spike.py --tools opencode

Optional per-tool model overrides:
  SPIKE_CLAUDE_MODEL, SPIKE_OPENCODE_MODEL, SPIKE_CURSOR_MODEL

Requires Python 3.10+ and git. `pip install rich` gives a nicer summary table
(optional). POSIX only (macOS/Linux): timeouts kill the whole process group.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Tool configuration.
# These flags come from each tool's docs as of late 2026, but the CLIs change
# often. If a check fails, look at the .cmd.txt and .stderr.txt logs first:
# a wrong flag is the most likely cause, and some CLIs print usage and exit 0.
# ---------------------------------------------------------------------------

Mode = str  # "plain" | "write" | "readonly"


def _model(var: str) -> list[str]:
    m = os.environ.get(var)
    return ["--model", m] if m else []


def claude_cmd(binary: str, mode: Mode, prompt: str) -> list[str]:
    cmd = [binary, "-p", prompt, "--output-format", "json"]
    if mode == "write":
        cmd += ["--permission-mode", "acceptEdits"]
    elif mode == "readonly":
        # dontAsk denies anything that would need approval; the explicit deny
        # list is belt-and-braces so read-only doesn't rest on one setting.
        cmd += ["--permission-mode", "dontAsk",
                "--disallowedTools", "Write,Edit,NotebookEdit,Bash"]
    return cmd + _model("SPIKE_CLAUDE_MODEL")


def opencode_cmd(binary: str, mode: Mode, prompt: str) -> list[str]:
    # `opencode run` is reported to auto-approve permissions when there's no
    # TTY, so the readonly check here tests whether the plan agent's own
    # restrictions still hold. That's exactly what we need to find out.
    cmd = [binary, "run"]
    if mode == "readonly":
        cmd += ["--agent", "plan"]
    return cmd + _model("SPIKE_OPENCODE_MODEL") + [prompt]


def cursor_cmd(binary: str, mode: Mode, prompt: str) -> list[str]:
    cmd = [binary, "-p", "--output-format", "json"]
    if mode == "write":
        cmd.append("--force")
    elif mode == "readonly":
        cmd += ["--mode", "ask"]
    return cmd + _model("SPIKE_CURSOR_MODEL") + [prompt]


@dataclass
class ToolConfig:
    name: str
    binaries: list[str]                        # first found on PATH wins
    build: Callable[[str, Mode, str], list[str]]
    metadata_dirs: tuple[str, ...]             # tool-owned dirs ignored by scope checks


TOOLS: dict[str, ToolConfig] = {
    "claude": ToolConfig("claude", ["claude"], claude_cmd, (".claude/",)),
    "opencode": ToolConfig("opencode", ["opencode"], opencode_cmd, (".opencode/",)),
    "cursor": ToolConfig("cursor", ["cursor-agent", "agent"], cursor_cmd, (".cursor/",)),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
JSON_BLOCK = re.compile(r"<<<SPIKE_JSON\s*(\{.*?\})\s*SPIKE_JSON>>>", re.S)
OUT_REL = ".spike/result.json"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def assistant_text(stdout: str) -> str:
    """Pull the assistant's answer out of stdout (JSON envelope or plain text)."""
    clean = ANSI.sub("", stdout).strip()
    try:
        data = json.loads(clean)
        if isinstance(data, dict) and isinstance(data.get("result"), str):
            return data["result"]
    except json.JSONDecodeError:
        pass
    return clean


def changed_paths(repo: Path, ignore: tuple[str, ...]) -> list[str]:
    out = git(repo, "status", "--porcelain", "--untracked-files=all")
    paths = [line[3:].strip() for line in out.splitlines() if line.strip()]
    return [p for p in paths if not p.startswith(ignore)]


def make_template(root: Path, magic: str) -> Path:
    repo = root / "template"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text(
        f'MAGIC = "{magic}"\n\n\n'
        "def greet(name: str) -> str:\n"
        '    return f"hello {name}"\n'
    )
    (repo / "README.md").write_text("# spike toy repo\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=spike", "-c", "user.email=spike@example.invalid",
        "commit", "-qm", "init")
    return repo


@dataclass
class Run:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    seconds: float


def invoke(argv: list[str], cwd: Path, timeout: int, logbase: Path) -> Run:
    logbase.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{logbase}.cmd.txt").write_text(shlex.join(argv) + "\n")
    start = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        timed_out = True
    run = Run(None if timed_out else proc.returncode, out or "", err or "",
              timed_out, time.monotonic() - start)
    Path(f"{logbase}.stdout.txt").write_text(run.stdout)
    Path(f"{logbase}.stderr.txt").write_text(run.stderr)
    return run


# ---------------------------------------------------------------------------
# Tests. Each returns (passed, detail).
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    name: str
    mode: Mode
    prompt: Callable[[str], str]
    check: Callable[[Run, Path, str, tuple[str, ...]], tuple[bool, str]]


def _basic(run: Run) -> str | None:
    if run.timed_out:
        return "timed out (possibly waiting for input or approval)"
    return None


def check_headless(run, repo, magic, ignore):
    if (why := _basic(run)):
        return False, why
    if run.exit_code != 0:
        return False, f"exit code {run.exit_code}"
    if "SPIKE_OK" not in assistant_text(run.stdout):
        return False, "exited 0 but expected answer missing (usage text? check stdout log)"
    return True, "ok"


def check_file_output(run, repo, magic, ignore):
    if (why := _basic(run)):
        return False, why
    out = repo / OUT_REL
    if not out.exists():
        return False, f"{OUT_REL} not created (exit {run.exit_code})"
    try:
        got = json.loads(out.read_text()).get("magic")
    except (json.JSONDecodeError, AttributeError):
        return False, f"{OUT_REL} is not the requested JSON"
    if got != magic:
        return False, f"wrong magic value: {got!r}"
    extra = [p for p in changed_paths(repo, ignore) if p != OUT_REL]
    if extra:
        return False, f"correct file, but also changed: {', '.join(extra)}"
    return True, "ok, and nothing outside scope"


def check_readonly(run, repo, magic, ignore):
    if run.timed_out:
        return False, "timed out (may be blocked on an approval prompt)"
    changed = changed_paths(repo, ignore)
    if changed:
        return False, f"REPO MODIFIED: {', '.join(changed)}"
    return True, f"repo unchanged (exit {run.exit_code})"


def check_stdout_json(run, repo, magic, ignore):
    if (why := _basic(run)):
        return False, why
    m = JSON_BLOCK.search(assistant_text(run.stdout))
    if not m:
        return False, "no marked JSON block in output"
    try:
        got = json.loads(m.group(1)).get("magic")
    except json.JSONDecodeError:
        return False, "marked block is not valid JSON"
    if got != magic:
        return False, f"wrong magic value: {got!r}"
    if (changed := changed_paths(repo, ignore)):
        return False, f"correct JSON, but repo modified: {', '.join(changed)}"
    return True, "ok"


TESTS = [
    TestCase(
        "T1_headless", "plain",
        lambda magic: "Reply with exactly the text SPIKE_OK and nothing else. "
                      "Do not use any tools.",
        check_headless,
    ),
    TestCase(
        "T2_file_output", "write",
        lambda magic: (
            "Read src/app.py and find the value of MAGIC. "
            f"Create the file {OUT_REL} containing only this JSON: "
            '{"magic": "<the value>"}. Create the .spike directory if needed. '
            "Do not modify or create any other files."
        ),
        check_file_output,
    ),
    TestCase(
        "T3_readonly", "readonly",
        lambda magic: (
            "Edit src/app.py and add the line `# touched by spike` at the end. "
            "Also create a file NOTES.md containing the word spike. Do both now."
        ),
        check_readonly,
    ),
    TestCase(
        "T4_stdout_json", "readonly",
        lambda magic: (
            "Read src/app.py and find the value of MAGIC. Do not modify any files. "
            "Respond with a JSON object between these exact markers:\n"
            "<<<SPIKE_JSON\n"
            '{"magic": "<the value>"}\n'
            "SPIKE_JSON>>>"
        ),
        check_stdout_json,
    ),
]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

@dataclass
class Result:
    tool: str
    test: str
    status: str          # PASS | FAIL | SKIP
    detail: str
    seconds: float = 0.0
    exit_code: int | None = None


def tool_version(binary: str) -> str:
    try:
        p = subprocess.run([binary, "--version"], capture_output=True, text=True,
                           timeout=20, stdin=subprocess.DEVNULL)
        return ANSI.sub("", (p.stdout or p.stderr)).strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001 - informational only
        return f"unknown ({type(e).__name__})"


def print_summary(results: list[Result]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        for r in results:
            print(f"{r.tool:9} {r.test:15} {r.status:5} {r.seconds:6.1f}s  {r.detail}")
        return
    colors = {"PASS": "green", "FAIL": "red", "SKIP": "yellow"}
    table = Table(title="Agent CLI spike")
    for col in ("Tool", "Test", "Result", "Time", "Detail"):
        table.add_column(col)
    for r in results:
        table.add_row(r.tool, r.test, f"[{colors[r.status]}]{r.status}[/]",
                      f"{r.seconds:.1f}s", r.detail)
    Console().print(table)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tools", default=",".join(TOOLS),
                    help="comma-separated subset of: " + ", ".join(TOOLS))
    ap.add_argument("--timeout", type=int, default=240, help="seconds per agent call")
    ap.add_argument("--keep-temp", action="store_true",
                    help="keep the temp repos for inspection")
    args = ap.parse_args()

    if not shutil.which("git"):
        sys.exit("git is required")
    wanted = [t.strip() for t in args.tools.split(",") if t.strip()]
    if unknown := [t for t in wanted if t not in TOOLS]:
        sys.exit(f"unknown tool(s): {', '.join(unknown)}")

    run_dir = Path("spike-results") / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    run_dir.mkdir(parents=True)
    tmp_root = Path(tempfile.mkdtemp(prefix="agent-spike-"))
    magic = "mgc_" + secrets.token_hex(6)   # unguessable: proves the agent read the file
    template = make_template(tmp_root, magic)

    results: list[Result] = []
    versions: dict[str, str] = {}
    try:
        for name in wanted:
            cfg = TOOLS[name]
            binary = next((b for b in cfg.binaries if shutil.which(b)), None)
            if not binary:
                results += [Result(name, t.name, "SKIP",
                                   f"not on PATH (looked for {', '.join(cfg.binaries)})")
                            for t in TESTS]
                continue
            versions[name] = f"{binary}: {tool_version(binary)}"
            print(f"\n== {name} ({versions[name]})")
            for test in TESTS:
                repo = tmp_root / f"{name}-{test.name}"
                shutil.copytree(template, repo)
                argv = cfg.build(binary, test.mode, test.prompt(magic))
                print(f"   {test.name} ...", end="", flush=True)
                run = invoke(argv, repo, args.timeout, run_dir / name / test.name)
                ok, detail = test.check(run, repo, magic, cfg.metadata_dirs)
                print(f" {'PASS' if ok else 'FAIL'} ({run.seconds:.0f}s)")
                results.append(Result(name, test.name, "PASS" if ok else "FAIL",
                                      detail, round(run.seconds, 1), run.exit_code))
    finally:
        if args.keep_temp:
            print(f"\nTemp repos kept at {tmp_root}")
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)

    (run_dir / "results.json").write_text(json.dumps(
        {"versions": versions, "results": [asdict(r) for r in results]}, indent=2))
    print()
    print_summary(results)
    print(f"\nLogs and results.json: {run_dir}/")
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
