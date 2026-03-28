#!/usr/bin/env python3
"""
Delusionist Factory MCP Server (Antigravity Optimized)

MCP (Model Context Protocol) server wrapping Delusionist Factory
for seamless integration with Antigravity AI agent.
"""

import os
import json
import random
import asyncio
from typing import Any

# MCP SDK imports
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Delusionist Factory class import
from main import DelusionistFactory, FileLock


# Initialize MCP server
server = Server("delusionist-factory")

# Factory instance
factory = DelusionistFactory()

# Word pool line counts (pre-calculated constants)
WORD_POOL_LINE_COUNTS = {
    "extracted_words.txt": 917273,  # Korean word pool
    "100000word.txt": 466551,       # English word pool
}


def get_word_pool_path(factory_instance: DelusionistFactory, is_korean: bool) -> str:
    """Get word pool file path based on language."""
    if is_korean:
        return os.path.join(factory_instance.base_dir, 'extracted_words.txt')
    else:
        return os.path.join(factory_instance.base_dir, '100000word.txt')


def get_line_count(filepath: str) -> int:
    """Get total line count of a file (uses pre-calculated constants)."""
    filename = os.path.basename(filepath)
    return WORD_POOL_LINE_COUNTS.get(filename, 10000)  # Default fallback


def get_random_words_from_file(filepath: str, count: int = 3) -> list[str]:
    """
    Get random words by picking random line numbers first,
    then reading only those lines using linecache (cached after first read).
    """
    import linecache
    
    total_lines = get_line_count(filepath)
    if total_lines == 0:
        return []
    
    # Pick random line numbers (1-indexed for linecache)
    target_lines = random.sample(range(1, total_lines + 1), min(count, total_lines))
    
    # Read only the target lines using linecache (caches file after first read)
    words = []
    for line_num in target_lines:
        line = linecache.getline(filepath, line_num)
        stripped = line.strip()
        if stripped:
            words.append(stripped)
    
    return words


def get_step_instructions(step: int, factory_instance: DelusionistFactory) -> str:
    """Generate step-specific instructions without stdout capture."""
    req = factory_instance.load_request()
    if not req:
        return "ERROR: request.json not found!"
    
    state = factory_instance.load_state()
    
    starting = req.get("STARTING_SENTENCE", "")
    mandatory = req.get("MANDATORY_WORD", [])
    imagery = req.get("PREFERRED_IMAGERY", [])
    chains_target = req.get("CHAINS_COUNT", 120)
    mode = req.get("MODE_SELECTION", "CHAOS").strip().upper()
    selection_b_count = req.get("SELECTION_B_COUNT", 8)
    refining_count = req.get("REFINING_COUNT", 2)
    direction = req.get("DIRECTION", "")
    step1_executor = (req.get("STEP1_EXECUTOR") or "GEMINI_CLI").strip().upper()
    if step1_executor not in ("GEMINI_CLI", "SELF"):
        step1_executor = "GEMINI_CLI"
    
    # Determine if Korean
    content_to_check = starting + direction
    import re
    is_korean = bool(re.search("[가-힣]", content_to_check))
    
    # Get word pool path
    word_pool_path = get_word_pool_path(factory_instance, is_korean)
    
    # Step 1: Chaining (external or self)
    if step == 1:
        chains_done = factory_instance.count_lines(factory_instance.section_a_path)
        
        if chains_done >= chains_target:
            # Advance to Step 2
            state["current_step"] = 2
            factory_instance.save_state(state)
            return f"STEP 1 COMPLETE ({chains_done} chains). Advancing to Step 2. Call run_delusionist again."

        if step1_executor == "GEMINI_CLI":
            # Create a ready-to-run Gemini prompt file for this batch.
            try:
                step1_batch_size = req.get("STEP1_BATCH_SIZE", 30)
                info = factory_instance.prepare_step1_gemini_prompt(batch_size=step1_batch_size)
            except Exception as e:
                return f"STEP 1 is external (Gemini CLI), but prompt preparation failed: {e}"

            return f"""
=== STEP 1: EXTERNAL (Gemini CLI) ===
Progress: {chains_done}/{chains_target}

NOTE:
- MCP/Agent deliberately SKIPS generating Step 1 (A-stage).
- Run Gemini CLI locally, then append the resulting lines to:
  {factory_instance.section_a_path}

Batch / ETA:
- Batch: {info['batch_index']}/{info['total_batches']} (this batch writes lines {info['batch_start']}~{info['batch_end']})
- ETA (rough): {info['eta_text']}

Prompt File:
- {info['prompt_path']}

Command:
- {info['cmd']}

After you append enough lines, call run_delusionist again and it will advance to Step 2.
"""

        # SELF: Provide agent instructions with random words similar to the original design.
        BATCH_SIZE = req.get("STEP1_BATCH_SIZE", 30)
        remaining = chains_target - chains_done
        current_batch = min(BATCH_SIZE, remaining)
        batch_start = chains_done + 1
        batch_end = chains_done + current_batch

        batch_random_words = []
        for _ in range(current_batch):
            batch_random_words.append(get_random_words_from_file(word_pool_path, 3))

        random_words_section = "\n".join([
            f"  [{i:03d}] {', '.join(words)}"
            for i, words in enumerate(batch_random_words, start=batch_start)
        ])

        return f"""
=== STEP 1: CHAINING (SELF) ===
Batch: #{batch_start} ~ #{batch_end} / {chains_target}
Progress: {chains_done}/{chains_target}

CONFIG:
- Starting Sentence: {starting}
- Mandatory Words: {', '.join(mandatory)}
- Mode: {mode}
- Preferred Imagery: {', '.join(imagery)}

RANDOM WORDS FOR THIS BATCH:
{random_words_section}

YOUR TASK:
1. Generate {current_batch} \"delusional variant sentences\" using the random words above
2. MUST include mandatory words ({', '.join(mandatory)}) in EVERY sentence
3. LANGUAGE RULE: No 3+ consecutive foreign words when mixing Korean/English
4. Call append_result with step=\"1\" and your generated sentences

After appending, call run_delusionist again to continue.
"""
    
    # Step 2: Refining
    elif step == 2:
        refined_done = factory_instance.count_lines(factory_instance.section_b_path)
        
        if refined_done >= selection_b_count:
            state["current_step"] = 3
            factory_instance.save_state(state)
            return f"STEP 2 COMPLETE ({refined_done} refined). Advancing to Step 3. Call run_delusionist again."
        
        BATCH_SIZE = 10
        remaining = selection_b_count - refined_done
        current_batch = min(BATCH_SIZE, remaining)
        
        return f"""
=== STEP 2: REFINING CoT ===
Progress: {refined_done}/{selection_b_count}

CONFIG:
- Direction: {direction[:100]}...
- Preferred Imagery: {', '.join(imagery)}

YOUR TASK:
1. Read section_a_chains.txt (use read_output_file with step="1")
2. Analyze all chains and extract key words/phrases matching DIRECTION and IMAGERY
3. Apply INGENUOUS filter: Select only ingenuous and innovative expressions
4. Generate {current_batch} "refined delusional sentences" including mandatory words
5. Each refined sentence MUST end with a parenthetical annotation: what was impressive, how it can be used as material/structure in C-stage, possible expansion directions (1-2 sentences)
6. Call append_result with step="2" and your generated sentences

After appending, call run_delusionist again to continue.
"""
    
    # Step 3: Final
    elif step == 3:
        final_done = factory_instance.count_lines(factory_instance.section_c_path)
        step3_finalized = state.get("step3_finalized", False)

        if step3_finalized:
            return f"""
=== ALL STEPS COMPLETE ===
Section A (Chains): {os.path.basename(factory_instance.section_a_path)}
Section B (Refined): {os.path.basename(factory_instance.section_b_path)}
Section C (Final): {os.path.basename(factory_instance.section_c_path)}

Use read_output_file with step="3" to view final results.
"""

        return f"""
=== STEP 3: FINAL CoT ===
Progress: {final_done} lines appended (target: {refining_count} entries, not finalized)

YOUR TASK:
1. Read section_b_refined.txt (use read_output_file with step="2")
2. Read the [기대치 정의] block in DIRECTION — exceed that ceiling. "This is fine" is failure; "I didn't expect this" is the target.
3. Stay VERTICALLY within the frame DIRECTION sets. Do not escape to adjacent domains. Go deeper, not wider.
4. Expand meanings to create appropriate-level final strategies/outputs ({refining_count} items)
5. Call append_result with step="3" and your generated outputs
6. On your LAST append, pass finalize=true to mark Step 3 as complete.
   → Step 3 does NOT auto-complete by line count. You must explicitly finalize.
   → You can append in multiple batches. Only the last one needs finalize=true.

After finalizing, call run_delusionist to confirm completion.
"""
    
    return "ERROR: Invalid step number"


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return list of available tools."""
    return [
        Tool(
            name="get_request_guide",
            description="""[CALL THIS FIRST] Get the full REQUEST_GUIDE.md — the complete operations manual for Delusionist Factory.

IMPORTANT: Call this tool BEFORE calling run_delusionist or update_request_config for the first time in a session.
It explains the 3-step pipeline, all request.json fields, DIRECTION framework, creative design principles, and anti-patterns.
Without reading this guide, you will misconfigure the factory and produce poor results.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="run_delusionist",
            description="""Execute Delusionist Factory - Creative delusional sentence generation pipeline.

Checks current state and returns Agent task instructions for the next Step:
- Step 1: (SKIPPED) External via Gemini CLI. MCP will provide the prompt/command only.
- Step 2: Refining CoT (Extract refined sentences)
- Step 3: Final CoT (Generate final outputs)

Follow the returned instructions, generate sentences, then call append_result.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "config_update": {
                        "type": "object",
                        "description": "Optional configuration update to apply specifically for this run (merges with request.json)",
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_status",
            description="Get current Delusionist Factory progress status including step, counts, and mode.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="append_result",
            description="""Append generated sentences to the output file for the specified step.

Arguments:
- step: Step number as STRING ("1", "2", or "3")
- content: Sentences to append (newline separated)
- finalize: (Step 3 only) Set to true on the LAST append to signal completion. Step 3 will NOT auto-complete by line count — it waits for this explicit signal.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "step": {
                        "type": "string",
                        "description": "Step number: '1' for section_a, '2' for section_b, '3' for section_c",
                        "enum": ["1", "2", "3"]
                    },
                    "content": {
                        "type": "string",
                        "description": "Sentences to append (newline separated)"
                    },
                    "finalize": {
                        "type": "boolean",
                        "description": "Step 3 only: set true on the last append to mark Step 3 as complete",
                        "default": False
                    }
                },
                "required": ["step", "content"]
            }
        ),
        Tool(
            name="get_request_config",
            description="Get current request.json configuration settings.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="update_request_config",
            description="""Update request.json configuration.

Arguments:
- config: Configuration object to update (full or partial)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "description": "Configuration object to update"
                    }
                },
                "required": ["config"]
            }
        ),
        Tool(
            name="reset_factory",
            description="Reset Delusionist Factory to initial state (clears output/ and staging/ folders).",
            inputSchema={
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "Confirmation flag (must be true to execute)"
                    }
                },
                "required": ["confirm"]
            }
        ),
        Tool(
            name="get_random_words",
            description="""Get random words from the word pool (uses Python random.sample).

Arguments:
- count: Number of words to extract (default: 3)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of words to extract",
                        "default": 3
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="read_output_file",
            description="""Read contents of a specific step's output file.

Arguments:
- step: Step number as STRING ("1", "2", or "3")""",
            inputSchema={
                "type": "object",
                "properties": {
                    "step": {
                        "type": "string",
                        "description": "Step number: '1' for section_a, '2' for section_b, '3' for section_c",
                        "enum": ["1", "2", "3"]
                    }
                },
                "required": ["step"]
            }
        ),
        Tool(
            name="prepare_parallel_gemini_workers",
            description="""Step 1(Chaining) 병렬 Gemini CLI 워커 준비.

남은 chains를 분할하고 각 워커용 프롬프트를 staging/worker_{id}_prompt.txt에 저장한다.
Operator(메인 에이전트)가 반환된 cmd를 run_command로 직접 병렬 실행하고,
응답을 append_result로 올리는 방식 — sub-agent 토큰이 0이 된다.

반환: 워커별 {worker_id, line_count, prompt_path, cmd, batch_start, batch_end} 배열.

두 가지 모드 (batch_size 우선):
- batch_size: 워커당 줄 수 지정 → 워커 수 자동 계산
- worker_count: 워커 수 직접 지정 → 줄을 균등 분할
둘 다 미지정 시 batch_size=25 기본값.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "worker_count": {
                        "type": "integer",
                        "description": "병렬 워커 수. batch_size와 동시 지정 시 batch_size 우선."
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "워커당 줄 수. 지정 시 워커 수를 자동 계산 (ceil(remaining / batch_size))."
                    }
                },
                "required": []
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute tool."""
    
    if name == "get_request_guide":
        guide_path = os.path.join(factory.base_dir, "REQUEST_GUIDE.md")
        if not os.path.exists(guide_path):
            return [TextContent(type="text", text="ERROR: REQUEST_GUIDE.md not found")]
        with open(guide_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return [TextContent(type="text", text=content)]

    elif name == "run_delusionist":
        config_update = arguments.get("config_update")
        
        # 1. Update request.json if config_update is provided
        if config_update:
            current = factory.load_request() or {}
            current.update(config_update)
            with open(factory.request_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
                
        # If we're at Step 1 and chains aren't done:
        # - GEMINI_CLI: return external prompt/command (don't run main.py)
        # - SELF: run main.py (prints instructions for the agent) as usual
        state = factory.load_state()
        step = state.get("current_step", 1)
        if step == 1:
            req = factory.load_request() or {}
            step1_executor = (req.get("STEP1_EXECUTOR") or "GEMINI_CLI").strip().upper()
            chains_target = req.get("CHAINS_COUNT", 120)
            chains_done = factory.count_lines(factory.section_a_path)
            if step1_executor == "GEMINI_CLI" and chains_done < chains_target:
                text = get_step_instructions(1, factory)
                return [TextContent(type="text", text=text)]

        import subprocess
        import sys

        # 2. Run main.py via subprocess to capture all output
        result = subprocess.run(
            [sys.executable, "main.py"],
            cwd=factory.base_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            print(f"[run_delusionist] stderr: {result.stderr}", file=sys.stderr)
            return [TextContent(type="text", text=f"Error running pipeline (exit {result.returncode}). Check server logs.")]
        output = result.stdout or "No output from main.py"
        return [TextContent(type="text", text=output)]
    
    elif name == "get_status":
        state = factory.load_state()
        req = factory.load_request()

        if not req:
            return [TextContent(type="text", text="ERROR: request.json not found")]

        chains_done = factory.count_lines(factory.section_a_path)
        refined_done = factory.count_lines(factory.section_b_path)
        final_done = factory.count_lines(factory.section_c_path)
        step3_finalized = state.get("step3_finalized", False)

        # Step 3: show finalize status instead of misleading line-count ratio
        if step3_finalized:
            step3_display = f"finalized ({final_done} lines)"
        elif final_done > 0:
            step3_display = f"{final_done} lines appended (not finalized)"
        else:
            step3_display = f"0/{req.get('REFINING_COUNT', 2)}"

        status = {
            "current_step": state.get("current_step", 1),
            "progress": {
                "step1_chains": f"{chains_done}/{req.get('CHAINS_COUNT', 120)}",
                "step2_refined": f"{refined_done}/{req.get('SELECTION_B_COUNT', 8)}",
                "step3_final": step3_display
            },
            "mode": req.get("MODE_SELECTION", "CHAOS"),
            "starting_sentence": req.get("STARTING_SENTENCE", "")
        }

        return [TextContent(type="text", text=json.dumps(status, ensure_ascii=False, indent=2))]
    
    elif name == "append_result":
        step_str = arguments.get("step", "")
        content = arguments.get("content", "")
        finalize = arguments.get("finalize", False)

        # Convert string step to int
        try:
            step = int(step_str)
        except (ValueError, TypeError):
            return [TextContent(type="text", text=f"ERROR: Invalid step '{step_str}'. Must be '1', '2', or '3'")]

        if step == 1:
            filepath = factory.section_a_path
        elif step == 2:
            filepath = factory.section_b_path
        elif step == 3:
            filepath = factory.section_c_path
        else:
            return [TextContent(type="text", text=f"ERROR: Invalid step {step}. Must be 1, 2, or 3")]

        # 파일 잠금으로 병렬 에이전트의 동시 쓰기 방지
        factory.locked_append(filepath, content)

        lines_added = len([l for l in content.strip().split('\n') if l.strip()])
        msg = f"SUCCESS: Appended {lines_added} lines to {os.path.basename(filepath)}"

        # Step 3 finalize: set flag in state.json so run_delusionist knows we're done
        if finalize and step == 3:
            state = factory.load_state()
            state["step3_finalized"] = True
            factory.save_state(state)
            msg += " | FINALIZED: Step 3 marked as complete."

        return [TextContent(type="text", text=msg)]
    
    elif name == "get_request_config":
        req = factory.load_request()
        if not req:
            return [TextContent(type="text", text="ERROR: request.json not found")]
        return [TextContent(type="text", text=json.dumps(req, ensure_ascii=False, indent=2))]
    
    elif name == "update_request_config":
        config = arguments.get("config", {})
        _NUMERIC_LIMITS = {
            "CHAINS_COUNT": (1, 700),
            "SELECTION_B_COUNT": (1, 200),
            "REFINING_COUNT": (1, 200),
            "STEP1_BATCH_SIZE": (1, 100),
        }
        for key, (lo, hi) in _NUMERIC_LIMITS.items():
            if key in config and isinstance(config[key], (int, float)):
                config[key] = max(lo, min(hi, int(config[key])))
        with FileLock(factory.config_lock_path):
            current = factory.load_request() or {}
            current.update(config)
            with open(factory.request_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)

        return [TextContent(type="text", text="SUCCESS: Updated request.json")]
    
    elif name == "reset_factory":
        if not arguments.get("confirm", False):
            return [TextContent(type="text", text="ERROR: confirm must be true to reset")]

        # Clear output
        if os.path.exists(factory.output_dir):
            for f in os.listdir(factory.output_dir):
                filepath = os.path.join(factory.output_dir, f)
                if os.path.isfile(filepath):
                    os.remove(filepath)

        # Clear staging (state, lock files, prompts)
        if os.path.exists(factory.staging_dir):
            for f in os.listdir(factory.staging_dir):
                filepath = os.path.join(factory.staging_dir, f)
                if os.path.isfile(filepath):
                    os.remove(filepath)

        return [TextContent(type="text", text="SUCCESS: Factory reset complete")]
    
    elif name == "get_random_words":
        count = min(max(int(arguments.get("count", 3)), 1), 100)
        
        # Determine word pool based on request
        req = factory.load_request()
        if not req:
            return [TextContent(type="text", text="ERROR: request.json not found")]
        
        starting = req.get("STARTING_SENTENCE", "")
        direction = req.get("DIRECTION", "")
        content_to_check = starting + direction
        
        # Check language preference first
        final_lang = req.get("FINAL_LANGUAGE", "").strip().upper()
        
        if final_lang == "KOREAN":
            is_korean = True
        elif final_lang == "ENGLISH":
            is_korean = False
        else:
            # Fallback to auto-detection
            import re
            is_korean = bool(re.search("[가-힣]", content_to_check))
        
        # Get random words using efficient file reading
        word_pool_path = get_word_pool_path(factory, is_korean)
        words = get_random_words_from_file(word_pool_path, count)
        
        return [TextContent(type="text", text=json.dumps(words, ensure_ascii=False))]
    
    elif name == "read_output_file":
        step_str = arguments.get("step", "")
        
        # Convert string step to int
        try:
            step = int(step_str)
        except (ValueError, TypeError):
            return [TextContent(type="text", text=f"ERROR: Invalid step '{step_str}'. Must be '1', '2', or '3'")]
        
        if step == 1:
            filepath = factory.section_a_path
        elif step == 2:
            filepath = factory.section_b_path
        elif step == 3:
            filepath = factory.section_c_path
        else:
            return [TextContent(type="text", text=f"ERROR: Invalid step {step}. Must be 1, 2, or 3")]
        
        if not os.path.exists(filepath):
            return [TextContent(type="text", text=f"File not found (empty): {os.path.basename(filepath)}")]
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if not content.strip():
            return [TextContent(type="text", text=f"File is empty: {os.path.basename(filepath)}")]
        
        return [TextContent(type="text", text=content)]
    
    elif name == "prepare_parallel_step1":
        batch_size = arguments.get("batch_size")
        worker_count = arguments.get("worker_count")

        if batch_size is not None and batch_size < 1:
            return [TextContent(type="text", text="ERROR: batch_size must be >= 1")]
        if worker_count is not None and worker_count < 1:
            return [TextContent(type="text", text="ERROR: worker_count must be >= 1")]

        try:
            batches = factory.prepare_parallel_batches(
                worker_count=worker_count,
                batch_size=batch_size,
            )
        except RuntimeError as e:
            return [TextContent(type="text", text=f"ERROR: {e}")]

        if not batches:
            return [TextContent(type="text", text="Step 1 already complete. Call run_delusionist to advance.")]

        result = {
            "total_workers": len(batches),
            "total_lines": sum(b["line_count"] for b in batches),
            "workers": batches,
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    elif name == "prepare_parallel_gemini_workers":
        batch_size = arguments.get("batch_size")
        worker_count = arguments.get("worker_count")

        if batch_size is not None and batch_size < 1:
            return [TextContent(type="text", text="ERROR: batch_size must be >= 1")]
        if worker_count is not None and worker_count < 1:
            return [TextContent(type="text", text="ERROR: worker_count must be >= 1")]

        try:
            workers = factory.prepare_parallel_gemini_workers(
                worker_count=worker_count,
                batch_size=batch_size,
            )
        except RuntimeError as e:
            return [TextContent(type="text", text=f"ERROR: {e}")]

        if not workers:
            return [TextContent(type="text", text="Step 1 already complete. Call run_delusionist to advance.")]

        result = {
            "total_workers": len(workers),
            "total_lines": sum(w["line_count"] for w in workers),
            "workers": workers,
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    else:
        return [TextContent(type="text", text=f"ERROR: Unknown tool '{name}'")]


async def main():
    """Run MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
