# Contributing

## Setup

```bash
uv sync
uv run horus
```

Before committing, lint the whole repo and run the tests:

```bash
uv run ruff check .
uv run pytest -q
```

## Branching

Work happens directly on `master`. Dependabot opens its own PRs.

## Commit messages

This project follows [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

- Write the description in English, imperative mood, lowercase, no trailing period (`add ram screen`, not `Added RAM screen.`).
- Use the body to explain *why*, not *what*.
- Breaking changes: add `!` after the type/scope (`feat(kernel)!: rename help to man`) and/or a `BREAKING CHANGE:` footer.
- Reference issues in the footer: `Closes #12`.

### Types

| Type | Use for | Release notes section |
|------|---------|-----------------------|
| `feat` | New user-visible functionality | Features |
| `fix` | Bug fix | Fixes |
| `perf` | Performance improvement | Fixes |
| `refactor` | Code change that neither fixes a bug nor adds a feature | Under the hood |
| `test` | Adding or changing tests only | Under the hood |
| `docs` | Documentation only | Under the hood |
| `style` | Formatting, no code change | Under the hood |
| `build` | Build system, packaging, dependencies | Under the hood |
| `ci` | GitHub Actions / CI config | Under the hood |
| `chore` | Anything else that doesn't touch `src/` or `tests/` | Under the hood |

### Scopes

Optional, but prefer one of the top-level packages in `src/horus/`:

`hardware`, `processes`, `kernel`, `filesystem`, `shell`, `session`, `events`, `story`, `network`, `apps`, `ui`, `display`, `audio`, `utils`

Use a more specific name when it helps (`feat(ui): ...` vs. `feat(cpu-screen): ...`), but stay consistent.

### Examples

```
feat(hardware): add per-core CPU scheduling
fix(audio): stop temperature alarm once temperature drops below warning
refactor(processes): draw load from a gaussian around a baseline
test(display): cover sprite clipping at the buffer edge
docs: add contributing guide
feat(kernel)!: replace help with man
```

## Versioning & releases

[Semantic Versioning](https://semver.org/), while on `0.x` minor bumps may contain breaking changes.

| Commits since last release | Bump |
|----------------------------|------|
| any `!` / `BREAKING CHANGE` | minor (pre-1.0) / major (from 1.0) |
| at least one `feat` | minor |
| only `fix`, `perf`, ... | patch |

To cut a release:

1. Bump the version in `pyproject.toml`, `src/horus/__about__.py` and `uv.lock`, and in the README status line.
2. Commit as `chore: release vX.Y.Z`.
3. Tag `vX.Y.Z` and create a GitHub release, grouping the commits by the sections in the table above.
4. Close the matching milestone.

## Issues, labels & milestones

Every milestone corresponds to one release (`v0.4.0`, ...). Items from the README's "Planned" list become issues and get assigned to a milestone once they are scheduled.

### Labels

`scripts/setup_github.py` creates these labels, the milestones and their issues from `scripts/github_data.yml` (see the docstring in the script).

**Type** (matches the commit types)

| Label | Color | Description |
|-------|-------|-------------|
| `feature` | `#0e8a16` | New functionality |
| `bug` | `#d73a4a` | Something isn't working |
| `refactor` | `#fbca04` | Internal cleanup without behaviour change |
| `docs` | `#0075ca` | Documentation |
| `tests` | `#bfd4f2` | Test coverage |
| `chore` | `#ededed` | Tooling, CI, dependencies |

**Area**

| Label | Color | Description |
|-------|-------|-------------|
| `area: hardware` | `#5319e7` | Hardware simulation (CPU, RAM, storage, power, cooling) |
| `area: processes` | `#5319e7` | Process table, scheduler, memory |
| `area: shell` | `#5319e7` | Shell, commands, kernel |
| `area: filesystem` | `#5319e7` | VFS, permissions, encryption |
| `area: ui` | `#5319e7` | Screens, layout, widgets |
| `area: display` | `#5319e7` | Renderer, shader, fonts, sprites |
| `area: audio` | `#5319e7` | Sound effects and playback |
| `area: story` | `#5319e7` | Story progress, gameplay content |

**Status**

| Label | Color | Description |
|-------|-------|-------------|
| `blocked` | `#b60205` | Waiting on something else |
| `good first issue` | `#7057ff` | Small and self-contained |
| `wontfix` | `#ffffff` | Won't be worked on |
| `dependencies` | `#0366d6` | Dependency updates (set by Dependabot) |
