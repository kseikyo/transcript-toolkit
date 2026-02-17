# Contributing to transcript-toolkit

## Adding Global Corrections

Global corrections (`corrections-global.json`) should be conservative. Only add:
- Universal terms used across many teams (GitHub, Kubernetes, API)
- Common ASR errors that affect everyone
- Proper nouns with standard capitalization

Avoid:
- Team-specific jargon
- Project codenames
- Person names

## Submitting Profiles

Profiles in `profiles/` should be:
- Anonymized if based on real teams (use fictional names like "Acme Engineering")
- Self-contained with both profile.json and corrections.json
- Documented with clear domain_context explaining the team's work

## Code Style

- Python 3.11+
- Type hints on all functions
- Docstrings on all public functions
- No external runtime dependencies (stdlib only)

## Testing

All new features need tests in `tests/`:

```bash
uv run --with pytest pytest tests/ -v
```

Tests should:
- Use `tmp_path` for file operations
- Use `monkeypatch` for mocking
- Not require network access

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit PR with clear description

## Questions?

Open an issue for discussion before major changes.
