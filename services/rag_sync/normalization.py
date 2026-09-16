# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Normalization of Confluence storage-format page bodies into markdown (WS9).

The storage format is deterministic, so one fetch serves both content hashing and
normalization. Content-bearing structure is kept as markdown (headings, paragraphs,
nested lists, tables, code, container macro bodies, link text, image/attachment
references by file name, the visible text of inline macros); non-content macros,
macro parameters, comment markers, emoticons, placeholders and empty elements are
dropped. Unknown macros keep their rich-text body when they have one, otherwise
they are dropped, logged at debug level.

The storage format is XHTML with a fixed, small tag vocabulary, so a dedicated
depth-aware renderer is both correct and dependency-free; a generic HTML-to-markdown
converter would add a dependency and still need macro-specific handling.
"""

import re
from html import unescape

from common import utils

logger = utils.get_logger("confluence_normalizer")

# Container macros whose body is content-bearing and is kept.
_CONTENT_MACROS = {"panel", "info", "note", "warning", "tip", "expand", "section", "column", "layout"}
# Non-content macros that only render dynamic navigation or listings of other content.
_DROP_MACROS = {
    "toc", "table-of-contents", "children", "page-tree", "pagetree", "attachments",
    "jiraissues", "jira", "recently-updated", "recentlyupdated", "listlabels", "contentbylabel",
    "blog-posts", "spacejump", "spaceslist", "nav", "navigation", "tasklist", "action",
}
# Inline macros rendered as their visible parameter text.
_INLINE_TEXT_MACROS = {"status", "date"}

_TAG_RE = re.compile(r"<[^>]+>")


def normalize_page_body(raw_body: str, page_title: str) -> str:
    """Converts a raw storage-format body into markdown, below a synthetic h1 title.

    Storage headings are shifted one level down (h1 -> h2), so the page title is the
    document's h1 and the body's own sections sit below it; together with the chunker
    this yields the ``Page title > Section > Subsection`` breadcrumbs. Entities are
    decoded and whitespace normalized; the heading structure survives, because
    chunking depends on it.
    """
    normalized = _normalize_whitespace(_render_fragment(raw_body))
    if not normalized:
        return ""
    return f"# {page_title}\n\n{normalized}"


def _render_fragment(fragment: str) -> str:
    """Renders one XHTML fragment to markdown by walking its top-level nodes."""
    parts: list[str] = []
    for node in _tokenize(fragment):
        match node:
            case ("text", text):
                parts.append(text)
            case ("tag", (tag, attrs, inner)):
                parts.append(_render_tag(tag, attrs, inner))
    return "".join(parts)


def _tokenize(fragment: str):
    """Yields ("text", text) and ("tag", (tag, attrs, inner)) nodes at one nesting level.

    The storage format is XHTML produced by the editor, so tags balance; a tolerant
    scan for the matching close tag is enough, without a full XML parser. Closing
    tags and comments yield nothing (their parent consumed them); CDATA sections
    yield their text content, since the editor wraps code bodies in them.
    """
    position = 0
    while position < len(fragment):
        match = _TAG_RE.search(fragment, position)
        if match is None:
            if position < len(fragment):
                yield ("text", fragment[position:])
            return
        if match.start() > position:
            yield ("text", fragment[position : match.start()])
        tag_text = match.group(0)
        if tag_text.startswith("</"):
            # A closing tag: its opening tag consumed it. Nothing to yield.
            position = match.end()
            continue
        if tag_text.startswith("<!--"):
            # A comment marker: dropped entirely.
            position = match.end()
            continue
        if tag_text.startswith("<![CDATA["):
            cdata_end = fragment.find("]]>", match.end())
            if cdata_end == -1:
                yield ("text", fragment[match.end() :])
                return
            yield ("text", fragment[match.end() : cdata_end])
            position = cdata_end + 3
            continue
        tag, attrs = _parse_tag(tag_text)
        if tag and not tag_text.endswith("/>") and not _is_self_closing(tag):
            inner, end = _extract_inner(fragment, match.end(), tag)
            yield ("tag", (tag, attrs, inner))
            position = end
        else:
            yield ("tag", (tag, attrs, ""))
            position = match.end()


def _parse_tag(tag_text: str) -> tuple[str, str]:
    """Extracts the tag name and its raw attribute text from ``<tag ...>``."""
    inner = tag_text[1:-1].rstrip("/")
    name = inner.split(None, 1)[0].lower() if inner else ""
    return name, inner[len(name) :]


def _extract_inner(fragment: str, start: int, tag: str) -> tuple[str, int]:
    """Returns the content between this tag and its matching close tag, and the end offset.

    Nested same-name tags (lists inside lists, tables inside cells) are honoured by
    counting depth.
    """
    open_re = re.compile(fr"<{tag}\b[^>]*/?>", re.IGNORECASE)
    close_re = re.compile(fr"</{tag}\s*>", re.IGNORECASE)
    depth = 1
    cursor = start
    while True:
        next_close = close_re.search(fragment, cursor)
        if not next_close:
            # Malformed input: take the rest rather than fail the page.
            return fragment[start:], len(fragment)
        next_open = open_re.search(fragment, cursor)
        if next_open and next_open.start() < next_close.start() and not next_open.group(0).endswith("/>"):
            depth += 1
            cursor = next_open.end()
        else:
            depth -= 1
            cursor = next_close.end()
            if depth == 0:
                return fragment[start : next_close.start()], next_close.end()


def _is_self_closing(tag: str) -> bool:
    return tag in {"br", "hr", "img", "input"}


def _render_tag(tag: str, attrs: str, inner: str) -> str:
    """Renders one storage-format tag (with its inner content) to markdown."""
    match tag:
        case "h1" | "h2" | "h3" | "h4" | "h5" | "h6":
            level = int(tag[1])
            text = _render_fragment(inner).strip()
            return f"\n\n{'#' * min(level + 1, 6)} {text}\n\n" if text else ""
        case "p":
            text = _render_fragment(inner).strip()
            return f"\n\n{text}\n\n" if text else ""
        case "br":
            return "\n"
        case "strong" | "b":
            text = _render_fragment(inner).strip()
            return f"**{text}**" if text else ""
        case "em" | "i":
            text = _render_fragment(inner).strip()
            return f"*{text}*" if text else ""
        case "code":
            text = _strip_tags(inner)
            return f"`{text}`" if text else ""
        case "pre":
            text = _strip_tags(inner)
            return f"\n\n```\n{text}\n```\n\n" if text else ""
        case "a":
            return _render_fragment(inner).strip()
        case "ul" | "ol":
            return _render_list(inner, ordered=tag == "ol")
        case "table":
            return _render_table(inner)
        case "ac:structured-macro":
            return _render_macro(attrs, inner)
        case "ac:image" | "ri:attachment":
            return _render_image(attrs, inner)
        case "ac:link" | "ac:plain-text-link-body":
            return _render_fragment(inner)
        case _:
            # Unknown tags keep their text content; wrapping structure tags (tbody
            # etc.) just pass through.
            return _render_fragment(inner)


def _render_macro(attrs: str, inner: str) -> str:
    """Renders an ``ac:structured-macro``: keep content bodies, drop the rest."""
    name_match = re.search(r'ac:name="([^"]+)"', attrs)
    name = name_match.group(1).lower() if name_match else ""
    if name in _DROP_MACROS:
        return ""
    if name in _INLINE_TEXT_MACROS:
        parameter = re.search(r"<ac:parameter[^>]*>(.*?)</ac:parameter>", inner, re.DOTALL)
        return parameter.group(1).strip() if parameter else ""
    if name in _CONTENT_MACROS:
        rendered = _render_fragment(inner).strip()
        # Panel-like macros render as block quotes so their content stays readable.
        return f"\n\n> {rendered}\n\n" if rendered else ""
    if name == "code":
        # The language travels as ac:parameter ac:name="language" (v2 storage) or as
        # ac:default-parameter (older storage).
        language_match = re.search(
            r'<ac:parameter ac:name="language">(.*?)</ac:parameter>', inner, re.DOTALL
        ) or re.search(r"<ac:default-parameter>(.*?)</ac:default-parameter>", inner, re.DOTALL)
        language = _strip_cdata(language_match.group(1).strip()) if language_match else ""
        body_match = re.search(r"<ac:plain-text-body>(.*?)</ac:plain-text-body>", inner, re.DOTALL)
        if body_match:
            code = _strip_cdata(unescape(body_match.group(1)))
            return f"\n\n```{language}\n{code}\n```\n\n"
        return ""
    # An unknown macro with a rich-text body keeps it; otherwise it is dropped.
    rich_body = re.search(r"<ac:rich-text-body>(.*?)</ac:rich-text-body>", inner, re.DOTALL)
    if rich_body:
        rendered = _render_fragment(rich_body.group(1)).strip()
        return f"\n\n{rendered}\n\n" if rendered else ""
    plain_body = re.search(r"<ac:plain-text-body>(.*?)</ac:plain-text-body>", inner, re.DOTALL)
    if plain_body:
        text = _strip_cdata(unescape(plain_body.group(1))).strip()
        return f"\n\n{text}\n\n" if text else ""
    logger.debug(f"Dropping unknown macro '{name}' without a content body.")
    return ""


def _render_image(attrs: str, inner: str = "") -> str:
    """Images and attachment references render by file name.

    The file name sits either directly on ``ri:attachment``'s attributes or on the
    ``ri:attachment`` child inside an ``ac:image`` wrapper.
    """
    filename_match = re.search(r'ri:filename="([^"]+)"', attrs) or re.search(r'ri:filename="([^"]+)"', inner)
    if not filename_match:
        filename_match = re.search(r'ac:default-parameter="([^"]+)"', attrs)
    return f"[image: {filename_match.group(1)}]" if filename_match else ""


def _render_list(inner: str, ordered: bool, indent: str = "") -> str:
    """Renders a list; nested lists inside items are indented under their item."""
    lines: list[str] = []
    for index, item in enumerate(_top_level_items(inner, "li"), start=1):
        marker = f"{index}. " if ordered else "- "
        rendered = _render_fragment(item).strip()
        if not rendered:
            continue
        # Multi-line item content (nested lists) is indented under the item marker.
        rendered = rendered.replace("\n\n", "\n")
        rendered = "\n".join(
            line if line_index == 0 else f"{indent}    {line}"
            for line_index, line in enumerate(rendered.split("\n"))
        )
        lines.append(f"{indent}{marker}{rendered}")
    if not lines:
        return ""
    return "\n\n" + "\n".join(lines) + "\n\n"


def _render_table(inner: str) -> str:
    rendered_rows: list[list[str]] = []
    for row in _top_level_items(inner, "tr"):
        cells = []
        for cell_kind in ("th", "td"):
            cells.extend(_top_level_items(row, cell_kind))
        if cells:
            rendered_rows.append([_render_fragment(cell).strip().replace("\n", " ") for cell in cells])
    if not rendered_rows:
        return ""
    width = max(len(row) for row in rendered_rows)
    padded = [row + [""] * (width - len(row)) for row in rendered_rows]
    lines = [
        "| " + " | ".join(padded[0]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in padded[1:])
    return "\n\n" + "\n".join(lines) + "\n\n"


def _top_level_items(fragment: str, tag: str) -> list[str]:
    """Inner content of every top-level ``<tag>`` element, honouring nesting depth."""
    open_re = re.compile(fr"<{tag}\b[^>]*>", re.IGNORECASE)
    close_re = re.compile(fr"</{tag}\s*>", re.IGNORECASE)
    items: list[str] = []
    depth = 0
    start: int | None = None
    cursor = 0
    while True:
        next_close = close_re.search(fragment, cursor)
        if not next_close:
            return items
        next_open = open_re.search(fragment, cursor)
        if next_open and next_open.start() < next_close.start():
            if depth == 0:
                start = next_open.end()
            depth += 1
            cursor = next_open.end()
        else:
            depth -= 1
            cursor = next_close.end()
            if depth == 0 and start is not None:
                items.append(fragment[start : next_close.start()])
                start = None


def _strip_tags(fragment: str) -> str:
    """The verbatim text of a code body: tags out, entities and CDATA decoded."""
    return _strip_cdata(unescape(_TAG_RE.sub("", fragment)))


def _strip_cdata(text: str) -> str:
    """Unwraps ``<![CDATA[...]]>`` sections, which the editor uses inside code bodies."""
    return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)


def _normalize_whitespace(text: str) -> str:
    """Decodes entities, trims lines and collapses runs of blank lines."""
    text = unescape(text)
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip()
