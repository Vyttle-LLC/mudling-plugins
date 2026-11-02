# Adding a plugin

This takes you from nothing to an open pull request. You need
[Rust](https://rustup.rs), [git](https://git-scm.com), a GitHub account, and a
game you know. You don't need to read MUDling's core.

## 1. Build the `mudling` command

```sh
git clone https://github.com/Vyttle-LLC/mudling
cd mudling
cargo build --release -p mudling-cli
```

The command is now at `target/release/mudling`. These steps call it `mudling`, so
either put that folder on your `PATH` or use the full path.

## 2. Fork this repo and make your plugin

Fork [mudling-plugins](https://github.com/Vyttle-LLC/mudling-plugins) on GitHub,
then:

```sh
git clone https://github.com/<you>/mudling-plugins
cd mudling-plugins
git switch -c add-mygame
mudling plugin new mygame --dir plugins
mudling plugin test plugins/mygame
```

The `id`, here `mygame`, is the folder's name too, and they must stay the same.
Use lowercase letters, digits, `.`, `_` and `-`. Other file and folder names may
also use capitals, but no spaces and nothing outside ASCII. You now have a plugin
that loads and passes its own test.

## 3. Teach it your game

Edit the files in `plugins/mygame/`:

- `plugin.toml` is the manifest. Set `name`, set `hosts` under `[servers]` to the
  game's address, and add `mssp_names` if the game sends its MSSP name. The
  directory shows and matches plugins by these.
- `text.toml` reads the game's text. Other extension points get files of their
  own.
- `hooks.luau` holds Luau hooks, for what a pattern can't read. If you need none,
  delete the file along with `[hooks]` and `permissions` in `plugin.toml` and
  every `hook = "…"` line in `text.toml`. Then run the `--update` command from
  step 4 once, because the sample's `.expected` still lists what the hook did.

The [plugin API reference](https://github.com/Vyttle-LLC/mudling/blob/main/docs/plugins/reference.md)
lists everything, and the
[cookbook](https://github.com/Vyttle-LLC/mudling/blob/main/docs/plugins/cookbook.md)
works through a real plugin.

To try a log from your own play without keeping it:

```sh
mudling plugin test plugins/mygame --log ~/somewhere/outside/this/repo/session.log
```

## 4. Write its tests

A test is a pair of files in `tests/`: `<name>.txt`, some game text, and
`<name>.expected`, what it should produce.

**Write the text by hand, and make up every name.** A real session log holds other
players' chat, so never commit one, not even part of one. CI fails any `*.log`
file.

Once the text covers what your plugin reads:

```sh
mudling plugin test plugins/mygame --update
```

This writes the `.expected` files. Read them, because whatever they hold is what
your plugin will be held to. Then run the test on its own to see it pass:

```sh
mudling plugin test plugins/mygame
```

Each `caught` line shows how many lines a pattern matched. Each `fail` line says
what's wrong. The last line is `passed` or `failed`.

## 5. Choose a license

Set `license` in `plugin.toml` to exactly `MIT` or `Apache-2.0`. `mudling plugin
new` starts you on `MIT`. The registry takes nothing else, so that plugins can be
bundled and forked freely. By opening a pull request, you confirm you have the
right to license your plugin that way.

## 6. Open a pull request

Add only your plugin's folder, so that review stays quick:

```sh
git add plugins/mygame
git commit -m "Add the mygame plugin"
git push -u origin add-mygame
```

Then open a pull request on GitHub, against `main` of
`Vyttle-LLC/mudling-plugins`.

If this is your first contribution here, a maintainer may need to approve the
checks before they run. GitHub asks for that on first pull requests.

## 7. What happens next

CI runs [these checks](docs/ci.md) and shows your plugin's cost per line in a
comment on the pull request. If a check fails, its log has a `fail <id> <kind>:`
line that says why, and [the same page](docs/ci.md#what-a-failure-means) says what
to do. Push a fix to the same branch and CI runs again.

Once it passes, an owner reviews your plugin. Merged plugins reach players with the
next index, a few minutes later.

## Updating a plugin

Open a pull request the same way, and raise `version` in `plugin.toml`, which is
how players learn there's an update. If you'd like to own your game's plugins and
review others' changes to them, say so in the pull request: owners join
`.github/CODEOWNERS` as contributors show up.
