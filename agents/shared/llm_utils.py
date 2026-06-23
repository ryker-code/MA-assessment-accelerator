import re


def extract_json(response: str) -> str:
    """Extract the first top-level JSON object from an LLM response.

    Handles: <think>...</think> blocks, markdown fences, grounding citations,
    and bare JSON.
    """
    # Strip <think>...</think> blocks (DeepSeek-R1, Qwen3, etc.)
    text = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

    # Strip any opening and closing markdown fence lines so brace-matching works
    # cleanly on the remaining text regardless of what appears after the fence.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # Find and extract the outermost { ... } via brace-matching.
    # This is more robust than a single regex because it handles nested objects,
    # escaped characters, and any trailing content (grounding citations, etc.).
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
                return text[start: i + 1]

    return text[start:]
