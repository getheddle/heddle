# Troubleshooting

Common issues and solutions when running Loom.

---

## NATS Connection

### Cannot connect to NATS

**Symptom:** Actor exits immediately with `bus.connected` never appearing in logs, or error `Could not connect to server`.

**Fix:**
```bash
# Check if NATS is running
nats-server --version  # Should print version
curl -s http://localhost:8222/varz | head -5  # NATS monitoring endpoint

# Start NATS via Docker (quickest)
docker run -d --name nats -p 4222:4222 -p 8222:8222 nats:latest

# Or via Homebrew (macOS)
brew install nats-server
nats-server &

# Or via Docker Compose (full stack)
docker compose up -d
```

### NATS connection drops intermittently

**Symptom:** Log shows `bus.disconnected` followed by `bus.reconnected` (or actor crash after 60s of retries).

**Fix:**
- Check NATS server resource usage (`nats-server` memory, disk, connections)
- Increase NATS max payload if sending large messages: `nats-server --max_payload 4MB`
- If behind a load balancer, ensure idle timeout exceeds NATS ping interval (default 2 min)
- Check network stability between client and NATS server

### Messages silently dropped

**Symptom:** Tasks published but no worker picks them up. No errors in logs.

**Cause:** NATS uses at-most-once delivery. If no subscriber is listening when a message is published, it is silently dropped.

**Fix:**
- Ensure workers are running *before* publishing tasks
- Start actors in the right order: workers → router → orchestrator/pipeline
- Check that `worker_type` in the task matches the worker's subscription (case-sensitive)
- Check `loom.tasks.dead_letter` for unroutable tasks: `loom dead-letter monitor`

---

## Workers

### Worker produces empty or invalid output

**Symptom:** Worker completes but output doesn't match `output_schema`. Downstream stages fail with validation errors.

**Fix:**
- Check the worker's system prompt — it must instruct the LLM to output valid JSON matching the schema
- Use the Workshop test bench to test the worker in isolation: `loom workshop --port 8080`
- Enable trace logging to see full I/O: `LOOM_TRACE=1 loom worker --config ...`
- Verify the LLM backend is responding correctly (try a direct API call)

### ANTHROPIC_API_KEY not set

**Symptom:** Workers using `standard` or `frontier` tier fail with authentication errors.

**Fix:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Or add to shell profile:
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc
```

### OLLAMA_URL not set / Ollama not running

**Symptom:** Workers using `local` tier fail to connect.

**Fix:**
```bash
# Install and start Ollama
brew install ollama  # macOS
ollama serve &

# Set URL (default is http://localhost:11434)
export OLLAMA_URL=http://localhost:11434

# Pull a model
ollama pull llama3.2
```

### Worker hangs or times out

**Symptom:** Worker never completes. Pipeline shows `PipelineTimeoutError`.

**Fix:**
- Check LLM backend is responsive (try a direct API call)
- Increase `timeout_seconds` in the stage config if the task is legitimately slow
- For Ollama, check if the model is still loading (`ollama ps`)
- Check if the worker is stuck in a tool-use loop (max 10 rounds by default)

---

## Pipelines

### PipelineMappingError: key not found in context

**Symptom:** `Stage 'X' mapping error: Path 'Y.output.Z': key 'Z' not found in context`

**Cause:** A stage's `input_mapping` references a field that the previous stage didn't produce.

**Fix:**
- Check the upstream stage's `output_schema` — does it include the field?
- Test the upstream worker in Workshop to see its actual output
- If the field is optional, add a `condition` to skip the downstream stage when it's missing

### PipelineValidationError: input/output validation failed

**Symptom:** Stage fails before or after execution with schema validation errors.

**Fix:**
- Check `input_schema` / `output_schema` in the stage config
- Use Workshop test bench to verify the worker's actual output format
- Common issue: schema says `"type": "integer"` but worker outputs a string number

### Circular dependency detected

**Symptom:** Pipeline fails to start with `ValueError: Circular dependency detected among stages`.

**Fix:**
- Check `input_mapping` paths — stage A referencing stage B *and* B referencing A creates a cycle
- Use `depends_on` to override automatic dependency inference if needed
- Visualize the dependency graph in Workshop's pipeline editor

---

## Router

### Tasks going to dead letter

**Symptom:** Tasks appear in `loom.tasks.dead_letter` instead of reaching workers.

**Cause:** Router can't find a matching route for the `worker_type` + `model_tier` combination.

**Fix:**
- Check `configs/router_rules.yaml` for tier overrides
- Verify the `worker_type` in the task matches a running worker's config `name`
- Check rate limits — rate-limited tasks may be dead-lettered
- Monitor dead letters: `loom dead-letter monitor --nats-url nats://localhost:4222`

---

## Workshop

### Workshop won't start

**Symptom:** `loom workshop` fails with import errors.

**Fix:**
```bash
# Install workshop dependencies
uv sync --extra workshop

# Or all extras
uv sync --all-extras
```

### App deployment fails

**Symptom:** ZIP upload returns error during app deployment.

**Fix:**
- Verify ZIP contains `manifest.yaml` at the root (not in a subdirectory)
- Check manifest fields: `name`, `version`, `description` are required
- Ensure all config files referenced in `entry_configs` exist in the ZIP
- ZIP must not contain symlinks or paths with `..`
- Build the ZIP using the app's `scripts/build-app.sh` for correct structure

---

## Docker / Kubernetes

### Container can't reach NATS

**Symptom:** Containers fail to connect to `nats://nats:4222`.

**Fix:**
- In Docker Compose: services use the service name as hostname (`nats`)
- Standalone Docker: use `--network host` or link containers
- In Kubernetes: verify the NATS service is in the same namespace
- Check: `docker exec <container> nslookup nats`

### Workshop not accessible from host

**Symptom:** Workshop runs but browser can't reach it.

**Fix:**
- Bind to `0.0.0.0` not `127.0.0.1`: `loom workshop --host 0.0.0.0 --port 8080`
- Docker: expose the port: `-p 8080:8080`
- Kubernetes: use NodePort (30080) or port-forward: `kubectl port-forward svc/loom-workshop 8080:8080`

---

## macOS Service (launchd)

### Services not starting after install

**Fix:**
```bash
# Check service status
launchctl list | grep loom

# Check logs
cat ~/Library/Logs/loom/workshop.err
cat ~/Library/Logs/loom/router.err

# Reload services
launchctl unload ~/Library/LaunchAgents/com.loom.workshop.plist
launchctl load ~/Library/LaunchAgents/com.loom.workshop.plist
```

### Permission denied

**Fix:**
- launchd user agents don't need sudo — run as your user
- If `loom` binary is in a restricted path, move it or adjust the plist

---

## Windows Service (NSSM)

### Services not starting

**Fix:**
```powershell
# Check service status
nssm status LoomWorkshop
nssm status LoomRouter

# Check logs
Get-Content "$env:LOCALAPPDATA\loom\logs\workshop.err"

# Restart
nssm restart LoomWorkshop
```

### NSSM not found

**Fix:**
```powershell
# Install via Chocolatey
choco install nssm

# Or download from https://nssm.cc/download
```

---

## Performance

### Pipeline is slow

**Fix:**
- Design stages with independent dependencies so they run in parallel
- Scale workers horizontally via NATS queue groups (run multiple instances)
- Set `max_concurrent_goals` in pipeline config for concurrent goal processing
- Check token usage logs (`worker.llm_usage`) for expensive stages

### High memory usage

**Fix:**
- Workers are stateless and `reset()` between tasks — check for leaked references
- DuckDB stores can grow large — monitor disk usage
- Dead-letter consumer has a bounded store (default 1000 entries) — adjust `max_size` if needed
- Redis checkpoint store: check TTL settings for expired entries
