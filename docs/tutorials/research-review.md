# Tutorial: Research Review Pipeline

Build a pipeline that extracts claims from research papers, checks the
methodology, and runs a blind adversarial review — in three phases, each
building on the last.

**What you'll learn:**

| Phase | What you build | Loom concepts |
|-------|---------------|---------------|
| 1 | A claim extractor you can test immediately | Worker configs, Workshop test bench, eval suites |
| 2 | A three-stage review pipeline | Pipeline configs, stage dependencies, input mappings |
| 3 | Blind adversarial review with parallel branches | Knowledge silos, blind workers, parallel stages, synthesis |

**Prerequisites:** Loom installed and configured (`loom setup` completed).
If you haven't done this yet, see the [Getting Started](../GETTING_STARTED.md) guide.

---

## The Problem

You read research papers and need to evaluate them systematically. Not
just "is this interesting?" but: What claims are being made? What evidence
supports them? Are there methodological gaps the authors don't acknowledge?
Would an independent reviewer reach the same conclusions?

Doing this by hand is slow. Asking a single AI to both summarize and
critique produces shallow, self-confirming output — the same model that
extracted the claims will rubber-stamp them when asked to review.

This tutorial builds a pipeline that solves each problem in a separate,
testable step.

## How It Maps to Loom

| What you want | Loom concept | Why |
|---------------|-------------|-----|
| "Extract the claims from this paper" | **Worker** with an extraction prompt | One worker = one job. Focused prompts produce better output than general-purpose ones. |
| "Check whether the methodology supports the claims" | **Second worker**, different prompt | A separate worker can apply different criteria without the extraction context contaminating its judgment. |
| "Summarize the review" | **Third worker** in a pipeline | The summarizer sees structured output from prior stages, not raw text. |
| "Get a genuinely independent opinion" | **Blind worker** (empty knowledge silo) | A worker with no access to domain knowledge can't pattern-match against the analytical frame. It evaluates from first principles. |
| "Did my prompt change make things better?" | **Workshop eval suite** | Run the same test cases before and after. Compare scores. No guessing. |
| "Run extraction → review → summary automatically" | **Pipeline config** | Define the stages in YAML. Loom handles the data flow and parallelism. |

---

## Phase 1: Extract Claims from a Paper

By the end of this phase, you'll have a working claim extractor that you
can test on any research abstract.

### What you're building

A single worker — `claim_extractor` — that takes a research abstract and
returns structured output:

- A list of claims, each tagged with its type (empirical, methodological,
  interpretive, recommendation)
- The evidence supporting each claim
- Limitations the authors acknowledge
- Potential issues the authors *don't* acknowledge

That last point is important. A good extractor doesn't just parrot the
abstract — it flags gaps.

### Step 1: Set up the example

Copy the example configs into your Loom project:

```bash
# From your loom directory
cp -r examples/research-review/phase-1/workers/claim_extractor.yaml \
      configs/workers/claim_extractor.yaml
```

Or create the file yourself. Here's the full config:

```yaml
# configs/workers/claim_extractor.yaml

name: "claim_extractor"

description: "Extracts structured claims from research text with confidence basis and limitations."

system_prompt: |
  You are a research claim extractor. You read academic text and identify
  the distinct claims being made, what evidence supports each one, and
  what limitations the authors acknowledge.

  INPUT FORMAT:
  - text (string): Research abstract or paper section to analyze
  - domain (string, optional): Research domain for context

  OUTPUT FORMAT:
  Respond with ONLY a JSON object:
  {
    "claims": [
      {
        "claim": "A clear statement of what is being asserted",
        "type": "empirical | methodological | interpretive | recommendation",
        "evidence": "What evidence or data supports this claim",
        "confidence_basis": "How confident the claim is and why",
        "limitations": "Any caveats, qualifications, or acknowledged weaknesses"
      }
    ],
    "methodology_summary": "Brief description of the study design or approach",
    "stated_limitations": ["Limitations the authors explicitly acknowledge"],
    "unstated_concerns": ["Potential issues the authors do NOT acknowledge"]
  }

  RULES:
  - Extract ALL distinct claims, not just the main finding
  - type must be one of: empirical, methodological, interpretive, recommendation
  - Do not invent evidence — only report what the text states
  - unstated_concerns should flag real methodological issues the authors missed
  - If the text is too short or vague to extract meaningful claims, return
    {"error": "Insufficient content for claim extraction"}

input_schema:
  type: object
  required: [text]
  properties:
    text:
      type: string
      minLength: 50
    domain:
      type: string

output_schema:
  type: object
  required: [claims, methodology_summary, stated_limitations, unstated_concerns]
  properties:
    claims:
      type: array
      items:
        type: object
        required: [claim, type, evidence, confidence_basis]
        properties:
          claim:
            type: string
          type:
            type: string
            enum: [empirical, methodological, interpretive, recommendation]
          evidence:
            type: string
          confidence_basis:
            type: string
          limitations:
            type: string
    methodology_summary:
      type: string
    stated_limitations:
      type: array
      items:
        type: string
    unstated_concerns:
      type: array
      items:
        type: string

default_model_tier: "standard"
max_input_tokens: 16000
max_output_tokens: 4000
reset_after_task: true
timeout_seconds: 90
```

Take a moment to read the config. Notice:

- **`system_prompt`** is the only instructions the LLM sees. It defines
  INPUT FORMAT, OUTPUT FORMAT, and RULES — three sections that keep the
  worker focused.
- **`input_schema`** and **`output_schema`** are JSON Schema. Loom
  validates input *before* calling the LLM and output *after*. If either
  fails, you get a clear error — not garbage output.
- **`default_model_tier: "standard"`** means this worker uses Claude
  Sonnet by default. Claim extraction benefits from stronger reasoning
  than a local model provides. You can override this in Workshop.

### Step 2: Validate the config

Before testing, check that the config is well-formed:

```bash
loom validate configs/workers/claim_extractor.yaml
```

You should see:

```text
✓ configs/workers/claim_extractor.yaml — valid worker config
```

If you get errors, check your YAML indentation. The most common mistake
is mixing tabs and spaces.

### Step 3: Test in Workshop

Start Workshop:

```bash
loom workshop
```

Open `http://localhost:8080` in your browser. You'll see `claim_extractor`
in the Workers list. Click **Test**.

The test bench shows input fields matching the schema: a `text` box and
an optional `domain` field. Paste this abstract from the sample data:

> This study examines the relationship between urban green space coverage
> and respiratory health outcomes across 12 mid-size cities (population
> 100,000-500,000) in the midwestern United States over a 5-year period
> (2019-2024). Using satellite-derived NDVI measurements cross-referenced
> with county-level hospitalization records for asthma, COPD, and
> bronchitis, we found a statistically significant inverse correlation
> (r=-0.67, p<0.01) between green space coverage percentage and
> age-adjusted respiratory hospitalization rates...

Set `domain` to `public health / urban planning` and click **Run**.

You'll see structured JSON output with:

- Multiple claims extracted (the main correlation finding, the
  socioeconomic moderation effect, the seasonal interaction, the policy
  recommendation)
- Each tagged with type, evidence, and confidence basis
- Stated limitations (socioeconomic confound, seasonal effect)
- Unstated concerns (e.g., ecological fallacy from county-level data,
  no individual-level exposure measurement, potential selection bias in
  which cities were studied)

**Try different tiers.** Switch to `local` and run the same abstract. Then
`frontier`. Compare: Does the local model miss claims? Does the frontier
model catch more unstated concerns? This comparison is a core Loom
workflow — the tier system exists to make it trivial.

### Step 4: Run the eval suite

Testing one abstract at a time tells you if the worker works. An eval
suite tells you if it works *consistently*.

The example includes a test suite with all four sample abstracts. To run
it in Workshop:

1. Go to the Workers list → `claim_extractor` → **Eval**
2. Load the test cases from `examples/research-review/phase-1/eval/test_suite.json`
   (or paste them manually)
3. Choose **field_match** scoring — this checks whether specific output
   fields match expected values
4. Click **Run Suite**

The eval checks that `methodology_summary` captures the study design
accurately for each abstract. In a real project, you'd add expected
values for claim count, claim types, and specific limitations you expect
the extractor to catch.

**Set a baseline.** Once you have a passing eval run, click **Set as
Golden Baseline**. Now any future changes to the system prompt or model
tier will be compared against this baseline. If your "improvement" makes
things worse, you'll see it immediately.

### Step 5: Iterate on the prompt

This is where the real work happens. Look at the eval results:

- **Are claims too vague?** Add a RULE: "Each claim must be specific
  enough to be falsifiable."
- **Missing unstated concerns?** Add examples of common methodological
  gaps to the system prompt.
- **Wrong claim types?** Add clearer definitions for each type.

Edit the system prompt in Workshop, save (creating a new version), and
re-run the eval. Compare against the golden baseline. This is the
Workshop flywheel: edit → test → evaluate → compare → repeat.

### What you have now

A working, tested claim extractor with:

- A YAML config you can version-control
- An eval suite that catches regressions
- A golden baseline for comparison
- Zero infrastructure (no NATS, no message bus, no deployment)

You can already use this as a standalone tool: paste any abstract into
Workshop, get structured claims out. But one worker working alone hits
a ceiling — it can extract claims, but it can't evaluate whether those
claims are well-supported. That's Phase 2.

---

## Phase 2: The Review Pipeline

Phase 1 gave you a claim extractor. But extracted claims sitting in JSON
aren't a review. You need:

1. A **methodology reviewer** that checks whether the study design
   actually supports the claims being made
2. A **review summarizer** that synthesizes the extraction and review
   into a structured report

Phase 2 chains these three workers into a pipeline — data flows
automatically from one stage to the next.

### What you're building

```text
  claim_extractor ──► methodology_reviewer ──► review_summarizer
  (extract claims)    (check the evidence)      (write the report)
```

### Loom concepts introduced

- **Pipeline config** — a YAML file defining stages, their order, and
  how data flows between them
- **Input mappings** — how one stage's output becomes the next stage's
  input (dot-notation paths like `extract.output.claims`)
- **Stage dependencies** — Loom infers the execution order from the
  input mappings. If stage B reads from stage A's output, A runs first.
  Stages that don't depend on each other run in parallel automatically.
- **Pipeline editor** — Workshop's visual graph of stage dependencies

### Step 1: Create the methodology reviewer

Copy the Phase 2 configs:

```bash
cp examples/research-review/phase-2/workers/*.yaml configs/workers/
cp examples/research-review/phase-2/orchestrators/*.yaml configs/orchestrators/
```

Open `configs/workers/methodology_reviewer.yaml`. This worker takes
three inputs: the original `text`, the `claims` array from the extractor,
and the `methodology_summary`. For each claim, it assesses whether the
described methodology can logically support it.

The key output field is `strength` — an enum of `strong`, `moderate`,
`weak`, or `unsupported`. This forces the LLM into a concrete assessment
rather than vague hedging like "the evidence is somewhat supportive."

Test it in Workshop: construct an input with a text, a claims array
(you can paste output from the claim extractor), and a methodology
summary. Run it and check whether the strength assessments are
defensible.

### Step 2: Create the review summarizer

Open `configs/workers/review_summarizer.yaml`. This worker receives
structured data from both prior stages — it never sees raw text. Its
job is synthesis, not re-analysis.

The output includes a `verdict` (accept / revise / reject) and a
`report` field — a narrative review written as if addressing the paper's
authors. The prompt explicitly says "Do not add new analysis — synthesize
what the extraction and review found."

### Step 3: Define the pipeline

Open `configs/orchestrators/research_review.yaml`. Three stages:

```yaml
pipeline_stages:
  - name: "extract"
    worker_type: "claim_extractor"
    input_mapping:
      text: "goal.context.text"
      domain: "goal.context.domain"

  - name: "review"
    worker_type: "methodology_reviewer"
    input_mapping:
      text: "goal.context.text"
      claims: "extract.output.claims"
      methodology_summary: "extract.output.methodology_summary"

  - name: "summarize"
    worker_type: "review_summarizer"
    input_mapping:
      claims: "extract.output.claims"
      methodology_summary: "extract.output.methodology_summary"
      stated_limitations: "extract.output.stated_limitations"
      unstated_concerns: "extract.output.unstated_concerns"
      claim_reviews: "review.output.claim_reviews"
      overall_methodology_score: "review.output.overall_methodology_score"
      design_strengths: "review.output.design_strengths"
      design_weaknesses: "review.output.design_weaknesses"
```

Read the `input_mapping` entries. `claims: "extract.output.claims"` means
"take the `claims` field from the `extract` stage's output and pass it
as the `claims` input to this stage." Loom sees that `review` references
`extract.output.*` and infers the dependency: `extract` must finish
before `review` starts.

The `summarize` stage reads from both `extract` and `review` — it waits
for both to complete. Since `review` already depends on `extract`, the
chain is strictly sequential: extract → review → summarize.

Validate the pipeline:

```bash
loom validate configs/orchestrators/research_review.yaml
```

### Step 4: Test the pipeline in Workshop

Open Workshop and navigate to the Pipeline List. Click
`research_review` to open the pipeline editor. You'll see the
dependency graph — three stages in a straight line.

To test, you can submit a goal through the pipeline editor or via CLI:

```bash
loom submit "Review this paper" \
    --context text="<paste abstract here>" \
    --context domain="public health"
```

The output from `summarize` is a complete review report with verdict,
strong and weak claims, key concerns, and a narrative report.

### Step 5: Evaluate each stage independently

The pipeline runs end-to-end, but you should evaluate each worker
separately. If the final report is bad, you need to know *which stage*
produced the problem:

- Did the extractor miss a claim? → Fix the extractor prompt.
- Did the reviewer misjudge methodology strength? → Fix the reviewer.
- Did the summarizer produce a misleading verdict? → Fix the summarizer.

Create eval suites for the methodology reviewer and summarizer the
same way you did for the claim extractor in Phase 1. Test each worker
in isolation in Workshop before relying on the pipeline.

---

## Phase 3: Blind Adversarial Review

Phases 1 and 2 give you automated extraction and review. But there's a
structural problem: the methodology reviewer reads the same claims that
the extractor produced. If the extractor framed a weak claim favorably,
the reviewer is primed to accept that framing.

Phase 3 fixes this with Loom's blind audit pattern — the same approach
used in the [Adversarial Review](../BLIND_AUDIT.md) guide, applied to
research review.

### What you're building

```text
  claim_extractor ──┬──► methodology_reviewer ──┐
                    │                            ├──► review_synthesizer
                    └──► neutralizer ──► blind_reviewer ──┘
                         (strips framing)   (no domain knowledge)
```

Two review paths run in parallel:

- The **sighted path** (methodology reviewer) evaluates claims with full
  context
- The **blind path** (neutralizer → blind reviewer) strips the original
  framing and evaluates from first principles

A **review synthesizer** merges both reports, explicitly flagging where
the sighted and blind reviewers disagree. Those disagreements are the
most valuable output — they're where the original framing may have hidden
a weakness.

### Loom concepts introduced

- **Knowledge silos** — the blind reviewer has an empty `knowledge_silos`
  list. It cannot access domain-specific reference material.
- **Terminology neutralizer** — a worker that strips loaded academic
  language so the blind reviewer isn't primed by disciplinary framing
- **Parallel pipeline branches** — the sighted and blind paths run
  simultaneously since neither depends on the other
- **Synthesis** — a final worker merges parallel results into one report

### Step 1: Create the terminology neutralizer

Copy the Phase 3 configs:

```bash
cp examples/research-review/phase-3/workers/*.yaml configs/workers/
cp examples/research-review/phase-3/orchestrators/*.yaml configs/orchestrators/
```

Open `configs/workers/terminology_neutralizer.yaml`. This worker
rewrites claims in plain language, preserving all factual content while
removing:

- Discipline-specific jargon ("statistically significant" → "the
  statistical test indicates this is unlikely to be random")
- Hedging that minimizes limitations ("somewhat" → removed)
- Framing that presupposes conclusions ("as expected" → removed)
- Rhetorical emphasis ("critically", "notably" → removed)

The output includes `framing_flags` — specific phrases that were
neutralized. These flags feed into the final synthesizer so it can
assess whether loaded language affected the sighted review.

Test it in Workshop: paste the claims output from Phase 1 and check
whether the neutralized versions preserve all the numbers and
measurements while stripping the evaluative language.

### Step 2: Create the blind reviewer

Open `configs/workers/blind_reviewer.yaml`. Two things make this
worker "blind":

1. **`knowledge_silos: []`** — explicitly empty. No domain reference
   material is injected into its prompt.
2. **Its input mapping only provides neutralized claims.** It never
   sees the original text, the paper's title, or the authors' framing.

The prompt tells it to evaluate from first principles: does the logic
hold? Does the evidence support the claim? What alternative
interpretations could explain the same data?

The most important output field is `alternative_interpretations` —
explanations that the original paper didn't consider. Because the
blind reviewer doesn't know the field's conventions, it's more likely
to propose interpretations that domain experts would overlook or
dismiss as "not how we do things."

### Step 3: Create the review synthesizer

Open `configs/workers/review_synthesizer.yaml`. This worker replaces
the Phase 2 `review_summarizer` — it merges two independent reviews
instead of one.

The key output fields are `agreements` (where both reviewers concur)
and `disagreements` (where they diverge). Each disagreement includes
`likely_cause` — why the reviewers reached different conclusions — and
`resolution` — which assessment is more defensible.

The prompt also checks for `framing_effects`: cases where the loaded
language flagged by the neutralizer may have biased the sighted
review's judgment.

### Step 4: Update the pipeline

Open `configs/orchestrators/research_review_blind.yaml`. The pipeline
now has five stages with parallel branches:

```yaml
# After extract, two paths run IN PARALLEL:
- name: "sighted_review"         # Path A: sighted
  input_mapping:
    text: "goal.context.text"     # Gets original text
    claims: "extract.output.claims"

- name: "neutralize"             # Path B: blind (step 1)
  input_mapping:
    claims: "extract.output.claims"

- name: "blind_review"           # Path B: blind (step 2)
  input_mapping:
    neutralized_claims: "neutralize.output.neutralized_claims"
```

Loom sees that `sighted_review` and `neutralize` both depend only on
`extract` — not on each other. They run concurrently. `blind_review`
waits for `neutralize`. `synthesize` waits for everything.

Validate:

```bash
loom validate configs/orchestrators/research_review_blind.yaml
```

### Step 5: Compare sighted vs. blind results

Run the pipeline on one of the sample abstracts and examine the
`synthesize` output. Look at the `disagreements` array:

- Does the blind reviewer flag logical gaps the sighted reviewer
  accepted?
- Does the sighted reviewer defend claims that the blind reviewer
  calls "weak"?
- Do the `framing_effects` connect loaded language to specific sighted
  review assessments?

The disagreements are the most valuable output. They don't mean the
sighted review is wrong — they mean there's something worth a human
looking at. The pipeline surfaces these points; the human decides.

---

## What's Next

You now have a five-worker pipeline that extracts claims, reviews them
from two independent perspectives, and synthesizes the results. Here are
two directions to push it further:

### Idea 1: Multi-Model Comparison

Run the blind reviewer on all three model tiers — local, standard, and
frontier — and compare where they agree and disagree. This surfaces
model-specific biases: a local model might miss subtle logical gaps
that a frontier model catches, but it might also flag "issues" that
are actually fine.

In practice: duplicate the blind reviewer stage three times in the
pipeline, each targeting a different tier. The synthesizer then has
three independent reviews to merge. Where all three agree on a problem,
you have high confidence. Where they disagree, you have something
worth investigating.

This is a natural use of Loom's tier system — the infrastructure for
running the same prompt against different models already exists.

### Idea 2: Batch Processing with RAG

Ingest a collection of papers into Loom's vector store, then run the
review pipeline on each one. After individual reviews are complete,
use a goal-decomposition orchestrator to synthesize cross-paper findings:
"What methodological patterns appear across these 20 papers? Where do
multiple papers make conflicting claims?"

This requires:

- A custom ingestor (or use the CSV/text ingestor from the Document
  Intake example) to feed papers into the RAG pipeline
- An orchestrator config with a synthesis goal
- A larger knowledge silo for the cross-paper analyst

This moves you from "reviewing one paper" to "reviewing a literature" —
the kind of work that takes a human researcher weeks and that no single
LLM conversation can hold in context.

---

*This tutorial uses the example configs in `examples/research-review/`.
Each phase directory contains the complete working configs for that phase
— you can copy them directly or build them step by step following the
walkthrough above.*
