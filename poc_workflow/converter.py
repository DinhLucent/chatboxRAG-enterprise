from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen


class ConversionError(RuntimeError):
    pass


class OcrRequiredError(ConversionError):
    pass


@dataclass
class MinerUConverter:
    command: str = "mineru"
    method: str = "auto"
    backend: str | None = "pipeline"
    api_url: str | None = None
    backend_url: str | None = None
    formula: bool | None = True
    table: bool | None = True
    image_analysis: bool | None = True
    max_pages: int | None = None
    timeout_seconds: int = 60 * 30

    @classmethod
    def from_env(cls) -> "MinerUConverter":
        timeout = int(os.getenv("MINERU_TIMEOUT_SECONDS", str(60 * 30)))
        return cls(
            command=os.getenv("MINERU_EXECUTABLE", "mineru"),
            method=os.getenv("MINERU_METHOD", "auto"),
            backend=os.getenv("MINERU_BACKEND") or "pipeline",
            api_url=os.getenv("MINERU_API_URL") or None,
            backend_url=os.getenv("MINERU_BACKEND_URL") or None,
            formula=_env_bool("MINERU_FORMULA", default=True),
            table=_env_bool("MINERU_TABLE", default=True),
            image_analysis=_env_bool("MINERU_IMAGE_ANALYSIS", default=True),
            max_pages=_env_int("MINERU_MAX_PAGES"),
            timeout_seconds=timeout,
        )

    def convert(
        self,
        source_path: Path,
        output_md: Path,
        language: str = "vi",
        artifact_root: Path | None = None,
        status_callback: Callable[[str, str], None] | None = None,
    ) -> Path:
        suffix = source_path.suffix.lower()
        output_md.parent.mkdir(parents=True, exist_ok=True)

        if suffix in {".md", ".markdown"}:
            _emit(status_callback, "build_outputs", "Copying Markdown source")
            shutil.copy2(source_path, output_md)
            return output_md

        if suffix == ".txt":
            _emit(status_callback, "build_outputs", "Converting text source to Markdown")
            text = source_path.read_text(encoding="utf-8", errors="ignore").strip()
            output_md.write_text(text + "\n", encoding="utf-8")
            return output_md

        if suffix == ".docx":
            _emit(status_callback, "build_outputs", "Converting DOCX to Markdown")
            self._convert_docx(source_path, output_md)
            return output_md

        if suffix == ".xlsx":
            _emit(status_callback, "build_outputs", "Converting XLSX to Markdown")
            self._convert_xlsx(source_path, output_md)
            return output_md

        if suffix == ".pdf":
            try:
                return self._convert_with_mineru(source_path, output_md, language, artifact_root, status_callback)
            except ConversionError as mineru_error:
                _emit(status_callback, "build_outputs", "Falling back to embedded PDF text extraction")
                self._convert_pdf_text_fallback(source_path, output_md, mineru_error)
                return output_md

        return self._convert_with_mineru(source_path, output_md, language, artifact_root, status_callback)

    def convert_with_mineru(
        self,
        source_path: Path,
        output_md: Path,
        language: str = "vi",
        artifact_root: Path | None = None,
        status_callback: Callable[[str, str], None] | None = None,
    ) -> Path:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        return self._convert_with_mineru(source_path, output_md, language, artifact_root, status_callback)

    def _convert_with_mineru(
        self,
        source_path: Path,
        output_md: Path,
        language: str = "vi",
        artifact_root: Path | None = None,
        status_callback: Callable[[str, str], None] | None = None,
    ) -> Path:
        mineru_bin = shutil.which(self.command)
        if not mineru_bin:
            raise ConversionError("MinerU CLI not found. Install/configure mineru or use Markdown/TXT sources.")

        _emit(status_callback, "check_service", self._service_detail())
        self._check_service()

        mineru_output_base = artifact_root or output_md.parent / "_mineru_raw"
        mineru_output = mineru_output_base / source_path.stem
        mineru_output.mkdir(parents=True, exist_ok=True)
        lang = "en" if language == "en" else "ch"
        command = [
            mineru_bin,
            "--path",
            str(source_path),
            "--output",
            str(mineru_output),
            "--method",
            self.method,
            "--lang",
            lang,
        ]
        if self.max_pages is not None:
            command.extend(["--start", "0", "--end", str(max(0, self.max_pages - 1))])
        if self.api_url:
            command.extend(["--api-url", self.api_url])
        if self.backend:
            command.extend(["--backend", self.backend])
        if self.backend_url:
            command.extend(["--url", self.backend_url])
        if self.formula is not None:
            command.extend(["--formula", str(self.formula).lower()])
        if self.table is not None:
            command.extend(["--table", str(self.table).lower()])
        if self.image_analysis is not None:
            command.extend(["--image-analysis", str(self.image_analysis).lower()])
        _emit(status_callback, "submit", "Submitting MinerU task")
        _emit(status_callback, "parse", self.profile_summary())
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
        )
        if result.returncode != 0:
            markdown_files = sorted(mineru_output.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
            if markdown_files:
                shutil.copy2(markdown_files[0], output_md)
                _emit(
                    status_callback,
                    "build_outputs",
                    f"Markdown built from {markdown_files[0]} after MinerU returned a non-zero status",
                )
                return output_md
            raise ConversionError(result.stderr.strip() or result.stdout.strip() or "MinerU conversion failed")

        _emit(status_callback, "download", "MinerU task completed; collecting output files")
        markdown_files = sorted(mineru_output.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not markdown_files:
            raise ConversionError(f"MinerU did not produce a Markdown file under {mineru_output}")
        shutil.copy2(markdown_files[0], output_md)
        _emit(status_callback, "build_outputs", f"Markdown built from {markdown_files[0]}")
        return output_md

    def profile_summary(self) -> str:
        return (
            f"MinerU parse: backend={self.backend or 'default'}, method={self.method}, "
            f"formula={self.formula}, table={self.table}, image_analysis={self.image_analysis}, "
            f"max_pages={self.max_pages or 'all'}"
        )

    def profile_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "method": self.method,
            "backend": self.backend,
            "api_url": self.api_url,
            "backend_url": self.backend_url,
            "formula": self.formula,
            "table": self.table,
            "image_analysis": self.image_analysis,
            "max_pages": self.max_pages,
            "timeout_seconds": self.timeout_seconds,
        }

    def _service_detail(self) -> str:
        if self.api_url:
            return f"Checking MinerU API service at {self.api_url}"
        return "Checking MinerU CLI and local service startup path"

    def _check_service(self) -> None:
        if not self.api_url:
            return
        health_url = self.api_url.rstrip("/") + "/health"
        try:
            with urlopen(health_url, timeout=10) as response:
                if response.status >= 400:
                    raise ConversionError(f"MinerU API health check failed: HTTP {response.status}")
        except (OSError, URLError) as exc:
            raise ConversionError(f"MinerU API is not ready at {health_url}: {exc}") from exc

    def _convert_pdf_text_fallback(self, source_path: Path, output_md: Path, mineru_error: Exception) -> None:
        lines = [
            f"# {source_path.stem}",
            "",
            "> Note: MinerU conversion was attempted first, but did not return usable Markdown. "
            "This fallback extracted embedded PDF text/tables for review.",
            "",
        ]

        extracted = False
        try:
            import pdfplumber

            with pdfplumber.open(source_path) as pdf:
                for page_index, page in enumerate(pdf.pages, start=1):
                    page_lines: list[str] = []
                    text = (page.extract_text() or "").strip()
                    if text:
                        page_lines.extend([text, ""])
                    for table_index, table in enumerate(page.extract_tables() or [], start=1):
                        rows = [[_clean_cell(cell) for cell in row] for row in table]
                        if not _has_table_content(rows):
                            continue
                        page_lines.extend([f"### Table {page_index}.{table_index}", ""])
                        _append_markdown_table(page_lines, rows)
                        page_lines.append("")
                    if page_lines:
                        lines.extend([f"## Page {page_index}", "", *page_lines])
                        extracted = True
        except Exception:
            extracted = False

        if not extracted:
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(source_path))
                for page_index, page in enumerate(reader.pages, start=1):
                    text = (page.extract_text() or "").strip()
                    if not text:
                        continue
                    lines.extend([f"## Page {page_index}", "", text, ""])
                    extracted = True
            except Exception as fallback_error:
                raise ConversionError(
                    f"MinerU failed and PDF text fallback failed: {fallback_error}. MinerU error: {mineru_error}"
                ) from fallback_error

        if not extracted:
            raise OcrRequiredError(f"MinerU failed and PDF text fallback found no embedded text: {mineru_error}")

        _write_markdown(output_md, lines)

    def _convert_docx(self, source_path: Path, output_md: Path) -> None:
        try:
            from docx import Document
        except Exception as exc:
            raise ConversionError("python-docx is required to convert DOCX files") from exc

        document = Document(str(source_path))
        lines = [f"# {source_path.stem}", ""]
        for paragraph in document.paragraphs:
            text = _clean_cell(paragraph.text)
            if text:
                lines.extend([text, ""])
        for index, table in enumerate(document.tables, start=1):
            rows = [[_clean_cell(cell.text) for cell in row.cells] for row in table.rows]
            if not _has_table_content(rows):
                continue
            lines.extend([f"## Table {index}", ""])
            _append_markdown_table(lines, rows)
            lines.append("")
        _write_markdown(output_md, lines)

    def _convert_xlsx(self, source_path: Path, output_md: Path) -> None:
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise ConversionError("openpyxl is required to convert XLSX files") from exc

        workbook = load_workbook(filename=source_path, data_only=True, read_only=True)
        lines = [f"# {source_path.stem}", ""]
        for worksheet in workbook.worksheets:
            rows: list[list[str]] = []
            for row in worksheet.iter_rows(values_only=True):
                values = [_clean_cell(value) for value in row]
                while values and not values[-1]:
                    values.pop()
                if any(values):
                    rows.append(values)
            if not rows:
                continue
            lines.extend([f"## Sheet: {worksheet.title}", ""])
            _append_markdown_table(lines, rows)
            lines.append("")
        workbook.close()
        _write_markdown(output_md, lines)


def _write_markdown(output_md: Path, lines: list[str]) -> None:
    text = "\n".join(lines).strip()
    if len(text) < 20:
        raise ConversionError(f"Converted Markdown is empty or too short: {output_md}")
    output_md.write_text(text + "\n", encoding="utf-8")


def _append_markdown_table(lines: list[str], rows: list[list[str]]) -> None:
    if not _has_table_content(rows):
        return
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = [_markdown_cell(cell) for cell in normalized[0]]
    if not any(header):
        header = [f"Column {index}" for index in range(1, width + 1)]
    else:
        header = [cell or f"Column {index}" for index, cell in enumerate(header, start=1)]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in row) + " |")


def _has_table_content(rows: list[list[str]]) -> bool:
    return any(any(cell for cell in row) for row in rows)


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", "\n").split())


def _markdown_cell(value: object) -> str:
    return _clean_cell(value).replace("|", "\\|")


def _emit(callback: Callable[[str, str], None] | None, step: str, detail: str) -> None:
    if callback is not None:
        callback(step, detail)


def _env_bool(name: str, default: bool | None = None) -> bool | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None
