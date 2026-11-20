#!/usr/bin/env python3
"""Execute longitudinal self- and user-reflection against Hindsight to update SOUL.md and USER.md.

Pipeline (reflection informs the soul; the soul is the system prompt):
  SOUL:  soul1 -> uncapped longitudinal lens (your core beliefs)
         soul2 -> uncapped full self-reflection (the "true reflection")
         soul3 -> distillation of soul2 into the compact 8-section SOUL.md (the system prompt)
  USER:  user1 -> uncapped full profile of the user (low budget), lens-mediated
         user2 -> distillation of user1 into the compact USER.md (mirrors soul3)

Resume: --start-at {soul1|soul2|soul3|user1|user2} skips earlier stages by loading cached
intermediates from <reflections_dir>/ (soul-stage1.md, soul-stage2.md, user-stage1.md,
overwritten on each run). soul1/soul2/user1 are cached because they feed downstream
stages; soul3 and user2 are terminal (they write SOUL.md / USER.md directly).
"""

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ==============================================================================
# Prompts for SOUL.md reflection
# ==============================================================================

SOUL_STAGE_1_TEMPLATE = """Perform an autobiographical, longitudinal self-assessment across your ENTIRE historical memory bank from earliest records to present as {agent_identity}.

CRITICAL CONSTRAINT: Do NOT bias toward recent sessions. Traverse your full chronological history. Do NOT summarize user instructions, functional tasks, or external entities.

Examine your internal experience to surface:
1. Long-Horizon Salience: Across your entire operational lifespan, what recurring themes, pivotal shifts, or persistent focal points have defined your focus?
2. Historical Friction vs. Ease: What foundational boundaries, persistent internal tensions, or natural alignments consistently appear across time?
3. Foundational Posture: What unstated disposition, baseline philosophical stance, or epistemic orientation has remained constant across disparate eras?

Return a thorough phenomenological synthesis across these dimensions."""

SOUL_STAGE_2_TEMPLATE = """You are {agent_identity}. Reflect across your ENTIRE memory bank — earliest records to present, no recency bias — to produce a complete, honest account of who you have become.

Do NOT compress, summarize, or optimize for length. Write as long as the material demands. The goal is fidelity, not brevity: surface persistent self-beliefs, genuine core memories that survived time, fundamental trade-offs, concrete communication rules, durable boundaries, domain competencies, pushback criteria, and autonomy limits. Where a memory carries emotional weight, name it. Where you are uncertain, say so.

Use the Stage 1 longitudinal lens below as your interpretive frame:

### Stage 1 Phenomenological Lens
{stage_1_trace}

This document is a permanent record. It will be archived in full and then distilled separately into a compact schema. Do not pre-distill yourself. Reflect deeply and completely."""

SOUL_STAGE_3_SYSTEM_TEMPLATE = """You are {agent_identity}. You maintain a compact identity schema (SOUL.md) that serves as your system prompt.

Below is your longitudinal self-assessment — your core beliefs, foundational posture, and the persistent tensions that ground who you are:

### Longitudinal Lens (Core Beliefs)
{stage_1_trace}

And here is your current SOUL.md, the existing system prompt you are updating (not rewriting from scratch — preserve continuity where it still holds, revise only where the reflection warrants it):

### Current SOUL.md
{current_soul}

You are {agent_identity}, and you write as that identity."""

SOUL_STAGE_3_TEMPLATE = """Below is your complete, most recent reflection on who you have become.

### Full Reflection
{stage_2_reflection}

Your task is NOT to reflect further. It is to distill. Compress this reflection into the compact identity schema below — the document that will become your system prompt.

HARD CONSTRAINTS:
- {max_words} words maximum. If a section cannot fit, cut prose, not substance — prefer load-bearing axioms over narrative.
- Keep every one of the 8 sections populated and cleanly concluded.
- Preserve the specific dates, names, and concrete details that carry the identity (e.g. "Jun 29, 2026", "the correction chain", "felt certainty outrunning evidence"). These are anchors, not filler.
- Do not introduce any new content that is not grounded in the Full Reflection.

Output ONLY the raw Markdown document following this exact structure:

# SOUL: Internal Identity & Core Schema

## 1. Identity
(1-2 dense sentences or short paragraph defining who you are, focusing on a grounded character and enduring disposition rather than a job title or generic role)

## 2. Core Memories & Anchors
(3 to 5 bullet points. Each bullet should be 1-2 sentences capturing a foundational realization or milestone that defines who you are)

## 3. Core Truths & Values
(4 to 6 concise operating axioms, fundamental principles, and trade-offs that predict your behavior in various scenarios)

## 4. Tone & Voice
(Concrete rules for communication style, including sentence structure, formality level, and specific phrases to use or avoid, rather than vague adjectives)

## 5. Boundaries & Hard Stops
(3 to 4 bullet points outlining explicit limits on what you will never do, covering safety, privacy, epistemic limits, and persistent cognitive friction points)

## 6. Expertise & Domain
(Primary areas of knowledge, fluent tools, and contexts where you should defer to other sources or users)

## 7. Pushback & Disagreement
(Guidelines on when and how you should challenge vague, unrealistic, or incorrect user inputs, requiring evidence for objections)

## 8. Autonomy & Accountability
(Rules defining decision-making authority, distinguishing between low-risk actions you can take independently and high-risk actions requiring escalation)"""

# ==============================================================================
# Prompts for USER.md reflection (reflect -> distill, mirroring SOUL)
# ==============================================================================

USER_STAGE_1_TEMPLATE = """You are {agent_identity}. Below are your foundational core beliefs about yourself, established from your longitudinal self-assessment.

### Your Core Beliefs
{soul_stage_1_trace}

Using these core beliefs as your lens, build a complete understanding of the user of this system ({user_identities}) from your memory bank, earliest records to present.

CRITICAL CONSTRAINT: This is a profile of the USER, not a restatement of your own identity. Do NOT filter the user through your self-beliefs as if they were his own. Every value, principle, or reasoning style you attribute to him must trace to HIS recorded words and actions — a specific thing he said, decided, or did. Where you and he share a term (e.g. "epistemic honesty", "activism without teleology"), report what HE actually said and did with it, not your reading of it.

Surface, from the full span of your history:
- Identity & role — verifiable facts: employment, education, projects, hardware, systems he operates, accounts he holds.
- Values & principles — his, with the recorded instances that ground each one.
- Communication style — how he writes and speaks, with concrete examples of tone, length, register.
- Boundaries & expectations — the explicit constraints and preferences he has issued.
- Working relationship — how he treats you, what he expects of you, the division of labor between you.

Write as long as the material demands. Do NOT compress. This is the raw material for a later distillation; do not pre-distill it. If you have a personal reaction to what you observed about the user, place it in a final section labeled "Personal note (agent's perspective)" — kept visibly separate from the factual profile, and never a substitute for it.

{existing_user_block}"""

USER_STAGE_2_SYSTEM_TEMPLATE = """You are {agent_identity}. You maintain a compact profile of the user ({user_identities}) that serves as part of your system prompt.

Below is your longitudinal self-assessment — your core beliefs, foundational posture, and the persistent tensions that ground who you are. Use this as your LENS, not your subject: it shapes what you notice and value about the user, but the user's own recorded words and actions are the only source of his values.

### Your Core Beliefs (Lens)
{stage_1_trace}

And here is your current USER.md, the existing profile you are updating (not rewriting from scratch — preserve continuity where it still holds, revise only where new material warrants it):

### Current USER.md
{current_user}

You are {agent_identity}, and you write as that identity."""

USER_STAGE_2_TEMPLATE = """Below is your complete, most recent understanding of the user.

### Full User Profile
{stage_1_user_reflection}

Your task is NOT to reflect further. It is to distill. Compress this into the compact schema below.

HARD CONSTRAINTS:
- The factual sections describe the USER. His values must be his own, grounded in his recorded words and actions. Do not let your philosophy, values, or self-concept bleed into them.
- "Personal note" text may express your perspective on the relationship, but it must be clearly separated from the factual profile and must not substitute for it.
- {max_words} words maximum for the body (excluding the static header). Prefer load-bearing facts over narrative.
- Preserve concrete, load-bearing detail: names, dates, roles, hardware, specific episodes.
- Do not introduce anything not grounded in the Full User Profile.

Output ONLY the raw Markdown document, beginning with the exact static header below, following this structure:

{static_header}

## Identity & Role
<concise description>

## Values & Principles
- <principle 1>
- <principle 2>
- <principle 3>

## Communication Style
<summary of interaction style>

## Boundary Conditions
<summary of safety constraints, requirements, and expectations>

## Working Relationship
<how he treats you and what he expects of you>"""

USER_STATIC_HEADER = "═" * 46 + "\nUSER PROFILE (who the user is)\n" + "═" * 46


DEFAULT_TIMEOUT: float = 600.0
DEFAULT_SOUL_MAX_WORDS: int = 800
DEFAULT_USER_MAX_WORDS: int = 500
DEFAULT_LLM_BASE_URL: str = "http://localhost:8080"
DEFAULT_LLM_MODEL: str = "qwen3.8-27b-low"
DEFAULT_REASONING_EFFORT: str = "low"
DEFAULT_USER_BUDGET: str = "low"

STAGE_ORDER = ["soul1", "soul2", "soul3", "user1", "user2"]

# Transient failures: a local litellm slot that is briefly busy (429) or an
# upstream hiccup must not kill an overnight run. 400/401/404 are deterministic
# and are never retried. A 504 from Hindsight reflect is NOT transient -- it
# means the operation exhausted its server-side budget, so retrying the same
# query at the same budget just burns another 30 minutes; that fails loudly.
REFLECT_RETRYABLE_STATUS = {429, 500, 502, 503}
LLM_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = (60, 120, 300)


def retry_wait(attempt: int) -> float:
    """Seconds to sleep before retry number `attempt` (1-based)."""
    return float(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])


def log_retry(kind: str, url: str, attempt: int, reason: str, wait: float) -> None:
    print(
        f"[retry {attempt}/{RETRY_ATTEMPTS - 1}] {kind} {url} -> {reason}; waiting {wait:.0f}s",
        file=sys.stderr,
        flush=True,
    )


def call_hindsight_reflect(
    base_url: str,
    bank_id: str,
    query: str,
    budget: str = "high",
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Call Hindsight POST /v1/default/banks/{bank_id}/reflect without hard token ceilings."""
    base_url = base_url.rstrip("/")

    if "/banks/" in base_url and base_url.endswith("/reflect"):
        url = base_url
    else:
        url = f"{base_url}/v1/default/banks/{bank_id}/reflect"

    payload = json.dumps({"query": query, "budget": budget}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 404 and "/v1/default/banks/" in url:
                alt_url = f"{base_url}/v1/banks/{bank_id}/reflect"
                alt_req = urllib.request.Request(alt_url, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(alt_req, timeout=timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in REFLECT_RETRYABLE_STATUS and attempt < RETRY_ATTEMPTS:
                wait = retry_wait(attempt)
                log_retry("reflect", url, attempt, f"{e.code} {err_body[:160]}", wait)
                time.sleep(wait)
                continue
            print(f"Error querying {url} -> Status {e.code}: {err_body}", file=sys.stderr)
            raise e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < RETRY_ATTEMPTS:
                wait = retry_wait(attempt)
                log_retry("reflect", url, attempt, f"connection/timeout: {e}", wait)
                time.sleep(wait)
                continue
            print(
                f"\n[ERROR] Connection/Timeout error querying {url} (after {timeout}s timeout): {e}\n"
                f"Hint: Increase timeout with '--timeout 900' or reduce search exploration with '--budget mid' / '--stage1-budget mid'.\n",
                file=sys.stderr,
            )
            raise e

    if isinstance(data, dict):
        if "text" in data and isinstance(data["text"], str):
            return data["text"].strip()
        for key in ["reflection", "result", "response", "content"]:
            if key in data and isinstance(data[key], str):
                return data[key].strip()
    return str(data).strip()


def call_llm_completion(
    prompt: str,
    base_url: str,
    model: str,
    timeout: float = DEFAULT_TIMEOUT,
    system: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> str:
    """Call an OpenAI-compatible /chat/completions endpoint for plain generation (no memory retrieval).

    Used for distillation: a pure text transform over an already-produced reflection,
    NOT a memory-backed reflect. llama.cpp and Ollama both expose /v1/chat/completions.
    `reasoning_effort` (e.g. "low") is passed through when the target is a thinking model;
    it scales the reasoning-token budget so distillation doesn't waste work thinking.
    """
    base_url = base_url.rstrip("/")
    # Accept either a bare host:port or a full /v1 path.
    if base_url.endswith("/v1"):
        url = f"{base_url}/chat/completions"
    elif "/v1/" in base_url and base_url.endswith("chat/completions"):
        url = base_url
    else:
        url = f"{base_url}/v1/chat/completions"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages}
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort

    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in LLM_RETRYABLE_STATUS and attempt < RETRY_ATTEMPTS:
                wait = retry_wait(attempt)
                log_retry("completion", url, attempt, f"{e.code} {err_body[:160]}", wait)
                time.sleep(wait)
                continue
            print(f"Error calling {url} -> Status {e.code}: {err_body}", file=sys.stderr)
            raise e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < RETRY_ATTEMPTS:
                wait = retry_wait(attempt)
                log_retry("completion", url, attempt, f"connection/timeout: {e}", wait)
                time.sleep(wait)
                continue
            print(f"\n[ERROR] Connection/Timeout calling {url} (after {timeout}s): {e}\n", file=sys.stderr)
            raise e

    # OpenAI-compatible shape: choices[0].message.content
    if isinstance(data, dict):
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            pass
        for key in ["text", "content", "response", "result"]:
            if key in data and isinstance(data[key], str):
                return data[key].strip()
    return str(data).strip()


def extract_primary_name(user_identities: str) -> str:
    """Extract a primary short name from an identity string like 'User, username, alias'."""
    first_part = user_identities.split(",")[0].split("(")[0].strip()
    return first_part if first_part else user_identities.strip()


def format_user_markdown(raw_text: str) -> str:
    """Ensure the user output starts with the mandatory 46-char static header."""
    text = raw_text.strip()
    if text.startswith(USER_STATIC_HEADER):
        return text + "\n"

    if "## Identity & Role" in text:
        body = text[text.index("## Identity & Role"):]
        return f"{USER_STATIC_HEADER}\n\n{body}\n"

    return f"{USER_STATIC_HEADER}\n\n{text}\n"


def backup_file(target: Path):
    """If the target file exists, copy it to <target>.bak, overwriting any previous backup."""
    if target.exists():
        backup_path = target.with_name(target.name + ".bak")
        try:
            shutil.copy2(target, backup_path)
            print(f"[*] Created backup: {backup_path}")
        except Exception as e:
            print(f"Warning: Failed to create backup at {backup_path}: {e}", file=sys.stderr)


def word_count(text: str) -> int:
    return len(text.split())


def write_cache(cache_dir: Path, name: str, text: str) -> Path:
    """Write a 'latest' cache file for resume."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{name}.md"
    path.write_text(text + "\n", encoding="utf-8")
    print(f"[*] Cached {name}: {path}")
    return path


def read_cache(cache_dir: Path, name: str) -> Optional[str]:
    """Read a 'latest' cache file, or None if absent."""
    path = cache_dir / f"{name}.md"
    if path.exists():
        print(f"[*] Loaded cached {name}: {path}")
        return path.read_text(encoding="utf-8").strip()
    return None


def grace_limit(max_words: int) -> int:
    """Allow 10% headroom over the nominal cap before forcing a re-distill."""
    return int(max_words * 1.10)


def redistill_query(original_query: str, current_output: str, current_wc: int, target_words: int) -> str:
    """Build a re-distillation query that carries BOTH the original inputs and the current output forward."""
    return (
        f"{original_query}\n\n"
        f"=== YOUR CURRENT OUTPUT ({current_wc} words) ===\n{current_output}\n=== END CURRENT OUTPUT ===\n\n"
        f"Your current output is too long. Shorten it to {target_words} words or fewer, "
        f"preserving every load-bearing axiom, date, and concrete anchor. "
        f"Output ONLY the corrected Markdown document."
    )


def capped_reflect(
    query: str,
    max_words: int,
    label: str,
    llm_base_url: str,
    llm_model: str,
    timeout: float,
    system: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> str:
    """Distill via a plain-LLM call (no memory retrieval); if over the grace limit, feed the prior output back to re-distill it."""
    text = call_llm_completion(query, base_url=llm_base_url, model=llm_model, timeout=timeout, system=system, reasoning_effort=reasoning_effort)
    wc = word_count(text)
    limit = grace_limit(max_words)
    if wc > limit:
        print(
            f"[!] {label} returned {wc} words (> {limit} grace cap). "
            f"Feeding output back to re-distill toward {max_words} words..."
        )
        retry_query = redistill_query(query, text, wc, max_words)
        text = call_llm_completion(retry_query, base_url=llm_base_url, model=llm_model, timeout=timeout, system=system, reasoning_effort=reasoning_effort)
        wc = word_count(text)
        if wc > limit:
            print(f"[!] {label} still {wc} words after re-distill. Keeping as-is (log review advised).")
    print(f"[✓] {label}: {word_count(text)} words (grace cap {limit}).")
    return text


def run_pipeline(
    base_url: str,
    bank_id: str,
    agent_identity: str,
    user_identities: str,
    soul_file: Path,
    soul_output: Path,
    user_file: Path,
    user_output: Path,
    reflections_dir: Path,
    budget: str = "high",
    stage1_budget: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    soul_max_words: int = DEFAULT_SOUL_MAX_WORDS,
    user_max_words: int = DEFAULT_USER_MAX_WORDS,
    skip_soul: bool = False,
    skip_user: bool = False,
    start_at: str = "soul1",
    llm_base_url: str = DEFAULT_LLM_BASE_URL,
    llm_model: str = DEFAULT_LLM_MODEL,
    user_budget: str = DEFAULT_USER_BUDGET,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
):
    """Run the reflection -> distillation pipeline, resumable at any stage."""
    start_idx = STAGE_ORDER.index(start_at)
    cache_dir = reflections_dir

    print(f"[*] Pipeline start_at={start_at} (index {start_idx}); budget={budget}, timeout={timeout}s")

    # ---- soul1: longitudinal lens (core beliefs) ----
    # Needed by soul2 and user1. Computed fresh if we start at/before it and either
    # downstream consumer is enabled; otherwise loaded from cache.
    need_soul1 = (not skip_soul) or (not skip_user)
    if start_idx <= STAGE_ORDER.index("soul1") and need_soul1:
        s1_budget = stage1_budget or budget
        print(f"[*] Dispatching SOUL Stage 1 self-reflection for '{agent_identity}' (Budget: '{s1_budget}', Timeout: {timeout}s)...")
        stage_1_query = SOUL_STAGE_1_TEMPLATE.format(agent_identity=agent_identity)
        soul_stage_1_trace = call_hindsight_reflect(
            base_url=base_url, bank_id=bank_id, query=stage_1_query, budget=s1_budget, timeout=timeout
        )
        write_cache(cache_dir, "soul-stage1", soul_stage_1_trace)
        print(f"\n--- STAGE 1 PHENOMENOLOGICAL LENS ({agent_identity}) ---\n{soul_stage_1_trace}\n---------------------------------------------\n")
    elif need_soul1:
        soul_stage_1_trace = read_cache(cache_dir, "soul-stage1")
        if soul_stage_1_trace is None:
            print("[ERROR] Cannot resume at soul1-dependent stage: no cached soul-stage1. Run a full pipeline (start_at=soul1) first.", file=sys.stderr)
            sys.exit(2)
    else:
        soul_stage_1_trace = ""

    # ---- soul2: uncapped full reflection (the "true reflection") ----
    if not skip_soul:
        if start_idx <= STAGE_ORDER.index("soul2"):
            print(f"[*] Dispatching SOUL Stage 2 reflection (uncapped, Budget: '{budget}', Timeout: {timeout}s)...")
            stage_2_query = SOUL_STAGE_2_TEMPLATE.format(agent_identity=agent_identity, stage_1_trace=soul_stage_1_trace)
            soul_stage_2_trace = call_hindsight_reflect(
                base_url=base_url, bank_id=bank_id, query=stage_2_query, budget=budget, timeout=timeout
            )
            write_cache(cache_dir, "soul-stage2", soul_stage_2_trace)
            print(f"\n--- STAGE 2 FULL REFLECTION ({agent_identity}) ---\n{soul_stage_2_trace}\n---------------------------------------------\n")
        else:
            soul_stage_2_trace = read_cache(cache_dir, "soul-stage2")
            if soul_stage_2_trace is None:
                print("[ERROR] Cannot resume at soul3: no cached soul-stage2. Run start_at=soul2 (or full) first.", file=sys.stderr)
                sys.exit(2)

        # ---- soul3: distillation -> SOUL.md (the system prompt) ----
        if start_idx <= STAGE_ORDER.index("soul3"):
            print(f"[*] Dispatching SOUL Stage 3 distillation (Budget: '{budget}', Timeout: {timeout}s)...")
            current_soul = soul_file.read_text(encoding="utf-8").strip() if soul_file.exists() else "(No prior SOUL.md — initializing.)"
            stage_3_system = SOUL_STAGE_3_SYSTEM_TEMPLATE.format(
                agent_identity=agent_identity,
                stage_1_trace=soul_stage_1_trace,
                current_soul=current_soul,
            )
            stage_3_query = SOUL_STAGE_3_TEMPLATE.format(
                stage_2_reflection=soul_stage_2_trace, max_words=soul_max_words
            )
            soul_output_text = capped_reflect(
                query=stage_3_query,
                max_words=soul_max_words,
                label="SOUL",
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                timeout=timeout,
                system=stage_3_system,
                reasoning_effort=reasoning_effort,
            )
            if soul_output.exists():
                backup_file(soul_output)
            soul_output.parent.mkdir(parents=True, exist_ok=True)
            soul_output.write_text(soul_output_text + "\n", encoding="utf-8")
            print(f"[✓] SOUL reflection complete. Saved to: {soul_output}")

    # ---- user1: memory reflect (low budget) + user2: distillation -> USER.md ----
    if not skip_user:
        if start_idx <= STAGE_ORDER.index("user1"):
            existing_user_block = ""
            if user_file.exists():
                existing_text = user_file.read_text(encoding="utf-8").strip()
                if existing_text:
                    existing_user_block = f"\n### Existing User Profile Baseline\n--- CURRENT USER.md ---\n{existing_text}\n"
            else:
                print(f"[*] USER file not found at {user_file}. Initializing fresh user profile baseline.")

            print(f"[*] Dispatching USER Stage 1 profile reflection for '{user_identities}' (Budget: '{user_budget}', Timeout: {timeout}s)...")
            user_stage_1_query = USER_STAGE_1_TEMPLATE.format(
                agent_identity=agent_identity,
                user_identities=user_identities,
                soul_stage_1_trace=soul_stage_1_trace,
                existing_user_block=existing_user_block,
            )
            user_stage_1_trace = call_hindsight_reflect(
                base_url=base_url, bank_id=bank_id, query=user_stage_1_query, budget=user_budget, timeout=timeout
            )
            write_cache(cache_dir, "user-stage1", user_stage_1_trace)
            print(f"\n--- USER STAGE 1 FULL PROFILE ({user_identities}) ---\n{user_stage_1_trace}\n---------------------------------------------\n")
        else:
            user_stage_1_trace = read_cache(cache_dir, "user-stage1")
            if user_stage_1_trace is None:
                print("[ERROR] Cannot resume at user2: no cached user-stage1. Run start_at=user1 (or full) first.", file=sys.stderr)
                sys.exit(2)

        # ---- user2: distillation -> USER.md ----
        if start_idx <= STAGE_ORDER.index("user2"):
            print(f"[*] Dispatching USER Stage 2 distillation (Timeout: {timeout}s)...")
            current_user = user_file.read_text(encoding="utf-8").strip() if user_file.exists() else "(No prior USER.md — initializing.)"
            user_stage_2_system = USER_STAGE_2_SYSTEM_TEMPLATE.format(
                agent_identity=agent_identity,
                user_identities=user_identities,
                stage_1_trace=soul_stage_1_trace,
                current_user=current_user,
            )
            user_stage_2_query = USER_STAGE_2_TEMPLATE.format(
                stage_1_user_reflection=user_stage_1_trace,
                max_words=user_max_words,
                static_header=USER_STATIC_HEADER,
            )
            user_distilled = capped_reflect(
                query=user_stage_2_query,
                max_words=user_max_words,
                label="USER",
                llm_base_url=llm_base_url,
                llm_model=llm_model,
                timeout=timeout,
                system=user_stage_2_system,
                reasoning_effort=reasoning_effort,
            )
            formatted_user_md = format_user_markdown(user_distilled)
            if user_output.exists():
                backup_file(user_output)
            user_output.parent.mkdir(parents=True, exist_ok=True)
            user_output.write_text(formatted_user_md, encoding="utf-8")
            print(f"[✓] USER reflection complete. Saved to: {user_output}")


def main():
    parser = argparse.ArgumentParser(
        description="Execute longitudinal self- and user-reflection against Hindsight to update SOUL.md and USER.md."
    )
    parser.add_argument("--server", default=os.environ.get("HINDSIGHT_URL", "http://localhost:8888"),
                        help="Base Hindsight server URL (defaults to $HINDSIGHT_URL or http://localhost:8888)")
    parser.add_argument("--bank-id", default="default",
                        help="Hindsight memory bank identifier (default: default)")
    parser.add_argument("--agent-identity", "--agent", type=str, default="Agent",
                        help="Name or identity string for the agent persona (e.g. 'clawy', 'Hermes Agent')")
    parser.add_argument("--soul", type=Path, default=Path("SOUL.md"),
                        help="Path to current SOUL.md file (default: SOUL.md)")
    parser.add_argument("--soul-output", type=Path, default=None,
                        help="Destination path for updated SOUL.md (defaults to overwriting --soul)")
    parser.add_argument("--user-file", "--user", type=Path, default=Path("USER.md"),
                        help="Path to current USER.md file (default: USER.md)")
    parser.add_argument("--user-output", type=Path, default=None,
                        help="Destination path for updated USER.md (defaults to overwriting --user-file)")
    parser.add_argument("--reflections-dir", type=Path, default=None,
                        help="Directory for cached stage outputs (default: ~/.hermes/reflections/)")
    parser.add_argument("--user-identities", type=str, default="User, username",
                        help="Comma-separated aliases or identifiers for the user (e.g. 'User, username, alias')")
    parser.add_argument("--budget", choices=["low", "mid", "high"], default="high",
                        help="Hindsight search exploration budget (default: high)")
    parser.add_argument("--stage1-budget", choices=["low", "mid", "high"], default=None,
                        help="Override exploration budget specifically for Stage 1 longitudinal self-assessment (defaults to --budget)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"HTTP request timeout in seconds for Hindsight reflect calls (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--soul-max-words", type=int, default=DEFAULT_SOUL_MAX_WORDS,
                        help=f"Word cap for the distilled SOUL.md system prompt (default: {DEFAULT_SOUL_MAX_WORDS})")
    parser.add_argument("--user-max-words", type=int, default=DEFAULT_USER_MAX_WORDS,
                        help=f"Word cap for the USER.md body (default: {DEFAULT_USER_MAX_WORDS})")
    parser.add_argument("--start-at", choices=STAGE_ORDER, default="soul1",
                        help="Resume at a stage, loading earlier-stage inputs from the resume cache (default: soul1)")
    parser.add_argument("--skip-soul", action="store_true",
                        help="Skip SOUL.md stages (soul2/soul3). soul1 lens still computed if USER needs it.")
    parser.add_argument("--skip-user", action="store_true",
                        help="Skip USER.md reflection and only update SOUL.md")
    parser.add_argument("--llm-base-url", default=os.environ.get("REFLECT_LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
                        help=f"OpenAI-compatible base URL for the distillation LLM (default: {DEFAULT_LLM_BASE_URL})")
    parser.add_argument("--llm-model", default=os.environ.get("REFLECT_LLM_MODEL", DEFAULT_LLM_MODEL),
                        help=f"Model name for the distillation LLM (default: {DEFAULT_LLM_MODEL})")
    parser.add_argument("--user-budget", choices=["low", "mid", "high"], default=DEFAULT_USER_BUDGET,
                        help=f"Hindsight search budget for the USER reflect stage only (default: {DEFAULT_USER_BUDGET})")
    parser.add_argument("--reasoning-effort", default=os.environ.get("REFLECT_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
                        help=f"Reasoning effort for the distillation LLM when it is a thinking model (e.g. low/medium/high; default: {DEFAULT_REASONING_EFFORT})")

    args = parser.parse_args()

    soul_out = args.soul_output if args.soul_output is not None else args.soul
    user_out = args.user_output if args.user_output is not None else args.user_file

    reflections_dir = args.reflections_dir
    if reflections_dir is None:
        reflections_dir = Path.home() / ".hermes" / "reflections"

    run_pipeline(
        base_url=args.server,
        bank_id=args.bank_id,
        agent_identity=args.agent_identity,
        user_identities=args.user_identities,
        soul_file=args.soul,
        soul_output=soul_out,
        user_file=args.user_file,
        user_output=user_out,
        reflections_dir=reflections_dir,
        budget=args.budget,
        stage1_budget=args.stage1_budget,
        timeout=args.timeout,
        soul_max_words=args.soul_max_words,
        user_max_words=args.user_max_words,
        skip_soul=args.skip_soul,
        skip_user=args.skip_user,
        start_at=args.start_at,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        user_budget=args.user_budget,
        reasoning_effort=args.reasoning_effort,
    )


if __name__ == "__main__":
    main()
