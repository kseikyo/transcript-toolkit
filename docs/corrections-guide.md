# Corrections Guide

## Entry Format

Each correction is a JSON object:

```json
{
  "asr": "github",
  "correct": "GitHub",
  "confidence": "high",
  "category": "tool",
  "notes": "Source code hosting platform",
  "context": {
    "strategy": "both",
    "neighbors": ["repo", "commit"],
    "exclude_neighbors": ["microsoft", "gitlab"]
  }
}
```

## Confidence Levels

- **high**: Always replace (99%+ certainty)
- **medium**: Replace if context matches (ambiguous without context)
- **low**: Flag for review (uncertain, often names)

## Context Rules

When ASR words are ambiguous, use context rules:

| Strategy | Behavior |
|----------|----------|
| `always` | Replace unconditionally (default) |
| `requires_neighbor` | Replace only if neighbor word present |
| `exclude_neighbor` | Replace unless exclusion word present |
| `both` | Requires neighbor AND no exclusion |

## Global vs Project Corrections

**Global** (`corrections-global.json`): Universal terms like GitHub, Kubernetes, API. Conservative — only add terms used across many teams.

**Project** (`profiles/<name>/corrections.json`): Team-specific terms like internal codenames, person names, project jargon.

## Maintenance Tips

1. Start with high confidence only
2. Add context rules when you see false positives
3. Review skipped items weekly to find new patterns
4. Keep notes explaining *why* a correction exists
