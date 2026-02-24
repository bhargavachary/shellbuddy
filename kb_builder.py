#!/usr/bin/env python3
"""
shellbuddy — kb_builder.py
Generates kb.json by calling GitHub Copilot (gpt-4.1) for each category.
Uses the same copilot backend already wired into the daemon — no extra API key needed.

Usage:
    python3 kb_builder.py                  # generate all categories
    python3 kb_builder.py --category git   # regenerate one category
    python3 kb_builder.py --resume         # skip already-done categories
    python3 kb_builder.py --validate-only  # audit existing kb.json

Output: kb.json in the same directory
Install: cp kb.json ~/.shellbuddy/kb.json  (daemon picks it up on next restart)
"""

import json
import re
import sys
import time
import argparse
from pathlib import Path

# Add shellbuddy backends to path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

try:
    from backends.copilot import call_copilot, get_copilot_token
except ImportError:
    print("ERROR: backends/copilot.py not found. Run from the shellbuddy repo root.")
    sys.exit(1)

# ── Output path ───────────────────────────────────────────────────────────────
OUT_FILE     = Path(__file__).parent / "kb.json"
PARTIAL_DIR  = Path(__file__).parent / ".kb_partial"
PARTIAL_DIR.mkdir(exist_ok=True)

# ── Categories ────────────────────────────────────────────────────────────────
# (name, slug, context, target_count)
CATEGORIES = [
    # Core Unix / Linux
    ("GNU Coreutils",        "gnu",         "ls, cp, mv, rm, find, xargs, sort, uniq, cut, paste, tr, wc, head, tail, tee, stat, chmod, chown, chgrp, ln, dd, split", 60),
    ("Text Processing",      "text",        "awk, sed, grep, ripgrep, cut, tr, column, jq, yq, miller, datamash", 50),
    ("Archive Compression",  "archive",     "tar, gzip, bzip2, xz, zstd, lz4, pigz, zip, unzip, 7z", 30),
    ("Linux Sysadmin",       "sysadmin",    "systemctl, journalctl, cron, at, logrotate, ulimit, sysctl, dmesg, uname, lsmod, modprobe, update-alternatives", 60),
    ("Process Management",   "process",     "ps, top, htop, kill, killall, nice, renice, nohup, screen, fg, bg, jobs, strace, ltrace, lsof", 50),
    ("Disk Storage",         "disk",        "df, du, lsblk, fdisk, parted, mkfs, mount, umount, fstab, iostat, iotop, smartctl, mdadm, lvm, pvs, vgs, lvs", 50),
    ("Users Permissions",    "users",       "useradd, usermod, userdel, passwd, sudo, su, chmod, chown, chgrp, ACLs, setfacl, getfacl, umask, PAM", 40),

    # Networking & Security
    ("Networking",           "network",     "curl, wget, ssh, scp, rsync, netstat, ss, ip, ifconfig, route, dig, nslookup, ping, traceroute, mtr, nmap, tcpdump, nc, socat", 60),
    ("Security",             "security",    "ssh hardening, gpg, openssl, fail2ban, iptables, ufw, nftables, auditd, file permissions, secrets management, env var leaks", 50),
    ("TLS PKI",              "tls",         "openssl s_client, openssl x509, certbot, cfssl, step-ca, TLS handshake debugging, certificate inspection", 30),

    # Version Control
    ("Git Core",             "git",         "git add, commit, push, pull, fetch, merge, rebase, cherry-pick, stash, tag, log, diff, show, blame, bisect", 60),
    ("Git Advanced",         "git-advanced","git reflog, worktrees, submodules, subtrees, hooks, filter-branch, bundle, archive, sparse-checkout, partial clone, rerere", 50),

    # Python Ecosystem
    ("Python Packaging",     "python-pkg",  "pip, conda, uv, poetry, pdm, hatch, pyproject.toml, requirements.txt, virtualenv, venv", 40),
    ("Python Dev Tools",     "python-dev",  "ruff, black, mypy, pylint, pytest, coverage, hypothesis, tox, pre-commit, py-spy, memray, scalene", 40),
    ("Jupyter",              "jupyter",     "jupyter notebook, jupyter lab, nbconvert, nbformat, papermill, nbstripout, voila, jupytext", 30),

    # Data Science
    ("Data Science Tools",   "datascience", "pandas, numpy, scipy, polars, dask, vaex, pyarrow, fastparquet, h5py, zarr, feather, csvkit, visidata", 50),
    ("MLOps Tracking",       "mlops",       "mlflow, wandb, dvc, cml, bentoml, seldon, ray, prefect, airflow, great_expectations, evidently", 50),

    # Machine Learning
    ("Machine Learning",     "ml",          "scikit-learn, joblib, optuna, hyperopt, shap, lime, eli5, imbalanced-learn, feature-engine, category_encoders", 50),

    # Deep Learning
    ("PyTorch",              "pytorch",     "torch, torchvision, torchaudio, torch.compile, DDP, FSDP, AMP, autocast, gradient checkpointing, torch.profiler, torchserve", 60),
    ("TensorFlow Keras",     "tensorflow",  "tf.keras, tf.data, tf.function, TFRecords, SavedModel, TFLite, TF Serving, mixed precision, tf.distribute", 40),
    ("JAX",                  "jax",         "jax.jit, jax.vmap, jax.pmap, jax.grad, flax, optax, haiku, orbax, XLA compilation, device mesh", 40),
    ("HuggingFace",          "huggingface", "transformers, datasets, accelerate, peft, trl, diffusers, tokenizers, evaluate, hub, optimum, text-generation-inference", 60),
    ("GPU CUDA",             "gpu",         "nvidia-smi, nvtop, CUDA_VISIBLE_DEVICES, cudnn, nccl, apex, cuda-memcheck, nsight, nvprof, rocm, gpu memory management", 50),
    ("Model Serving",        "serving",     "torchserve, triton inference server, onnxruntime, vllm, text-generation-inference, ollama, llama.cpp, llamafile, bentoml", 40),

    # Infrastructure
    ("Docker",               "docker",      "docker build, run, compose, exec, logs, stats, network, volume, multi-stage builds, layer caching, security scanning, buildx", 60),
    ("Kubernetes",           "kubernetes",  "kubectl, helm, kustomize, RBAC, namespaces, ingress, services, deployments, statefulsets, daemonsets, jobs, cronjobs, debugging", 60),
    ("Cloud AWS",            "aws",         "aws s3, ec2, iam, lambda, ecs, eks, rds, cloudwatch, cloudformation, ssm, secrets manager, cost explorer, cli profiles", 50),
    ("Cloud GCP Azure",      "gcp-azure",   "gcloud, gsutil, bq, az, azure devops, GCS, BigQuery, Cloud Run, GKE, AKS, Azure ML, service accounts, workload identity", 40),
    ("Terraform",            "terraform",   "terraform plan, apply, destroy, state, import, workspace, modules, providers, remote backend, drift detection, terragrunt", 40),

    # Databases
    ("Databases SQL",        "db-sql",      "psql, mysql, sqlite3, pg_dump, pg_restore, explain analyze, vacuum, indexes, transactions, replication, pgbouncer", 50),
    ("Databases NoSQL",      "db-nosql",    "redis-cli, mongosh, cassandra-cli, cqlsh, elasticsearch, opensearch, clickhouse-client, influxdb", 40),

    # JavaScript / Frontend
    ("Node JS",              "node",        "npm, pnpm, yarn, npx, node, nvm, ts-node, eslint, prettier, vitest, jest, webpack, vite, esbuild, rollup, turbo", 50),

    # Performance Observability
    ("Profiling Perf",       "perf",        "perf, flamegraph, strace, dtrace, bpftrace, eBPF, valgrind, heaptrack, gprof, py-spy, async-profiler, jstack", 40),
    ("Monitoring",           "monitoring",  "prometheus, alertmanager, grafana, loki, tempo, opentelemetry, jaeger, datadog agent, telegraf, netdata, glances", 30),

    # Editors & Terminal
    ("Vim Neovim",           "vim",         "vim, nvim command-line patterns, :substitute, :global, macros, registers, marks, quickfix, LSP from CLI", 30),
    ("Tmux",                 "tmux",        "tmux sessions, windows, panes, copy mode, plugins, scripting, nested sessions, socket, resurrect", 30),

    # Package Managers & Build
    ("Package Managers",     "pkgmgr",      "brew, apt, yum, dnf, pacman, cargo, go get/install, gem, mix, stack, cabal, nix", 40),
    ("Build Systems",        "build",       "make, cmake, ninja, bazel, buck, meson, cargo build, go build, tsc, gradle, maven, ant", 30),

    # VHDL / FPGA
    ("VHDL FPGA",            "fpga",        "ghdl, vivado, vitis, quartus, verilator, yosys, nextpnr, cocotb, iverilog, ModelSim, openFPGALoader", 30),

    # macOS specific
    ("macOS",                "macos",       "brew, launchctl, defaults, diskutil, security, osascript, pbcopy, pbpaste, open, caffeinate, networksetup, airport, mdfind", 40),
]

# ── Prompt ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a senior DevOps/MLOps engineer and Linux sysadmin building a terminal knowledge base.
Generate shell command rules for an ambient terminal coaching tool.

Each rule must follow this exact JSON schema:
{
  "id": "<slug>-NNN",
  "pattern": "<python regex anchored with ^>",
  "cmd": "<primary command token, e.g. git>",
  "severity": "<danger|warn|tip|upgrade>",
  "hint": "<max 68 chars, actionable, specific>",
  "detail": "<2-3 sentences of expert knowledge from man pages / sysadmin books>",
  "tags": ["tag1", "tag2"]
}

Severity guide:
- danger  : data loss, irreversible, security breach (e.g. rm -rf /, git push --force main)
- warn    : silent failure, footgun, common mistake (e.g. missing flag, wrong env)
- tip     : suboptimal but safe; better idiom exists (e.g. use --jobs for parallelism)
- upgrade : a faster/modern tool replaces this one (e.g. fd instead of find)

Rules:
1. pattern MUST be valid Python regex, anchored with ^, double-escaped (\\\\s+ not \\s+)
2. hint MUST be under 68 characters. Be specific — include the exact flag or tool.
3. detail MUST contain real technical depth (not obvious). Reference flags, man page behaviour, edge cases.
4. cmd MUST be the literal first token the user would type (git, python, docker, etc.)
5. id MUST use the provided slug prefix and a zero-padded 3-digit number
6. Focus on PRO tips — things a junior dev wouldn't know, or footguns experts still hit
7. NO markdown, NO explanation outside the JSON array. Output ONLY a valid JSON array.
"""

def make_user_prompt(name, slug, context, count):
    return (
        f"Generate exactly {count} rules for category: {name}\n"
        f"Slug prefix: {slug}\n"
        f"Context / tools covered: {context}\n\n"
        f"Focus areas:\n"
        f"- Common dangerous misuse patterns (danger/warn)\n"
        f"- Performance flags most people miss (tip)\n"
        f"- Modern tool replacements (upgrade)\n"
        f"- Silent failure modes\n"
        f"- Environment/config gotchas\n"
        f"Vary the patterns — cover different subcommands and flag combinations."
    )

# ── Validation ────────────────────────────────────────────────────────────────
REQUIRED = {"id", "pattern", "cmd", "severity", "hint", "detail", "tags"}
SEVERITIES = {"danger", "warn", "tip", "upgrade"}

def validate(entries, slug):
    valid = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        if not REQUIRED.issubset(e.keys()):
            continue
        if e.get("severity") not in SEVERITIES:
            continue
        if len(e.get("hint", "")) > 72:
            e["hint"] = e["hint"][:69] + "..."
        try:
            re.compile(e["pattern"])
        except re.error:
            continue
        if not e.get("id", "").startswith(slug):
            e["id"] = f"{slug}-{len(valid):03d}"
        valid.append(e)
    return valid

# ── Extract JSON from response ────────────────────────────────────────────────
def extract_json(text):
    # Strip markdown fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    # Find first [ ... ] block
    start = text.find("[")
    end   = text.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
        return []

# ── Generate one category via Copilot gpt-4.1 ────────────────────────────────
def generate_category(name, slug, context, count, retries=2):
    partial_file = PARTIAL_DIR / f"{slug}.json"
    if partial_file.exists():
        print(f"  [cached] {name}")
        return json.loads(partial_file.read_text())

    print(f"  [gen]    {name} (~{count} rules)...", end=" ", flush=True)
    full_prompt = SYSTEM_PROMPT + "\n\n" + make_user_prompt(name, slug, context, count)

    for attempt in range(retries + 1):
        try:
            raw = call_copilot(full_prompt, model="gpt-4.1", max_tokens=8000)
            if not raw:
                raise RuntimeError("empty response from copilot")
            entries = extract_json(raw)
            valid = validate(entries, slug)
            print(f"{len(valid)} valid")
            if valid:
                partial_file.write_text(json.dumps(valid, indent=2))
            return valid
        except Exception as e:
            print(f"error (attempt {attempt + 1}): {e}")
            if attempt < retries:
                time.sleep(2)
    return []

# ── Deduplicate ───────────────────────────────────────────────────────────────
def dedup(entries):
    seen_ids = {}
    seen_patterns = {}
    out = []
    for e in entries:
        pid = e["id"]
        pat = e["pattern"]
        if pid in seen_ids or pat in seen_patterns:
            continue
        seen_ids[pid] = True
        seen_patterns[pat] = True
        out.append(e)
    return out

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="shellbuddy KB builder")
    parser.add_argument("--category", help="Regenerate only this slug (e.g. git)")
    parser.add_argument("--resume",   action="store_true", help="Skip cached categories")
    parser.add_argument("--validate-only", action="store_true", help="Validate existing kb.json")
    args = parser.parse_args()

    if args.validate_only:
        if not OUT_FILE.exists():
            print("kb.json not found")
            return
        data = json.loads(OUT_FILE.read_text())
        print(f"Total entries: {len(data)}")
        by_cat = {}
        by_sev = {}
        bad_patterns = 0
        for e in data:
            by_cat[e.get("cmd","?")] = by_cat.get(e.get("cmd","?"), 0) + 1
            by_sev[e.get("severity","?")] = by_sev.get(e.get("severity","?"), 0) + 1
            try:
                re.compile(e["pattern"])
            except re.error:
                bad_patterns += 1
                print(f"  bad pattern: {e['id']} → {e['pattern']}")
        print(f"Bad patterns: {bad_patterns}")
        print("By severity:", json.dumps(by_sev, indent=2))
        top = sorted(by_cat.items(), key=lambda x: -x[1])[:15]
        print("Top cmds:", top)
        return

    # Verify copilot token is available before starting
    token, _ = get_copilot_token()
    if not token:
        print("ERROR: Copilot token not available. Make sure VS Code + GitHub Copilot is signed in.")
        sys.exit(1)
    print("Copilot token OK\n")

    if args.category:
        # Regenerate one category
        match = [c for c in CATEGORIES if c[1] == args.category]
        if not match:
            print(f"Unknown slug: {args.category}")
            print("Available:", [c[1] for c in CATEGORIES])
            return
        name, slug, context, count = match[0]
        # Clear cache for this slug
        partial = PARTIAL_DIR / f"{slug}.json"
        partial.unlink(missing_ok=True)
        entries = generate_category(name, slug, context, count)
        # Merge into existing kb.json
        if OUT_FILE.exists():
            existing = json.loads(OUT_FILE.read_text())
            existing = [e for e in existing if not e["id"].startswith(slug)]
            existing.extend(entries)
            final = dedup(existing)
        else:
            final = dedup(entries)
        OUT_FILE.write_text(json.dumps(final, indent=2))
        print(f"Done. Total: {len(final)}")
        return

    # Full build
    print(f"Building kb.json — {len(CATEGORIES)} categories\n")
    all_entries = []
    for name, slug, context, count in CATEGORIES:
        entries = generate_category(name, slug, context, count)
        all_entries.extend(entries)
        time.sleep(0.5)  # gentle rate limiting

    final = dedup(all_entries)
    OUT_FILE.write_text(json.dumps(final, indent=2))
    print(f"\nDone. Total rules: {len(final)}")
    print(f"Output: {OUT_FILE}")
    print(f"Copy to ~/.shellbuddy/kb.json to activate.")

if __name__ == "__main__":
    main()
