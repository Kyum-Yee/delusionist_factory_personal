import json
import re
import subprocess
from typing import Any, Optional


def _extract_first_json_object(text: str) -> dict[str, Any]:
    """
    Gemini CLI --output-format json sometimes prints non-JSON prelude lines
    (e.g. "Loaded cached credentials.") before the JSON payload.
    Extract the first JSON object robustly.
    """
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _end = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("Could not find a JSON object in Gemini CLI output.")


def run_gemini_cli(prompt: str, model: Optional[str] = None, timeout_s: int = 180) -> dict[str, Any]:
    """
    Runs `gemini` in one-shot mode and returns the parsed JSON output.
    """
    cmd = ["gemini", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"gemini exited with {proc.returncode}. Output:\n{combined.strip()}")

    return _extract_first_json_object(combined)


# Strip common leading enumeration markers like "1. ", "(1) ", "- ", "• ".
_LEADING_ENUM_RE = re.compile(r"^\s*(?:[-*•]|\(?\d+[\).\]]|\d+\.|\d+\))\s+")


def split_and_clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        s = _LEADING_ENUM_RE.sub("", s).strip()
        if s:
            lines.append(s)
    return lines
