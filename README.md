# transcript-toolkit

Generic, project-agnostic meeting transcript correction system. Works for any team, any language, any transcript source (Read AI, Otter.ai, Zoom, Google Meet, etc.).

## Quick Start

```bash
# Clone and setup
git clone https://github.com/kseikyo/transcript-toolkit.git
cd transcript-toolkit
uv sync

# Run your first correction
uv run python scripts/fix-transcript.py meetings/standup.md --profile profiles/acme-engineering
```

## Architecture

transcript-toolkit uses a two-stage pipeline:

1. **Deterministic correction** (`fix-transcript.py`) — applies known corrections from dictionaries
2. **AI review** (Claude Code via skill) — resolves ambiguous cases using context

Project-specific configuration lives in "profile" folders. Global corrections apply to all projects.

## Scripts

| Script | Purpose | Example |
|--------|---------|---------|
| `fix-transcript.py` | Apply deterministic corrections | `fix-transcript.py transcript.md --profile profiles/my-team` |
| `add-correction.py` | Add entries to dictionaries | `add-correction.py --profile profiles/my-team --asr "github" --correct "GitHub"` |
| `ai-review.py` | Apply AI decisions to transcripts | `cat decisions.json | ai-review.py --apply --update-dict` |

## Profile System

Profiles are folders under `profiles/` containing:
- `profile.json` — team context, language, speakers, domain description
- `corrections.json` — project-specific ASR corrections

Copy `profiles/template/` to create a new profile.

## Documentation

- [Corrections Guide](docs/corrections-guide.md) — how to maintain dictionaries
- [Workflow Architecture](docs/workflow-architecture.md) — full system diagram
- [Adding a Profile](docs/adding-a-profile.md) — step-by-step onboarding
- [Contributing](CONTRIBUTING.md) — how to contribute

## License

MIT
