from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen

from .utils import safe_filename


MINERU_ARTIFACT_INDEX_NAME = "mineru_artifact_index.json"
MINERU_RICH_ARTIFACT_TYPES = {
    "content_list",
    "content_list_v2",
    "middle_json",
    "model_json",
    "image",
    "origin_pdf",
}


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
    gateway_url: str | None = None
    gateway_api_key: str | None = None
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
            gateway_url=os.getenv("MINERU_GATEWAY_URL") or None,
            gateway_api_key=os.getenv("MINERU_GATEWAY_API_KEY") or os.getenv("CONVERSION_GATEWAY_API_KEY") or None,
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

        if suffix in {".xlsx", ".pdf"}:
            return self._convert_with_mineru(source_path, output_md, language, artifact_root, status_callback)

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
        if self.gateway_url:
            return self._convert_with_gateway(source_path, output_md, language, artifact_root, status_callback)
        return self._convert_with_mineru(source_path, output_md, language, artifact_root, status_callback)

    def _convert_with_gateway(
        self,
        source_path: Path,
        output_md: Path,
        language: str = "vi",
        artifact_root: Path | None = None,
        status_callback: Callable[[str, str], None] | None = None,
    ) -> Path:
        try:
            import requests
        except Exception as exc:  # pragma: no cover - dependency guard
            raise ConversionError("requests is required for MinerU conversion gateway integration") from exc

        gateway = str(self.gateway_url or "").rstrip("/")
        if not gateway:
            raise ConversionError("MinerU gateway URL is empty")
        headers = {"X-API-Key": self.gateway_api_key} if self.gateway_api_key else {}
        lang = "latin" if language == "vi" else "en"
        _emit(status_callback, "check_service", f"Checking MinerU conversion gateway at {gateway}")
        health = requests.get(f"{gateway}/health", headers=headers, timeout=10)
        health.raise_for_status()

        _emit(status_callback, "submit", "Submitting MinerU gateway conversion task")
        with source_path.open("rb") as handle:
            files = {"files[]": (source_path.name, handle, "application/octet-stream")}
            data = {
                "parse_method": self.method,
                "lang": lang,
                "return_images": "true",
                "postprocess_vi": "false",
            }
            response = requests.post(
                f"{gateway}/v1/conversions",
                headers=headers,
                files=files,
                data=data,
                timeout=60,
            )
        response.raise_for_status()
        payload = response.json()
        jobs = payload.get("jobs") or []
        if not jobs:
            raise ConversionError(f"MinerU gateway did not return a job: {payload}")
        job_id = str(jobs[0]["job_id"])

        deadline = time.monotonic() + self.timeout_seconds
        status_payload: dict[str, object] = {}
        while time.monotonic() < deadline:
            _emit(status_callback, "parse", f"Polling MinerU gateway job {job_id}")
            status_response = requests.get(f"{gateway}/v1/conversions/{job_id}", headers=headers, timeout=30)
            status_response.raise_for_status()
            status_payload = status_response.json()
            status = status_payload.get("status")
            if status == "completed":
                break
            if status in {"failed", "cancelled"}:
                raise ConversionError(f"MinerU gateway job {job_id} failed: {status_payload.get('error')}")
            time.sleep(2)
        else:
            raise ConversionError(f"MinerU gateway job {job_id} timed out after {self.timeout_seconds}s")

        _emit(status_callback, "download", f"Downloading MinerU gateway result for {job_id}")
        result_response = requests.get(f"{gateway}/v1/conversions/{job_id}/result", headers=headers, timeout=120)
        if result_response.status_code != 200:
            raise ConversionError(
                f"MinerU gateway result download failed: HTTP {result_response.status_code}: {result_response.text}"
            )
        result_root = (artifact_root or output_md.parent / "_mineru_raw") / "gateway" / job_id
        result_root.mkdir(parents=True, exist_ok=True)
        zip_path = result_root / "mineru_result.zip"
        zip_path.write_bytes(result_response.content)
        with zipfile.ZipFile(zip_path) as archive:
            markdown_names = sorted(
                (name for name in archive.namelist() if name.lower().endswith(".md")),
                key=lambda name: ("/postprocess/" in name.replace("\\", "/").lower(), len(name)),
            )
            if not markdown_names:
                raise ConversionError(f"MinerU gateway result did not contain Markdown for job {job_id}")
            selected_name = markdown_names[0]
            output_md.write_bytes(archive.read(selected_name))
            manifest_path = result_root / "zip_manifest.txt"
            manifest_path.write_text("\n".join(archive.namelist()) + "\n", encoding="utf-8")
            _emit(status_callback, "extract_artifacts", "Extracting MinerU sidecar metadata and images")
            collect_mineru_zip_artifacts(
                zip_path=zip_path,
                result_root=result_root,
                output_md=output_md,
                selected_markdown_name=selected_name,
                source_path=source_path,
                job_id=job_id,
            )
        if not output_md.exists():
            raise ConversionError(f"MinerU gateway result did not contain Markdown for job {job_id}")
        _emit(status_callback, "build_outputs", f"Markdown built from MinerU gateway result {selected_name}")
        return output_md

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
        staged_source_path = self._stage_input_for_mineru(source_path, mineru_output_base)
        mineru_output = mineru_output_base
        mineru_output.mkdir(parents=True, exist_ok=True)
        lang = "en" if language == "en" else "ch"
        command = [
            mineru_bin,
            "--path",
            str(staged_source_path),
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
                _emit(status_callback, "extract_artifacts", "Indexing partial MinerU artifacts after non-zero exit")
                collect_mineru_directory_artifacts(
                    source_root=mineru_output,
                    output_md=output_md,
                    selected_markdown_path=markdown_files[0],
                    source_path=source_path,
                )
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
        _emit(status_callback, "extract_artifacts", "Indexing MinerU sidecar metadata and images")
        collect_mineru_directory_artifacts(
            source_root=mineru_output,
            output_md=output_md,
            selected_markdown_path=markdown_files[0],
            source_path=source_path,
        )
        _emit(status_callback, "build_outputs", f"Markdown built from {markdown_files[0]}")
        return output_md

    def _stage_input_for_mineru(self, source_path: Path, mineru_output_base: Path) -> Path:
        """Stage input near artifacts while preserving the filename MinerU uses for outputs."""
        ascii_stage = _env_bool("MINERU_ASCII_STAGE_INPUT", default=False)
        safe_stem = safe_filename(source_path.stem)[:120] if ascii_stage else source_path.stem[:120]
        staged_dir = mineru_output_base / "_input"
        staged_dir.mkdir(parents=True, exist_ok=True)
        staged_path = staged_dir / f"{safe_stem}{source_path.suffix.lower()}"
        shutil.copy2(source_path, staged_path)
        return staged_path

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
            "gateway_url": self.gateway_url,
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


def collect_mineru_zip_artifacts(
    *,
    zip_path: Path,
    result_root: Path,
    output_md: Path,
    selected_markdown_name: str,
    source_path: Path,
    job_id: str | None = None,
) -> Path:
    artifact_root = result_root / "mineru_artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = [
        {
            "artifact_id": "mineru_markdown_selected",
            "type": "markdown",
            "path": str(output_md),
            "zip_member": selected_markdown_name,
            "selected": True,
            "size_bytes": output_md.stat().st_size if output_md.exists() else None,
            "checksum": _sha256_path(output_md) if output_md.exists() else None,
        }
    ]
    used_paths: set[Path] = set()
    with zipfile.ZipFile(zip_path) as archive:
        for member_index, member_name in enumerate(archive.namelist(), start=1):
            if member_name.endswith("/"):
                continue
            artifact_type = _mineru_artifact_type(member_name)
            if artifact_type not in MINERU_RICH_ARTIFACT_TYPES:
                continue
            data = archive.read(member_name)
            destination = _mineru_artifact_destination(artifact_root, member_name, artifact_type, used_paths)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            entry = {
                "artifact_id": f"mineru_{artifact_type}_{member_index}",
                "type": artifact_type,
                "path": str(destination),
                "zip_member": member_name,
                "selected": False,
                "size_bytes": len(data),
                "checksum": _sha256_bytes(data),
            }
            if artifact_type.endswith("_json") or artifact_type.startswith("content_list"):
                entry["json_summary"] = _json_artifact_summary(data)
            artifacts.append(entry)

    index = _mineru_artifact_index_payload(
        source_path=source_path,
        output_md=output_md,
        artifacts=artifacts,
        zip_path=zip_path,
        selected_markdown_name=selected_markdown_name,
        job_id=job_id,
    )
    index_path = result_root / MINERU_ARTIFACT_INDEX_NAME
    _write_json(index_path, index)
    return index_path


def collect_mineru_directory_artifacts(
    *,
    source_root: Path,
    output_md: Path,
    selected_markdown_path: Path,
    source_path: Path,
) -> Path:
    artifact_root = source_root / "mineru_artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = [
        {
            "artifact_id": "mineru_markdown_selected",
            "type": "markdown",
            "path": str(output_md),
            "source_path": str(selected_markdown_path),
            "selected": True,
            "size_bytes": output_md.stat().st_size if output_md.exists() else None,
            "checksum": _sha256_path(output_md) if output_md.exists() else None,
        }
    ]
    used_paths: set[Path] = set()
    files = [path for path in source_root.rglob("*") if path.is_file() and path.name != MINERU_ARTIFACT_INDEX_NAME]
    for artifact_index, path in enumerate(files, start=1):
        try:
            path.relative_to(artifact_root)
            continue
        except ValueError:
            pass
        artifact_type = _mineru_artifact_type(path.as_posix())
        if artifact_type not in MINERU_RICH_ARTIFACT_TYPES:
            continue
        destination = _mineru_artifact_destination(artifact_root, path.name, artifact_type, used_paths)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        data = destination.read_bytes()
        entry = {
            "artifact_id": f"mineru_{artifact_type}_{artifact_index}",
            "type": artifact_type,
            "path": str(destination),
            "source_path": str(path),
            "selected": False,
            "size_bytes": destination.stat().st_size,
            "checksum": _sha256_bytes(data),
        }
        if artifact_type.endswith("_json") or artifact_type.startswith("content_list"):
            entry["json_summary"] = _json_artifact_summary(data)
        artifacts.append(entry)

    index = _mineru_artifact_index_payload(
        source_path=source_path,
        output_md=output_md,
        artifacts=artifacts,
        selected_markdown_name=str(selected_markdown_path),
    )
    index_path = source_root / MINERU_ARTIFACT_INDEX_NAME
    _write_json(index_path, index)
    return index_path


def find_mineru_artifact_index(search_root: Path, output_md: Path | None = None) -> Path | None:
    if not search_root.exists():
        return None
    candidates = sorted(
        search_root.rglob(MINERU_ARTIFACT_INDEX_NAME),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if output_md is None:
        return candidates[0] if candidates else None
    try:
        expected = output_md.resolve()
    except OSError:
        expected = output_md
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        indexed_output = payload.get("output_markdown_path")
        if not indexed_output:
            continue
        try:
            if Path(str(indexed_output)).resolve() == expected:
                return candidate
        except OSError:
            if str(indexed_output) == str(output_md):
                return candidate
    return candidates[0] if candidates else None


def _mineru_artifact_index_payload(
    *,
    source_path: Path,
    output_md: Path,
    artifacts: list[dict[str, Any]],
    selected_markdown_name: str,
    zip_path: Path | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    summary = {
        "has_content_list": any(item["type"] == "content_list" for item in artifacts),
        "has_content_list_v2": any(item["type"] == "content_list_v2" for item in artifacts),
        "has_middle_json": any(item["type"] == "middle_json" for item in artifacts),
        "has_model_json": any(item["type"] == "model_json" for item in artifacts),
        "image_count": sum(1 for item in artifacts if item["type"] == "image"),
        "rich_artifact_count": sum(1 for item in artifacts if item["type"] in MINERU_RICH_ARTIFACT_TYPES),
    }
    return {
        "schema_version": "mineru_artifact_index_v1",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_path": str(source_path),
        "source_name": source_path.name,
        "output_markdown_path": str(output_md),
        "selected_markdown": selected_markdown_name,
        "mineru_result_zip": str(zip_path) if zip_path else None,
        "job_id": job_id,
        "summary": summary,
        "artifacts": artifacts,
    }


def _mineru_artifact_type(name: str) -> str:
    normalized = name.replace("\\", "/").lower()
    filename = normalized.rsplit("/", 1)[-1]
    if filename.endswith("_content_list_v2.json"):
        return "content_list_v2"
    if filename.endswith("_content_list.json"):
        return "content_list"
    if filename.endswith("_middle.json"):
        return "middle_json"
    if filename.endswith("_model.json"):
        return "model_json"
    if filename.endswith(".md"):
        return "markdown"
    if filename.endswith("_origin.pdf") or filename == "origin.pdf":
        return "origin_pdf"
    image_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    if "/images/" in normalized or any(filename.endswith(ext) for ext in image_extensions):
        return "image"
    if filename.endswith(".json"):
        return "json"
    return "other"


def _mineru_artifact_destination(
    artifact_root: Path,
    original_name: str,
    artifact_type: str,
    used_paths: set[Path],
) -> Path:
    filename = safe_filename(Path(original_name.replace("\\", "/")).name)
    if artifact_type == "content_list":
        candidate = artifact_root / "metadata" / "content_list.json"
    elif artifact_type == "content_list_v2":
        candidate = artifact_root / "metadata" / "content_list_v2.json"
    elif artifact_type == "middle_json":
        candidate = artifact_root / "metadata" / "middle.json"
    elif artifact_type == "model_json":
        candidate = artifact_root / "metadata" / "model.json"
    elif artifact_type == "image":
        candidate = artifact_root / "images" / filename
    elif artifact_type == "origin_pdf":
        candidate = artifact_root / "origin" / filename
    else:
        candidate = artifact_root / "metadata" / filename

    if candidate not in used_paths and not candidate.exists():
        used_paths.add(candidate)
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 10_000):
        alternative = candidate.with_name(f"{stem}_{index}{suffix}")
        if alternative not in used_paths and not alternative.exists():
            used_paths.add(alternative)
            return alternative
    raise ConversionError(f"Could not allocate MinerU artifact path for {original_name}")


def _json_artifact_summary(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"parseable": False, "error": str(exc)}
    summary: dict[str, Any] = {"parseable": True, "top_level_type": type(payload).__name__}
    if isinstance(payload, list):
        summary["item_count"] = len(payload)
        if payload and all(isinstance(item, list) for item in payload):
            summary["page_count"] = len(payload)
            summary["block_count"] = sum(len(item) for item in payload if isinstance(item, list))
        content_types = sorted(_content_types_from_payload(payload))
        if content_types:
            summary["content_types"] = content_types
    elif isinstance(payload, dict):
        summary["keys"] = sorted(str(key) for key in payload.keys())[:50]
        if isinstance(payload.get("pdf_info"), list):
            summary["page_count"] = len(payload["pdf_info"])
        content_types = sorted(_content_types_from_payload(payload))
        if content_types:
            summary["content_types"] = content_types
    return summary


def _content_types_from_payload(payload: Any) -> set[str]:
    content_types: set[str] = set()
    if isinstance(payload, dict):
        value = payload.get("type")
        if isinstance(value, str):
            content_types.add(value)
        for child in payload.values():
            content_types.update(_content_types_from_payload(child))
    elif isinstance(payload, list):
        for item in payload:
            content_types.update(_content_types_from_payload(item))
    return content_types


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
