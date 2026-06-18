import re


def extract_json(response: str) -> str:
    """Extract the first top-level JSON object from an LLM response.

    Handles: <think>...</think> blocks, markdown fences, and bare JSON.
    """
    # Strip <think>...</think> blocks (DeepSeek-R1, Qwen3, etc.)
    text = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

    # Try markdown fenced JSON first
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    # Find the outermost { ... }
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return text[start:]
