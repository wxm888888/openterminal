"""
Robust JSON extraction from LLM responses.

Provides a multi-strategy approach to extract JSON objects or arrays
from free-form text that may contain markdown code fences, trailing
commas, unescaped control characters, or other common LLM response
artifacts.
"""

import re
import json


def extract_json(response_text: str) -> dict | list:
    """
    Extract a JSON object or array from *response_text*.

    Tries multiple strategies in order:
    1.  ```json ... ``` code fence
    2.  Generic ``` ... ``` code fence
    3.  Fix control chars in ```json block + parse
    4.  Fix control chars + backslash escapes in ```json block + parse
    5.  Entire text as JSON
    6.  Brace-matched JSON object
    7.  Bracket-matched JSON array
    8.  Fix trailing commas, then retry brace match
    9.  Fix invalid backslash escapes and retry brace match
    10. Fix control chars in full text, then brace match
    11. Fix missing commas, then brace match
    12. Combine all fixes (control chars + backslash escapes + trailing commas + missing commas), then brace match
    13. Auto-repair loop to inject missing characters (e.g. closing braces) at error boundaries

    Raises ``ValueError`` if no valid JSON can be extracted.
    """
    if not response_text or not isinstance(response_text, str):
        raise ValueError("Empty or invalid response text")

    text = response_text.strip()

    # --- Code-fence strategies ---

    # Strategy 1: ```json code block
    if "```json" in text:
        try:
            json_content = text.split("```json")[1].split("```")[0].strip()
            return json.loads(json_content)
        except (IndexError, json.JSONDecodeError):
            pass

    # Strategy 2: generic ``` code block
    if "```" in text:
        try:
            json_content = text.split("```")[1].split("```")[0].strip()
            return json.loads(json_content)
        except (IndexError, json.JSONDecodeError):
            pass

    # Strategy 3: fix control chars (unescaped newlines/tabs in strings) in ```json block
    if "```json" in text:
        try:
            json_content = text.split("```json")[1].split("```")[0].strip()
            fixed = _fix_control_chars_in_strings(json_content)
            return json.loads(fixed)
        except (IndexError, json.JSONDecodeError):
            pass

    # Strategy 4: fix control chars + backslash escapes in ```json block
    if "```json" in text:
        try:
            json_content = text.split("```json")[1].split("```")[0].strip()
            fixed = _fix_control_chars_in_strings(json_content)
            sanitized = _fix_invalid_escapes(fixed)
            return json.loads(sanitized)
        except (IndexError, json.JSONDecodeError):
            pass

    # --- Plain text strategies ---

    # Strategy 5: entire text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 6: brace-matched object
    result = _match_balanced(text, "{", "}")
    if result is not None:
        return result

    # Strategy 7: bracket-matched array
    result = _match_balanced(text, "[", "]")
    if result is not None:
        return result

    # Strategy 8: fix trailing commas and retry
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    result = _match_balanced(fixed, "{", "}")
    if result is not None:
        return result

    # Strategy 9: fix invalid single-backslash escapes common in regex strings
    sanitized = _fix_invalid_escapes(text)
    result = _match_balanced(sanitized, "{", "}")
    if result is not None:
        return result

    # Strategy 10: fix control chars in full text, then brace match
    ctrl_fixed = _fix_control_chars_in_strings(text)
    result = _match_balanced(ctrl_fixed, "{", "}")
    if result is not None:
        return result

    # Strategy 11: fix missing commas (common Kimi error)
    comma_fixed = _fix_missing_commas(text)
    result = _match_balanced(comma_fixed, "{", "}")
    if result is not None:
        return result

    # Strategy 12: combine all fixes — control chars + backslash escapes + trailing commas + missing commas
    all_fixed = _fix_control_chars_in_strings(text)
    all_fixed = _fix_invalid_escapes(all_fixed)
    all_fixed = re.sub(r",\s*([}\]])", r"\1", all_fixed)
    all_fixed = _fix_missing_commas(all_fixed)
    result = _match_balanced(all_fixed, "{", "}")
    if result is not None:
        return result

    # Strategy 13: Auto-repair loop
    try:
        # Find the first JSON syntax character to avoid json.loads immediately failing on markdown fences
        start_brace = all_fixed.find('{')
        start_bracket = all_fixed.find('[')
        start_idx = -1
        if start_brace != -1 and start_bracket != -1:
            start_idx = min(start_brace, start_bracket)
        elif start_brace != -1:
            start_idx = start_brace
        elif start_bracket != -1:
            start_idx = start_bracket
            
        if start_idx != -1:
            return _auto_repair_json(all_fixed[start_idx:])
        else:
            return _auto_repair_json(all_fixed)
    except ValueError:
        pass

    raise ValueError(f"Failed to extract JSON from response: {text}")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _auto_repair_json(text: str, max_fixes: int = 5) -> dict | list:
    """Repeatedly attempt to parse and inject missing chars at error boundaries."""
    current_text = text
    for _ in range(max_fixes):
        result = _match_balanced(current_text, "{", "}")
        if result is not None:
            return result
        result_array = _match_balanced(current_text, "[", "]")
        if result_array is not None:
            return result_array

        # Find where the error is
        try:
            return json.loads(current_text)
        except json.JSONDecodeError as e:
            pos = e.pos
            if pos >= len(current_text):
                break
            
            # Common Kimi error 1: Missing '}' before ']'
            # Error: Expecting ',' delimiter (because it expected a comma or '}' inside an object)
            error_char = current_text[pos]
            
            # Missing '}' before a new object in an array
            if "Expecting property name" in e.msg and error_char in '{[':
                comma_pos = current_text.rfind(',', 0, pos)
                if comma_pos != -1:
                    current_text = current_text[:comma_pos] + '}' + current_text[comma_pos:]
                    continue

            if error_char == ']':
                # Try injecting a '}' before the ']'
                current_text = current_text[:pos] + '}' + current_text[pos:]
                continue
                
            # Common Kimi error 2: Missing ',' before '{' or '"'
            if error_char in '{':
                current_text = current_text[:pos] + ',' + current_text[pos:]
                continue
                
            if error_char == '"':
                current_text = current_text[:pos] + ',' + current_text[pos:]
                continue
            
            break
            
    raise ValueError("Auto-repair exhausted")


def _fix_control_chars_in_strings(text: str) -> str:
    """
    Replace unescaped control characters (newline, carriage return, tab)
    inside JSON string values with their escaped equivalents.

    Uses a simple state machine to track whether we are inside a
    double-quoted string, properly handling escaped quotes.
    """
    result: list[str] = []
    in_string = False
    for ch in text:
        if ch == '"':
            # Count preceding backslashes to handle escaped quotes
            num_bs = 0
            j = len(result) - 1
            while j >= 0 and result[j] == '\\':
                num_bs += 1
                j -= 1
            if num_bs % 2 == 0:
                in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


def _fix_invalid_escapes(text: str) -> str:
    r"""
    Double-escape invalid JSON backslash sequences.

    JSON only allows: ``\" \\ \/ \b \f \n \r \t \uXXXX``.
    LLMs often produce ``\s \d \[ \(`` etc. (from regex patterns).
    This function turns ``\s`` into ``\\s`` so ``json.loads`` accepts it.
    """
    valid_after_backslash = {chr(34), chr(92), chr(47), "b", "f", "n", "r", "t", "u"}
    result: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            next_ch = text[i + 1]
            if next_ch in valid_after_backslash:
                # Valid JSON escape, keep as-is
                result.append(text[i])
                result.append(next_ch)
                i += 2
            elif next_ch == '\\':
                # Already doubled backslash, keep as-is
                result.append(text[i])
                result.append(next_ch)
                i += 2
            else:
                # Invalid escape like \s, \d, \[ — double the backslash
                result.append('\\')
                result.append('\\')
                result.append(next_ch)
                i += 2
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


def _fix_missing_commas(text: str) -> str:
    """
    Fix missing commas between list elements or between an array and the next object key.
    Kimi often outputs: `} {` or `] "key":` instead of `}, {` and `], "key":`.
    """
    fixed = re.sub(r'\}\s*\{', '}, {', text)
    fixed = re.sub(r'\]\s*\"', '], "', fixed)
    return fixed


def _match_balanced(text: str, open_char: str, close_char: str):
    """Return the first balanced ``open_char``/``close_char`` span as parsed JSON, or *None*."""
    start = text.find(open_char)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
