# The signing key

CI signs [the index](index-format.md) with **Ed25519**. MUDling verifies it with the
public key built into the app, so someone who gets hold of the `index` branch, or
sits between a player and GitHub, can't change what the app installs.

Ed25519 is small and well known: a 32-byte public key that fits on a line in the
app's source, a 64-byte signature, and no parameters to get wrong. It's in OpenSSL
on every CI runner, so signing adds no dependency, and it has audited
implementations in Rust, such as `ed25519-dalek`.

## Setting it up

This needs doing once. You need OpenSSL 3 (macOS's own `openssl` is LibreSSL, which
can't do this, so use `nix shell nixpkgs#openssl` or Homebrew's), and
[`gh`](https://cli.github.com) signed in with admin rights on this repo.

```sh
# 1. Make the key pair.
openssl genpkey -algorithm ed25519 -out index-signing-key.pem

# 2. Print the public key, the one line the app needs.
openssl pkey -in index-signing-key.pem -pubout -outform DER | tail -c 32 | base64

# 3. Give the private key to CI.
gh secret set INDEX_SIGNING_KEY --repo Vyttle-LLC/mudling-plugins < index-signing-key.pem

# 4. Keep it in your password manager, then remove the file.
rm index-signing-key.pem
```

The public key from step 2 is 44 base64 characters, the raw 32 bytes. It isn't
secret. Build it into the app.

Until the secret is set, the `publish` job fails with
`the INDEX_SIGNING_KEY secret isn't set`, and nothing is published.

## Replacing it

If the key leaks, the app must get a new public key, so that's an app release.
Repeat the steps above, ship the release, and tell players to update. An app with
the old key refuses every index signed with the new one, and keeps its last good
index.
