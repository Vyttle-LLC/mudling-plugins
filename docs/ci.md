# What CI checks

`.github/workflows/registry.yml` runs on every pull request and on every push to
`main`. It builds `mudling` from the commit pinned in
[`ci/pins.env`](../ci/pins.env), tests the checks themselves against
[a fixture](../ci/test_registry.py), then runs `ci/registry.py check` over every
folder in `plugins/`.

| Check | How | `fail` kind |
| --- | --- | --- |
| Only plugin folders sit under `plugins/`, beside its README. Each is named for its `id`. Every file and folder name uses only ASCII letters, digits, `.`, `_` and `-`. There are no symbolic links and no `*.log` files. | `ci/registry.py` | `layout` |
| The license is `MIT` or `Apache-2.0`, exactly. | `ci/registry.py` | `license` |
| The manifest and every other file load. | `mudling plugin test` | `manifest` |
| Every pattern compiles. | `mudling plugin test` | `pattern` |
| The plugin has tests, each produces its `.expected`, and no hook fails. | `mudling plugin test` | `tests`, `expected`, `hook` |
| No hook overruns its limits, and each log stays within the budget. | `mudling plugin test`, then below | `budget` |
| The Luau compiles and lints clean. | `luau-analyze`, under [`ci/luaurc`](../ci/luaurc) | `lint` |

A layout failure stops that plugin's other checks, because `plugin test` prints
paths and a bad name could confuse what reads them. Hooks must also survive the
shared log described [below](#the-budget), not only the plugin's own tests.

The hook files are linted as one, in the manifest's order, because they load into
one VM. A plugin's own `.luaurc` doesn't count.

Merging needs every check to pass. On `main` the same checks run again, and the
[signed index](index-format.md) is built only if they pass.

## What a failure means

| Line | What to do |
| --- | --- |
| `fail <id> layout: …` | Rename the folder or the `id` so that they match, or rename or remove the file it names. |
| `fail <id> license: …` | Set `license = "MIT"` or `"Apache-2.0"`, if you have the right to. |
| `fail <id> manifest: …` | The reason names the file. Try `mudling plugin test plugins/<id>`. |
| `fail <id> pattern: …` | The reason shows the pattern. Patterns are Rust `regex`, with no lookaround or backreferences. |
| `fail <id> expected: …` | Your plugin produced something else. If the new output is right, run `mudling plugin test plugins/<id> --update`, read the difference, and commit it. |
| `fail <id> tests: …` | Add a test: see [CONTRIBUTING](../CONTRIBUTING.md#4-write-its-tests). |
| `fail <id> hook: …` | A hook raised an error on one of your test logs, or on the shared log. Text from another game can match your pattern, so a hook shouldn't assume what it gets. |
| `fail <id> budget: … overran` | A hook hit its limits. Do less work per event. |
| `fail <id> budget: … the reference` | It costs too much per line: see below. |
| `fail <id> lint: …` | The finding names the file and line. Prefix a variable you mean to leave unused with `_`. |
| `couldn't run: …` | The problem is in CI, not your plugin. A maintainer will look. |

## The budget

A plugin may add at most 5 µs per line at p99: see
[the line budget](https://github.com/Vyttle-LLC/mudling/blob/main/docs/plugins/reference.md#the-line-budget)
in the plugin API reference. `mudling plugin test` measures that directly, but GitHub's shared runners can't be trusted for an
absolute number: they read up to four times over and vary twofold between runs.
So CI ignores `plugin test`'s own 5 µs verdict and judges the plugin against
[a reference plugin](../ci/reference) in the same job, as `mudling-bench compare`
judges a base against a head:

- The reference costs about 5 µs a line on a quiet machine.
- Both replay the same log, in turns: plugin, reference, reference, plugin.
- Stalls only ever add time, so each side's lowest time in a block of three rounds
  is its truest.
- A plugin is over budget if its lowest p99 per line, with the host's own work,
  is more than 1.10× the reference's.
- One lucky round can set a low, so a plugin that loses gets a fresh block. It
  fails only if it loses three blocks running.
- This repeats for each of the plugin's test logs and for one shared log, the
  fixture session from `mudling-bench`, so that a short test log can't hide a
  cost. The worst result stands.

The total p99 is compared, not the amount added, because the difference of two
p99s is mostly noise. The pull request gets a comment with the amount added by
each, as this runner measured them, and the ratio that decides. Only the ratio
counts.

### The absolute check

A maintainer can check the 5 µs itself on a quiet machine, with nothing else
running, on a release build:

```sh
cargo build --release -p mudling-cli   # in the MUDling repo
target/release/mudling plugin test <path to plugins/id>
target/release/mudling plugin test <path to plugins/id> --log crates/mudling-bench/fixtures/session.txt
```

Each prints `cost +<µs>` when within budget and `fail budget: +<µs>` when over.
Run this for a plugin close to the limit, or when a player reports a slow one.

### Keeping the reference honest

Run the same on the reference after raising `MUDLING_COMMIT`, or when the numbers
look wrong:

```sh
target/release/mudling plugin test <path to ci/reference> --log crates/mudling-bench/fixtures/session.txt
```

It should read about `+5 µs`. It costs about 1 µs per rule, so add or remove rules
in [`ci/reference/text.toml`](../ci/reference/text.toml) to bring it back. On an
Apple Silicon Mac at MUDling commit `e0240d0`, five rules read between +4 and
+5 µs on that log.

## Running it yourself

You need Python 3.12, `luau-analyze` from
[Luau's releases](https://github.com/luau-lang/luau/releases), OpenSSL 3 (the tests
sign with it; macOS's own `openssl` won't do) and a `mudling` built from the commit
in `ci/pins.env`:

```sh
python3 ci/registry.py check --mudling <mudling> --luau-analyze <luau-analyze> \
  --session-log <MUDling repo>/crates/mudling-bench/fixtures/session.txt
MUDLING=<mudling> LUAU_ANALYZE=<luau-analyze> SESSION_LOG=<as above> \
  python3 -m unittest discover ci
```

## Repository settings this relies on

CI can't set these itself. A maintainer sets them on GitHub:

- A ruleset on `main` that requires a pull request, the `Check plugins` status, and
  a review from a code owner. Without it, a failed check and `CODEOWNERS` only
  advise.
- Under Settings › Actions › General, approval only for "first-time contributors
  who are new to GitHub". On the stricter setting, a first-time contributor's CI
  waits for a person to approve it.

## Why it's safe to run a stranger's plugin

- The `check` job has a read-only token and no secrets. Plugins can't reach the
  file system or the network anyway, because hooks run in MUDling's Luau sandbox.
- The `publish` job holds the signing key. It runs only on `main`, after review,
  and it only reads plugin files. It never runs them.
- A pull request can change the checks too, and under `pull_request` its version
  runs. That can't touch the key, and the review catches it: a change outside
  `plugins/` is never a plugin.
- `budget-comment.yml` can write to pull requests, so it runs from `main` and
  treats the report as forgeable. Only ids and numbers reach the comment.
