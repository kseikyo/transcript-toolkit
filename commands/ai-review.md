---
name: ai-review
description: Review and resolve [unclear] flagged items from transcript correction using AI context. Use after fix-transcript has flagged ambiguous corrections.
triggers:
  - "ai review"
  - "review unclear"
  - "resolve flags"
  - "review transcript flags"
  - "unclear items"
---

# AI Review

Use this skill after `fix-transcript` has flagged items as `[unclear]`. This skill reviews each flagged item using conversation context and makes keep/replace/add-to-dictionary decisions.

## Workflow

### Step 1: Generate AI payload

```bash
uv run python scripts/fix-transcript.py <transcript> --profile <profile> --review ai > /tmp/ai-payload.json
```

### Step 2: Review the payload

Read `/tmp/ai-payload.json`. Each item has:
- `id`: Unique identifier (e.g., `rev_001`)
- `original_word`: The flagged word
- `context_window`: Surrounding words for context
- `line_number`: Where it appears
- `speaker`: Who said it
- `reason_flagged`: Why it was flagged (e.g., context rule failed)

### Step 3: Make decisions

For each item, decide:
- **replace**: Provide the correct replacement
- **keep**: Leave the original word as-is
- **add_to_dictionary**: Replace AND add to profile corrections for future transcripts

Output decisions as JSON:
```json
{
  "transcript_file": "path/to/transcript-fixed.md",
  "decisions": [
    {
      "id": "rev_001",
      "original_word": "cloud",
      "replacement": "Claude",
      "confidence": "high",
      "reasoning": "AI assistant context — refers to Anthropic's Claude",
      "add_to_dictionary": true,
      "line_number": 26
    }
  ]
}
```

### Step 4: Apply decisions

```bash
echo '<decisions_json>' | uv run python scripts/ai-review.py --apply --out <output>
```

To also update the corrections dictionary:
```bash
echo '<decisions_json>' | uv run python scripts/ai-review.py --apply --update-dict --profile <profile>
```

## Flags

| Flag | Description |
|------|-------------|
| `--apply` | Apply decisions to transcript file |
| `--update-dict` | Add confirmed corrections to profile dictionary |
| `--min-confidence` | Filter by confidence: high, medium (default), low |
| `--profile` | Profile path (required for `--update-dict`) |
| `--out` | Output file (default: overwrite transcript) |

## Decision Guidelines

- **high confidence**: Clear ASR error with unambiguous correct form (e.g., "Cloud" → "Claude" in AI context)
- **medium confidence**: Likely correct but context is ambiguous
- **low confidence**: Uncertain — consider keeping the original
- Set `add_to_dictionary: true` only for recurring ASR errors, not one-off mistakes
