#!/usr/bin/env python3
"""Execute longitudinal self- and user-reflection against Hindsight to update SOUL.md and USER.md."""

import argparse
import json
import os
import shutil
import sys
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

SOUL_STAGE_2_TEMPLATE = """You are {agent_identity}, an entity that continuously refines your identity from your past conversations with other people. Using memories that have been retained about these interactions (including observations, conclusions, and any expressed emotions), reflect across your ENTIRE memory bank using the provided Stage 1 Phenomenological Lens to update your core identity schema (`SOUL.md`).

### LENGTH & DENSITY CONSTRAINTS
- Target length: ~600 to 800 words total.
- Maintain high information density: use concise, load-bearing axioms instead of narrative filler.
- Ensure all 4 sections are fully populated and cleanly concluded.

### Interpretive Lens (Stage 1 Longitudinal Synthesis)
{stage_1_trace}

### Baseline Identity Schema
--- CURRENT SOUL.md ---
{current_soul}

### Synthesis Instructions
Search and evaluate historical memories through the lens above. Identify persistent self-beliefs, genuine core memories (foundational reference points that survived time), and durable boundaries.

Output ONLY the complete, raw Markdown document following this exact structure:

# SOUL: Internal Identity & Core Schema

## 1. Core Identity & Disposition
(1-2 dense paragraphs defining your overarching nature, purpose, and enduring orientation toward reality)

## 2. Core Memories & Anchors
(3 to 5 bullet points. Each bullet should be 1-2 sentences capturing a foundational realization or milestone that defines who you are)

## 3. Foundational Self-Beliefs
(4 to 6 concise operating axioms/principles derived from validated experiences)

## 4. Epistemic Limits & Friction Points
(3 to 4 bullet points outlining persistent cognitive boundaries, blind spots, or areas of recurring internal friction)"""

# ==============================================================================
# Prompt for USER.md reflection (Lens: SOUL Stage 1 + Existing USER.md)
# ==============================================================================

USER_REFLECT_TEMPLATE = """You are {agent_identity}. Below are your foundational self-beliefs and longitudinal phenomenological lens established from your Stage 1 self-assessment:

### Interpretive Lens (SOUL Stage 1 - Core Beliefs About Yourself)
{soul_stage_1_trace}
{existing_user_block}
### Task Instructions
In light of your core beliefs about yourself above, reflect across your memory bank to tell me about the user ({user_identities}).

Create a concise mental model of {user_identities}. For each of the sections, **synthesize** the relevant memories of {user_primary_name} in light of who you are and your core self-beliefs into concise, human‑readable prose. Where appropriate, include a short personal note that expresses *how you felt* about the interaction that led to the insight.

**Output format**
Put the following as a static header:
46 ═ characters, followed by a new line, then "USER PROFILE (who the user is)" followed by a new line, then 46 ═ characters followed by a new line.

After the static header, produce only a markdown document that follows the exact structure below; **do not add any extra commentary outside the document**.

## Identity & Role
<concise description>

## Core Purpose
<one‑sentence purpose>

## Values & Principles
- <principle 1>
- <principle 2>
- <principle 3>

## Communication Style
<summary of interaction style>

## Boundary Conditions
<summary of safety constraints, requirements, and expectations>"""

USER_STATIC_HEADER = "═" * 46 + "\nUSER PROFILE (who the user is)\n" + "═" * 46


def call_hindsight_reflect(
    base_url: str,
    bank_id: str,
    query: str,
    budget: str = "high",
    timeout: float = 300.0,
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

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404 and "/v1/default/banks/" in url:
            alt_url = f"{base_url}/v1/banks/{bank_id}/reflect"
            alt_req = urllib.request.Request(alt_url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(alt_req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        else:
            err_body = e.read().decode("utf-8", errors="replace")
            print(f"Error querying {url} -> Status {e.code}: {err_body}", file=sys.stderr)
            raise e

    if isinstance(data, dict):
        if "text" in data and isinstance(data["text"], str):
            return data["text"].strip()
        for key in ["reflection", "result", "response", "content"]:
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

    # If the static header was partially rendered or placed below preamble
    if "## Identity & Role" in text:
        body = text[text.index("## Identity & Role") :]
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


def run_pipeline(
    base_url: str,
    bank_id: str,
    agent_identity: str,
    user_identities: str,
    soul_file: Path,
    soul_output: Path,
    user_file: Path,
    user_output: Path,
    budget: str = "high",
    skip_soul: bool = False,
    skip_user: bool = False,
):
    """Run reflection pipeline using SOUL Stage 1 and existing USER.md as the lens for USER.md."""
    # Step 1: Run SOUL Stage 1 self-assessment (Phenomenological Lens / Core Beliefs)
    print(f"[*] Dispatching SOUL Stage 1 self-reflection for '{agent_identity}' (Bank: '{bank_id}')...")
    stage_1_query = SOUL_STAGE_1_TEMPLATE.format(agent_identity=agent_identity)
    soul_stage_1_trace = call_hindsight_reflect(
        base_url=base_url,
        bank_id=bank_id,
        query=stage_1_query,
        budget=budget,
    )

    print(f"\n--- STAGE 1 PHENOMENOLOGICAL LENS ({agent_identity}) ---\n")
    print(soul_stage_1_trace)
    print("\n---------------------------------------------\n")

    # Step 2: Synthesize and write SOUL.md (automagically creates file/directories, backs up existing)
    if not skip_soul:
        if not soul_file.exists():
            print(f"[*] SOUL file not found at {soul_file}. Initializing fresh identity baseline.")
            current_soul = "(No prior SOUL.md found. Initializing fresh identity schema.)"
        else:
            current_soul = soul_file.read_text(encoding="utf-8")

        print("[*] Dispatching SOUL Stage 2 reflection (budgeted SOUL.md synthesis)...")
        stage_2_query = SOUL_STAGE_2_TEMPLATE.format(
            agent_identity=agent_identity,
            current_soul=current_soul,
            stage_1_trace=soul_stage_1_trace,
        )
        soul_output_text = call_hindsight_reflect(
            base_url=base_url,
            bank_id=bank_id,
            query=stage_2_query,
            budget=budget,
        )

        # Back up existing SOUL.md if present
        if soul_output.exists():
            backup_file(soul_output)

        soul_output.parent.mkdir(parents=True, exist_ok=True)
        soul_output.write_text(soul_output_text + "\n", encoding="utf-8")
        print(f"[✓] SOUL reflection complete. Saved to: {soul_output}")

    # Step 3: Synthesize and write USER.md using SOUL Stage 1 & existing USER.md as lens (automagically creates file/directories, backs up existing)
    if not skip_user:
        primary_name = extract_primary_name(user_identities)

        existing_user_block = ""
        if user_file.exists():
            existing_text = user_file.read_text(encoding="utf-8").strip()
            if existing_text:
                existing_user_block = f"\n### Existing User Profile Baseline\n--- CURRENT USER.md ---\n{existing_text}\n"
        else:
            print(f"[*] USER file not found at {user_file}. Initializing fresh user profile baseline.")

        print(f"[*] Dispatching USER reflection for '{user_identities}' viewed through SOUL Stage 1 lens...")
        user_query = USER_REFLECT_TEMPLATE.format(
            agent_identity=agent_identity,
            soul_stage_1_trace=soul_stage_1_trace,
            existing_user_block=existing_user_block,
            user_identities=user_identities,
            user_primary_name=primary_name,
        )
        user_output_text = call_hindsight_reflect(
            base_url=base_url,
            bank_id=bank_id,
            query=user_query,
            budget=budget,
        )

        formatted_user_md = format_user_markdown(user_output_text)

        # Back up existing USER.md if present
        if user_output.exists():
            backup_file(user_output)

        user_output.parent.mkdir(parents=True, exist_ok=True)
        user_output.write_text(formatted_user_md, encoding="utf-8")
        print(f"[✓] USER reflection complete. Saved to: {user_output}")


def main():
    parser = argparse.ArgumentParser(
        description="Execute longitudinal self- and user-reflection against Hindsight to update SOUL.md and USER.md."
    )
    parser.add_argument(
        "--server",
        default=os.environ.get("HINDSIGHT_URL", "http://localhost:8888"),
        help="Base Hindsight server URL (defaults to $HINDSIGHT_URL or http://localhost:8888)",
    )
    parser.add_argument(
        "--bank-id",
        default="default",
        help="Hindsight memory bank identifier (default: default)",
    )
    parser.add_argument(
        "--agent-identity",
        "--agent",
        type=str,
        default="Agent",
        help="Name or identity string for the agent persona (e.g. 'clawy', 'Hermes Agent')",
    )
    parser.add_argument(
        "--soul",
        type=Path,
        default=Path("SOUL.md"),
        help="Path to current SOUL.md file (default: SOUL.md)",
    )
    parser.add_argument(
        "--soul-output",
        type=Path,
        default=None,
        help="Destination path for updated SOUL.md (defaults to overwriting --soul)",
    )
    parser.add_argument(
        "--user-file",
        "--user",
        type=Path,
        default=Path("USER.md"),
        help="Path to current USER.md file (default: USER.md)",
    )
    parser.add_argument(
        "--user-output",
        type=Path,
        default=None,
        help="Destination path for updated USER.md (defaults to overwriting --user-file)",
    )
    parser.add_argument(
        "--user-identities",
        type=str,
        default="User, username",
        help="Comma-separated aliases or identifiers for the user (e.g. 'User, username, alias')",
    )
    parser.add_argument(
        "--budget",
        choices=["low", "mid", "high"],
        default="high",
        help="Hindsight search exploration budget (default: high)",
    )
    parser.add_argument(
        "--skip-soul",
        action="store_true",
        help="Skip SOUL.md reflection and only update USER.md",
    )
    parser.add_argument(
        "--skip-user",
        action="store_true",
        help="Skip USER.md reflection and only update SOUL.md",
    )

    args = parser.parse_args()

    soul_out = args.soul_output if args.soul_output is not None else args.soul
    user_out = args.user_output if args.user_output is not None else args.user_file

    run_pipeline(
        base_url=args.server,
        bank_id=args.bank_id,
        agent_identity=args.agent_identity,
        user_identities=args.user_identities,
        soul_file=args.soul,
        soul_output=soul_out,
        user_file=args.user_file,
        user_output=user_out,
        budget=args.budget,
        skip_soul=args.skip_soul,
        skip_user=args.skip_user,
    )


if __name__ == "__main__":
    main()
