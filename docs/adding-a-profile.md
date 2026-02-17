# Adding a Profile

## 1. Copy Template

```bash
cp -r profiles/template profiles/my-team-name
```

## 2. Fill profile.json

Edit `profiles/my-team-name/profile.json`:

```json
{
  "profile_name": "my-team-name",
  "description": "My team — building X product",
  "language": "en-US",
  "source": "Read AI",
  "speakers": ["Alice Smith", "Bob Jones"],
  "domain_context": "SaaS platform for Y industry. Stack: React, Python, PostgreSQL."
}
```

## 3. Run First Transcript

```bash
uv run python scripts/fix-transcript.py meetings/standup.md --profile profiles/my-team-name
```

Check the output to see what gets flagged.

## 4. Build Your Dictionary

Add corrections as you encounter them:

```bash
uv run python scripts/add-correction.py --profile profiles/my-team-name \
  --asr "codename" --correct "CodeName" --category "tool"
```

## 5. Iterate

Run transcripts → review flags → add corrections → repeat.

Accuracy improves with each meeting as your dictionary grows.
