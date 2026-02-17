# Fix Transcript

Use this skill when the user wants to correct a meeting transcript.

## Overview

transcript-toolkit uses a two-stage pipeline:
1. **Deterministic pass** — apply known corrections from dictionaries
2. **AI review + grammar pass** — resolve ambiguities and fix punctuation

## When to Use

- User says "fix this transcript"
- User provides a transcript file and asks for correction
- User mentions ASR errors or transcription mistakes

## Workflow

### Step 1: Identify Inputs

Ask or determine:
- Path to transcript file (.md or .txt)
- Which profile to use (folder under profiles/)

If no profile specified, use `profiles/acme-engineering` as example or ask user.

### Step 2: Run Deterministic Correction

```bash
uv run python scripts/fix-transcript.py {transcript} --profile {profile} --review ai --out {transcript}-fixed.md
```

This produces:
- `{transcript}-fixed.md` — corrected transcript
- JSON payload to stdout with flagged items for review

### Step 3: Review Flagged Items

Capture the JSON payload and review each item:

```python
# The payload structure:
{
  "version": "1.0",
  "profile_context": {
    "language": "en-US",
    "domain": "B2B SaaS platform...",
    "speakers": ["Priya Sharma", "Marcus Chen", ...]
  },
  "transcript_file": "standup-2026-02-14.md",
  "items": [
    {
      "id": "rev_001",
      "original_word": "cloud",
      "context_window": "...ask cloud about the embedding...",
      "line_number": 42,
      "speaker": "Marcus Chen",
      "reason_flagged": "context rule: both — no AI neighbor found"
    }
  ]
}
```

For each item, use the profile context to decide:
- **Replace** → provide replacement word
- **Keep** → leave as-is

Build decisions array:

```json
{
  "transcript_file": "standup-2026-02-14.md",
  "profile": "profiles/acme-engineering",
  "decisions": [
    {
      "id": "rev_001",
      "original_word": "cloud",
      "replacement": "Claude",
      "confidence": "high",
      "reasoning": "Context mentions 'embedding dimensions' — AI terminology. Speaker is discussing the AI assistant.",
      "add_to_dictionary": false
    }
  ]
}
```

### Step 4: Apply Decisions

Pipe your decisions JSON to ai-review.py:

```bash
cat << 'DECISIONS' | uv run python scripts/ai-review.py --apply --update-dict --profile {profile}
{"transcript_file": "...", "profile": "...", "decisions": [...]}
DECISIONS
```

### Step 5: Grammar and Punctuation Pass

Read the fixed transcript and:

1. Fix obvious grammar errors
2. Fix punctuation (add missing commas, periods)
3. Fix sentence structure issues
4. **PRESERVE:**
   - Speaker labels (e.g., `**Priya Sharma** (00:01:32)`)
   - Timestamps
   - Natural informal speech patterns (ums, ahs, filler words)
   - Original meaning — never paraphrase

5. **NEVER:**
   - Summarize or condense content
   - Change the meaning of what was said
   - Remove filler words intentionally
   - Alter timestamps or speaker attributions

### Step 6: Output Final Transcript

Write the result as `{meeting}-final.md` in the same folder as the original.

```bash
# Final file location:
{original-dir}/{meeting}-final.md
```

## Script Arguments Reference

### fix-transcript.py
- `transcript` — path to raw transcript
- `--profile` — path to profile folder
- `--out` — output file path
- `--dry-run` — preview without writing
- `--min-confidence` — high | medium | low (default: high)
- `--log` — audit log path
- `--review` — human | ai

### ai-review.py
- `--apply` — apply decisions to transcript
- `--update-dict` — add confirmed corrections to dictionary
- `--min-confidence` — filter decisions (default: medium)
- `--profile` — profile path (for --update-dict)

### add-correction.py
- `--profile` or `--global` — target dictionary
- `--asr` — wrong ASR word
- `--correct` — correct replacement
- `--confidence` — high | medium | low
- `--category` — tool | person | concept | place | other
- `--notes` — description
- `--dry-run` — preview without writing

## Example Invocations

**Manual mode (no AI review):**
```bash
uv run python scripts/fix-transcript.py meetings/standup.md --profile profiles/acme-engineering
```

**With AI review (this skill):**
```bash
# Run with --review ai to get payload
uv run python scripts/fix-transcript.py meetings/standup.md --profile profiles/acme-engineering --review ai

# Then apply decisions
# (handled by this skill)
```

**Human review mode:**
```bash
uv run python scripts/fix-transcript.py meetings/standup.md --profile profiles/acme-engineering --review human
```
