# Why Heddle

## The Input Layer Problem

The value of AI for professional work doesn't live in the model. Every
frontier model has already ingested the entire internet. Claude knows what
a good analysis looks like. So does GPT, Gemini, and every other frontier
model. The model's knowledge was never the constraint.

The constraint is the **input layer**: your ability to encode what you
know — the priorities, the edge cases, the decision sequences, the
domain-specific reasoning — into instructions precise enough that a
literal-minded machine can act on them without guessing.

A vague prompt produces the average of everything the model has seen. A
precise prompt, one that closes off every path except the one you want,
produces work that looks like it came from someone who knows what they're
doing. The difference is entirely in the input.

## What Most Tools Get Wrong

Most AI tools and frameworks optimize the **output layer** — fine-tuning
models on domain corpora, wrapping APIs with retrieval pipelines, building
vertical SaaS products that charge per seat for access to a specialized
model. The assumption: if we train the model on enough contracts (or medical
records, or intelligence reports), the outputs will be good enough that the
human can step back.

This doesn't work. Not because the technology is bad, but because the
bottleneck was never the model's knowledge. The bottleneck is the process:
the sequence of decisions someone makes when working through a problem.
What to look at first. What to weigh heavily. What edge cases to check.
That process is invisible in the finished product — you can't reconstruct
it by training on outputs. It has to be explicitly encoded by someone who
understands the domain and how to communicate with the model.

The same error shows up at every level:

- **Prompt template marketplaces** sell pre-made prompts that stop
  working the moment you need them for anything real. Good prompts don't
  generalize because the judgment baked into them is specific to the
  situation.

- **Vertical AI wrappers** fine-tune models on domain documents and charge
  premium prices for access. But the model already knew the domain — the
  missing ingredient was the human's process, not the model's knowledge.

- **Multi-agent frameworks** (CrewAI, AutoGen, LangGraph) provide
  orchestration infrastructure but leave the input layer entirely to the
  user. They solve the plumbing problem. The input layer problem is
  untouched.

## What Heddle Does Differently

Heddle is infrastructure for the input layer. It gives you a system for
encoding what you know into AI instructions that are validated, testable,
version-tracked, and composable — whether you're a researcher building
analytical pipelines or a teacher grading essays.

### Worker configs are skill files

A Heddle worker config is a YAML file containing a system prompt, typed
input/output contracts, model tier selection, and knowledge access rules.
No Python code needed. This is the equivalent of what practitioners who
go deep with AI call "skill files" — reusable documents encoding
process knowledge. The difference: Heddle's are structurally validated
(the system catches malformed instructions before they run), version-tracked
(every edit is preserved), and testable (you can run evaluation suites
against them and measure whether a change made things better or worse).

### Workshop is the compounding flywheel

People who build effective AI skill files describe a reinforcement loop:
run the instructions, notice what worked and what didn't, update the
instructions, repeat. Over many iterations, the skill file accumulates
decisions about what works.

Heddle's Workshop systematizes this loop. Instead of noticing problems by
feel and editing a markdown file, you:

1. Define test cases with expected outputs
2. Run evaluation suites with scoring (field match, exact match, or LLM-as-judge)
3. Set golden dataset baselines
4. Detect regressions when you change a prompt
5. Compare worker versions side by side

The refinement loop becomes measurable. Your judgment still drives the
process — the Workshop just makes it visible whether your latest edit
actually improved things.

### Blind audit prevents the abdication trap

The most common failure mode with AI: shipping output without genuine
review. The human asks the AI to do the thinking, takes whatever comes
back, and acts on it. The results range from embarrassing to catastrophic.

Heddle's blind audit pattern is an architectural solution. Workers designated
as "blind" (for audit or adversarial review) are prevented from accessing
the data they're evaluating — they literally don't have the knowledge silo.
They can't conform to the analytical frame because they can't see it. A
terminology neutralizer strips loaded language before the blind reviewer
ever sees the content. The result: genuine adversarial evaluation, not
the pseudo-confirmatory review you get when the same model (or the same
human) reviews its own work.

### Config-driven means anyone can build

Most AI frameworks require Python fluency to do anything useful. Heddle's
workers are defined entirely in YAML. System prompt, input/output schema,
model tier, knowledge access — all configuration. The interactive
scaffolding (`heddle new worker`, `heddle new pipeline`) generates valid YAML
from guided prompts. The Workshop provides a visual interface for testing
and evaluation. You can build, test, and iterate on workers without
writing code.

---

## When to Use Heddle (and When Not To)

**Heddle is a good fit when:**

- You want more from AI than a single prompt can deliver
- Multiple steps need to work together (extract → classify → summarize)
- You want to measure whether AI output is actually getting better as you iterate
- You need to classify, summarize, extract from, or review a batch of documents
- You want a second AI to check the first one's work (blind audit)
- The people building the workflows aren't software engineers
- Work needs to be reproducible and explainable

**Some concrete examples:**

- Classify and summarize 300 public comment emails on a zoning proposal
- Grade free-response essays against a rubric, then check for grading bias
- Extract claims from research papers and flag contradictions
- Compare how different AI models answer the same set of questions
- Build an analytical pipeline with genuine adversarial review

**Heddle is probably not what you need when:**

- You need a chatbot or conversational interface
- Your use case is a single prompt with no pipeline logic
- You're building a consumer-facing SaaS product (Heddle is infrastructure, not a product)
- You need real-time streaming responses to end users
- A simple Python script calling an API would solve the problem

## Heddle vs. Other Frameworks

| | Heddle | LangChain / LangGraph | CrewAI | AutoGen | Python script |
|---|---|---|---|---|---|
| **Config-driven** | Workers defined in YAML, no code needed | Code-first (Python) | Code-first (Python) | Code-first (Python) | Code-first |
| **Built-in evaluation** | Workshop with scoring, baselines, regression detection | External tools needed | No built-in eval | No built-in eval | Write your own |
| **Knowledge silos** | Enforced per-worker, blind audit support | Not enforced | Not enforced | Not enforced | N/A |
| **Statelessness** | Architectural — workers reset after every task | Optional, not enforced | Agents carry state | Agents carry state | Up to you |
| **Progressive disclosure** | CLI → Workshop → NATS (use only what you need) | Must understand the framework upfront | Must understand agents/tasks upfront | Must understand agents/conversations upfront | N/A |
| **Message bus** | NATS (real decoupling, horizontal scaling) | In-process | In-process | In-process | In-process |
| **MCP-native** | Single YAML config → MCP server | Requires custom integration | Not supported | Not supported | Build from scratch |
| **Testing without infra** | Workshop runs without NATS | Requires full setup | Requires full setup | Requires full setup | No infrastructure to begin with |

The honest answer: if your use case is a single LLM call with some prompt
engineering, you don't need a framework at all. Write a Python script.
Frameworks earn their keep when you have multiple steps that need to work
together reliably, when you need to test and measure output quality
systematically, or when the people building the workflows aren't software
engineers.

---

## Further Reading

- **[Concepts](CONCEPTS.md)** — how Heddle works, in plain language
- **[Getting Started](GETTING_STARTED.md)** — install and get your first result
- **[Workshop Tour](WORKSHOP_TOUR.md)** — the evaluation and testing UI
- **[Workers Reference](workers-reference.md)** — six shipped workers ready to use
