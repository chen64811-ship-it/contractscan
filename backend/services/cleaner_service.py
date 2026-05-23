# -*- coding: utf-8 -*-
"""
Data Cleaning Service
Removes garbage characters, extra whitespace, blank lines; normalizes formatting.
"""
import re


def clean_text(raw_text):
    """
    Clean raw extracted text.

    Args:
        raw_text: raw text (may contain garbage chars, extra spaces/blank lines etc.)

    Returns:
        Cleaned text string.
    """
    if not raw_text:
        return ""

    text = raw_text

    # 1. Normalize Windows line endings to \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Remove invisible garbage characters
    # Remove control characters (except newline and tab)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Remove UTF-8 encoding error replacement character (�)
    text = text.replace("\ufffd", "")

    # 3. Trim leading/trailing whitespace per line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)  # trailing spaces
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)  # leading spaces

    # 4. Collapse 3+ blank lines into a single blank line
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 4.5. Fix extra whitespace around '+' symbols (before general space compression)
    # e.g. "word  +  word" → "word + word" (excludes markdown list items like "+ item")
    fixed_lines = []
    for _ln in text.split('\n'):
        if not re.match(r'^\+\s', _ln):
            _ln = re.sub(r'[ \t]{2,}(\+)', r' \1', _ln)
            _ln = re.sub(r'(\+)[ \t]{2,}', r'\1 ', _ln)
        fixed_lines.append(_ln)
    text = '\n'.join(fixed_lines)

    # 5. Compress multiple spaces within lines (preserving sentence structure)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 5b. Remove extra whitespace between CJK characters and between CJK and punctuation
    text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]) ([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\uff0c\u3002\uff01\uff1f\u3001\uff1b\uff1a\u201c\u201d\u2018\u2019\u3010\u3011\u300a\u300b\uff08\uff09])', r'\1\2', text)
    text = re.sub(r'([\uff0c\u3002\uff01\uff1f\u3001\uff1b\uff1a\u201c\u201d\u2018\u2019\u3010\u3011\u300a\u300b\uff08\uff09]) ([\u4e00-\u9fff])', r'\1\2', text)
    # Run again (handle consecutive CJK spaces compressed to single then cleaned)
    text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]) ([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\uff0c\u3002\uff01\uff1f\u3001\uff1b\uff1a\u201c\u201d\u2018\u2019\u3010\u3011\u300a\u300b\uff08\uff09])', r'\1\2', text)

    # 6. Convert full-width spaces and various special whitespace
    text = text.replace("\u3000", " ")  # full-width space
    text = re.sub(r"[\u00a0\u2000-\u200b\u2028\u2029\u202f\u205f\u3000]+", " ", text)

    # 6b. Re-compress whitespace after conversions (full-width space etc. may create consecutive spaces)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)  # clean trailing spaces
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)  # clean leading spaces

    # 7. Remove Unicode directional formatting characters
    text = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", text)

    # 8. Remove common crawler/OCR residual garbage patterns (long meaningless symbol runs)
    text = re.sub(r"[_\-=]{5,}", "", text)  # 5+ consecutive dashes/underscores
    text = re.sub(r"[*#]{5,}", "", text)     # 5+ consecutive asterisks/hashes

    # 9. Strip leading/trailing blank lines
    text = text.strip()

    # 10. One final pass to collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 11. Remove duplicate paragraphs (keep first occurrence of each)
    text = _remove_duplicate_paragraphs(text)

    return text


def _remove_duplicate_paragraphs(text):
    """
    Remove duplicate paragraphs (delimited by double newlines).
    Keeps the first occurrence of each paragraph, removes subsequent duplicates.
    """
    paragraphs = text.split('\n\n')
    seen = set()
    unique = []
    for para in paragraphs:
        # Normalize paragraph (trim whitespace) for comparison, avoid false positives from whitespace differences
        key = para.strip()
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(para)
    return '\n\n'.join(unique)


def text_to_markdown(text, title=None):
    """
    Format cleaned text as Markdown.

    Args:
        text: cleaned text
        title: optional, file title (placed as H1 at the top)

    Returns:
        Formatted Markdown string.
    """
    lines = []

    # Add title as H1 if provided
    if title:
        lines.append(f"# {title}\n")

    # Append body text
    if text:
        lines.append(text)

    result = "\n".join(lines)

    # Ensure no trailing blank lines
    result = result.rstrip("\n") + "\n"

    return result
