# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Heading-aware chunking of normalized page bodies.

Splits along markdown headings while tracking the heading path. Each chunk carries
its breadcrumb (``Page title > Section > Subsection``) as a prefix. A section with
no body text doesn't become a chunk of its own; its heading still appears in its
subsections' breadcrumbs. An oversized section is split greedily by paragraphs and
an oversized paragraph by words, and the breadcrumb is re-applied to every piece.

The token budget includes the breadcrumb and is measured with a conservative
character-based estimate (``RAG_CHUNK_MAX_TOKENS`` times four characters per token),
which adds no dependency and stays safe while the budget is far below the embedding
model's maximum input.
"""

import re
from dataclasses import dataclass

import config

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def _headings(markdown: str) -> list[re.Match[str]]:
    """The markdown headings outside fenced code, where a comment line can start with ``#``."""
    fenced = [match.span() for match in _FENCE_RE.finditer(markdown)]
    return [
        match
        for match in _HEADING_RE.finditer(markdown)
        if not any(start <= match.start() < end for start, end in fenced)
    ]


@dataclass(slots=True)
class PageChunk:
    """One breadcrumb-prefixed chunk of a page body, with its 0-based index."""

    breadcrumb: str
    text: str
    index: int

    def content(self) -> str:
        """The text handed to the embedding model: breadcrumb plus chunk text."""
        return f"{self.breadcrumb}\n\n{self.text}"


def chunk_page_body(markdown: str, page_title: str) -> list[PageChunk]:
    """Splits a normalized page body into breadcrumb-prefixed chunks."""
    budget = config.DocumentRagConfig.CHUNK_MAX_TOKENS * config.DocumentRagConfig.CHARACTERS_PER_TOKEN
    chunks: list[PageChunk] = []
    for breadcrumb, text in _split_sections(markdown):
        if not text:
            continue
        full_breadcrumb = f"{page_title} > {breadcrumb}" if breadcrumb else page_title
        for piece in split_text_by_budget(text, full_breadcrumb, budget):
            chunks.append(PageChunk(breadcrumb=full_breadcrumb, text=piece, index=len(chunks)))
    return chunks


def split_text_by_budget(text: str, breadcrumb: str, budget: int | None = None) -> list[str]:
    """Splits text so each breadcrumb-prefixed piece fits the configured budget."""
    if not text:
        return []
    character_budget = budget or (
        config.DocumentRagConfig.CHUNK_MAX_TOKENS * config.DocumentRagConfig.CHARACTERS_PER_TOKEN
    )
    text_budget = max(character_budget - len(breadcrumb) - 2, 1)
    return _split_by_budget(text, text_budget)


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    """Splits the markdown into (breadcrumb, section text) pairs.

    The breadcrumb is the heading path below the h1 page title; a heading with no
    body text yields an empty-text section, which the caller drops while later
    sections inherit the heading in their breadcrumbs.
    """
    matches = _headings(markdown)
    if not matches:
        body = markdown.strip()
        return [("", body)] if body else []

    sections: list[tuple[str, str]] = []
    # (level, title) of the open headings; a skipped level (an h2 straight under the h1) leaves no gap.
    heading_path: list[tuple[int, str]] = []
    preamble = markdown[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 1:
            # The h1 is the page title; it is prepended by the caller, not repeated.
            heading_path = []
            breadcrumb = ""
        else:
            while heading_path and heading_path[-1][0] >= level:
                heading_path.pop()
            heading_path.append((level, title))
            breadcrumb = " > ".join(heading for _, heading in heading_path)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((breadcrumb, markdown[match.end() : end].strip()))
    return sections


def _split_by_budget(text: str, budget: int) -> list[str]:
    """Splits a section into pieces that fit the budget, breadcrumb excluded.

    The breadcrumb length is subtracted from the budget by the caller embedding it;
    here the budget applies to the piece text alone, which keeps the total
    (breadcrumb + text) within the configured budget.
    """
    if len(text) <= budget:
        return [text]
    pieces: list[str] = []
    current = ""
    for paragraph in _split_blocks(text):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= budget:
            current = candidate
        else:
            if current:
                pieces.append(current)
            if len(paragraph) <= budget:
                current = paragraph
            else:
                pieces.extend(_split_by_lines(paragraph, budget))
                current = ""
    if current:
        pieces.append(current)
    return pieces


def _split_blocks(text: str) -> list[str]:
    """Non-empty line blocks, splitting on blank lines.

    Consecutive list items or table lines stay in one block, so lists and tables
    don't get shredded across chunks.
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _split_by_lines(block: str, budget: int) -> list[str]:
    """Splits an oversized block between its lines (list items, table rows), and an oversized line between words."""
    pieces: list[str] = []
    current = ""
    for line in block.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= budget:
            current = candidate
            continue
        if current:
            pieces.append(current)
        if len(line) <= budget:
            current = line
        else:
            *full, current = _split_by_words(line, budget)
            pieces.extend(full)
    if current:
        pieces.append(current)
    return pieces


def _split_by_words(line: str, budget: int) -> list[str]:
    """Splits a line between words; a word longer than the budget is cut at the budget."""
    pieces: list[str] = []
    current = ""
    for word in line.split(" "):
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= budget:
            current = candidate
            continue
        if current:
            pieces.append(current)
        while len(word) > budget:
            pieces.append(word[:budget])
            word = word[budget:]
        current = word
    if current:
        pieces.append(current)
    return pieces
