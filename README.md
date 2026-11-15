# rust-tools

Shared tooling for [hugoh](https://github.com/hugoh)'s Rust repositories (`tamis`, `upd`). Modeled on [go-tools](https://github.com/hugoh/go-tools), deliberately smaller: a Copier template for the config files the repos share, two reusable workflows, and a Renovate preset.

## Copier template

Templates `.cargo/config.toml`, `.cargo-crap.toml`, `clippy.toml`, `deny.toml`, `hk.pkl`, `mise.toml` (+ `mise.package.toml`, `mise.release.toml`), `biome.jsonc`, `.jscpd.json`, `.markdownlint.json`, `.ryl.toml`, `.editorconfig`, and `.github/workflows/semantic-pr.yml`.

Seeded once, then owned by the repo (`_skip_if_exists`): `rust-toolchain.toml` and `.renovaterc.json`.

Not templated, on purpose (too repo-specific until a third Rust project shows what varies): `.anodizer.yaml`, `cross.yml`, `pages.yml`, `mise-tasks/`, and the release jobs of `ci.yml`.

### Adopting in an existing repo

```sh
uvx copier copy https://github.com/hugoh/rust-tools.git .
```

Answer from `test/fixtures/<repo>.yml`, review the diff (mostly the "managed" header), keep repo-specific `hk.pkl` steps (e.g. tamis's `package-assets`, `systemd`) as local additions that `copier update` merges.

## Composite actions

`.github/actions/rust-setup` (toolchain + cargo cache) and `.github/actions/apply-tag` (release commit and tag) are hosted here, not copied. Reference them from a repo's own `ci.yml` as `hugoh/rust-tools/.github/actions/<name>@<sha> # vX.Y.Z`. They run in the caller's workspace, so `rust-setup` still reads the caller's `rust-toolchain.toml`.

## Reusable workflows

`rust-hk.yml` and `rust-test.yml` replace the `hk` and `test` jobs of a repo's `ci.yml`:

```yaml
jobs:
  hk:
    uses: hugoh/rust-tools/.github/workflows/rust-hk.yml@<sha> # vX.Y.Z
    permissions: {contents: read, packages: read, statuses: write}
  test:
    uses: hugoh/rust-tools/.github/workflows/rust-test.yml@<sha> # vX.Y.Z
    permissions: {actions: read, contents: read}
```

`rust-hk.yml` takes `prebuild: true` to run `mise run prebuild` first; `rust-test.yml` takes `setup-command` to run a shell command (such as starting a service) before the tests.

Calling a reusable workflow changes the check names (`hk` becomes `hk / hk`): re-run `repo-admin.sh sync <repo>` so branch protection requires the new names.

## Renovate

`rust-renovaterc.json` is the shared hub config; `presets/copier-owned-files.json` keeps Renovate off files Copier owns.

## Development

`mise run render-check` renders the template against `test/fixtures/*.yml` and checks the output parses. A merge to `main` with a conventional commit cuts a release via `cocogitto`.
