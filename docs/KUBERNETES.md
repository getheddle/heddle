# Kubernetes Deployment

**Loom — Lightweight Orchestrated Operational Mesh**

---

## Overview

Loom ships with Kubernetes manifests in `k8s/` that are ready for Minikube.
The manifests deploy NATS, Redis, the router, an orchestrator, and worker
pods into a dedicated `loom` namespace.

---

## Minikube Deployment

### Start Minikube

```bash
minikube start --cpus=4 --memory=8192 --driver=docker
eval $(minikube docker-env)
```

### Build Container Images

Build images inside Minikube's Docker daemon so they're available to pods
without a registry:

```bash
docker build -f Dockerfile.worker -t loom-worker:latest .
docker build -f Dockerfile.router -t loom-router:latest .
docker build -f Dockerfile.orchestrator -t loom-orchestrator:latest .
```

### Create Namespace and Secrets

```bash
kubectl create namespace loom
kubectl create secret generic loom-secrets \
  --namespace loom \
  --from-literal=anthropic-api-key="$ANTHROPIC_API_KEY"
```

### Deploy

```bash
kubectl apply -k k8s/
kubectl get pods -n loom -w
```

---

## Manifest Structure

```
k8s/
├── namespace.yaml              # loom namespace
├── nats-deployment.yaml        # NATS server
├── redis-deployment.yaml       # Redis server
├── router-deployment.yaml      # Loom router
├── orchestrator-deployment.yaml # Loom orchestrator
├── worker-deployment.yaml      # Loom worker(s)
└── kustomization.yaml          # Kustomize overlay
```

---

## Ollama on Mac with Minikube

For local LLM inference, run Ollama natively on the host and point workers to
the host address:

```bash
# On host
ollama serve &

# In worker config or environment
OLLAMA_URL=http://host.minikube.internal:11434
```

---

## Environment Variables

Workers, router, and orchestrator containers use the following environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `WORKER_CONFIG` | Workers | Path to worker YAML config |
| `MODEL_TIER` | Workers | Model tier (local, standard, frontier) |
| `NATS_URL` | All | NATS server URL |
| `OLLAMA_URL` | Optional | Ollama API endpoint |
| `ANTHROPIC_API_KEY` | Optional | Anthropic API key (from secret) |
| `FRONTIER_MODEL` | Optional | Model name for frontier tier |

---

*For local development setup, see [Getting Started](GETTING_STARTED.md).
For architecture details, see [Architecture](ARCHITECTURE.md).*
