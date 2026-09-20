# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for WS9b attachment extraction, OCR, conversion, and limits."""

import io
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

from rag_sync import ocr, office_conversion  # noqa: E402
from rag_sync.attachment_extraction import (  # noqa: E402
    ExtractionError,
    UnsupportedFormatError,
    _normalize_extracted_text,
    _page_text_with_ocr,
    extract_attachment,
    extract_attachment_async,
    skip_reason,
)
from rag_sync.office_conversion import OfficeConversionError  # noqa: E402


def _pdf_bytes(*texts: str) -> bytes:
    import pymupdf

    document = pymupdf.open()
    for text in texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def _image_bytes(size: tuple[int, int] = (80, 40), image_format: str = "PNG") -> bytes:
    from PIL import Image

    image = Image.new("RGB", size, "white")
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def _animated_gif_bytes() -> bytes:
    from PIL import Image

    frames = [Image.new("RGB", (20, 20), color) for color in ("white", "black")]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


def _docx_bytes(text: str) -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pptx_bytes(*slide_texts: str) -> bytes:
    from pptx import Presentation

    presentation = Presentation()
    for text in slide_texts:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = text
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = "First"
    workbook.active.append(["Name", "Value"])
    workbook.active.append(["Alpha", 1])
    workbook.active.append([4711])  # a numeric-only row: content, not a page footer
    second = workbook.create_sheet("Second")
    second.append(["Beta", 2])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


class TestAttachmentExtraction:
    def test_txt_and_markdown_are_verbatim_but_csv_is_normalized(self):
        content = b"  kept  \n12\nword-\nwrapped\n"

        assert extract_attachment("notes.md", content).pages[0].text == content.decode()
        assert extract_attachment("notes.md", content).pages[0].text == content.decode()
        # 12 is a CSV row, not a PDF page footer: it stays.
        assert extract_attachment("notes.csv", content).pages[0].text == "kept\n12\nwordwrapped"

    def test_pdf_extracts_native_text_and_renders_each_page(self):
        document = extract_attachment(
            "guide.pdf",
            _pdf_bytes("First page native text is long enough.", "Second page native text is long enough."),
        )

        assert document.total_page_count == 2
        assert ["First page" in page.text for page in document.pages] == [True, False]
        assert all(page.image and page.image.startswith(b"\x89PNG") for page in document.pages)

    def test_pdf_page_cap_retains_true_page_count(self):
        with patch("config.DocumentRagConfig.MAX_PAGES_PER_DOCUMENT", 1):
            document = extract_attachment(
                "guide.pdf", _pdf_bytes("First long native page.", "Second long native page.")
            )

        assert document.total_page_count == 2
        assert len(document.pages) == 1

    def test_raster_image_is_resized_normalized_and_ocrd(self):
        with (
            patch("rag_sync.ocr.extract_text", return_value="German text: Größe"),
            patch("config.DocumentRagConfig.MAX_IMAGE_PIXELS", 32),
        ):
            document = extract_attachment("diagram.jpg", _image_bytes((100, 50), "JPEG"))

        from PIL import Image

        assert document.pages[0].text == "German text: Größe"
        assert document.pages[0].image is not None
        with Image.open(io.BytesIO(document.pages[0].image)) as image:
            assert max(image.size) <= 32
            assert image.format == "PNG"

    def test_multiframe_image_obeys_page_cap_and_retains_true_count(self):
        with (
            patch("rag_sync.ocr.extract_text", return_value=""),
            patch("config.DocumentRagConfig.MAX_PAGES_PER_DOCUMENT", 1),
        ):
            document = extract_attachment("animated.gif", _animated_gif_bytes())

        assert document.total_page_count == 2
        assert len(document.pages) == 1

    def test_xlsx_is_read_sheet_by_sheet_with_page_cap(self):
        with patch("config.DocumentRagConfig.MAX_PAGES_PER_DOCUMENT", 1):
            document = extract_attachment("book.xlsx", _xlsx_bytes())

        assert document.total_page_count == 2
        assert len(document.pages) == 1
        assert "Name Value" in document.pages[0].text
        assert "4711" in document.pages[0].text
        assert document.pages[0].image is None

    @pytest.mark.parametrize(
        ("extension", "expects_image"),
        [
            (".docx", True),
            (".pptx", True),
            (".doc", True),
            (".ppt", True),
            (".odt", True),
            (".odp", True),
            (".rtf", True),
            (".xls", False),
            (".ods", False),
        ],
    )
    async def test_office_formats_use_converted_pdf(self, extension, expects_image):
        with (
            patch("rag_sync.office_conversion.conversion_available", return_value=True),
            patch(
                "rag_sync.office_conversion.convert_to_pdf",
                return_value=_pdf_bytes("Converted page has native text."),
            ),
        ):
            document = await extract_attachment_async(f"document{extension}", b"source")

        assert "Converted page" in document.pages[0].text
        assert (document.pages[0].image is not None) is expects_image

    async def test_docx_falls_back_to_native_reader_when_conversion_is_unavailable(self):
        with patch("rag_sync.office_conversion.conversion_available", return_value=False):
            document = await extract_attachment_async("guide.docx", _docx_bytes("Native DOCX text"))

        assert document.pages[0].text == "Native DOCX text"
        assert document.pages[0].image is None

    async def test_pptx_fallback_keeps_one_page_per_slide_and_true_count(self):
        with (
            patch("rag_sync.office_conversion.conversion_available", return_value=True),
            patch(
                "rag_sync.office_conversion.convert_to_pdf",
                side_effect=OfficeConversionError("failed"),
            ),
            patch("config.DocumentRagConfig.MAX_PAGES_PER_DOCUMENT", 1),
        ):
            document = await extract_attachment_async("slides.pptx", _pptx_bytes("First slide", "Second slide"))

        assert document.total_page_count == 2
        assert len(document.pages) == 1
        assert "First slide" in document.pages[0].text

    async def test_convert_only_format_fails_when_conversion_is_unavailable(self):
        with (
            patch("rag_sync.office_conversion.conversion_available", return_value=False),
            pytest.raises(OfficeConversionError, match="needs it"),
        ):
            await extract_attachment_async("legacy.doc", b"source")

    @pytest.mark.parametrize(
        ("file_name", "conversion_available", "expected_reason"),
        [
            ("archive.zip", True, "not ingested"),
            ("no-extension", True, "not ingested"),
            ("legacy.doc", False, "needs office conversion"),
            ("legacy.doc", True, None),
            ("guide.docx", False, None),
            ("Scan.PNG", False, None),
        ],
    )
    def test_skip_reason_covers_unsupported_and_unconvertible_formats(
        self, file_name, conversion_available, expected_reason
    ):
        with patch("rag_sync.office_conversion.conversion_available", return_value=conversion_available):
            reason = skip_reason(file_name)

        if expected_reason is None:
            assert reason is None
        else:
            assert expected_reason in reason

    def test_unsupported_format_is_rejected(self):
        with pytest.raises(UnsupportedFormatError):
            extract_attachment("archive.zip", b"zip")

    def test_sync_api_rejects_office_files(self):
        with pytest.raises(ExtractionError, match="extract_attachment_async"):
            extract_attachment("guide.docx", b"source")

    def test_normalization_repairs_hyphenation_and_drops_page_numbers_only_when_asked(self):
        text = " multi   space \n42\nhyphen-\nated\n\n\nend "
        assert _normalize_extracted_text(text, strip_page_numbers=True) == "multi space\nhyphenated\n\nend"
        assert _normalize_extracted_text(text) == "multi space\n42\nhyphenated\n\nend"

    def test_ocr_rules_use_full_page_for_image_only_and_embedded_images_for_text_pages(self):
        page = MagicMock()
        page.get_images.return_value = [(7,), (7,)]
        page.parent.extract_image.return_value = {"image": _image_bytes()}
        with patch("rag_sync.ocr.extract_text", side_effect=["full page", "embedded"]) as extract_text:
            assert _page_text_with_ocr(page, "", b"page") == "full page"
            native = "This native text is comfortably above the OCR threshold."
            combined = _page_text_with_ocr(page, native, b"page")

        assert combined == f"{native}\n\n[embedded image text]\nembedded"
        assert extract_text.call_count == 2
        page.parent.extract_image.assert_called_once_with(7)


class TestOfficeConversion:
    async def test_timeout_is_reported_as_conversion_error(self):
        with (
            patch(
                "rag_sync.office_conversion._run_soffice",
                side_effect=subprocess.TimeoutExpired("soffice", 1),
            ),
            pytest.raises(OfficeConversionError, match="timed out"),
        ):
            await office_conversion.convert_to_pdf(b"source", "guide.docx")

    async def test_filename_is_sanitized_inside_the_temporary_directory(self):
        seen_source = None

        def fake_convert(source: Path, output_directory: Path) -> Path:
            nonlocal seen_source
            seen_source = source
            pdf = output_directory / f"{source.stem}.pdf"
            pdf.write_bytes(b"pdf")
            return pdf

        with patch("rag_sync.office_conversion._run_soffice", side_effect=fake_convert):
            result = await office_conversion.convert_to_pdf(b"source", "../unsafe.docx")

        assert result == b"pdf"
        assert seen_source is not None
        assert seen_source.name == "unsafe.docx"
        assert seen_source.parent.name.startswith("rag-convert-")

    def test_soffice_runs_headless_safe_and_with_isolated_profile(self, tmp_path):
        source = tmp_path / "guide.docx"
        source.write_bytes(b"source")
        output_directory = tmp_path / "out"
        output_directory.mkdir()

        def fake_run(command, **kwargs):
            (output_directory / "guide.pdf").write_bytes(b"pdf")
            return MagicMock(returncode=0, stderr="")

        with (
            patch("rag_sync.office_conversion.shutil.which", return_value="/usr/bin/soffice"),
            patch("rag_sync.office_conversion.subprocess.run", side_effect=fake_run) as run,
        ):
            produced = office_conversion._run_soffice(source, output_directory)

        command = run.call_args.args[0]
        assert "--headless" in command
        assert "--safe-mode" in command
        assert any(argument.startswith("-env:UserInstallation=file:") for argument in command)
        assert produced.read_bytes() == b"pdf"


class TestOcr:
    def setup_method(self):
        ocr._engine = None
        ocr._engine_initialization_attempted = False

    def teardown_method(self):
        ocr._engine = None
        ocr._engine_initialization_attempted = False

    def test_engine_is_initialized_once_with_packaged_model_paths(self, tmp_path, monkeypatch):
        created = []

        class FakeRapidOcr:
            def __init__(self, params):
                created.append(params)

        monkeypatch.setitem(
            sys.modules,
            "rapidocr",
            types.SimpleNamespace(__file__=str(tmp_path / "__init__.py"), RapidOCR=FakeRapidOcr),
        )

        assert ocr.get_engine() is ocr.get_engine()
        assert len(created) == 1
        models_dir = tmp_path / "models"
        assert created[0]["Det.model_path"] == str(models_dir / "PP-OCRv6_det_small.onnx")
        assert created[0]["Cls.model_path"] == str(models_dir / "ch_ppocr_mobile_v2.0_cls_mobile.onnx")
        assert created[0]["Rec.model_path"] == str(models_dir / "PP-OCRv6_rec_small.onnx")

    @pytest.mark.parametrize(("lines", "expected"), [(("first", "second"), "first\nsecond"), (None, "")])
    def test_ocr_lines_are_joined_and_empty_detection_yields_empty_text(self, lines, expected):
        ocr._engine = MagicMock(return_value=types.SimpleNamespace(txts=lines))
        ocr._engine_initialization_attempted = True

        assert ocr.extract_text(b"image") == expected

    def test_ocr_failure_degrades_to_empty_text(self):
        engine = MagicMock(side_effect=RuntimeError("bad image"))
        ocr._engine = engine
        ocr._engine_initialization_attempted = True

        assert ocr.extract_text(b"image") == ""
