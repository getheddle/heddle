# Kubernetes Deployment

**Loom — Lightweight Orchestrated Operational Mesh**

---

## Overview

Loom ships with Kubernetes manifests in `k8s/` that are ready for Minikube.
The manifests deploy NATS, Valkey, the router, an orchestrator, and worker
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
docker build -f docker/Dockerfile.worker -t loom-worker:latest .
docker build -f docker/Dockerfile.router -t loom-router:latest .
docker build -f docker/Dockerfile.orchestrator -t loom-orchestrator:latest .
docker build -f docker/Dockerfile.workshop -t loom-workshop:latest .
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

### Access Workshop

The Workshop is exposed via NodePort on port 30080:

```bash
# Minikube
minikube service loom-workshop -n loom

# Or access directly
open http://$(minikube ip):30080
```

---

## Manifest Structure

```text
k8s/
├── namespace.yaml              # loom namespace
├── nats-deployment.yaml        # NATS server
├── redis-deployment.yaml       # Valkey server
├── router-deployment.yaml      # Loom router
├── orchestrator-deployment.yaml # Loom orchestrator
├── worker-deployment.yaml      # Loom worker(s)
├── workshop-deployment.yaml    # Loom Workshop web UI (NodePort 30080)
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

## Resource Requests and Limits

Configure resource requests and limits for each component type:

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Router | 100m | 500m | 128Mi | 256Mi |
| Orchestrator | 200m | 1000m | 256Mi | 512Mi |
| Worker (local) | 200m | 1000m | 256Mi | 512Mi |
| Worker (standard) | 100m | 500m | 128Mi | 256Mi |
| NATS | 100m | 500m | 128Mi | 256Mi |
| Valkey | 100m | 500m | 128Mi | 256Mi |

Workers with local LLM backends (Ollama) need more resources because they
proxy API calls. Workers using remote APIs (Anthropic) are lighter.

Example in a deployment spec:

```yaml
resources:
  requests:
    cpu: "200m"
    memory: "256Mi"
  limits:
    cpu: "1000m"
    memory: "512Mi"
```

---

## Health Checks

Loom actors are long-running async processes. Use liveness and readiness
probes to detect stuck or unresponsive actors:

```yaml
livenessProbe:
  exec:
    command: ["python", "-c", "import sys; sys.exit(0)"]
  initialDelaySeconds: 10
  periodSeconds: 30
  failureThreshold: 3
readinessProbe:
  exec:
    command: ["python", "-c", "import sys; sys.exit(0)"]
  initialDelaySeconds: 5
  periodSeconds: 10
```

For the router and orchestrator, consider adding NATS connectivity checks
as part of the liveness probe.

---

## Horizontal Scaling

Loom actors scale horizontally via NATS queue groups with zero code changes.
Multiple replicas of the same actor type automatically load-balance.

```bash
# Scale workers manually
kubectl scale deployment/loom-worker --replicas=5 -n loom
```

### HPA Auto-Scaling

Use Horizontal Pod Autoscaler for CPU-based scaling:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: loom-worker-hpa
  namespace: loom
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: loom-worker
  minReplicas: 1
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

Pipeline orchestrators also support concurrent goal processing via
`max_concurrent_goals` in config, which can complement horizontal scaling.

---

## Persistent Volumes

Valkey requires persistent storage for checkpoint data:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: redis-data
  namespace: loom
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
```

Mount the PVC in the Valkey deployment's pod spec:

```yaml
volumes:
  - name: redis-data
    persistentVolumeClaim:
      claimName: redis-data
containers:
  - name: redis
    volumeMounts:
      - name: redis-data
        mountPath: /data
```

---

*For local development setup, see [Getting Started](GETTING_STARTED.md).
For architecture details, see [Architecture](ARCHITECTURE.md).*
