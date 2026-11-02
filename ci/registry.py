#!/usr/bin/env python3
"""The registry's CI: checks plugins, and builds the signed index.

    registry.py check --mudling BIN --luau-analyze BIN --session-log FILE
                      [--plugins DIR] [--report FILE]
    registry.py index --commit SHA --published-at TIME --output FILE
                      [--plugins DIR]
    registry.py comment REPORT

`check` exits 0 when every plugin passed, 1 when one failed and 2 when it
couldn't run. `mudling plugin test` does the loading and replaying;
docs/plugins/reference.md in the MUDling repo is the contract for its output.
docs/ci.md explains each check, and docs/index-format.md the index.

Standard library only, plus `openssl` 3 for the signature. `index` never runs
a plugin's code, so the signing key is never near it.
"""

import argparse
import base64
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

CI_FOLDER = Path(__file__).parent
REFERENCE_PLUGIN = CI_FOLDER / "reference"
LUAU_CONFIG = CI_FOLDER / "luaurc"

LICENSES = ("MIT", "Apache-2.0")
INDEX_FORMAT = 1
SIGNING_KEY_VARIABLE = "INDEX_SIGNING_KEY"
BUDGET_DOCS = "https://github.com/Vyttle-LLC/mudling-plugins/blob/main/docs/ci.md#the-budget"

# The budget is judged as `mudling-bench compare` judges a build: both sides
# run in turns on one machine, each block compares the lowest value each side
# reached, and a plugin is over only if it loses in every block.
MOST_OVER_REFERENCE = 1.10
ROUNDS_PER_BLOCK = 3
BLOCKS = 3

FAIL_LINE = re.compile(r"fail (\w+): (.*)")
COST_LINE = re.compile(
    r"(?:cost |fail budget: )\+(-?[\d.]+) µs a line at p99 "
    r"\(([\d.]+) with, [\d.]+ without\), budget [\d.]+ µs"
)
LUAU_FINDING = re.compile(r"\./hooks\.luau\((\d+),(\d+)\): (.*)")
PLUGIN_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")


class CouldNotRun(Exception):
    """A tool failed in a way that says nothing about the plugin."""


@dataclass
class Tools:
    mudling: Path
    luau_analyze: Path
    session_log: Path
    reference: Path = REFERENCE_PLUGIN


@dataclass
class Failure:
    kind: str
    detail: str


@dataclass
class Cost:
    added_us: float
    with_us: float


@dataclass
class Budget:
    """One log's verdict: the plugin's cost against the reference's."""

    log: str
    plugin: Cost
    reference: Cost
    within: bool

    @property
    def ratio(self) -> float:
        return self.plugin.with_us / self.reference.with_us


@dataclass
class Result:
    id: str
    failures: list[Failure]
    budget: Budget | None = None


def read_manifest(folder: Path) -> dict | None:
    """The manifest, or None if there's none to read: loading then says why."""
    try:
        return tomllib.loads((folder / "plugin.toml").read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def check_layout(folder: Path, manifest: dict | None) -> list[Failure]:
    failures = []
    if manifest is not None and manifest.get("id") != folder.name:
        failures.append(
            Failure("layout", f"the folder is {folder.name} but the id is {manifest.get('id')}")
        )
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder)
        if path.is_symlink():
            failures.append(Failure("layout", f"{name} is a symbolic link"))
        if path.suffix.lower() == ".log":
            failures.append(
                Failure("layout", f"{name}: session logs hold other players' chat, so they never go in the registry")
            )
    return failures


def check_license(manifest: dict | None) -> list[Failure]:
    if manifest is None or manifest.get("license") in LICENSES:
        return []
    wanted = " or ".join(LICENSES)
    return [Failure("license", f"the license is {manifest.get('license')}, and must be {wanted}")]


def plugin_test(tools: Tools, folder: Path, log: Path | None = None) -> list[str]:
    """The lines of `mudling plugin test`. Exit 1 is a verdict, so it's fine."""
    command = [tools.mudling, "plugin", "test", folder]
    if log is not None:
        command += ["--log", log]
    run = subprocess.run(command, capture_output=True, text=True)
    lines = run.stdout.splitlines()
    if run.returncode not in (0, 1) or not lines or lines[-1] not in ("passed", "failed"):
        raise CouldNotRun(f"mudling plugin test {folder} exited {run.returncode}: {run.stderr.strip()}")
    return lines


def load_failure_kind(reason: str) -> str:
    if "the pattern doesn't compile" in reason:
        return "pattern"
    if "the Luau doesn't compile" in reason:
        return "lint"
    return "manifest"


def test_failures(lines: list[str]) -> list[Failure]:
    """What `plugin test` failed for, leaving out its absolute budget.

    `mudling plugin test` holds a line to 5 µs on whatever machine it's on. A
    shared runner can't be trusted with that, so `check_budget` judges the cost
    against the reference instead. A hook that overran is no timing of the
    machine's, so it still fails here.
    """
    failures = []
    for line in lines:
        found = FAIL_LINE.fullmatch(line)
        if found is None or COST_LINE.fullmatch(line):
            continue
        kind, reason = found.groups()
        failures.append(Failure(load_failure_kind(reason) if kind == "load" else kind, reason))
    return failures


def lint_hooks(tools: Tools, folder: Path, hook_files: list[str]) -> list[Failure]:
    """Lints the hooks with luau-analyze, under the registry's own config.

    The files load into one VM, so they're linted as one: a global from an
    earlier file is known to a later one. Findings name the plugin's own files.
    """
    if not hook_files:
        return []
    combined, starts = [], []
    for name in hook_files:
        lines = (folder / name).read_text().splitlines()
        starts.append((len(combined), name))
        combined += lines
    with tempfile.TemporaryDirectory() as scratch:
        shutil.copy(LUAU_CONFIG, Path(scratch) / ".luaurc")
        (Path(scratch) / "hooks.luau").write_text("\n".join(combined) + "\n")
        run = subprocess.run(
            [tools.luau_analyze, "hooks.luau"], cwd=scratch, capture_output=True, text=True
        )
    failures = []
    for line in (run.stdout + run.stderr).splitlines():
        found = LUAU_FINDING.fullmatch(line)
        if found is None:
            raise CouldNotRun(f"luau-analyze said: {line}")
        at, column, message = int(found[1]) - 1, found[2], found[3]
        start, name = [entry for entry in starts if entry[0] <= at][-1]
        failures.append(Failure("lint", f"{name}:{at - start + 1}:{column}: {message}"))
    if run.returncode != 0 and not failures:
        raise CouldNotRun(f"luau-analyze exited {run.returncode} and said nothing")
    return failures


def read_cost(lines: list[str]) -> Cost:
    for line in lines:
        found = COST_LINE.fullmatch(line)
        if found is not None:
            return Cost(float(found[1]), float(found[2]))
    raise CouldNotRun("mudling plugin test printed no cost")


def judge_budget(log: str, measure_plugin, measure_reference) -> Budget:
    """Both sides in turns: `plugin` is over only if it loses in every block."""
    for _ in range(BLOCKS):
        plugin_costs, reference_costs = [], []
        for round_number in range(ROUNDS_PER_BLOCK):
            # In turns, so neither always runs first.
            if round_number % 2 == 0:
                plugin_costs.append(measure_plugin())
                reference_costs.append(measure_reference())
            else:
                reference_costs.append(measure_reference())
                plugin_costs.append(measure_plugin())
        plugin = min(plugin_costs, key=lambda cost: cost.with_us)
        reference = min(reference_costs, key=lambda cost: cost.with_us)
        if plugin.with_us <= reference.with_us * MOST_OVER_REFERENCE:
            return Budget(log, plugin, reference, within=True)
    return Budget(log, plugin, reference, within=False)


def check_budget(tools: Tools, folder: Path) -> Budget:
    """The worst verdict over the plugin's own logs and the shared session log.

    The shared log means a plugin can't look cheap by testing on three lines.
    """
    logs = [*sorted((folder / "tests").glob("*.txt")), tools.session_log]
    budgets = [
        judge_budget(
            log.name,
            lambda log=log: read_cost(plugin_test(tools, folder, log)),
            lambda log=log: read_cost(plugin_test(tools, tools.reference, log)),
        )
        for log in logs
    ]
    return max(budgets, key=lambda budget: (not budget.within, budget.ratio))


def check_plugin(tools: Tools, folder: Path) -> Result:
    manifest = read_manifest(folder)
    failures = check_layout(folder, manifest) + check_license(manifest)
    test_problems = test_failures(plugin_test(tools, folder))
    failures += test_problems
    if any(failure.kind in ("manifest", "pattern", "lint") for failure in test_problems):
        return Result(folder.name, failures)  # It didn't load, so nothing else can run.

    hook_files = manifest.get("hooks", {}).get("files", [])
    failures += lint_hooks(tools, folder, hook_files)
    budget = check_budget(tools, folder)
    if not budget.within:
        limit = f"{MOST_OVER_REFERENCE:.2f}"
        failures.append(
            Failure(
                "budget",
                f"on {budget.log}, {budget.ratio:.2f}× the reference's cost a line, and the limit is {limit}×",
            )
        )
    return Result(folder.name, failures, budget)


def plugin_folders(plugins: Path) -> list[Path]:
    return sorted(path for path in plugins.iterdir() if path.is_dir())


def render_budget_table(results: list[dict]) -> str:
    """The budget, from a report. A pull request can forge the report, and this
    goes on the pull request, so only ids and numbers get through."""
    rows = [
        "| Plugin | Added a line | Reference added | Against the reference | Limit | Log |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        budget = result.get("budget")
        if budget is None or not PLUGIN_ID.fullmatch(result["id"]):
            continue
        plugin, reference = budget["plugin"], budget["reference"]
        ratio = float(plugin["with_us"]) / float(reference["with_us"])
        log = budget["log"] if PLUGIN_ID.fullmatch(budget["log"]) else "(not shown)"
        rows.append(
            f"| {result['id']} | +{float(plugin['added_us']):.2f} µs | +{float(reference['added_us']):.2f} µs"
            f" | {ratio:.2f}× | {MOST_OVER_REFERENCE:.2f}× | {log} |"
        )
    return "\n".join(rows) if len(rows) > 2 else ""


def budget_comment(report: Path) -> str:
    table = render_budget_table(json.loads(report.read_text()))
    if not table:
        return ""
    return (
        "<!-- registry-budget -->\n"
        "### Line budget\n\n"
        f"{table}\n\n"
        "These are this runner's numbers, measured in one job beside a reference plugin that costs "
        "about the 5 µs budget on a quiet machine. Only the comparison with the reference counts: "
        f"see [the budget]({BUDGET_DOCS})."
    )


def run_check(args: argparse.Namespace) -> bool:
    tools = Tools(args.mudling.resolve(), args.luau_analyze.resolve(), args.session_log.resolve())
    results = [check_plugin(tools, folder) for folder in plugin_folders(args.plugins)]
    for result in results:
        for failure in result.failures:
            print(f"fail {result.id} {failure.kind}: {failure.detail}")
        if not result.failures:
            print(f"passed {result.id}")
    print(f"{len(results)} plugins checked")
    report = [dataclasses.asdict(result) for result in results]
    if args.report is not None:
        args.report.write_text(json.dumps(report, indent=2))
    table = render_budget_table(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and table:
        with open(summary, "a") as file:
            file.write(f"### Line budget\n\n{table}\n")
    return not any(result.failures for result in results)


def content_hash(folder: Path) -> str:
    """Hashes a folder's relative paths and contents: docs/index-format.md."""
    files = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())
    listing = "".join(
        f"{hashlib.sha256((folder / name).read_bytes()).hexdigest()}  {name}\n" for name in files
    )
    return "sha256:" + hashlib.sha256(listing.encode()).hexdigest()


def index_entry(folder: Path) -> dict:
    manifest = tomllib.loads((folder / "plugin.toml").read_text())
    servers = manifest.get("servers", {})
    return {
        "id": manifest["id"],
        "name": manifest["name"],
        "version": manifest["version"],
        "license": manifest["license"],
        "games": {
            "hosts": servers.get("hosts", []),
            "mssp_names": servers.get("mssp_names", []),
        },
        "source": f"plugins/{folder.name}",
        "hash": content_hash(folder),
    }


def sign(payload: bytes, private_key_pem: str) -> str:
    """The base64 Ed25519 signature of `payload`."""
    with tempfile.TemporaryDirectory() as scratch:
        key, message, signature = (Path(scratch) / name for name in ("key", "message", "signature"))
        key.write_text(private_key_pem)
        message.write_bytes(payload)
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", key, "-in", message, "-out", signature],
            check=True,
            capture_output=True,
        )
        return base64.b64encode(signature.read_bytes()).decode()


def build_index(plugins: Path, commit: str, published_at: str, private_key_pem: str) -> str:
    signed = json.dumps(
        {
            "format": INDEX_FORMAT,
            "commit": commit,
            "published_at": published_at,
            "plugins": [index_entry(folder) for folder in plugin_folders(plugins)],
        },
        ensure_ascii=False,
        indent=2,
    )
    signature = sign(signed.encode(), private_key_pem)
    return json.dumps({"signed": signed, "signature": signature}, ensure_ascii=False, indent=2) + "\n"


def run_index(args: argparse.Namespace) -> bool:
    private_key_pem = os.environ.get(SIGNING_KEY_VARIABLE)
    if not private_key_pem:
        raise CouldNotRun(
            f"the {SIGNING_KEY_VARIABLE} secret isn't set, so no index was signed: see docs/signing.md"
        )
    args.output.write_text(build_index(args.plugins, args.commit, args.published_at, private_key_pem))
    return True


def run_comment(args: argparse.Namespace) -> bool:
    print(budget_comment(args.report))
    return True


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="The plugin registry's CI.")
    commands = parser.add_subparsers(required=True)

    check = commands.add_parser("check", help="check every plugin")
    check.set_defaults(run=run_check)
    check.add_argument("--plugins", type=Path, default=Path("plugins"))
    check.add_argument("--mudling", type=Path, required=True)
    check.add_argument("--luau-analyze", type=Path, required=True)
    check.add_argument("--session-log", type=Path, required=True)
    check.add_argument("--report", type=Path)

    index = commands.add_parser("index", help="build the signed index")
    index.set_defaults(run=run_index)
    index.add_argument("--plugins", type=Path, default=Path("plugins"))
    index.add_argument("--commit", required=True)
    index.add_argument("--published-at", required=True)
    index.add_argument("--output", type=Path, required=True)

    comment = commands.add_parser("comment", help="write a report's pull request comment")
    comment.set_defaults(run=run_comment)
    comment.add_argument("report", type=Path)

    return parser.parse_args(arguments)


def main() -> int:
    args = parse_arguments(sys.argv[1:])
    try:
        return 0 if args.run(args) else 1
    except CouldNotRun as problem:
        print(f"couldn't run: {problem}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
