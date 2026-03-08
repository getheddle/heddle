# LOOM — Lightweight Orchestrated Operational Mesh

Actor-based multi-LLM agent framework.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         LOOM                                │
│                                                             │
│  ┌──────────┐    ┌─────────────────────────────────────┐    │
│  │   CLI /  │───>│         NATS Message Bus             │    │
│  │   API    │    │  loom.goals.*  loom.tasks.*          │    │
│  └──────────┘    │  loom.results.*  loom.control.*      │    │
│                  └───┬──────────┬──────────┬────────────┘    │
│                      │          │          │                 │
│              ┌───────v──┐  ┌───v────┐  ┌──v───────────┐    │
│              │ORCHESTRA- │  │ ROUTER │  │   WORKERS    │    │
│              │  TOR      │  │(determ-│  │              │    │
│              │           │  │inistic)│  │ ┌──────────┐ │    │
│              │ Decomposes│  │        │  │ │Summarizer│ │    │
│              │ goals into│  │ Routes │  │ │ (local)  │ │    │
│              │ subtasks  │  │ tasks  │  │ └──────────┘ │    │
│              │           │  │ by tier│  │ ┌──────────┐ │    │
│              │ Synthesiz-│  │ & type │  │ │Classifier│ │    │
│              │ es results│  │        │  │ │ (local)  │ │    │
│              │           │  └────────┘  │ └──────────┘ │    │
│              │ Self-     │              │ ┌──────────┐ │    │
│              │ checkpts  │              │ │Extractor │ │    │
│              │     │     │              │ │(standard)│ │    │
│              └─────┼─────┘              │ └──────────┘ │    │
│                    │                    └──────────────┘    │
│              ┌─────v─────┐                                  │
│              │   Redis   │     ┌───────────────────────┐    │
│              │Checkpoints│     │   LLM Backends        │    │
│              └───────────┘     │  ┌───────┐ ┌────────┐│    │
│                                │  │Ollama │ │Claude  ││    │
│                                │  │(local)│ │  API   ││    │
│                                │  └───────┘ └────────┘│    │
│                                └───────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Components

- **Workers** — Stateless, narrowly-scoped LLM actors that process a single task and reset. Each has a fixed system prompt, a scoped knowledge context, and strict structured I/O contracts.
- **Orchestrators** — Longer-lived LLM actors that decompose complex goals into subtasks, route them to workers via a message queue, synthesize results, and perform periodic self-summarization checkpoints.
- **Router** — A deterministic (non-LLM) component that inspects task metadata and routes messages to the appropriate model backend based on configurable rules.
- **Message Bus** — NATS (single binary, zero dependencies) handles all inter-actor communication.
- **Checkpoint Store** — Redis for orchestrator state snapshots and summarization checkpoints.

## Local Setup (Mac / Minikube)

### Prerequisites

```bash
# Install Minikube and kubectl
brew install minikube kubectl

# Start Minikube with enough resources
minikube start --cpus=4 --memory=8192 --driver=docker

# Point Docker CLI to Minikube's Docker daemon
eval $(minikube docker-env)
```

### Build and Deploy

```bash
# Build container images (inside Minikube's Docker)
docker build -f Dockerfile.worker -t loom-worker:latest .
docker build -f Dockerfile.router -t loom-router:latest .
docker build -f Dockerfile.orchestrator -t loom-orchestrator:latest .

# Create the API key secret
kubectl create namespace loom
kubectl create secret generic loom-secrets \
  --namespace loom \
  --from-literal=anthropic-api-key="YOUR_KEY_HERE"

# Deploy everything
kubectl apply -k k8s/

# Verify pods are running
kubectl get pods -n loom -w

# View logs
kubectl logs -n loom -l app=loom-router -f
kubectl logs -n loom -l app=loom-worker -f
kubectl logs -n loom -l app=loom-orchestrator -f
```

### Test with CLI

```bash
# Port-forward NATS for local CLI access
kubectl port-forward -n loom svc/nats 4222:4222 &

# Submit a test goal
loom submit "Summarize the key themes in the following text: ..." --nats-url nats://localhost:4222

# Monitor NATS subjects
# Install nats CLI: brew tap nats-io/nats-tools && brew install nats-io/nats-tools/nats
nats sub "loom.>" --server=nats://localhost:4222
```

### Running Ollama on Host (Recommended for Mac)

Running Ollama inside Minikube on Mac is slow because there's no GPU passthrough. Better approach:

```bash
# Install and run Ollama natively on Mac
brew install ollama
ollama serve &
ollama pull llama3.2:3b

# In your worker env vars, point to host:
# OLLAMA_URL=http://host.minikube.internal:11434
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run unit tests (no infrastructure needed)
pytest tests/test_messages.py tests/test_contracts.py -v

# Lint
ruff check src/
```
