# mudling-plugins

The community plugin registry for [MUDling](https://github.com/Vyttle-LLC/mudling),
a MUD client. Each plugin teaches MUDling about a game: its prompts, its tables,
its map, its gear. MUDling's plugin directory (Settings › Plugins › Browse) lists
what's here.

To add a plugin, read [CONTRIBUTING.md](CONTRIBUTING.md). It goes from
`mudling plugin new` to an open pull request.

## What's in this repo

| Path | What it is |
| --- | --- |
| `plugins/<id>/` | One folder per plugin. |
| `.github/CODEOWNERS` | Who reviews what. |
| `ci/` | The checks every pull request goes through, and their tests. |
| `docs/ci.md` | What each check does, and why a failure happened. |
| `docs/index-format.md` | The signed index that the app reads. |
| `docs/signing.md` | The signing key, and how to set or replace it. |

## The rules

- **One folder per plugin:** `plugins/<id>/`, named for the plugin's `id`.
- **MIT or Apache-2.0 only,** so a plugin can be bundled and forked freely.
- **Every plugin ships tests:** a few lines of made-up game text, and what they
  should produce.
- **No session logs.** They hold other players' chat. Write test text by hand.
- **CI runs first.** It checks the manifest, the patterns, the plugin's tests, its
  cost per line and its Luau, before anyone reviews the pull request.
- **Then a person reviews it:** an owner from `CODEOWNERS`, Michael to begin with.
  Owners for each game join as contributors show up.

## How a plugin reaches players

When a pull request merges to `main`, CI checks everything again and builds an
index with one entry per plugin. It signs the index and publishes it to the
`index` branch, and MUDling reads it from there. Nothing in the app trusts an
index that doesn't verify.

## License

The repo itself is [MIT](LICENSE). Each plugin carries the license its
`plugin.toml` names: MIT or Apache-2.0.
