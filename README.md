# rust-tools

Shared tooling for [hugoh](https://github.com/hugoh)'s Rust repositories (`tamis`, `upd`). Modeled on [go-tools](https://github.com/hugoh/go-tools), deliberately smaller: a Copier template for the config files the repos share, two reusable workflows, and a Renovate preset.

## Copier template

Templates the config files the Rust repos share: `.cargo/config.toml`, `.cargo-crap.toml`, `clippy.toml`, `hk.pkl`, `mise.toml` (+ `mise.package.toml`, `mise.release.toml`), `biome.jsonc`, `.jscpd.json`, `.markdownlint.json`, `.ryl.toml`, `.editorconfig` and `.github/workflows/semantic-pr.yml`.

It also templates the mise tasks that are the same in every repo: `build`, `dev`, `clean`, `fix`, `ci`, `lint`, `test`, `ci:test`, `coverage`, `crap` (+ `crap:baseline`, `crap:fetch`, `crap:top`), `deps:upgrade`, `lint:rust` and `lint:release`. `lint:release` also fails when a `cloudsmiths:` entry in `.anodizer.yaml` has no `keep_versions`: Cloudsmith's free plan has no retention, so anodizer must prune. Repo differences are three variables: `has_prebuild` (a `prebuild` task that `build`, `dev`, `coverage` and `lint:rust` depend on), `build_extra_sources` (extra globs that trigger a rebuild) `ci_test_extra_depends` (extra tasks `ci:test` runs), `lint_extra_depends` (extra tasks `lint` runs) and `test_extra_depends` (extra tasks `test` runs first).

The coverage gate and the files left out of it are not variables: they track the repo's source tree, so they live in `.config/mise/conf.d/coverage.toml` (`COVERAGE_MIN_LINES`, `COVERAGE_IGNORE_REGEX`), which is seeded once.

Seeded once, then owned by the repo (`_skip_if_exists`): `rust-toolchain.toml`, `deny.toml`, `.config/mise/conf.d/coverage.toml` and `.renovaterc.json`. Their content tracks the repo (targets, the dependency tree's licenses and advisories, the source files), so a template would only move that data into `.copier-answers.yml`.

Not templated, on purpose (repo-specific): `.anodizer.yaml`, `cross.yml`, `pages.yml`, the release jobs of `ci.yml`, and the tasks that exist in one repo only (`cross`, `site`, `web:*`, `test:e2e`, ...).

### Adopting in an existing repo

```sh
uvx copier copy https://github.com/hugoh/rust-tools.git .
```

Answer from `test/fixtures/<repo>.yml`, review the diff (mostly the "managed" header), keep repo-specific `hk.pkl` steps (e.g. tamis's `package-assets`, `systemd`) as local additions that `copier update` merges.

## Composite actions

`.github/actions/apply-tag` (release commit and tag) is hosted here, not copied. Reference it from a repo's own `ci.yml` as `hugoh/rust-tools/.github/actions/apply-tag@<sha> # vX.Y.Z`.

Toolchain and cache setup is [`actions-rust-lang/setup-rust-toolchain`](https://github.com/actions-rust-lang/setup-rust-toolchain), called directly. Pass `cache-save-if: ${{ github.ref == 'refs/heads/main' }}` (its default saves from every branch) and set `CARGO_BUILD_WARNINGS: warn` in the workflow's `env:` (its `build-warnings` default is `deny`).

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

## The `ci-gate` job

Every repo's `ci.yml` ends its checks with a `ci-gate` job ([`re-actors/alls-green`](https://github.com/re-actors/alls-green)) over every job that must pass: `hk`, `test`, and the repo's own such as `e2e`. It is the one required status check, and the release pipeline starts behind it: the first release job (`release`, or `tag` next to `plan` and `preflight`) has `needs: ci-gate`, so nothing is tagged, published or released from a commit whose checks did not pass. A new check goes in the gate's `needs`, not in branch protection, and `repo-admin.sh sync` requires `ci-gate` in place of the jobs it covers.

It lives in each repo's `ci.yml` and not in the template, because the jobs it lists are repo-specific:

```yaml
  ci-gate:
    if: always()
    needs: [hk, test]   # plus the repo's own checks, e.g. e2e
    timeout-minutes: 2
    runs-on: ubuntu-latest
    permissions: {}
    steps:
      - uses: re-actors/alls-green@<sha> # vX.Y.Z
        with:
          jobs: ${{ toJSON(needs) }}
```

## Renovate

`rust-renovaterc.json` is the shared hub config; `presets/copier-owned-files.json` keeps Renovate off files Copier owns.

## Development

`mise run render-check` renders the template against `test/fixtures/*.yml` and checks the output parses. A merge to `main` with a conventional commit cuts a release via `cocogitto`.
