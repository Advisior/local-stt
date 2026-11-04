# Contributing

Thanks for contributing to Local-STT. This repo is small and fast-moving, so we optimize for clarity and quick review.

## How to Contribute

1) Fork and clone the repo
2) Create a branch
3) Make your changes
4) Run tests and update docs if needed
5) Open a pull request

## Development

```bash
# Clone and setup
git clone https://github.com/Advisior/local-stt.git
cd local-stt

# Install dependencies
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install mlx-whisper

# Build and install the menu bar app
bash scripts/build-app.sh
bash scripts/install-app.sh
```

## Tests

```bash
python -m unittest discover -s tests
```

## Code Style

- Keep changes focused and small
- Prefer tests for behavior changes
- Avoid introducing dependencies unless necessary
- Follow existing patterns in the codebase

## Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/). Examples:

- `feat: add French language support`
- `fix: resolve hotkey conflict on macOS`
- `docs: update README badges`

## Pull Requests

- Describe the problem and the fix
- Include tests or explain why they are not needed
- Link issues when relevant

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Releasing New Versions

When shipping a new version:

1. **Update version numbers** in all files:
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `src/claude_stt/__init__.py` → `__version__ = "X.Y.Z"`
   - `.claude-plugin/plugin.json` → `"version": "X.Y.Z"`
   - `.claude-plugin/marketplace.json` → `"version": "X.Y.Z"`

2. **Update CHANGELOG.md** with the new version and changes

3. **Push the tag** `vX.Y.Z`. The Release workflow builds the app zip and the standalone Python runtime, creates a draft release if none exists (notes: the CHANGELOG section), attaches both with their `.sha256` files and only then publishes the release. If either build fails, the release stays a draft or is not created, so `install.sh` keeps using the previous release. A release drafted beforehand keeps its notes. A published release is never turned back into a draft: if it already has all assets, a re-run leaves it unchanged; if it lacks some (published in the web UI before the workflow finished), only the missing ones are added. So push the tag or create a draft rather than publishing in the web UI, which would make the release visible before its assets are attached.

To build locally instead: `bash scripts/build-app.sh` and, on an Apple Silicon Mac, `bash scripts/build-runtime.sh`.

### Version Strategy

We use semantic versioning (`MAJOR.MINOR.PATCH`):
- **PATCH** (0.0.x): Bug fixes, minor improvements
- **MINOR** (0.x.0): New features, non-breaking changes
- **MAJOR** (x.0.0): Breaking changes
