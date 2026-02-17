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

3. **Build the app:** `bash scripts/build-app.sh`

4. **Create a GitHub Release** with the built ZIP from `dist/`

### Version Strategy

We use semantic versioning (`MAJOR.MINOR.PATCH`):
- **PATCH** (0.0.x): Bug fixes, minor improvements
- **MINOR** (0.x.0): New features, non-breaking changes
- **MAJOR** (x.0.0): Breaking changes
