# Claude Code Configuration - Claude Flow V3

## 🚨 AUTOMATIC SWARM ORCHESTRATION

**When starting work on complex tasks, Claude Code MUST automatically:**

1. **Initialize the swarm** using CLI tools via Bash
2. **Spawn concurrent agents** using Claude Code's Task tool
3. **Coordinate via hooks** and memory

### 🚨 CRITICAL: CLI + Task Tool in SAME Message

**When user says "spawn swarm" or requests complex work, Claude Code MUST in ONE message:**
1. Call CLI tools via Bash to initialize coordination
2. **IMMEDIATELY** call Task tool to spawn REAL working agents
3. Both CLI and Task calls must be in the SAME response

**CLI coordinates, Task tool agents do the actual work!**

### 🛡️ Anti-Drift Config (PREFERRED)

**Use this to prevent agent drift:**
```bash
npx @claude-flow/cli@latest swarm init --topology hierarchical --max-agents 8 --strategy specialized
```
- **hierarchical**: Coordinator catches divergence
- **max-agents 6-8**: Smaller team = less drift
- **specialized**: Clear roles, no overlap
- **consensus**: raft (leader maintains state)

---

### 🔄 Auto-Start Swarm Protocol (Background Execution)

When the user requests a complex task, **spawn agents in background and WAIT for completion:**

```javascript
// STEP 1: Initialize swarm coordination (anti-drift config)
Bash("npx @claude-flow/cli@latest swarm init --topology hierarchical --max-agents 8 --strategy specialized")

// STEP 2: Spawn ALL agents IN BACKGROUND in a SINGLE message
// Use run_in_background: true so agents work concurrently
Task({
  prompt: "Research requirements, analyze codebase patterns, store findings in memory",
  subagent_type: "researcher",
  description: "Research phase",
  run_in_background: true  // ← CRITICAL: Run in background
})
Task({
  prompt: "Design architecture based on research. Document decisions.",
  subagent_type: "system-architect",
  description: "Architecture phase",
  run_in_background: true
})
Task({
  prompt: "Implement the solution following the design. Write clean code.",
  subagent_type: "coder",
  description: "Implementation phase",
  run_in_background: true
})
Task({
  prompt: "Write comprehensive tests for the implementation.",
  subagent_type: "tester",
  description: "Testing phase",
  run_in_background: true
})
Task({
  prompt: "Review code quality, security, and best practices.",
  subagent_type: "reviewer",
  description: "Review phase",
  run_in_background: true
})

// STEP 3: WAIT - Tell user agents are working, then STOP
// Say: "I've spawned 5 agents to work on this in parallel. They'll report back when done."
// DO NOT check status repeatedly. Just wait for user or agent responses.
```

### ⏸️ CRITICAL: Spawn and Wait Pattern

**After spawning background agents:**

1. **TELL USER** - "I've spawned X agents working in parallel on: [list tasks]"
2. **STOP** - Do not continue with more tool calls
3. **WAIT** - Let the background agents complete their work
4. **RESPOND** - When agents return results, review and synthesize

**Example response after spawning:**
```
I've launched 5 concurrent agents to work on this:
- 🔍 Researcher: Analyzing requirements and codebase
- 🏗️ Architect: Designing the implementation approach
- 💻 Coder: Implementing the solution
- 🧪 Tester: Writing tests
- 👀 Reviewer: Code review and security check

They're working in parallel. I'll synthesize their results when they complete.
```

### 🚫 DO NOT:
- Continuously check swarm status
- Poll TaskOutput repeatedly
- Add more tool calls after spawning
- Ask "should I check on the agents?"

### ✅ DO:
- Spawn all agents in ONE message
- Tell user what's happening
- Wait for agent results to arrive
- Synthesize results when they return

## 🧠 AUTO-LEARNING PROTOCOL

### Before Starting Any Task
```bash
# 1. Search memory for relevant patterns from past successes
Bash("npx @claude-flow/cli@latest memory search --query '[task keywords]' --namespace patterns")

# 2. Check if similar task was done before
Bash("npx @claude-flow/cli@latest memory search --query '[task type]' --namespace tasks")

# 3. Load learned optimizations
Bash("npx @claude-flow/cli@latest hooks route --task '[task description]'")
```

### After Completing Any Task Successfully
```bash
# 1. Store successful pattern for future reference
Bash("npx @claude-flow/cli@latest memory store --namespace patterns --key '[pattern-name]' --value '[what worked]'")

# 2. Train neural patterns on the successful approach
Bash("npx @claude-flow/cli@latest hooks post-edit --file '[main-file]' --train-neural true")

# 3. Record task completion with metrics
Bash("npx @claude-flow/cli@latest hooks post-task --task-id '[id]' --success true --store-results true")

# 4. Trigger optimization worker if performance-related
Bash("npx @claude-flow/cli@latest hooks worker dispatch --trigger optimize")
```

### Continuous Improvement Triggers

| Trigger | Worker | When to Use |
|---------|--------|-------------|
| After major refactor | `optimize` | Performance optimization |
| After adding features | `testgaps` | Find missing test coverage |
| After security changes | `audit` | Security analysis |
| After API changes | `document` | Update documentation |
| Every 5+ file changes | `map` | Update codebase map |
| Complex debugging | `deepdive` | Deep code analysis |

### Memory-Enhanced Development

**ALWAYS check memory before:**
- Starting a new feature (search for similar implementations)
- Debugging an issue (search for past solutions)
- Refactoring code (search for learned patterns)
- Performance work (search for optimization strategies)

**ALWAYS store in memory after:**
- Solving a tricky bug (store the solution pattern)
- Completing a feature (store the approach)
- Finding a performance fix (store the optimization)
- Discovering a security issue (store the vulnerability pattern)

### 📋 Agent Routing (Anti-Drift)

| Code | Task | Agents |
|------|------|--------|
| 1 | Bug Fix | coordinator, researcher, coder, tester |
| 3 | Feature | coordinator, architect, coder, tester, reviewer |
| 5 | Refactor | coordinator, architect, coder, reviewer |
| 7 | Performance | coordinator, perf-engineer, coder |
| 9 | Security | coordinator, security-architect, auditor |
| 11 | Docs | researcher, api-docs |

**Codes 1-9: hierarchical/specialized (anti-drift). Code 11: mesh/balanced**

### 🎯 Task Complexity Detection

**AUTO-INVOKE SWARM when task involves:**
- Multiple files (3+)
- New feature implementation
- Refactoring across modules
- API changes with tests
- Security-related changes
- Performance optimization
- Database schema changes

**SKIP SWARM for:**
- Single file edits
- Simple bug fixes (1-2 lines)
- Documentation updates
- Configuration changes
- Quick questions/exploration

## 🚨 CRITICAL: CONCURRENT EXECUTION & FILE MANAGEMENT

**ABSOLUTE RULES**:
1. ALL operations MUST be concurrent/parallel in a single message
2. **NEVER save working files, text/mds and tests to the root folder**
3. ALWAYS organize files in appropriate subdirectories
4. **USE CLAUDE CODE'S TASK TOOL** for spawning agents concurrently, not just MCP

### ⚡ GOLDEN RULE: "1 MESSAGE = ALL RELATED OPERATIONS"

**MANDATORY PATTERNS:**
- **TodoWrite**: ALWAYS batch ALL todos in ONE call (5-10+ todos minimum)
- **Task tool (Claude Code)**: ALWAYS spawn ALL agents in ONE message with full instructions
- **File operations**: ALWAYS batch ALL reads/writes/edits in ONE message
- **Bash commands**: ALWAYS batch ALL terminal operations in ONE message
- **Memory operations**: ALWAYS batch ALL memory store/retrieve in ONE message

### 📁 File Organization Rules

**NEVER save to root folder. Use these directories:**
- `/src` - Source code files
- `/tests` - Test files
- `/docs` - Documentation and markdown files
- `/config` - Configuration files
- `/scripts` - Utility scripts
- `/examples` - Example code

## Project Config (Anti-Drift Defaults)

- **Topology**: hierarchical (prevents drift)
- **Max Agents**: 8 (smaller = less drift)
- **Strategy**: specialized (clear roles)
- **Consensus**: raft
- **Memory**: hybrid
- **HNSW**: Enabled
- **Neural**: Enabled

## 🚀 V3 CLI Commands (26 Commands, 140+ Subcommands)

### Core Commands

| Command | Subcommands | Description |
|---------|-------------|-------------|
| `init` | 4 | Project initialization with wizard, presets, skills, hooks |
| `agent` | 8 | Agent lifecycle (spawn, list, status, stop, metrics, pool, health, logs) |
| `swarm` | 6 | Multi-agent swarm coordination and orchestration |
| `memory` | 11 | AgentDB memory with vector search (150x-12,500x faster) |
| `mcp` | 9 | MCP server management and tool execution |
| `task` | 6 | Task creation, assignment, and lifecycle |
| `session` | 7 | Session state management and persistence |
| `config` | 7 | Configuration management and provider setup |
| `status` | 3 | System status monitoring with watch mode |
| `workflow` | 6 | Workflow execution and template management |
| `hooks` | 17 | Self-learning hooks + 12 background workers |
| `hive-mind` | 6 | Queen-led Byzantine fault-tolerant consensus |

### Advanced Commands

| Command | Subcommands | Description |
|---------|-------------|-------------|
| `daemon` | 5 | Background worker daemon (start, stop, status, trigger, enable) |
| `neural` | 5 | Neural pattern training (train, status, patterns, predict, optimize) |
| `security` | 6 | Security scanning (scan, audit, cve, threats, validate, report) |
| `performance` | 5 | Performance profiling (benchmark, profile, metrics, optimize, report) |
| `providers` | 5 | AI providers (list, add, remove, test, configure) |
| `plugins` | 5 | Plugin management (list, install, uninstall, enable, disable) |
| `deployment` | 5 | Deployment management (deploy, rollback, status, environments, release) |
| `embeddings` | 4 | Vector embeddings (embed, batch, search, init) - 75x faster with agentic-flow |
| `claims` | 4 | Claims-based authorization (check, grant, revoke, list) |
| `migrate` | 5 | V2 to V3 migration with rollback support |
| `doctor` | 1 | System diagnostics with health checks |
| `completions` | 4 | Shell completions (bash, zsh, fish, powershell) |

### Quick CLI Examples

```bash
# Initialize project
npx @claude-flow/cli@latest init --wizard

# Start daemon with background workers
npx @claude-flow/cli@latest daemon start

# Spawn an agent
npx @claude-flow/cli@latest agent spawn -t coder --name my-coder

# Initialize swarm
npx @claude-flow/cli@latest swarm init --v3-mode

# Search memory (HNSW-indexed)
npx @claude-flow/cli@latest memory search --query "authentication patterns"

# System diagnostics
npx @claude-flow/cli@latest doctor --fix

# Security scan
npx @claude-flow/cli@latest security scan --depth full

# Performance benchmark
npx @claude-flow/cli@latest performance benchmark --suite all
```

## 🚀 Available Agents (60+ Types)

### Core Development
`coder`, `reviewer`, `tester`, `planner`, `researcher`

### V3 Specialized Agents
`security-architect`, `security-auditor`, `memory-specialist`, `performance-engineer`

### 🔐 @claude-flow/security
CVE remediation, input validation, path security:
- `InputValidator` - Zod validation
- `PathValidator` - Traversal prevention
- `SafeExecutor` - Injection protection

### Swarm Coordination
`hierarchical-coordinator`, `mesh-coordinator`, `adaptive-coordinator`, `collective-intelligence-coordinator`, `swarm-memory-manager`

### Consensus & Distributed
`byzantine-coordinator`, `raft-manager`, `gossip-coordinator`, `consensus-builder`, `crdt-synchronizer`, `quorum-manager`, `security-manager`

### Performance & Optimization
`perf-analyzer`, `performance-benchmarker`, `task-orchestrator`, `memory-coordinator`, `smart-agent`

### GitHub & Repository
`github-modes`, `pr-manager`, `code-review-swarm`, `issue-tracker`, `release-manager`, `workflow-automation`, `project-board-sync`, `repo-architect`, `multi-repo-swarm`

### SPARC Methodology
`sparc-coord`, `sparc-coder`, `specification`, `pseudocode`, `architecture`, `refinement`

### Specialized Development
`backend-dev`, `mobile-dev`, `ml-developer`, `cicd-engineer`, `api-docs`, `system-architect`, `code-analyzer`, `base-template-generator`

### Testing & Validation
`tdd-london-swarm`, `production-validator`

## 🪝 V3 Hooks System (27 Hooks + 12 Workers)

### All Available Hooks

| Hook | Description | Key Options |
|------|-------------|-------------|
| `pre-edit` | Get context before editing files | `--file`, `--operation` |
| `post-edit` | Record editing outcome for learning | `--file`, `--success`, `--train-neural` |
| `pre-command` | Assess risk before commands | `--command`, `--validate-safety` |
| `post-command` | Record command execution outcome | `--command`, `--track-metrics` |
| `pre-task` | Record task start, get agent suggestions | `--description`, `--coordinate-swarm` |
| `post-task` | Record task completion for learning | `--task-id`, `--success`, `--store-results` |
| `session-start` | Start/restore session (v2 compat) | `--session-id`, `--auto-configure` |
| `session-end` | End session and persist state | `--generate-summary`, `--export-metrics` |
| `session-restore` | Restore a previous session | `--session-id`, `--latest` |
| `route` | Route task to optimal agent | `--task`, `--context`, `--top-k` |
| `route-task` | (v2 compat) Alias for route | `--task`, `--auto-swarm` |
| `explain` | Explain routing decision | `--topic`, `--detailed` |
| `pretrain` | Bootstrap intelligence from repo | `--model-type`, `--epochs` |
| `build-agents` | Generate optimized agent configs | `--agent-types`, `--focus` |
| `metrics` | View learning metrics dashboard | `--v3-dashboard`, `--format` |
| `transfer` | Transfer patterns via IPFS registry | `store`, `from-project` |
| `list` | List all registered hooks | `--format` |
| `intelligence` | RuVector intelligence system | `trajectory-*`, `pattern-*`, `stats` |
| `worker` | Background worker management | `list`, `dispatch`, `status`, `detect` |
| `progress` | Check V3 implementation progress | `--detailed`, `--format` |
| `statusline` | Generate dynamic statusline | `--json`, `--compact`, `--no-color` |
| `coverage-route` | Route based on test coverage gaps | `--task`, `--path` |
| `coverage-suggest` | Suggest coverage improvements | `--path` |
| `coverage-gaps` | List coverage gaps with priorities | `--format`, `--limit` |
| `pre-bash` | (v2 compat) Alias for pre-command | Same as pre-command |
| `post-bash` | (v2 compat) Alias for post-command | Same as post-command |

### 12 Background Workers

| Worker | Priority | Description |
|--------|----------|-------------|
| `ultralearn` | normal | Deep knowledge acquisition |
| `optimize` | high | Performance optimization |
| `consolidate` | low | Memory consolidation |
| `predict` | normal | Predictive preloading |
| `audit` | critical | Security analysis |
| `map` | normal | Codebase mapping |
| `preload` | low | Resource preloading |
| `deepdive` | normal | Deep code analysis |
| `document` | normal | Auto-documentation |
| `refactor` | normal | Refactoring suggestions |
| `benchmark` | normal | Performance benchmarking |
| `testgaps` | normal | Test coverage analysis |

### Essential Hook Commands

```bash
# Core hooks
npx @claude-flow/cli@latest hooks pre-task --description "[task]"
npx @claude-flow/cli@latest hooks post-task --task-id "[id]" --success true
npx @claude-flow/cli@latest hooks post-edit --file "[file]" --train-neural true

# Session management
npx @claude-flow/cli@latest hooks session-start --session-id "[id]"
npx @claude-flow/cli@latest hooks session-end --export-metrics true
npx @claude-flow/cli@latest hooks session-restore --session-id "[id]"

# Intelligence routing
npx @claude-flow/cli@latest hooks route --task "[task]"
npx @claude-flow/cli@latest hooks explain --topic "[topic]"

# Neural learning
npx @claude-flow/cli@latest hooks pretrain --model-type moe --epochs 10
npx @claude-flow/cli@latest hooks build-agents --agent-types coder,tester

# Background workers
npx @claude-flow/cli@latest hooks worker list
npx @claude-flow/cli@latest hooks worker dispatch --trigger audit
npx @claude-flow/cli@latest hooks worker status

# Coverage-aware routing
npx @claude-flow/cli@latest hooks coverage-gaps --format table
npx @claude-flow/cli@latest hooks coverage-route --task "[task]"

# Statusline (for Claude Code integration)
npx @claude-flow/cli@latest hooks statusline
npx @claude-flow/cli@latest hooks statusline --json
```

## 🔄 Migration (V2 to V3)

```bash
# Check migration status
npx @claude-flow/cli@latest migrate status

# Run migration with backup
npx @claude-flow/cli@latest migrate run --backup

# Rollback if needed
npx @claude-flow/cli@latest migrate rollback

# Validate migration
npx @claude-flow/cli@latest migrate validate
```

## 🧠 Intelligence System (RuVector)

V3 includes the RuVector Intelligence System:
- **SONA**: Self-Optimizing Neural Architecture (<0.05ms adaptation)
- **MoE**: Mixture of Experts for specialized routing
- **HNSW**: 150x-12,500x faster pattern search
- **EWC++**: Elastic Weight Consolidation (prevents forgetting)
- **Flash Attention**: 2.49x-7.47x speedup

The 4-step intelligence pipeline:
1. **RETRIEVE** - Fetch relevant patterns via HNSW
2. **JUDGE** - Evaluate with verdicts (success/failure)
3. **DISTILL** - Extract key learnings via LoRA
4. **CONSOLIDATE** - Prevent catastrophic forgetting via EWC++

## 📦 Embeddings Package (v3.0.0-alpha.12)

Features:
- **sql.js**: Cross-platform SQLite persistent cache (WASM, no native compilation)
- **Document chunking**: Configurable overlap and size
- **Normalization**: L2, L1, min-max, z-score
- **Hyperbolic embeddings**: Poincaré ball model for hierarchical data
- **75x faster**: With agentic-flow ONNX integration
- **Neural substrate**: Integration with RuVector

## 🐝 Hive-Mind Consensus

### Topologies
- `hierarchical` - Queen controls workers directly
- `mesh` - Fully connected peer network
- `hierarchical-mesh` - Hybrid (recommended)
- `adaptive` - Dynamic based on load

### Consensus Strategies
- `byzantine` - BFT (tolerates f < n/3 faulty)
- `raft` - Leader-based (tolerates f < n/2)
- `gossip` - Epidemic for eventual consistency
- `crdt` - Conflict-free replicated data types
- `quorum` - Configurable quorum-based

## V3 Performance Targets

| Metric | Target |
|--------|--------|
| Flash Attention | 2.49x-7.47x speedup |
| HNSW Search | 150x-12,500x faster |
| Memory Reduction | 50-75% with quantization |
| MCP Response | <100ms |
| CLI Startup | <500ms |
| SONA Adaptation | <0.05ms |

## 📊 Performance Optimization Protocol

### Automatic Performance Tracking
```bash
# After any significant operation, track metrics
Bash("npx @claude-flow/cli@latest hooks post-command --command '[operation]' --track-metrics true")

# Periodically run benchmarks (every major feature)
Bash("npx @claude-flow/cli@latest performance benchmark --suite all")

# Analyze bottlenecks when performance degrades
Bash("npx @claude-flow/cli@latest performance profile --target '[component]'")
```

### Session Persistence (Cross-Conversation Learning)
```bash
# At session start - restore previous context
Bash("npx @claude-flow/cli@latest session restore --latest")

# At session end - persist learned patterns
Bash("npx @claude-flow/cli@latest hooks session-end --generate-summary true --persist-state true --export-metrics true")
```

### Neural Pattern Training
```bash
# Train on successful code patterns
Bash("npx @claude-flow/cli@latest neural train --pattern-type coordination --epochs 10")

# Predict optimal approach for new tasks
Bash("npx @claude-flow/cli@latest neural predict --input '[task description]'")

# View learned patterns
Bash("npx @claude-flow/cli@latest neural patterns --list")
```

## 🔧 Environment Variables

```bash
# Configuration
CLAUDE_FLOW_CONFIG=./claude-flow.config.json
CLAUDE_FLOW_LOG_LEVEL=info

# Provider API Keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# MCP Server
CLAUDE_FLOW_MCP_PORT=3000
CLAUDE_FLOW_MCP_HOST=localhost
CLAUDE_FLOW_MCP_TRANSPORT=stdio

# Memory
CLAUDE_FLOW_MEMORY_BACKEND=hybrid
CLAUDE_FLOW_MEMORY_PATH=./data/memory
```

## 🔍 Doctor Health Checks

Run `npx @claude-flow/cli@latest doctor` to check:
- Node.js version (20+)
- npm version (9+)
- Git installation
- Config file validity
- Daemon status
- Memory database
- API keys
- MCP servers
- Disk space
- TypeScript installation

## 🚀 Quick Setup

```bash
# Add MCP servers (auto-detects MCP mode when stdin is piped)
claude mcp add claude-flow -- npx -y @claude-flow/cli@latest
claude mcp add ruv-swarm -- npx -y ruv-swarm mcp start  # Optional
claude mcp add flow-nexus -- npx -y flow-nexus@latest mcp start  # Optional

# Start daemon
npx @claude-flow/cli@latest daemon start

# Run doctor
npx @claude-flow/cli@latest doctor --fix
```

## 🎯 Claude Code vs CLI Tools

### Claude Code Handles ALL EXECUTION:
- **Task tool**: Spawn and run agents concurrently
- File operations (Read, Write, Edit, MultiEdit, Glob, Grep)
- Code generation and programming
- Bash commands and system operations
- TodoWrite and task management
- Git operations

### CLI Tools Handle Coordination (via Bash):
- **Swarm init**: `npx @claude-flow/cli@latest swarm init --topology <type>`
- **Swarm status**: `npx @claude-flow/cli@latest swarm status`
- **Agent spawn**: `npx @claude-flow/cli@latest agent spawn -t <type> --name <name>`
- **Memory store**: `npx @claude-flow/cli@latest memory store --key "mykey" --value "myvalue" --namespace patterns`
- **Memory search**: `npx @claude-flow/cli@latest memory search --query "search terms"`
- **Memory list**: `npx @claude-flow/cli@latest memory list --namespace patterns`
- **Memory retrieve**: `npx @claude-flow/cli@latest memory retrieve --key "mykey" --namespace patterns`
- **Hooks**: `npx @claude-flow/cli@latest hooks <hook-name> [options]`

## 📝 Memory Commands Reference (IMPORTANT)

### Store Data (ALL options shown)
```bash
# REQUIRED: --key and --value
# OPTIONAL: --namespace (default: "default"), --ttl, --tags
npx @claude-flow/cli@latest memory store --key "pattern-auth" --value "JWT with refresh tokens" --namespace patterns
npx @claude-flow/cli@latest memory store --key "bug-fix-123" --value "Fixed null check" --namespace solutions --tags "bugfix,auth"
```

### Search Data (semantic vector search)
```bash
# REQUIRED: --query (full flag, not -q)
# OPTIONAL: --namespace, --limit, --threshold
npx @claude-flow/cli@latest memory search --query "authentication patterns"
npx @claude-flow/cli@latest memory search --query "error handling" --namespace patterns --limit 5
```

### List Entries
```bash
# OPTIONAL: --namespace, --limit
npx @claude-flow/cli@latest memory list
npx @claude-flow/cli@latest memory list --namespace patterns --limit 10
```

### Retrieve Specific Entry
```bash
# REQUIRED: --key
# OPTIONAL: --namespace (default: "default")
npx @claude-flow/cli@latest memory retrieve --key "pattern-auth"
npx @claude-flow/cli@latest memory retrieve --key "pattern-auth" --namespace patterns
```

### Initialize Memory Database
```bash
npx @claude-flow/cli@latest memory init --force --verbose
```

**KEY**: CLI coordinates the strategy via Bash, Claude Code's Task tool executes with real agents.

## Support

- Documentation: https://github.com/ruvnet/claude-flow
- Issues: https://github.com/ruvnet/claude-flow/issues

---

Remember: **Claude Flow CLI coordinates, Claude Code Task tool creates!**

---

# WiFi DensePose — Project Knowledge Base

## Hardware Setup

### ESP32 CSI Nodes (4x, ceiling-mounted in garage)
Firmware: RunBot CSI Node v0.2.0 (`6a962865-dirty`, compiled 2026-03-16)
All nodes send UDP CSI packets to Mac (192.168.1.132:5005), WiFi channel 6.

| Node | IP | HTTP API | NVS Config |
|------|-----|----------|------------|
| node01 | 192.168.1.137 | http://192.168.1.137:8080 | `firmware/runbot-csi-node-firmware/vendor/ruview-v0.2.0-esp32-release/nvs_config_node01.csv` |
| node02 | 192.168.1.117 | http://192.168.1.117:8080 | `...nvs_config_node02.csv` |
| node03 | 192.168.1.101 | http://192.168.1.101:8080 | `...nvs_config_node03.csv` |
| node04 | 192.168.1.125 | http://192.168.1.125:8080 | `...nvs_config_node04.csv` |

**Node HTTP API endpoints:**
- `GET /api/v1/status` — node health, firmware version, uptime, send_errors
- `POST /api/v1/reboot` — remote reboot (use when nodes stop sending)
- `GET /api/v1/config` — current NVS configuration

**Troubleshooting nodes:**
- If nodes stop sending CSI: reboot all via `POST /api/v1/reboot`
- Normal packet rate: ~22-23 pps per node, ~90 pps total for 4 nodes
- If UDP port 5005 is busy: `lsof -ti :5005 | xargs kill`

### Video Teacher (Pixel 8 Pro)
- App: "IP Camera" (RTSP server)
- RTSP URL: `rtsp://admin:admin@192.168.1.148:8554/live`
- Resolution: 640x480, 30fps, H264+AAC
- Camera mounted on ceiling, image rotated 90 degrees CW
- Check camera: `ffprobe -v quiet -i "rtsp://admin:admin@192.168.1.148:8554/live" -show_entries stream=codec_name -of csv=p=0 -timeout 3000000`

### Mac (data collection host)
- IP: 192.168.1.132
- Python venv: `/Users/arsen/Desktop/wifi-densepose/venv/bin/python3`
- Captures go to: `temp/captures/`
- Keyframes go to: `output/keyframes/`

## Data Capture — Ready-to-Use Scripts

### Quick single capture (with video teacher)
```bash
venv/bin/python3 scripts/run_atomic_csi_training_capture.py \
  --mode teacher_capture \
  --label-prefix "my_session" \
  --step-name "walk_center" \
  --duration-sec 30 \
  --person-count-expected 1 \
  --space-id garage \
  --dataset-epoch garage_ceiling_v2 \
  --geometry-label ceiling_fixed_mount_v2 \
  --video-teacher \
  --video-backend network_rtsp_ffmpeg \
  --video-source-url "rtsp://admin:admin@192.168.1.148:8554/live" \
  --countdown-sec 4
```

### Long background capture (hours, 1-min chunks)
```bash
venv/bin/python3 scripts/long_capture_daemon.py --hours 2 --chunk-sec 60
# Stop: touch /tmp/csi_capture_stop
# Status: tail -f temp/long_capture.log
# PID: cat temp/long_capture.pid
```

### Session 3 pack (12 structured clips with voice prompts)
```bash
bash scripts/run_session3_full_pack.sh
# 3x empty, 3x static, 3x motion, 3x entry/exit
# Voice prompts in Russian (macOS say -v Milena)
```

### Pixel 8 Pro baseline pack (5 clips)
```bash
bash scripts/run_pixel8pro_garage_baseline_pack.sh
```

## Data Files Format

Each capture produces:
- `{label}.ndjson.gz` — CSI packets (ts_ns, src_ip, src_port, payload_b64)
- `{label}.teacher.mp4` — RTSP video (if camera available)
- `{label}.summary.json` — metadata (duration, packet count, sources, person_count_expected)
- `{label}.clip.json` — clip manifest for analysis scripts

CSI payload: IQ pairs as int8, 128 subcarriers. Active bands: indices 6-58 (lo) and 70-122 (hi).

## ML Pipeline — Model History

| Version | Script | Ground Truth | Clips | Windows | Binary BalAcc | 3-class BalAcc | Key Issue |
|---------|--------|-------------|-------|---------|---------------|----------------|-----------|
| V5 | `csi_motion_pipeline_v5.py` | CSI-derived | 38 | 8061 | 0.54 | 0.41 | Circular labeling (CSI labels -> CSI model) |
| V5-cascade | `csi_motion_pipeline_v5_cascade.py` | CSI-derived | 38 | 8061 | — | 0.41 | Same circular problem |
| V6 | `csi_motion_pipeline_v6_framediff.py` | Video frame-diff | 53 | 4599 | 0.50 | 0.32 | Frame-diff unreliable in dark garage |
| V7 | `build_manual_annotations_and_train_v7.py` | Manual human | 7 | 222 | 0.89 | 0.48 | Too few clips, 12 empty windows |
| V8 | `csi_motion_pipeline_v8_full_corpus.py` | Manual+YOLO+all | 27 | 876 | 0.80 | 0.63 | Best generalization with empty_garage data |
| V9 | `csi_motion_pipeline_v9_all_sources.py` | Manual+YOLO+clip.json | 27 | 876 | 0.80 | 0.44 | YOLO motion labels too noisy for 3-class |

**Key lessons:**
- Quality of annotations >> quantity of data. 840 windows with correct labels beat 8000 with noisy ones.
- YOLO is unreliable in dark garage (misses static people, max=6 phantoms). Only trust YOLO for presence, not absence.
- pixel8pro clips have video only (no CSI) — they cannot be used for CSI model training.
- Adding diverse empty-room recordings from different sessions is critical for honest evaluation.
- V8 with `empty_garage_20260317_223236` is the most honest model — binary 0.80 is real generalization.

**Best model**: `output/v8_full_corpus_model_20260317_223719.pkl` (HGB, 40 features, StratifiedGroupKFold)

### Data availability summary
- **27 clips with CSI + annotations** — all in `temp/captures/*.ndjson.gz`
- **24 pixel8pro clips** — VIDEO ONLY, no CSI. Cannot use for CSI training.
- **51 labels with YOLO keyframes** — in `output/keyframes/` + `temp/video_teacher/*.yolo_annotations.csv`
- **1 dedicated empty recording** — `empty_garage_20260317_223236` (3 min, 4 nodes)

### Feature extraction
- 5-second windows, per-node: mean, std, max, range, pps, temporal_var, normalized_mean
- Cross-node: mean_std, mean_range, std_mean, tvar_mean, tvar_max
- Aggregate: agg_mean, agg_std, agg_pps
- Temporal context: delta from previous window
- Total: 40 features

### What works for ground truth (in order of quality)
1. **Manual annotation from keyframes** — best, but slow
2. **Scripted captures** (person_count_expected in summary.json) — good for known scenarios
3. **YOLO detection** — unreliable in dark garage (misses static people, phantom detections)
4. **Frame differencing** — only detects motion, can't distinguish empty vs static person
5. **CSI-derived labels** — NEVER use (circular labeling problem)

## Person Detection in Dark Garage

- **HOG detector**: Failed completely (avg 0.0 persons). Too dark.
- **YOLOv8n**: Unreliable. Detects ~1.9 avg in 4-person scene. Low confidence (0.2-0.4).
- **Frame differencing**: Works for motion detection only. Cannot count people.
- **Manual keyframe review**: Only reliable method. Camera rotated 90 CW, use PiP overlay for verification.

YOLO installed: `venv/bin/python3 -c "import ultralytics"` (v8.4.23)
YOLO script: `scripts/detect_persons_yolo.py --conf 0.2`

## Capture Chronology (2026-03-17)

### Session 1: Multi-person tests (20:10-20:19)
- `three_person_static_test` — 3 people standing still, 22s
- `four_person_static_test` — 4 people standing still, 22s
- `multi_person_freeform` — 3 people walking, 62s
- `multi_person_freeform_long` — 2 people walking, 122s

### Session 2: Long capture (20:30-21:28)
- `longcap_chunk0001-0012` — 12 chunks x 5 min, 1 person freeform
- 425K packets, 4 nodes stable, video OK
- Exit event captured in chunk 9 (person left room)

### Session 3: Short chunks (22:12-22:21)
- `longcap_chunk0001-0009` (221250-222107) — 9 chunks x 1 min
- 47K packets, 4 nodes, video OK chunks 1-7 (phone died chunks 8-9)

### Earlier sessions (2026-03-10 to 2026-03-16)
- `garage_ceiling_v2_*` — 162 clips, various scenarios (1 person)
- `garage_breathing_*` — breathing detection attempts
- `garage_compare_*` — calibration clips
- All stored in `temp/captures/` with .summary.json metadata

## What's Needed Next

1. **More empty room data** — only 12/840 windows are empty. Record 3-5 min of empty garage.
2. **More multi-person data** — only ~160/840 windows have 2+ people. Need structured 2/3/4 person sessions.
3. **Session 3 structured pack** — `run_session3_full_pack.sh` ready but not yet executed.
4. **Better lighting for video teacher** — current single lamp makes YOLO unreliable.
5. **Backend fix** — `v1/src/app.py` broken by another agent's changes (import errors). Low priority.

## Geometry

Space: garage, ceiling-fixed-mount-v2
- 4 ESP32 nodes on ceiling
- Corridor-shaped room
- Door at one end (entry/exit zone)
- Center zone under lamp (most activity)
- Storage area on one side

---

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
Never save working files, text/mds and tests to the root folder.

## 🚨 SWARM EXECUTION RULES (CRITICAL)
1. **SPAWN IN BACKGROUND**: Use `run_in_background: true` for all agent Task calls
2. **SPAWN ALL AT ONCE**: Put ALL agent Task calls in ONE message for parallel execution
3. **TELL USER**: After spawning, list what each agent is doing (use emojis for clarity)
4. **STOP AND WAIT**: After spawning, STOP - do NOT add more tool calls or check status
5. **NO POLLING**: Never poll TaskOutput or check swarm status - trust agents to return
6. **SYNTHESIZE**: When agent results arrive, review ALL results before proceeding
7. **NO CONFIRMATION**: Don't ask "should I check?" - just wait for results

Example spawn message:
```
"I've launched 4 agents in background:
- 🔍 Researcher: [task]
- 💻 Coder: [task]
- 🧪 Tester: [task]
- 👀 Reviewer: [task]
Working in parallel - I'll synthesize when they complete."
```
