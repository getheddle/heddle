# Tutorial: Document Intake Pipeline

Build a pipeline that reads public comments from a CSV, classifies them,
extracts structured data, and audits the classifications for bias — in
three phases, each building on the last.

**What you'll learn:**

| Phase | What you build | Heddle concepts |
|-------|---------------|---------------|
| 1 | A comment classifier you can test immediately | Worker configs, Workshop test bench, eval suites |
| 2 | A four-stage intake pipeline with a custom CSV reader | ProcessingBackend, processor workers, pipelines with mixed worker types |
| 3 | Bias detection with blind and sighted audit paths | Blind workers, parallel pipeline branches, sighted vs. blind analysis |

**Prerequisites:** Heddle installed and configured (`heddle setup` completed).
If you haven't done this yet, see the [Getting Started](../GETTING_STARTED.md) guide.

---

## The Problem

Your department receives hundreds of public comments on a development
proposal. Each comment needs to be categorized by topic, tagged with a
stance (support, oppose, conditional), and scanned for specific requests
that require follow-up. Then you need a summary report.

Doing this by hand takes days. Using a single AI prompt loses nuance —
a 50-comment batch sent to one prompt produces shallow classification
and misses action items buried in long comments.

Worse: how do you know the AI isn't systematically biased? Maybe it's
classifying all short comments as "general" regardless of content. Maybe
it's more likely to mark comments as "oppose" when they mention certain
topics. You can't check unless you explicitly audit the results.

This tutorial builds a pipeline that solves each problem in a separate,
testable, auditable step.

## How It Maps to Heddle

| What you want | Heddle concept | Why |
|---------------|-------------|-----|
| "Sort these comments into categories" | **Worker** with a classification prompt | One worker = one job. The classifier doesn't try to extract or summarize. |
| "Read my CSV file" | **Processor worker** with a custom backend | Non-LLM work (reading files) gets its own worker type. Same I/O contracts. |
| "Pull out names, dates, and specific requests" | **Second worker**, different prompt | Extraction is a different task than classification — a separate worker keeps each prompt focused. |
| "Summarize everything" | **Third worker** in a pipeline | The summarizer gets structured data from prior stages, not raw text. |
| "Is the classifier biased?" | **Blind worker** (sees classifications but not text) | It can spot statistical patterns without being influenced by the content. |
| "Are similar comments treated consistently?" | **Sighted reviewer** (sees both text and classifications) | It can catch content-level inconsistencies the blind worker can't. |
| "Did my prompt change make things better?" | **Workshop eval suite** | Run test cases before and after. Compare scores. |
| "Run the whole thing automatically" | **Pipeline config** | Define stages in YAML. Heddle handles the data flow. |

---

## Phase 1: Classify a Comment

By the end of this phase, you'll have a working classifier that you
can test on any public comment.

### What you're building

A single worker — `comment_classifier` — that takes a text comment and
returns:

- A primary topic from a fixed taxonomy (traffic, environment, housing,
  schools, economic, infrastructure, historic, health, community, general)
- A stance (support, oppose, conditional support, neutral, off-topic)
- Whether the comment contains actionable requests
- The specific action items, extracted from the text
- A confidence score

### Step 1: Set up the example

Copy the example config into your Heddle project:

```bash
cp examples/document-intake/phase-1/workers/comment_classifier.yaml \
   configs/workers/comment_classifier.yaml
```

Open the config and read through it. A few things to notice:

**The taxonomy is in the prompt, not the schema.** Unlike the shipped
`classifier` worker (which takes categories as input), this one has the
categories built in. This is a design choice — a built-in taxonomy works
better when the categories are stable and domain-specific.

**`stance` uses an enum in the output schema.** Heddle will reject any
output where `stance` isn't one of the five valid values. This catches
cases where the LLM invents a stance like "mostly supportive."

**`default_model_tier: "local"`.** Classification is pattern-matching —
local models handle it well. This keeps the pipeline fast and free for
the classification stage.

### Step 2: Validate and test

```bash
heddle validate configs/workers/comment_classifier.yaml
heddle workshop
```

Open `http://localhost:8080`, find `comment_classifier`, click **Test**.

Paste this comment from the sample data:

> I strongly support the proposed mixed-use development at the former
> Millbrook factory site. Our neighborhood has needed walkable retail
> for years, and the inclusion of 40 affordable housing units addresses
> a real gap. My only concern is parking — the plan shows 180 spaces for
> 220 residential units plus commercial.

Set `context` to "Mixed-use development proposal at former Millbrook
factory site" and click **Run**.

You should get a classification with `primary_topic: "traffic"` (the
parking concern) or `"housing"` (the affordable housing angle), `stance:
"conditional_support"`, and `actionable: true` with an action item about
the traffic impact study.

**Try the edge case.** Paste this one:

> This is just another giveaway to developers. The planning board always
> approves everything. Wake up people.

You should get `primary_topic: "general"`, `stance: "oppose"`,
`actionable: false`, and a lower confidence score. If the classifier
invents action items for this comment, your prompt needs tightening.

### Step 3: Run the eval suite

The example includes a test suite with six comments covering different
topics and stances, including edge cases:

1. Go to Workers list → `comment_classifier` → **Eval**
2. Load `examples/document-intake/phase-1/eval/test_suite.json`
3. Choose **field_match** scoring
4. Click **Run Suite**

The eval checks three fields per comment: `primary_topic`, `stance`, and
`actionable`. These are the fields where the classifier most needs to be
consistent.

**Set a golden baseline** once you have passing results. This is your
regression detector — any future prompt changes are compared against it.

### What you have now

A tested classifier with an eval suite and golden baseline. You can paste
any comment into Workshop and get structured output. But classifying one
comment at a time isn't useful when you have 300 of them in a CSV file.
That's Phase 2.

---

## Phase 2: The Intake Pipeline

Phase 1 gave you a classifier for individual comments. Phase 2 chains
four workers into a pipeline that processes a CSV of comments end-to-end.

### What you're building

```text
  csv_reader ──► comment_classifier ──► entity_extractor ──► batch_summarizer
  (processor)    (classify each)        (extract entities)   (aggregate report)
```

The first stage is a **processor worker** — it runs Python code, not an
LLM. The CSV reader is a custom `ProcessingBackend` that you write (~40
lines of Python). This demonstrates that Heddle pipelines can mix LLM and
non-LLM work.

### Heddle concepts introduced

**Processor workers** run a Python class instead of calling an LLM. The
worker config says `worker_kind: "processor"` and points to a class that
extends `SyncProcessingBackend`. That class implements one method:
`process_sync(payload, config) → {"output": dict, "model_used": str}`.
Same I/O contract validation as LLM workers — same `input_schema`,
same `output_schema`.

**Custom ProcessingBackend** — the `CsvReaderBackend` in
`processing/csv_reader.py`. It reads a CSV file, validates the columns,
and returns all rows as structured records. The key insight: backends
inherit from `SyncProcessingBackend`, which automatically offloads the
synchronous `process_sync` call to a thread pool. Write blocking code;
Heddle handles the async.

**Batch-aware workers** — the Phase 2 classifier and extractor take
arrays of records instead of single items. In Phase 1 you tested
individual comments. In a pipeline, the csv_reader returns all records
at once, so downstream workers handle the full batch.

**Input mappings** — the pipeline config specifies how data flows between
stages using dot-notation paths. `records: "read_csv.output.records"`
means "take the `records` field from the `read_csv` stage's output."
Heddle infers dependencies from these paths — if stage B reads from stage
A's output, A must complete first.

### Step 1: Understand the CSV reader

Open `examples/document-intake/processing/csv_reader.py`. The entire
backend is about 40 lines of actual logic:

- Read a CSV file from the `source_path` in the payload
- Validate that the specified `text_column` exists
- Return all rows as a list of dicts
- Handle encoding issues (UTF-8 with Latin-1 fallback)

The worker config that uses this backend is in
`phase-2/workers/csv_reader.yaml`:

```yaml
name: "csv_reader"
worker_kind: "processor"
processing_backend: "examples.document_intake.processing.csv_reader.CsvReaderBackend"
```

Notice: `worker_kind: "processor"` — no `system_prompt`, no model tier,
no token limits. But `input_schema` and `output_schema` are still
required. The contract validation works exactly the same way.

### Step 2: Copy configs and set up

```bash
cp examples/document-intake/phase-2/workers/*.yaml configs/workers/
cp examples/document-intake/phase-2/orchestrators/*.yaml configs/orchestrators/
heddle validate configs/workers/csv_reader.yaml
heddle validate configs/workers/entity_extractor.yaml
heddle validate configs/workers/batch_summarizer.yaml
heddle validate configs/orchestrators/document_intake.yaml
```

For the `CsvReaderBackend` to be importable, ensure the `processing/`
directory is on your Python path. If running from the heddle project root:

```bash
export PYTHONPATH="${PYTHONPATH}:examples/document-intake"
```

### Step 3: Walk through the pipeline config

Open `configs/orchestrators/document_intake.yaml`. Four stages:

1. **`read_csv`** — processor worker, tier `local` (no LLM).
   `input_mapping` pulls `source_path` and `text_column` from the goal
   context (values you provide when submitting the pipeline).

2. **`classify`** — LLM worker. `records: "read_csv.output.records"`
   creates a dependency on `read_csv`. Heddle waits for `read_csv` to
   finish before starting `classify`.

3. **`extract`** — LLM worker. Reads from both `read_csv.output.records`
   and `classify.output.classifications`. Depends on both prior stages.

4. **`summarize`** — LLM worker. Reads from `classify`, `extract`, and
   `read_csv`. Produces the final report.

The dependency chain is strictly sequential: read → classify → extract →
summarize. Each stage must wait for the one before it. Phase 3 adds
parallel branches.

### Step 4: Test individual workers in Workshop

Before running the full pipeline, test each worker individually in
Workshop. This is a key workflow pattern: test the parts, then assemble.

For the batch classifier and extractor, you can construct test inputs
by pasting a few records as JSON arrays.

### Step 5: Run the pipeline

With NATS running and workers deployed:

```bash
heddle submit "Process comments" \
    --context source_path="examples/document-intake/sample-data/public_comments.csv" \
    --context text_column="text" \
    --context description="Mixed-use development proposal at former Millbrook factory site"
```

Or test in Workshop's pipeline editor.

The output from the `summarize` stage is a structured report: executive
summary, topic breakdown, stance distribution, deduplicated action items,
and staff recommendations — all generated from 12 comments processed
through four stages.

### What you have now

A working intake pipeline with a custom processing backend, batch
classification, entity extraction, and automated summarization. The
summary is useful, but you have no way to know if the classifier is
fair. That's Phase 3.

---

## Phase 3: Bias Detection

Phases 1 and 2 give you automated intake and summarization. But how do
you know the classifier isn't systematically biased? Maybe it's marking
all short comments as "general." Maybe comments mentioning certain
neighborhoods get classified differently.

Phase 3 adds two audit workers that check the classifications from two
independent perspectives.

### What you're building

```text
  read_csv ──► classify ──┬──► extract ──► summarize
                          │
                          ├──► blind_bias_auditor
                          │
                          └──► fairness_reviewer
```

Three paths run in parallel after classification:

- The **intake path** (extract → summarize) produces the summary report
  just like Phase 2
- The **blind audit** checks classification patterns without seeing the
  original text — it catches statistical biases
- The **fairness review** checks consistency with full context — it
  catches content-level misclassifications

### Heddle concepts introduced

**Blind workers** — the `blind_bias_auditor` has `knowledge_silos: []`
and its input mapping gives it only the classification results, never
the original text. It cannot evaluate whether individual classifications
are correct. But it can spot patterns: "all low-confidence items go to
the same category" or "comments classified as 'oppose' never have action
items."

**Sighted vs. blind** — the `fairness_reviewer` gets both the text and
the classifications. It can check whether similar content is treated
consistently, whether classification quality varies by author type, and
whether action items were missed. Together, the blind and sighted
reviewers catch different kinds of problems.

**Parallel pipeline branches** — after `classify` completes, three stages
run concurrently: `extract`, `bias_audit`, and `fairness_review`. None of
them depend on each other — they all depend only on `classify` (and
`read_csv`). Heddle infers this parallelism automatically from the
`input_mapping` paths.

### Step 1: Create the blind bias auditor

Copy the Phase 3 configs:

```bash
cp examples/document-intake/phase-3/workers/blind_bias_auditor.yaml configs/workers/
cp examples/document-intake/phase-3/workers/fairness_reviewer.yaml configs/workers/
cp examples/document-intake/phase-3/orchestrators/document_intake_audited.yaml configs/orchestrators/
```

Open `configs/workers/blind_bias_auditor.yaml`. Notice the input schema:
it takes `classifications` (array) and `total_count` (integer). No `text`
field. No `records` field. This worker literally cannot see what was
classified — only how it was classified.

The prompt tells it to look for specific bias patterns: catch-all
categories, confidence clustering, stance imbalance, low-confidence
dumping. These are statistical checks that don't require seeing the
original data.

### Step 2: Understand the fairness reviewer

Open `configs/workers/fairness_reviewer.yaml`. This one takes `records`,
`text_column`, AND `classifications`. It can compare the text to its
classification and check for inconsistencies:

- Did two similar comments get different topics?
- Did the stance assignment match what the comment actually says?
- Were action items missed in some comments but caught in others?

The fairness reviewer produces `misclassification_suspects` (specific
comments it thinks were classified wrong) and an `overall_fairness_score`.

### Step 3: Walk through the parallel pipeline

Open `configs/orchestrators/document_intake_audited.yaml`. The key
difference from Phase 2: after `classify`, three stages start
concurrently:

```yaml
# These three all depend on classify but NOT on each other:
- name: "extract"
  input_mapping:
    records: "read_csv.output.records"
    classifications: "classify.output.classifications"

- name: "bias_audit"
  input_mapping:
    classifications: "classify.output.classifications"
    total_count: "classify.output.total_classified"

- name: "fairness_review"
  input_mapping:
    records: "read_csv.output.records"
    classifications: "classify.output.classifications"
```

Heddle sees that `extract`, `bias_audit`, and `fairness_review` all
reference `classify.output.*` but none reference each other. It runs
them in parallel automatically.

### Step 4: Compare the audit outputs

Run the pipeline and examine the three output streams:

- **`summarize`** gives you the intake report (same as Phase 2)
- **`bias_audit`** tells you whether the classification distribution
  looks suspicious
- **`fairness_review`** tells you which specific classifications might
  be wrong

With 12 sample comments, the blind auditor might flag that the
"general" category is underused or that confidence scores cluster
suspiciously high. The fairness reviewer might catch that comment-001
(parking concern with overall support) could reasonably be classified
as "housing" instead of "traffic."

These disagreements and flags are the most valuable output — they
tell you where to focus your human review time.

### What you have now

A six-worker pipeline with a custom processing backend and parallel
audit branches. The intake path processes comments into a structured
summary. The audit path checks whether the processing was fair and
consistent. The pipeline output includes both the results and the
quality assessment of those results.

---

## What's Next

You now have a complete document intake system with built-in quality
assurance. Here are two directions to push it further:

### Idea 1: Custom Ingestor for RAG

Write a simple `Ingestor` subclass that feeds the CSV data into Heddle's
RAG pipeline vector store. This enables semantic search across all
processed comments: "Find all comments that mention traffic concerns
near the proposed site" — returning results ranked by relevance, not
just keyword matching.

This requires implementing the `Ingestor` ABC from
`heddle.contrib.rag.ingestion` and registering it as a new ingestor type.
The CSV reader backend you already built handles the file parsing — the
ingestor wraps it with normalization and chunking for vector storage.

### Idea 2: Scheduled Monitoring

Set up Heddle's scheduler to watch a folder for new CSV drops and
automatically run the intake pipeline. Each morning, planning staff
would find a fresh summary report covering any new comments received
overnight.

This uses Heddle's scheduler component with a cron-style trigger and
file-watching logic in a custom backend. The pipeline itself doesn't
change — scheduling is infrastructure, not workflow.

---

*This tutorial uses the example configs in `examples/document-intake/`.
Each phase directory contains the complete working configs for that phase
— you can copy them directly or build them step by step following the
walkthrough above.*
