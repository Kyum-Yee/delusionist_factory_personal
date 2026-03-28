
import os
import sys
import json
import random
import logging
import shutil
import fcntl
import shlex

# Configure logging to stderr explicitly (avoid polluting stdout for MCP)
logging.basicConfig(level=logging.INFO, format='[DELUSIONIST] %(message)s', stream=sys.stderr)


class FileLock:
    """프로세스 간 파일 잠금 (fcntl.flock 기반). 병렬 에이전트의 동시 쓰기 방지."""

    def __init__(self, lock_path):
        self.lock_path = lock_path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        self.f = open(self.lock_path, 'w')
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *args):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


class DelusionistFactory:
    DEFAULT_STEP1_MODE = "GEMINI_CLI"  # A-step is external by default
    # Avoid hardcoding a specific model to prevent churn; let `gemini` CLI pick its default.
    DEFAULT_GEMINI_MODEL = ""

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.input_dir = os.path.join(self.base_dir, 'input')
        self.output_dir = os.path.join(self.base_dir, 'output')
        self.staging_dir = os.path.join(self.base_dir, 'staging')
        
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.staging_dir, exist_ok=True)
        
        self.request_path = os.path.join(self.input_dir, 'request.json')
        self.word_pool_path = None  # Will be set dynamically in run() based on request.json
        self.state_path = os.path.join(self.staging_dir, 'state.json')
        
        # Output files for each step
        self.section_a_path = os.path.join(self.output_dir, 'section_a_chains.txt')
        self.section_b_path = os.path.join(self.output_dir, 'section_b_refined.txt')
        self.section_c_path = os.path.join(self.output_dir, 'section_c_final.txt')

        # Lock files for concurrent access
        self.append_lock_path = os.path.join(self.staging_dir, 'append.lock')
        self.state_lock_path = os.path.join(self.staging_dir, 'state.lock')
        self.config_lock_path = os.path.join(self.staging_dir, 'config.lock')

    def _format_duration(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        if m <= 0:
            return f"{s}s"
        return f"{m}m {s:02d}s"

    def _gemini_available(self) -> bool:
        return shutil.which("gemini") is not None

    def _resolve_language_and_pool(self, req: dict) -> tuple[str, str]:
        starting = req.get("STARTING_SENTENCE", "")
        direction = req.get("DIRECTION", "")
        final_language = req.get("FINAL_LANGUAGE", "Korean")

        # 1) Explicit preference
        final_lang_upper = str(final_language).strip().upper()
        if final_lang_upper == "KOREAN":
            is_korean = True
        elif final_lang_upper == "ENGLISH":
            is_korean = False
        else:
            # 2) Auto-detection fallback
            content_to_check = str(starting) + str(direction)
            is_korean = self._is_korean(content_to_check)

        if is_korean:
            return (os.path.join(self.base_dir, 'extracted_words.txt'), "Korean")
        return (os.path.join(self.base_dir, '100000word.txt'), "English")

    def _build_step1_gemini_prompt(
        self,
        direction: str,
        starting: str,
        mandatory: list[str],
        imagery: list[str],
        language_rule: str,
        batch_start: int,
        batch_random_words: list[list[str]],
    ) -> str:
        # Keep prompt compact but strict about output formatting for easy parsing.
        lines = []
        lines.append("You are generating creative Korean sentences for a pipeline step called STEP 1 (CHAINING).")
        lines.append("")
        lines.append("OUTPUT FORMAT (STRICT):")
        lines.append(f"- Return exactly {len(batch_random_words)} lines.")
        lines.append("- Each line starts with a 3-digit number (e.g., 001, 002...) followed by a period and space, then the sentence.")
        lines.append("- In each sentence, wrap the random words (or their domain-adapted variants) in markdown bold (**word**). At least 3 bold words per line.")
        lines.append("- End each sentence with a parenthetical annotation: what collision emerged, what direction it could go. e.g., (충돌: 빙하+요리 → 느린 해동 조리법 가능성)")
        lines.append("- No titles, no explanations, no extra blank lines.")
        lines.append("")
        lines.append("CONSTRAINTS:")
        if mandatory:
            lines.append(f"- Every line MUST include ALL mandatory words exactly as written: {', '.join(mandatory)}")
        if language_rule:
            lines.append(f"- LANGUAGE_RULE: {language_rule}")
        if imagery:
            lines.append(f"- Prefer imagery motifs: {', '.join(imagery)}")
        lines.append("- The sentences should feel like a surreal collision (bold, unexpected connections), but still read naturally.")
        lines.append("- Random words are for context pollution: you may replace them with context-fitting variants if needed, but keep the 'collision' spirit.")
        lines.append("")
        lines.append("CONTEXT:")
        if direction:
            lines.append("DIRECTION:")
            lines.append(direction.strip())
            lines.append("")
        if starting:
            lines.append("STARTING_SENTENCE (seed tone/energy, do not copy verbatim if awkward):")
            lines.append(starting.strip())
            lines.append("")
        lines.append("RANDOM WORDS PER LINE:")
        for idx, words in enumerate(batch_random_words, start=batch_start):
            joined = ", ".join(words)
            lines.append(f"- Line {idx}: {joined}")
        lines.append("")
        lines.append("Now produce the lines.")
        return "\n".join(lines).strip() + "\n"

    def prepare_step1_gemini_prompt(self, batch_size: int = 30) -> dict:
        """
        Prepares the STEP 1 Gemini prompt (external execution) and writes it to staging.
        Returns metadata including the prompt path and recommended CLI command.
        """
        req = self.load_request()
        if not req:
            raise RuntimeError("request.json not found")

        chains_target = req.get("CHAINS_COUNT", 100)
        direction = req.get("DIRECTION", "")
        starting = req.get("STARTING_SENTENCE", "")
        mandatory = req.get("MANDATORY_WORD", [])
        imagery = req.get("PREFERRED_IMAGERY", [])
        language_rule = req.get("LANGUAGE_RULE", "NO_3_CONSECUTIVE_FOREIGN_WORDS")

        chains_done = self.count_lines(self.section_a_path)
        remaining = max(0, int(chains_target) - int(chains_done))
        current_batch = min(int(batch_size), remaining)
        batch_start = chains_done + 1
        batch_end = chains_done + current_batch
        total_batches = (int(chains_target) + int(batch_size) - 1) // int(batch_size)
        batch_index = (int(chains_done) // int(batch_size)) + 1

        # Determine word pool based on request
        self.word_pool_path, detected_lang = self._resolve_language_and_pool(req)

        batch_random_words: list[list[str]] = []
        for _ in range(current_batch):
            batch_random_words.append(self.get_random_words_from_file(self.word_pool_path, 3))

        prompt = self._build_step1_gemini_prompt(
            direction=direction,
            starting=starting,
            mandatory=mandatory,
            imagery=imagery,
            language_rule=language_rule,
            batch_start=batch_start,
            batch_random_words=batch_random_words,
        )

        prompt_path = os.path.join(self.staging_dir, "step1_gemini_prompt.txt")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)

        model = os.getenv("DELUSIONIST_GEMINI_MODEL", self.DEFAULT_GEMINI_MODEL).strip()
        if model:
            cmd = f"gemini --output-format json --model {shlex.quote(model)} \"$(cat {shlex.quote(prompt_path)})\""
            model_label = model
        else:
            # If Gemini CLI updates its default (e.g. newer preview), this stays future-proof.
            cmd = f"gemini --output-format json \"$(cat {shlex.quote(prompt_path)})\""
            model_label = "(gemini CLI default)"

        # ETA: best-effort heuristic (configurable via env for your machine/model).
        # Defaults are intentionally conservative to avoid premature "it hung" assumptions.
        # Set:
        # - DELUSIONIST_STEP1_ETA_OVERHEAD_S (default 20)
        # - DELUSIONIST_STEP1_ETA_S_PER_LINE (default 1.2)
        overhead_s = float(os.getenv("DELUSIONIST_STEP1_ETA_OVERHEAD_S", "20").strip() or "20")
        per_line_s = float(os.getenv("DELUSIONIST_STEP1_ETA_S_PER_LINE", "1.2").strip() or "1.2")
        eta_s = int(overhead_s + (current_batch * per_line_s))
        # Give a range (x0.7 ~ x1.6) since network/auth variance is real.
        eta_low = int(eta_s * 0.7)
        eta_high = int(eta_s * 1.6)
        eta_text = f"~{self._format_duration(eta_low)} to {self._format_duration(eta_high)}"

        return {
            "prompt_path": prompt_path,
            "cmd": cmd,
            "chains_done": chains_done,
            "chains_target": chains_target,
            "current_batch": current_batch,
            "batch_start": batch_start,
            "batch_end": batch_end,
            "batch_index": batch_index,
            "total_batches": total_batches,
            "eta_text": eta_text,
            "detected_lang": detected_lang,
            "word_pool": os.path.basename(self.word_pool_path),
            "model": model_label,
        }

    def load_request(self):
        if not os.path.exists(self.request_path):
            return None
        with open(self.request_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    # Word pool line counts (pre-calculated constants to avoid loading full file)
    WORD_POOL_LINE_COUNTS = {
        "extracted_words.txt": 917273,  # Korean word pool
        "100000word.txt": 466551,       # English word pool
    }

    def get_line_count(self, filepath):
        """Get total line count using constants."""
        filename = os.path.basename(filepath)
        return self.WORD_POOL_LINE_COUNTS.get(filename, 10000)

    def get_random_words_from_file(self, filepath, count=3):
        """
        Efficient random word selection using linecache.
        Avoids loading 24MB+ text files into memory.
        """
        import linecache
        
        total_lines = self.get_line_count(filepath)
        if total_lines == 0:
            return []
        
        # Pick random line numbers (1-indexed for linecache)
        target_lines = random.sample(range(1, total_lines + 1), min(count, total_lines))
        
        words = []
        for line_num in target_lines:
            line = linecache.getline(filepath, line_num)
            stripped = line.strip()
            if stripped:
                words.append(stripped)
        
        return words

    def get_mode_ratio(self, mode):
        """모드별 Python 랜덤 vs AI 선택 비율"""
        if mode == "CHAOS":
            return {"python_random": 0.7, "ai_semantic": 0.3}
        else:  # NUANCE
            return {"python_random": 0.3, "ai_semantic": 0.7}

    def _analyze_vocab_level(self, direction):
        """
        DIRECTION 텍스트를 AI에게 전달하여 적절한 어휘 수준 판단을 유도.
        (키워드 기반 자동 분석 대신 AI가 맥락을 파악하도록 함)
        """
        # AI가 직접 판단하도록 가이드만 제공
        return f"DIRECTION 분석 후 적절한 어휘 수준 판단: '{direction[:50]}...'"

    def _is_korean(self, text):
        """텍스트에 한국어가 포함되어 있는지 확인"""
        if not text:
            return False
        # 한글 유니코드 범위 확인 (가-힣)
        import re
        return bool(re.search("[가-힣]", text))

    def load_state(self):
        with FileLock(self.state_lock_path):
            if not os.path.exists(self.state_path):
                return {"current_step": 1}
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {"current_step": 1}

    def save_state(self, state):
        with FileLock(self.state_lock_path):
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)

    def locked_append(self, filepath, content):
        """파일 잠금 기반 안전한 append. 병렬 에이전트 동시 쓰기 방지."""
        with FileLock(self.append_lock_path):
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(content.strip() + '\n')

    def count_lines(self, filepath):
        if not os.path.exists(filepath):
            return 0
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                # Ignore whitespace-only lines (including indented blank lines).
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def prepare_parallel_batches(self, worker_count=None, batch_size=None):
        """
        Step 1 병렬 실행용 배치 준비.

        두 가지 모드:
        - worker_count: 워커 수 지정 → 남은 줄을 균등 분할
        - batch_size: 워커당 줄 수 지정 → 워커 수 자동 계산 (ceil(remaining / batch_size))
        둘 다 미지정 시 batch_size=25 기본값.

        Returns: list[dict] — 각 워커의 {worker_id, line_count, random_words, context}
        """
        req = self.load_request()
        if not req:
            raise RuntimeError("request.json not found")

        chains_target = req.get("CHAINS_COUNT", 100)
        chains_done = self.count_lines(self.section_a_path)
        remaining = max(0, chains_target - chains_done)

        if remaining == 0:
            return []

        # batch_size 우선: 워커당 줄 수로 워커 수 역산
        if batch_size is not None and batch_size >= 1:
            worker_count = -(-remaining // batch_size)  # ceil(remaining / batch_size)
        elif worker_count is not None and worker_count >= 1:
            pass  # worker_count 그대로 사용
        else:
            # 둘 다 미지정 → batch_size=25 기본값
            batch_size = 25
            worker_count = -(-remaining // batch_size)

        self.word_pool_path, detected_lang = self._resolve_language_and_pool(req)

        # 전체 랜덤 단어 미리 생성
        all_random_words = [
            self.get_random_words_from_file(self.word_pool_path, 3)
            for _ in range(remaining)
        ]

        # worker_count개로 균등 분할
        chunk_size = -(-remaining // worker_count)  # ceiling division
        context = {
            "direction": req.get("DIRECTION", ""),
            "starting_sentence": req.get("STARTING_SENTENCE", ""),
            "mandatory_words": req.get("MANDATORY_WORD", []),
            "preferred_imagery": req.get("PREFERRED_IMAGERY", []),
            "language_rule": req.get("LANGUAGE_RULE", "NO_3_CONSECUTIVE_FOREIGN_WORDS"),
            "mode": req.get("MODE_SELECTION", "CHAOS"),
        }

        batches = []
        for i in range(worker_count):
            start_idx = i * chunk_size
            end_idx = min(start_idx + chunk_size, remaining)
            if start_idx >= remaining:
                break
            batches.append({
                "worker_id": i + 1,
                "line_count": end_idx - start_idx,
                "random_words": all_random_words[start_idx:end_idx],
                "context": context,
            })

        return batches

    def prepare_parallel_gemini_workers(
        self,
        worker_count: int | None = None,
        batch_size: int | None = None,
    ) -> list[dict]:
        """
        Step 1 병렬 Gemini CLI 워커 준비.

        prepare_parallel_batches()와 동일한 분할 로직이지만,
        각 워커에 대해 staging/worker_{id}_prompt.txt를 생성하고
        실행할 gemini 명령어(cmd)를 함께 반환한다.

        Operator(메인 에이전트)가 run_command로 gemini를 직접 병렬 실행하고
        응답을 append_result로 올리면 sub-agent 토큰이 0이 된다.

        Returns:
            list[dict] — 워커별 {
                worker_id,
                line_count,
                prompt_path,   # staging/worker_{id}_prompt.txt
                cmd,           # 실행할 gemini 명령어 (문자열)
                batch_start,   # 이 워커가 담당하는 시작 줄 번호
                batch_end,     # 이 워커가 담당하는 끝 줄 번호
            }
        """
        batches = self.prepare_parallel_batches(
            worker_count=worker_count,
            batch_size=batch_size,
        )
        if not batches:
            return []

        req = self.load_request()
        if not req:
            raise RuntimeError("request.json not found")

        direction = req.get("DIRECTION", "")
        starting = req.get("STARTING_SENTENCE", "")
        mandatory = req.get("MANDATORY_WORD", [])
        imagery = req.get("PREFERRED_IMAGERY", [])
        language_rule = req.get("LANGUAGE_RULE", "NO_3_CONSECUTIVE_FOREIGN_WORDS")
        model = os.getenv("DELUSIONIST_GEMINI_MODEL", self.DEFAULT_GEMINI_MODEL).strip()

        # chains_done 기준으로 전역 줄 번호 계산
        chains_done = self.count_lines(self.section_a_path)
        workers_out = []
        running_offset = 0  # 이 워커 이전까지 생성된 줄 수의 합

        for batch in batches:
            wid = batch["worker_id"]
            wcount = batch["line_count"]
            batch_start = chains_done + running_offset + 1
            batch_end = chains_done + running_offset + wcount
            random_words = batch["random_words"]  # list[list[str]], 길이 == wcount

            prompt = self._build_step1_gemini_prompt(
                direction=direction,
                starting=starting,
                mandatory=mandatory,
                imagery=imagery,
                language_rule=language_rule,
                batch_start=batch_start,
                batch_random_words=random_words,
            )

            prompt_path = os.path.join(
                self.staging_dir, f"worker_{wid}_prompt.txt"
            )
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(prompt)

            if model:
                cmd = (
                    f'gemini --output-format json --model {shlex.quote(model)} '
                    f'"$(cat {shlex.quote(prompt_path)})"'
                )
            else:
                cmd = f'gemini --output-format json "$(cat {shlex.quote(prompt_path)})"'

            workers_out.append(
                {
                    "worker_id": wid,
                    "line_count": wcount,
                    "prompt_path": prompt_path,
                    "cmd": cmd,
                    "batch_start": batch_start,
                    "batch_end": batch_end,
                }
            )
            running_offset += wcount

        return workers_out

    def run(self):
        logging.info("Initializing Delusionist Factory Engine...")
        
        # 1. Load Request
        req = self.load_request()
        if not req:
            logging.error("request.json not found!")
            return
        
        starting = req.get("STARTING_SENTENCE", "")
        mandatory = req.get("MANDATORY_WORD", [])
        imagery = req.get("PREFERRED_IMAGERY", [])
        chains_target = req.get("CHAINS_COUNT", 100)
        mode = req.get("MODE_SELECTION", "CHAOS").strip().upper()
        selection_b_count = req.get("SELECTION_B_COUNT", 10)  # Step 2에서 추출할 문장 수
        refining_count = req.get("REFINING_COUNT", 1)  # Step 3 최종 출력 수
        direction = req.get("DIRECTION", "")
        final_language = req.get("FINAL_LANGUAGE", "Korean")  # Step 3 출력 언어
        language_rule = req.get("LANGUAGE_RULE", "NO_3_CONSECUTIVE_FOREIGN_WORDS")
        # Step 1 executor selection:
        # - request.json: STEP1_EXECUTOR = "GEMINI_CLI" | "SELF"
        # - env override: DELUSIONIST_STEP1
        step1_mode = (req.get("STEP1_EXECUTOR") or os.getenv("DELUSIONIST_STEP1") or self.DEFAULT_STEP1_MODE).strip().upper()
        if step1_mode not in ("GEMINI_CLI", "SELF"):
            step1_mode = self.DEFAULT_STEP1_MODE
        
        self.word_pool_path, detected_lang = self._resolve_language_and_pool(req)

        # word_pool = self.load_word_pool() # REMOVED: Memory inefficiency
        state = self.load_state()
        ratio = self.get_mode_ratio(mode)
        
        logging.info(f"[CONFIG] Mode: {mode} | Chains: {chains_target}")
        logging.info(f"[CONFIG] Selection B: {selection_b_count} | Final Output: {refining_count}")
        logging.info(f"[CONFIG] Detected Language: {detected_lang} -> Pool: {os.path.basename(self.word_pool_path)}")
        logging.info(f"[CONFIG] Ratio: Python {ratio['python_random']*100:.0f}% / AI {ratio['ai_semantic']*100:.0f}%")
        
        # ========== STEP 1: Chaining CoT ==========
        if state["current_step"] == 1:
            chains_done = self.count_lines(self.section_a_path)
            BATCH_SIZE = req.get("STEP1_BATCH_SIZE", 25)
            
            if chains_done < chains_target:
                # Calculate batch info
                remaining = chains_target - chains_done
                current_batch = min(BATCH_SIZE, remaining)
                batch_start = chains_done + 1
                batch_end = chains_done + current_batch
                
                # Generate random words for each chain in this batch
                batch_random_words = []
                for i in range(current_batch):
                    batch_random_words.append(self.get_random_words_from_file(self.word_pool_path, 3))
                
                logging.info(f"[STEP 1] Chaining Progress: {chains_done}/{chains_target}")

                if step1_mode == "GEMINI_CLI":
                    info = self.prepare_step1_gemini_prompt(batch_size=BATCH_SIZE)

                    print("\n" + "="*70)
                    print(f"  [STEP 1: EXTERNAL (GEMINI CLI)] - Batch #{info['batch_start']}~{info['batch_end']} / {chains_target}")
                    print("="*70)
                    print("  NOTE: MCP/Agent does NOT generate STEP 1. Run Gemini CLI and append results.")
                    print(f"  - Batch: {info['batch_index']}/{info['total_batches']} | ETA: {info['eta_text']}")
                    print(f"  - Prompt saved to: {info['prompt_path']}")
                    print(f"  - Recommended model: {info['model']}")
                    print("  - Run:")
                    print(f"      {info['cmd']}")
                    print("  - Then append the returned lines to:")
                    print(f"      {self.section_a_path}")
                    print("  - After you have enough lines, re-run and it will advance to STEP 2.")
                    print("="*70 + "\n")
                    return
                
                print("\n" + "="*70)
                print(f"  [STEP 1: CHAINING CoT] - Batch #{batch_start}~{batch_end} / {chains_target}")
                print("="*70)
                print("  ")
                print("  ## 💡 Core Concept: Stochastic Context Pollution")
                print("  - LLM은 스스로를 놀라게 할 수 없습니다. 외부 무작위성이 확률 곡선을 깹니다.")
                print("  - 깨끗한 맥락은 진부한 결과를 낳고, 오염된 맥락은 창의적 연결을 강제합니다.")
                print("  ")
                print("  ## 📋 Configuration & Context")
                print(f"  - 🎯 DIRECTION (방향성): \"{direction}\"")
                print(f"  - 🌱 STARTING_SENTENCE: \"{starting}\"")
                print(f"  - 🔑 MANDATORY_WORD: {', '.join(mandatory)}")
                print(f"  - 🎨 PREFERRED_IMAGERY: {', '.join(imagery)}")
                print(f"  - ⚙️ MODE: {mode} (Python Randomness Ratio: {ratio['python_random']*100:.0f}%)")
                print("  ")
                print("  ## 🎲 Random Word Injection (Context Pollution)")
                print(f"  이번 배치에서 사용할 무작위 단어들 ({current_batch}줄분):")
                print("  " + "-"*66)
                for idx, words in enumerate(batch_random_words, start=batch_start):
                    print(f"     [{idx:03d}] {', '.join(words)}")
                print("  " + "-"*66)
                print("  ")
                print("  ## 🚀 Agent Action Required (구체적 지시사항)")
                print("  ")
                print(f"  1. 위 'DIRECTION'을 깊이 분석하십시오. 이 방향성이 우리가 도달해야 할 도착점입니다.")
                print(f"  2. 'STARTING_SENTENCE'와 위 '무작위 단어'를 충돌시켜, 논리를 파괴하는 '망상적 문장'을 만드십시오.")
                print(f"  3. ⚠️ 과감성 필수: 안전하고 말이 되는 문장은 실패입니다. 기괴하고, 충격적이고, 초현실적인 연결을 시도하십시오.")
                print(f"  4. [권한] '창의적 발산'이 더 필요하다면 `update_request_config`로 CHAINS_COUNT를 과감히 늘리십시오 (예: 50, 100, 200, 300).")
                print(f"  5. [필수] '{', '.join(mandatory)}' 포함 & {language_rule} 준수.")
                print(f"  6. [CONTEXT RULE] 문맥의 자연스러움이 최우선입니다. 무작위 단어가 뜬금없는 단어라면, 이를 그대로 쓰지 말고 문맥에 맞게 치환하십시오.")
                print(f"  7. 의학, 공학, 화학, 언어학, 예술등 분야의 난해한 전문용어는 문맥에 맞을때만 사용. 아니면 대체")
                print("  ")
                print(f"  8. [출력 형식] 각 문장 앞에 번호를 붙이십시오 (예: 001, 002...).")
                print(f"     → 위 Random Word Injection 목록에서 문장 번호와 동일한 번호의 무작위 단어 3개를 해당 문장에 1:1 대응시키십시오. (예: [001]의 3단어 → 001번 문장에서 사용, [002]의 3단어 → 002번 문장에서 사용. 문장 간 단어 겹침 없음)")
                print(f"     → 사용한 무작위 단어(또는 도메인에 맞게 변형한 단어)를 문장 내에서 markdown 볼드(**단어**)로 표시하십시오. 볼드 최소 3개.")
                print(f"     → 예: [001]에 빙하, 항해, 균열이 배정된 경우 → 001. 식감의 **균열** 속에서 **항해**하듯 한 접시의 조합이 **빙하**처럼 녹아내린다. (충돌: 빙하+요리 → 느린 해동 조리법 가능성)")
                print(f"  9. [주석 필수] 각 문장 끝에 괄호로 짧은 주석을 추가하십시오.")
                print(f"     → 이 문장에서 어떤 충돌이 발생했는지, 어떤 방향으로 발전 가능한지를 한 줄로 메모.")
                print(f"     → 다음 단계에서 이 주석을 선택적으로 참고하여 아이디어를 확장합니다.")
                print("  ")
                print(f"  👉 생성 목표: DIRECTION(\"{direction[:30]}...\")을 향해 폭주하는 {current_batch}개의 파격적인 문장")
                print(f"  👉 행동: 결과물을 `{self.section_a_path}` 파일에 정확히 append 하십시오.")
                print("  ")
                print("="*70 + "\n")
                return
            
            else:
                # Audit: Verify mandatory words in all chains
                logging.info(f"[STEP 1] ✅ Chaining Complete! ({chains_done} chains)")
                
                # Move to Step 2
                state["current_step"] = 2
                self.save_state(state)
                logging.info("[STATE] Advancing to STEP 2...")
        
        # ========== STEP 2: Refining CoT (문장 추출 - Batch Mode) ==========
        if state["current_step"] == 2:
            refined_done = self.count_lines(self.section_b_path)
            BATCH_SIZE = 10
            
            if refined_done < selection_b_count:
                remaining = selection_b_count - refined_done
                current_batch = min(BATCH_SIZE, remaining)
                batch_start = refined_done + 1
                batch_end = refined_done + current_batch
                
                logging.info(f"[STEP 2] Selection B Progress: {refined_done}/{selection_b_count}")
                
                print("\n" + "="*70)
                print(f"  [STEP 2: REFINING CoT] - Selection B #{batch_start}~{batch_end} / {selection_b_count}")
                print("="*70)
                print("  ")
                print("  ## 💡 Core Concept: Collision Naming — 충돌에 나만의 이름 붙이기")
                print("  - Step 1의 혼돈에서 '기존에 함께 쓰이지 않던 관념·아이디어의 조합'을 찾아내십시오.")
                print("  - 이미 알려진 관념·아이디어의 재서술은 탈락. 새로운 충돌만 남기십시오.")
                print("  - 비유적 표현은 허용하되, 그 비유가 가리키는 새로운 조합의 실체가 있어야 합니다.")
                print("  ")
                print("  ## 📋 Refinement Context")
                print(f"  - 🎯 DIRECTION: \"{direction}\"")
                print(f"  - 🖼 PREFERRED_IMAGERY: {', '.join(imagery)}")
                print(f"  - 🔍 Source File: {self.section_a_path} (STEP 1 Output)")
                print("  ")
                print("  ## 🚀 Agent Action Required (구체적 지시사항)")
                print("  ")
                print(f"  0. [이전 단계 주석 참고] STEP 1 문장 끝의 괄호 주석은 선택적으로 참고하십시오. 새로운 발상의 실마리가 될 수 있습니다.")
                print(f"  1. [충돌 식별] STEP 1의 문장에서 '기존에 함께 쓰이지 않던 관념·아이디어의 조합'을 찾으십시오.")
                print(f"     → 이미 존재하는 관념·아이디어를 단순히 다시 설명한 것은 탈락.")
                print(f"     → 최소 2개 이상의 영역이 교차하는 조합만 선별하십시오.")
                print(f"  2. [고유 명명] 찾아낸 충돌에 나만의 이름을 붙이십시오.")
                print(f"     → 이미 알려진 관념·아이디어의 이름을 그대로 쓰면 감점.")
                print(f"     → 이름은 짧고 직관적이되, 기존 어디에도 없는 조합이어야 합니다.")
                print(f"  3. [실체 부여] 이름 붙인 충돌이 실제로 무엇인지 구체적으로 서술하되,")
                print(f"     → 기존의 단일 관념·아이디어 하나로 환원 가능하면 안 됩니다.")
                print(f"     → '행위(동사)' 또는 '사건(상황)'이 하나 이상 포함되어야 합니다.")
                print(f"  4. [검증] 베테랑이 읽었을 때 '이건 못 본 건데, 말이 되네'가 기준입니다.")
                print(f"     → '아, 이거 알아'면 탈락. '이건 새로운데 납득이 된다'여야 통과.")
                print(f"  4-1. [탈락 기준] 이 아이디어가 무작위 단어 주입 없이도 도메인 전문가가 10분 안에 떠올릴 수 있는가?")
                print(f"     → 그렇다면 탈락. Stochastic Context Pollution의 존재 이유는 전문가의 사고 반경 바깥을 치는 것이다.")
                print(f"  5. [있어 보이기 감지] 아래 패턴이 보이면 즉시 삭제하거나 구체적 내용으로 교체하십시오:")
                print(f"     → 고유명사 나열 (예: 'A의 사상, B의 미학' 식의 장식적 열거)")
                print(f"     → 실체 없는 메타포 연쇄 (비유가 비유를 설명하고, 그 비유를 또 비유로 설명하는 구조)")
                print(f"     → 과도한 미사여구 ('~의 ~의 ~' 관형어가 3단 이상 중첩되는 문장)")
                print(f"  6. 필수 단어({', '.join(mandatory)})가 문맥에 자연스럽게 녹아들었는지 확인하십시오.")
                print(f"  7. [CONTEXT RULE] 무작위 단어가 뜬금없으면 그대로 쓰지 말고 문맥에 맞게 치환하십시오.")
                print(f"  8. [JARGON BAN] 난해한 전문용어는 문맥에 맞을 때만 사용. 아니면 일상어로 대체.")
                print(f"  9. [주석 필수] 각 정제 문장 끝에 괄호로 짧은 주석을 추가하십시오:")
                print(f"     → 뭐가 인상적이었는지, C단계에서 어떤 소재/구조로 활용 가능한지, 어떤 방향으로 확장할 수 있는지를 1~2문장으로 메모.")
                print(f"     → 예: \"(이 충돌은 C단계에서 활동 설계의 '축소 실행' 옵션으로 쓸 수 있다. 면역학 비유가 날카롭다)\"")
                print(f"  10. '{current_batch}개'의 정제된 문장을 완성하십시오.")
                print("  ")
                print(f"  👉 생성 목표: DIRECTION에 부합하면서도, 기존에 없던 관념·아이디어의 조합인 {current_batch}개의 문장")
                print(f"  👉 행동: 결과물을 `{self.section_b_path}` 파일에 정확히 append 하십시오.")
                print("  ")
                print("="*70 + "\n")
                return
            
            else:
                logging.info(f"[STEP 2] ✅ Refining Complete! ({refined_done} sentences)")
                state["current_step"] = 3
                self.save_state(state)
                logging.info("[STATE] Advancing to STEP 3...")
        
        # ========== STEP 3: Final CoT (최종 번역 - Batch Mode) ==========
        if state["current_step"] == 3:
            final_done = self.count_lines(self.section_c_path)
            BATCH_SIZE = 5

            if not state.get("step3_finalized", False):
                logging.info(f"[STEP 3] Final Progress: {final_done} lines appended (target: {refining_count} entries, not finalized)")
                current_batch = min(BATCH_SIZE, refining_count)  # advisory batch size
                
                # 어휘 수준 분석
                vocab_hint = self._analyze_vocab_level(direction)
                
                print("\n" + "="*70)
                print(f"  [STEP 3: FINAL CoT] - {final_done} lines appended / {refining_count} entries target")
                print("="*70)
                print("  ")
                print("  ## 💡 Core Concept: Objectification — DIRECTION 작성자의 언어로 객관화")
                print("  - Step 2의 재료를 융합하되, '자신만의 표현'은 거의 제거하십시오.")
                print("  - 최종 결과물은 DIRECTION을 쓴 사람의 어휘 수준·톤·전문성에 맞춰야 합니다.")
                print("  ")
                print("  ## 📋 Final Context")
                print(f"  - 🎯 DIRECTION: \"{direction}\"")
                print(f"  - 🗣 FINAL_LANGUAGE: {final_language}")
                print(f"  - 📊 Analysis: {vocab_hint}")
                print("  ")
                print("  ## 🚀 Agent Action Required (구체적 지시사항)")
                print("  ")
                print(f"  0. [이전 단계 주석 참고] STEP 2 문장 끝의 괄호 주석은 선택적으로 참고하십시오. 어떤 소재/구조로 활용할지 힌트가 담겨 있습니다.")
                print(f"  1. STEP 2의 결과물({self.section_b_path})을 바탕으로, 최종 결과물을 구성하십시오.")
                print(f"  2. [언어 수준 매칭] DIRECTION의 어투·어휘·전문성 수준을 분석하고, 그 수준에 맞춰 작성하십시오.")
                print(f"     → DIRECTION이 전문적이면 전문 용어 유지 (MCP를 돌리는 AI가 유저에게 설명 가능하므로).")
                print(f"     → DIRECTION이 일상적이면 쉬운 표현으로 전환.")
                print(f"  3. [자기 표현 제한] 각 최종 결과물에서 '자신만의 독창적 표현'은 제목 1개 + 핵심 키워드 1개가 한계입니다.")
                print(f"     → 나머지는 전부 DIRECTION과 STEP 2 재료에서의 표현을 유추 가능한 표현으로 구성하십시오.")
                print(f"     → 독자가 읽었을 때 '이건 내가 쓴 direction에서 나온 말이구나'라고 느껴야 합니다.")
                print(f"  4. [객관화 원칙] 주관적 감탄이나 미사여구를 배제하십시오.")
                print(f"     → '~의 미학이다', '~의 언어다' 같은 추상적 정의문은 금지. 대신 '~하면 ~가 된다'는 조건-결과 구조로 서술.")
                print(f"     → 모든 단락은 '뭘 하라는 건지' 한 줄로 요약 가능해야 합니다.")
                print(f"  5. [있어 보이기 최종 점검] 아래 해당하면 삭제 또는 교체:")
                print(f"     → 고유명사·사조 나열 (구체적이고 자가 검증 가능한 과학적으로 엄밀한 설명 없이 이름만 나열하는 경우)")
                print(f"     → 구체적 행위·사건·이해관계가 없는 설정")
                print(f"     → 과도한 미사여구, 비유가 비유를 낳는 순환 구조")
                print(f"  6. [가용성] 결과물은 DIRECTION 작성자가 바로 활용할 수 있는 형태여야 합니다. 해석이 필요한 암호가 아니라, 읽으면 바로 행동으로 옮길 수 있는 수준.")
                print(f"  7. [작동 검증] 각 아이디어가 실제로 작동하는지 최소 1개의 구체적 예시/시나리오로 시뮬레이션하십시오.")
                print(f"     → 요리라면 조리 과정을 단계별로 걸어보고, 문학이라면 해당 구조로 짧은 시연 단락을 써보고, 비즈니스라면 고객 시나리오를 돌려보십시오.")
                print(f"     → 시뮬레이션에서 논리가 깨지거나 물리적/구조적으로 불가능한 부분이 발견되면, 아이디어를 수정하거나 교체하십시오.")
                print(f"     → 시뮬레이션 결과 자체도 최종 결과물에 포함하여 독자가 작동 원리를 볼 수 있게 하십시오.")
                print(f"  8. [기대치 초과] DIRECTION 내의 [기대치 정의] 블록을 읽고, 그 천장을 넘어서십시오.")
                print(f"     → '이 정도면 됐다'가 아니라 '이건 예상 못 했다'가 반응이어야 합니다.")
                print(f"     → 기대치가 전문가 수준이면 전문가가 동료에게 공유할 밀도를, 5세 기준이면 5세가 소리 지르며 좋아할 것을 만드십시오.")
                print(f"  9. [수직적 깊이] DIRECTION이 설정한 프레임 안에서만 파십시오. 밖으로 나가지 않습니다.")
                print(f"     → 요청이 'RP 캐릭터 시트'면 RP 캐릭터 시트의 최고봉을 만드십시오 — 갑자기 소설이나 논문을 쓰지 마십시오.")
                print(f"     → 요청이 '5세 기준'이면 20대 기준을 섞지 마십시오. 해당 프레임 내부의 밀도와 정교함으로 승부하십시오.")
                print(f"  10. {refining_count}개의 최종 결과물을 생성하십시오.")
                print("  ")
                print(f"  👉 생성 목표: DIRECTION을 달성하는, 완결성 있는 {refining_count}개의 Masterpiece")
                print(f"  👉 행동: 결과물을 `{self.section_c_path}` 파일에 정확히 append 하십시오.")
                print(f"  👉 완료 신호: 모든 결과물을 append한 뒤, 마지막 append_result 호출 시 finalize=true를 전달하십시오.")
                print(f"     → finalize=true가 전달되어야만 Step 3이 완료 처리됩니다.")
                print(f"     → 여러 번 나눠서 append해도 됩니다. 마지막 한 번만 finalize=true이면 됩니다.")
                print("  ")
                print("="*70 + "\n")
                return
            
            else:
                logging.info(f"[STEP 3] ✅ Final Complete! (finalized, {final_done} lines)")
                logging.info("")
                logging.info("="*50)
                logging.info("  🎉 DELUSIONIST FACTORY - ALL STEPS COMPLETE!")
                logging.info("="*50)
                logging.info(f"  Section A (Chains): {self.section_a_path}")
                logging.info(f"  Section B (Refined): {self.section_b_path}")
                logging.info(f"  Section C (Final): {self.section_c_path}")
                logging.info("="*50)


if __name__ == "__main__":
    factory = DelusionistFactory()
    factory.run()
