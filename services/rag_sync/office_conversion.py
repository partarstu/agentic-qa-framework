# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Bounded, isolated headless LibreOffice conversion for office attachments."""

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

import config
from common import utils

logger = utils.get_logger("rag_office_conversion")

_semaphore: asyncio.Semaphore | None = None


class OfficeConversionError(RuntimeError):
    """An office document could not be converted to PDF."""


def conversion_available() -> bool:
    """Returns whether office conversion is enabled and LibreOffice is installed."""
    if not config.DocumentRagConfig.OFFICE_CONVERSION_ENABLED:
        logger.warning("Office conversion is disabled; affected formats are skipped.")
        return False
    if shutil.which("soffice") is None:
        logger.warning("The LibreOffice binary (soffice) is missing; affected formats are skipped.")
        return False
    return True


async def convert_to_pdf(source_bytes: bytes, file_name: str) -> bytes:
    """Converts one office attachment to PDF under the configured timeout."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(config.DocumentRagConfig.OFFICE_CONVERSION_CONCURRENCY)

    safe_name = file_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "attachment"
    async with _semaphore:
        with tempfile.TemporaryDirectory(prefix="rag-convert-") as workdir:
            work = Path(workdir)
            source = work / safe_name
            source.write_bytes(source_bytes)
            output_directory = work / "out"
            output_directory.mkdir()
            try:
                pdf = await asyncio.wait_for(
                    asyncio.to_thread(_run_soffice, source, output_directory),
                    timeout=config.DocumentRagConfig.OFFICE_CONVERSION_TIMEOUT_SECONDS + 1,
                )
            except (TimeoutError, subprocess.TimeoutExpired) as error:
                raise OfficeConversionError(
                    f"Converting '{safe_name}' timed out after "
                    f"{config.DocumentRagConfig.OFFICE_CONVERSION_TIMEOUT_SECONDS} seconds."
                ) from error
            return pdf.read_bytes()


def _run_soffice(source: Path, output_directory: Path) -> Path:
    """Runs one synchronous LibreOffice process with an isolated temporary profile."""
    soffice = shutil.which("soffice")
    if soffice is None:
        raise OfficeConversionError("The LibreOffice binary (soffice) is missing.")

    with tempfile.TemporaryDirectory(prefix="rag-lo-profile-") as profile:
        command = [
            soffice,
            "--headless",
            "--safe-mode",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--nofirststartwizard",
            f"-env:UserInstallation={Path(profile).as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_directory),
            str(source),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=config.DocumentRagConfig.OFFICE_CONVERSION_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise
        if result.returncode != 0:
            raise OfficeConversionError(f"soffice exited with {result.returncode}: {result.stderr.strip()}")

    produced = output_directory / f"{source.stem}.pdf"
    if not produced.exists():
        raise OfficeConversionError(f"soffice produced no PDF for {source.name}.")
    return produced
