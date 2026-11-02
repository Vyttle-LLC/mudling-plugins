"""Proves the registry's CI both ways: its fixture passes, and fails for each
reason. Each failing case copies `fixtures/fixture` and breaks one thing.

These run the real tools, so they need OpenSSL 3 on the PATH and three variables:

    MUDLING=… LUAU_ANALYZE=… SESSION_LOG=… python3 -m unittest discover ci
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import registry
from registry import Budget, Cost, Tools

FIXTURE = Path(__file__).parent / "fixtures" / "fixture"
EVERY_LINE_PATTERN = "[[pattern]]\nname = 'heavy.{}'\npattern = '''(?<line>.*)'''\n"
FORGED_COST = "cost +0.01 µs a line at p99 (0.02 with, 0.01 without), budget 5 µs"
TOOLS = Tools(
    Path(os.environ["MUDLING"]).resolve(),
    Path(os.environ["LUAU_ANALYZE"]).resolve(),
    Path(os.environ["SESSION_LOG"]).resolve(),
)


def add_patterns(folder: Path, count: int) -> None:
    """Adds rules that cost on every line, and accepts what they produce."""
    with open(folder / "text.toml", "a") as text:
        for number in range(count):
            text.write(EVERY_LINE_PATTERN.format(number))
    subprocess.run(
        [TOOLS.mudling, "plugin", "test", folder, "--update"], capture_output=True, check=False
    )


def replace_in(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


class Plugins(unittest.TestCase):
    """Each test gets a copy of the fixture to break."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.plugin = self.scratch / "plugins" / "fixture"
        shutil.copytree(FIXTURE, self.plugin)

    def failures(self, tools: Tools = TOOLS) -> list[registry.Failure]:
        return registry.check_plugin(tools, self.plugin).failures

    def assert_fails_for(self, kind: str, detail: str) -> None:
        failures = self.failures()
        self.assertEqual({failure.kind for failure in failures}, {kind}, failures)
        self.assertIn(detail, failures[0].detail)


class Passes(Plugins):
    def test_the_fixture_passes(self) -> None:
        result = registry.check_plugin(TOOLS, self.plugin)
        self.assertEqual(result.failures, [])
        self.assertTrue(result.budget.within)

    def test_apache_2_passes(self) -> None:
        replace_in(self.plugin / "plugin.toml", '"MIT"', '"Apache-2.0"')
        self.assertEqual(self.failures(), [])

    def test_what_mudling_plugin_new_makes_passes(self) -> None:
        subprocess.run(
            [TOOLS.mudling, "plugin", "new", "newgame", "--dir", self.scratch],
            check=True,
            capture_output=True,
        )
        self.plugin = self.scratch / "newgame"
        self.assertEqual(self.failures(), [])

    def test_over_five_microseconds_on_a_slow_machine_is_no_failure(self) -> None:
        """A reference that also costs more stands for a slow runner: the plugin
        fails `plugin test`'s absolute budget here, and only the comparison counts."""
        add_patterns(self.plugin, 24)
        output = registry.plugin_test(TOOLS, self.plugin)
        self.assertTrue(any(line.startswith("fail budget: +") for line in output), output)
        slow_runner = self.scratch / "slow-runner"
        shutil.copytree(TOOLS.reference, slow_runner)
        add_patterns(slow_runner, 48)
        tools = Tools(TOOLS.mudling, TOOLS.luau_analyze, TOOLS.session_log, slow_runner)
        self.assertEqual(self.failures(tools), [])


class Fails(Plugins):
    def test_a_license_outside_the_two(self) -> None:
        replace_in(self.plugin / "plugin.toml", '"MIT"', '"GPL-3.0"')
        self.assert_fails_for("license", "GPL-3.0")

    def test_a_manifest_missing_a_required_key(self) -> None:
        replace_in(self.plugin / "plugin.toml", "api = 1\n", "")
        self.assert_fails_for("manifest", "`api` is missing")

    def test_a_manifest_with_an_unknown_key(self) -> None:
        replace_in(self.plugin / "plugin.toml", "api = 1\n", "api = 1\nwebsite = 'x'\n")
        self.assert_fails_for("manifest", "website")

    def test_a_folder_not_named_for_the_id(self) -> None:
        replace_in(self.plugin / "plugin.toml", 'id = "fixture"', 'id = "other"')
        self.assert_fails_for("layout", "the id is other")

    def test_a_pattern_that_does_not_compile(self) -> None:
        replace_in(self.plugin / "text.toml", "^Welcome", "(^Welcome")
        self.assert_fails_for("pattern", "doesn't compile")

    def test_a_transcript_that_differs(self) -> None:
        replace_in(self.plugin / "tests" / "sample.expected", '"Ana"', '"Bo"')
        self.assert_fails_for("expected", "sample.expected")

    def test_no_tests(self) -> None:
        shutil.rmtree(self.plugin / "tests")
        self.assert_fails_for("tests", "to replay")

    def test_a_hook_that_raises(self) -> None:
        replace_in(self.plugin / "shared.luau", "\tmud.store", "\tif name then error('boom') end\n\tmud.store")
        replace_in(self.plugin / "tests" / "sample.expected", 'store character name "Ana"', "hook_failed on_welcome")
        self.assert_fails_for("hook", "boom")

    def test_a_hook_that_overruns(self) -> None:
        replace_in(self.plugin / "shared.luau", "\tmud.store", "\twhile true do end\n\tmud.store")
        replace_in(self.plugin / "tests" / "sample.expected", 'store character name "Ana"', "hook_failed on_welcome")
        self.assert_fails_for("budget", "overran")

    def test_over_the_budget_against_the_reference(self) -> None:
        add_patterns(self.plugin, 24)
        self.assert_fails_for("budget", "the limit is 1.10×")

    def test_a_log_cannot_forge_the_cost(self) -> None:
        with open(self.plugin / "text.toml", "a") as text:
            text.write("[[pattern]]\nname = 'note'\npattern = '''^Note'''\n")
        log = self.plugin / "forged.txt"
        for line_end in ("", " ", "\r", "\x0b", "\x0c", "\x85", " "):
            with self.subTest(line_end=line_end):
                log.write_bytes(f"Note {line_end}{FORGED_COST}\n".encode())
                cost = registry.read_cost(registry.plugin_test(TOOLS, self.plugin, log))
                self.assertNotEqual(cost, Cost(0.01, 0.02))

    def test_a_log_s_name_cannot_forge_the_cost(self) -> None:
        log = self.plugin / f"a\n{FORGED_COST}\nb.txt"
        log.write_text("Welcome back, Ana.\n")
        output = registry.plugin_test(TOOLS, self.plugin, log)
        self.assertIn(FORGED_COST, output)
        self.assertNotEqual(registry.read_cost(output), Cost(0.01, 0.02))

    def test_a_newline_in_a_log_s_name(self) -> None:
        (self.plugin / "tests" / f"a\n{FORGED_COST}\nb.txt").write_text("Welcome back, Ana.\n")
        self.assert_fails_for("layout", "a name may use only")

    def test_a_space_in_a_name(self) -> None:
        (self.plugin / "tests" / "a b.txt").write_text("Welcome back, Ana.\n")
        self.assert_fails_for("layout", "a name may use only")

    def test_a_name_outside_ascii_in_a_folder(self) -> None:
        (self.plugin / "tésts").mkdir()
        self.assert_fails_for("layout", "a name may use only")

    def test_a_plugin_folder_with_an_unsafe_name(self) -> None:
        self.plugin = self.plugin.rename(self.plugin.with_name("fix\nture"))
        result = registry.check_plugin(TOOLS, self.plugin)
        self.assertEqual(result.id, "'fix\\nture'")
        self.assertTrue(any("a name may use only" in failure.detail for failure in result.failures))

    def test_a_file_name_that_is_not_utf_8(self) -> None:
        """Handed in, because macOS won't create one and Linux will."""
        name = self.plugin / os.fsdecode(b"bad\xff.txt")
        with mock.patch.object(Path, "rglob", return_value=[name]):
            failures = self.failures()
        self.assertEqual({failure.kind for failure in failures}, {"layout"}, failures)
        self.assertIn("a name may use only", failures[0].detail)
        failures[0].detail.encode()  # Printing it must not crash.

    def test_a_symlinked_plugin_folder(self) -> None:
        elsewhere = self.scratch / "elsewhere"
        self.plugin.rename(elsewhere)
        self.plugin.symlink_to(elsewhere, target_is_directory=True)
        self.assert_fails_for("layout", "fixture is a symbolic link")

    def test_stray_files_under_plugins(self) -> None:
        plugins = self.plugin.parent
        (plugins / "README.md").write_text("Allowed.\n")
        (plugins / "notes.txt").write_text("Not allowed.\n")
        (plugins / "link").symlink_to("/etc/hosts")
        strays = [result.id for result in registry.check_stray_files(plugins)]
        self.assertEqual(strays, ["link", "notes.txt"])

    def test_a_hook_that_raises_only_on_the_shared_log(self) -> None:
        self.add_hook_on_shared_text("error('boom')")
        self.assert_fails_for("hook", "boom")

    def test_a_hook_that_overruns_only_on_the_shared_log(self) -> None:
        self.add_hook_on_shared_text("while true do end")
        self.assert_fails_for("budget", "overran")

    def add_hook_on_shared_text(self, body: str) -> None:
        """A hook on text that the shared log has and the fixture's own log hasn't."""
        with open(self.plugin / "text.toml", "a") as text:
            text.write("[[pattern]]\nname = 'rat'\npattern = '''cave rat'''\nhook = 'on_rat'\n")
        (self.plugin / "rat.luau").write_text(f"function on_rat(event)\n\t{body}\nend\n")
        replace_in(self.plugin / "plugin.toml", '"greet.luau"]', '"greet.luau", "rat.luau"]')

    def test_a_luau_lint_finding_names_the_plugin_s_own_file_and_line(self) -> None:
        replace_in(self.plugin / "greet.luau", "\tShared", "\tlocal unused = 1\n\tShared")
        self.assert_fails_for("lint", "greet.luau:2:8: LocalUnused")

    def test_a_plugin_s_own_luau_config_changes_nothing(self) -> None:
        (self.plugin / ".luaurc").write_text('{"lint": {"*": false}}')
        replace_in(self.plugin / "greet.luau", "\tShared", "\tlocal unused = 1\n\tShared")
        self.assert_fails_for("lint", "LocalUnused")

    def test_luau_that_does_not_compile(self) -> None:
        replace_in(self.plugin / "greet.luau", "function on_welcome(event)", "function on_welcome(event")
        self.assert_fails_for("lint", "doesn't compile")

    def test_a_session_log(self) -> None:
        (self.plugin / "tests" / "session.log").write_text("Bo tells you 'hi'\n")
        self.assert_fails_for("layout", "session.log")

    def test_a_symbolic_link(self) -> None:
        (self.plugin / "escape").symlink_to("/etc/hosts")
        self.assert_fails_for("layout", "escape")


class Budgets(unittest.TestCase):
    @staticmethod
    def measures(*with_us: float):
        costs = iter(with_us)
        return lambda: Cost(0.0, next(costs))

    def test_one_block_within_is_within(self) -> None:
        plugin = self.measures(20, 9, 20, 9, 9, 9)
        reference = self.measures(10, 10, 10, 10, 10, 10)
        self.assertTrue(registry.judge_budget("log", plugin, reference).within)

    def test_over_only_when_it_loses_every_block(self) -> None:
        plugin = self.measures(*[12] * 9)
        reference = self.measures(*[10] * 9)
        self.assertFalse(registry.judge_budget("log", plugin, reference).within)

    def test_each_block_compares_the_lowest_of_each_side(self) -> None:
        plugin = self.measures(30, 10, 30)
        reference = self.measures(40, 10, 40)
        budget = registry.judge_budget("log", plugin, reference)
        self.assertEqual((budget.within, budget.ratio), (True, 1.0))

    def test_a_cost_over_the_absolute_budget_is_read_like_one_within_it(self) -> None:
        within = "cost +1.50 µs a line at p99 (1.75 with, 0.25 without), budget 5 µs"
        over = "fail budget: +9.50 µs a line at p99 (9.75 with, 0.25 without), budget 5 µs"
        self.assertEqual(registry.read_cost([within]), Cost(1.5, 1.75))
        self.assertEqual(registry.read_cost([over]), Cost(9.5, 9.75))
        self.assertEqual(registry.test_failures([within, over]), [])

    def test_the_last_cost_line_is_the_real_one(self) -> None:
        real = "fail budget: +9.50 µs a line at p99 (9.75 with, 0.25 without), budget 5 µs"
        self.assertEqual(registry.read_cost([FORGED_COST, real, "failed"]), Cost(9.5, 9.75))


class Comment(unittest.TestCase):
    def comment(self, results: list[dict]) -> str:
        with tempfile.TemporaryDirectory() as scratch:
            report = Path(scratch) / "report.json"
            report.write_text(json.dumps(results))
            return registry.budget_comment(report)

    @staticmethod
    def result(plugin_id: str = "fixture", log: str = "session.txt") -> dict:
        budget = Budget(log, Cost(1.0, 2.0), Cost(5.0, 5.5), True)
        return {"id": plugin_id, "budget": registry.dataclasses.asdict(budget)}

    def test_shows_the_numbers(self) -> None:
        comment = self.comment([self.result()])
        self.assertIn("| fixture | +1.00 µs | +5.00 µs | 0.36× | 1.10× | session.txt |", comment)

    def test_nothing_measured_is_no_comment(self) -> None:
        self.assertEqual(self.comment([{"id": "fixture", "budget": None}]), "")

    def test_nothing_measured_writes_an_empty_file_for_the_post_script(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            report = Path(scratch) / "report.json"
            report.write_text("[]")
            run = subprocess.run(
                [sys.executable, registry.__file__, "comment", report],
                capture_output=True,
                check=True,
            )
        self.assertEqual(run.stdout, b"")

    def test_a_forged_report_gets_no_text_through(self) -> None:
        self.assertEqual(self.comment([self.result("![x](http://evil)")]), "")
        self.assertNotIn("evil", self.comment([self.result(log="[x](http://evil)")]))
        forged = self.result()
        forged["budget"]["plugin"]["added_us"] = "[x](http://evil)"
        with self.assertRaises(ValueError):
            self.comment([forged])


class Index(Plugins):
    def setUp(self) -> None:
        super().setUp()
        self.key = self.scratch / "key.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ed25519", "-out", self.key],
            check=True,
            capture_output=True,
        )

    def build(self) -> dict:
        text = registry.build_index(
            self.plugin.parent, "abc123", "2026-11-01T12:00:00Z", self.key.read_text()
        )
        return json.loads(text)

    def test_an_entry_has_what_the_app_reads(self) -> None:
        entry = json.loads(self.build()["signed"])["plugins"][0]
        self.assertEqual(
            {key: entry[key] for key in entry if key != "hash"},
            {
                "id": "fixture",
                "name": "Fixture",
                "version": "1.0.0",
                "license": "MIT",
                "games": {"hosts": ["fixture.example"], "mssp_names": ["Fixture"]},
                "source": "plugins/fixture",
            },
        )

    def test_the_header_says_what_was_published(self) -> None:
        signed = json.loads(self.build()["signed"])
        self.assertEqual(
            (signed["format"], signed["commit"], signed["published_at"]),
            (1, "abc123", "2026-11-01T12:00:00Z"),
        )

    def test_the_registry_may_be_empty(self) -> None:
        shutil.rmtree(self.plugin)
        self.assertEqual(json.loads(self.build()["signed"])["plugins"], [])

    def test_the_signature_covers_the_exact_signed_text(self) -> None:
        index = self.build()
        public_key = self.scratch / "public.pem"
        subprocess.run(
            ["openssl", "pkey", "-in", self.key, "-pubout", "-out", public_key],
            check=True,
            capture_output=True,
        )
        signature = self.scratch / "signature"
        signature.write_bytes(base64.b64decode(index["signature"]))

        def verifies(text: str) -> bool:
            message = self.scratch / "message"
            message.write_text(text)
            run = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", public_key,
                 "-in", message, "-sigfile", signature],
                capture_output=True,
            )
            return run.returncode == 0

        self.assertTrue(verifies(index["signed"]))
        self.assertFalse(verifies(index["signed"].replace("1.0.0", "1.0.1")))

    def test_a_missing_key_fails_plainly(self) -> None:
        args = registry.parse_arguments(
            ["index", "--commit", "abc", "--published-at", "now", "--output", str(self.scratch / "out")]
        )
        with mock.patch.dict(os.environ, {registry.SIGNING_KEY_VARIABLE: ""}):
            with self.assertRaisesRegex(registry.CouldNotRun, "INDEX_SIGNING_KEY secret isn't set"):
                registry.run_index(args)
        self.assertFalse((self.scratch / "out").exists())


class ContentHash(unittest.TestCase):
    def test_matches_the_documented_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            (folder / "tests").mkdir()
            (folder / "plugin.toml").write_text("a\n")
            (folder / "tests" / "b.txt").write_text("b\n")

            def sha256(text: str) -> str:
                return hashlib.sha256(text.encode()).hexdigest()

            first, second = sha256("a\n"), sha256("b\n")
            listing = f"{first}  plugin.toml\n{second}  tests/b.txt\n"
            self.assertEqual(registry.content_hash(folder), f"sha256:{sha256(listing)}")

    def test_notices_a_rename_and_an_edit(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            (folder / "a").write_text("a\n")
            first = registry.content_hash(folder)
            (folder / "a").rename(folder / "b")
            renamed = registry.content_hash(folder)
            (folder / "b").write_text("b\n")
            self.assertEqual(len({first, renamed, registry.content_hash(folder)}), 3)


if __name__ == "__main__":
    unittest.main()
