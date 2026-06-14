"""Word/character/image/table/formula counting helpers for markdown text."""

import re

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:-]+\|[\s:|-]+$", re.MULTILINE)
_BLOCK_FORMULA_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_INLINE_FORMULA_RE = re.compile(r"(?<!\$)\$[^\$\n]+\$(?!\$)")
_MD_SYNTAX_RE = re.compile(r"[#>*_`~-]")


def _strip_markdown(markdown_text: str) -> str:
    """Remove image/table syntax and common markdown punctuation for fairer text counts."""
    text = _IMAGE_RE.sub("", markdown_text)
    text = _TABLE_ROW_RE.sub("", text)
    text = _MD_SYNTAX_RE.sub("", text)
    return text


def text_stats(markdown_text: str) -> dict:
    """Return word/character counts for the given markdown text."""
    plain = _strip_markdown(markdown_text)
    char_count = len(plain)
    char_count_no_spaces = len(re.sub(r"\s", "", plain))
    word_count = len(plain.split())
    return {
        "word_count": word_count,
        "char_count": char_count,
        "char_count_no_spaces": char_count_no_spaces,
    }


def count_md_tables(markdown_text: str) -> int:
    """Count distinct markdown table blocks (a header row followed by a separator row)."""
    lines = markdown_text.splitlines()
    count = 0
    for i in range(len(lines) - 1):
        if _TABLE_ROW_RE.match(lines[i]) and _TABLE_SEP_RE.match(lines[i + 1]):
            count += 1
    return count


def count_formulas(markdown_text: str) -> int:
    """Count LaTeX formula blocks ($$...$$) and inline formulas ($...$)."""
    block_count = len(_BLOCK_FORMULA_RE.findall(markdown_text))
    without_blocks = _BLOCK_FORMULA_RE.sub("", markdown_text)
    inline_count = len(_INLINE_FORMULA_RE.findall(without_blocks))
    return block_count + inline_count


def count_images(markdown_text: str) -> int:
    """Count markdown image references (![...](...))."""
    return len(_IMAGE_RE.findall(markdown_text))
