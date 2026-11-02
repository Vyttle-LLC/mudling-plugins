# The signed index

MUDling's plugin directory reads this file to learn what the registry holds. CI
builds it from `plugins/` on every push to `main` (`build_index` in
[`ci/registry.py`](../ci/registry.py)).

## Where it is

```text
https://raw.githubusercontent.com/Vyttle-LLC/mudling-plugins/index/index.json
```

That's `index.json` on the `index` branch, which holds nothing else and gets one
commit per publish. Its history is a record of every index.

## The file

The index and its signature are one file, so a client can never fetch one without
the other. It's a JSON object with two strings:

```json
{
  "signed": "{\n  \"format\": 1,\n  \"commit\": \"…\", …}",
  "signature": "2Qxl…=="
}
```

| Key | What it is |
| --- | --- |
| `signed` | The index, as a string of JSON. |
| `signature` | The base64 Ed25519 signature of `signed`'s UTF-8 bytes. |

To read it, a client must, in this order:

1. Parse the outer object.
2. Verify `signature` over the exact bytes of `signed`, with the public key built
   into the app. If it fails, stop and keep the last good index. See
   [signing.md](signing.md) for the key.
3. Only then parse `signed`.
4. Refuse a `format` it doesn't know.
5. Refuse an index with an older `published_at` than the one it has, so that an
   old signed index can't be replayed to hide an update.

Because the signature covers a string, nothing needs canonicalizing, and a client
must not re-serialize `signed` before verifying.

## The index

```json
{
  "format": 1,
  "commit": "9f2c1e7a54b8d3f06a1c2e4b7d8091a3c5e6f7ab",
  "published_at": "2026-11-02T17:04:31Z",
  "plugins": [
    {
      "id": "mygame",
      "name": "My Game",
      "version": "1.2.0",
      "license": "MIT",
      "games": {
        "hosts": ["mygame.example", "*.mygame.example"],
        "mssp_names": ["My Game"]
      },
      "source": "plugins/mygame",
      "hash": "sha256:3b0f…"
    }
  ]
}
```

| Key | What it is |
| --- | --- |
| `format` | This format's version: `1`. A change a client can't ignore raises it. A new key doesn't. |
| `commit` | The full commit on `main` this was built from. Plugins are fetched at this commit, never from `main`. |
| `published_at` | That commit's committer time, as UTC ISO 8601. |
| `plugins` | One entry per plugin, sorted by `id`. It may be empty. |

Each entry:

| Key | What it is |
| --- | --- |
| `id` | The plugin's `id`. |
| `name` | The name players see. |
| `version` | `MAJOR.MINOR.PATCH`. |
| `license` | `MIT` or `Apache-2.0`. |
| `games` | Which games it's for: `hosts` and `mssp_names`, as in the manifest's `[servers]`. A host may start with a `*.` wildcard, and case doesn't matter in either. Both empty means a `default` plugin, for any game. |
| `source` | The plugin's folder in the repo at `commit`. |
| `hash` | The folder's content hash, below. |

## Fetching a plugin

Download the folder at `source` from the repo at `commit`, for instance from
`https://codeload.github.com/Vyttle-LLC/mudling-plugins/tar.gz/<commit>`. Compute
its content hash, and install it only if the hash equals the entry's `hash`.

## The content hash

The hash covers the name and exact bytes of every file in the folder, and works
the way `sha256sum` prints:

1. List every file under the folder, as paths relative to it with `/` separators.
2. Sort them by their UTF-8 bytes.
3. For each, write a line: the lowercase hex SHA-256 of its contents, two spaces,
   the path, and a newline.
4. Take the SHA-256 of those lines. The hash is `sha256:` and its lowercase hex.

From inside a plugin's folder, this prints the same hex:

```sh
find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256
```
