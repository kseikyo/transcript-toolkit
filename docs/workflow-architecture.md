# Workflow Architecture

## Pipeline Diagram

```
Raw transcript (.md/.txt)
         |
         v
+-----------------------------+
|  fix-transcript.py          |
|  - Load global corrections  |
|  - Load profile corrections |
|  - Merge & sort             |
|  - Apply with context rules |
+-------------+---------------+
              |
              v
      Fixed transcript
      + audit log
              |
     +--------+--------+
     |                 |
     v                 v
[--review human]  [--review ai]
Interactive       JSON payload
review            to stdout
     |                 |
     v                 v
  Grammar pass    Claude Code
  (Claude skill)  reviews items
     |                 |
     +--------+--------+
              |
              v
      Final transcript
              |
     +--------+--------+
     |                 |
     v                 v
  Confirmed       add-correction.py
  corrections     updates dictionary
     |                 |
     +-----------------+
              |
              v
      Dictionary grows
              |
              v
         [repeat]
```

## Stage Details

### 1. Deterministic Correction
Loads corrections from global + profile, filters by confidence, applies replacements with case restoration. Skipped items flagged with `[unclear: "word" → ?]`.

### 2. Review (Optional)
- **Human**: Interactive walkthrough of skipped items
- **AI**: JSON payload piped to Claude Code for context-aware decisions

### 3. Grammar Pass
Claude Code skill fixes punctuation and sentence structure while preserving speaker labels, timestamps, and natural speech patterns.

### 4. Dictionary Growth
Confirmed corrections from review are added back to the project dictionary, improving accuracy for future transcripts.

## Data Flow

- Corrections flow: global + profile → merged → filtered → applied
- Feedback loop: review → confirmed → dictionary → future transcripts
