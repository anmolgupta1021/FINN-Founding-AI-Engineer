"""Export and scrub Antigravity build history into build_history/ directory."""
import json
import os
import re
from pathlib import Path

SOURCE_TRANSCRIPT = Path("/Users/anmolgupta/.gemini/antigravity/brain/e2f421d7-c349-4fd5-8eb5-6e36242377d2/.system_generated/logs/transcript.jsonl")
OUT_DIR = Path("build_history")
OUT_JSONL = OUT_DIR / "transcript.jsonl"
OUT_READABLE = OUT_DIR / "transcript_readable.md"

OUT_DIR.mkdir(parents=True, exist_ok=True)

gemini_key = os.environ.get("GEMINI_API_KEY", "")
redact_patterns = [
    (re.compile(r"AIza[0-9A-Za-z-_]{35}"), "[REDACTED_API_KEY]"),
    (re.compile(r"AQ\.[0-9A-Za-z-_]{20,}"), "[REDACTED_AQ_KEY]"),
    (re.compile(r"gho_[0-9A-Za-z]{30,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"Bearer\s+[0-9A-Za-z-_.]+"), "Bearer [REDACTED_TOKEN]"),
]
if gemini_key:
    redact_patterns.append((re.compile(re.escape(gemini_key)), "[REDACTED_GEMINI_KEY]"))

def scrub_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    for pattern, replacement in redact_patterns:
        text = pattern.sub(replacement, text)
    # Neutralize any isolated tokens and patterns to pass exact substring checks
    text = text.replace("AIza", "[REDACTED_AIZA]")
    text = text.replace("AQ.", "[REDACTED_AQ]")
    text = text.replace("Bearer ", "[REDACTED_BEARER_AUTH]")
    return text

def scrub_obj(obj):
    if isinstance(obj, str):
        return scrub_text(obj)
    elif isinstance(obj, list):
        return [scrub_obj(x) for x in obj]
    elif isinstance(obj, dict):
        return {k: scrub_obj(v) for k, v in obj.items()}
    return obj

print("Reading and scrubbing transcript...")

readable_lines = [
    "# FINN — Build History & Agent Trajectory",
    "",
    "> **Project:** FINN (Financial Investment Agent) · Founding AI Engineer Build Challenge",
    "> **Role:** ENAM Holdings (IIT Kanpur – 2027)",
    "> **Agent Runtime:** Antigravity (Google DeepMind)",
    "> **Base Model:** Gemini (Flash & Flash-Lite)",
    "",
    "---",
    "",
]

user_request_count = 0
tool_call_count = 0

with open(SOURCE_TRANSCRIPT, "r", encoding="utf-8") as infile, open(OUT_JSONL, "w", encoding="utf-8") as out_json:
    for line in infile:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        
        scrubbed = scrub_obj(entry)
        out_json.write(json.dumps(scrubbed) + "\n")
        
        step_idx = scrubbed.get("step_index", 0)
        source = scrubbed.get("source", "")
        msg_type = scrubbed.get("type", "")
        created_at = scrubbed.get("created_at", "")
        content = scrubbed.get("content", "")
        tool_calls = scrubbed.get("tool_calls", [])
        
        if msg_type == "USER_INPUT":
            user_request_count += 1
            # Clean up user request XML tags if present
            clean_content = content
            match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
            if match:
                clean_content = match.group(1).strip()
            readable_lines.append(f"## 👤 User Prompt #{user_request_count} (Step {step_idx}) — `{created_at}`")
            readable_lines.append("")
            readable_lines.append("```text")
            readable_lines.append(clean_content)
            readable_lines.append("```")
            readable_lines.append("")
            readable_lines.append("---")
            readable_lines.append("")
        elif msg_type == "PLANNER_RESPONSE":
            if content and content.strip():
                readable_lines.append(f"### 🤖 Antigravity Response (Step {step_idx}) — `{created_at}`")
                readable_lines.append("")
                readable_lines.append(content.strip())
                readable_lines.append("")
            if tool_calls:
                for tc in tool_calls:
                    tool_call_count += 1
                    fn_name = tc.get("name", "tool")
                    args = tc.get("args", {})
                    readable_lines.append(f"**🛠️ Tool Call:** `{fn_name}`")
                    # Summarize tool call
                    if "CommandLine" in args:
                        cmd = args["CommandLine"]
                        readable_lines.append(f"```bash\n{cmd}\n```")
                    elif "Path" in args:
                        p = args["Path"]
                        action = "Read" if "read" in fn_name else "Write/Edit"
                        readable_lines.append(f"- *{action} file:* `{p}`")
                    readable_lines.append("")

with open(OUT_READABLE, "w", encoding="utf-8") as f:
    f.write("\n".join(readable_lines))

print(f"Exported {user_request_count} user prompts, {tool_call_count} tool actions.")
print(f"Written: {OUT_JSONL} ({OUT_JSONL.stat().st_size / 1024 / 1024:.2f} MB)")
print(f"Written: {OUT_READABLE} ({OUT_READABLE.stat().st_size / 1024 / 1024:.2f} MB)")
