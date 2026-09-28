"""Trusted local CLI adapters over the same Python tools used by the web app.

One JSON object on stdin; one JSON result or {"error":"CODE"} on stdout.
File paths are trusted CLI inputs, never accepted as web API file selectors.
"""
import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from .core import AppError, ensure
from .pdf import pdf_operation


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class TextPrescription(Strict):
    op: Literal["text"]
    text: str = Field(min_length=1, max_length=50000)
    cloudConsent: bool = False


class FilePrescription(Strict):
    op: Literal["file"]
    path: str = Field(min_length=1, max_length=4096)
    cloudConsent: bool = False


class DetailRequest(Strict):
    op: Literal["detail"]
    itemId: str = Field(pattern=r"^\d{5,20}$")


class LookupRequest(Strict):
    op: Literal["lookup"]
    name: str = Field(min_length=2, max_length=120)


class PdfIndex(Strict):
    op: Literal["index"]
    pdf: str
    index: str


class PdfSearch(PdfIndex):
    op: Literal["search"]
    terms: list[str] = Field(min_length=1, max_length=25)

    @field_validator("terms")
    @classmethod
    def bounded_terms(cls, terms):
        if any(not term.strip() or len(term) > 120 for term in terms):
            raise ValueError("invalid term")
        return terms


class PdfContext(PdfIndex):
    op: Literal["context"]
    page: int = Field(ge=1, le=1000)
    start: int = Field(ge=0)
    end: int | None = Field(default=None, gt=0)
    before: int = Field(default=0, ge=0, le=2)
    after: int = Field(default=3, ge=0, le=4)
    nextPage: bool = False


class Segment(Strict):
    index: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quad: list[float] | None

    @field_validator("quad")
    @classmethod
    def eight_coordinates(cls, value):
        if value is not None and len(value) != 8:
            raise ValueError("invalid quad")
        return value


class Hit(Strict):
    id: str = Field(min_length=1, max_length=100)
    page: int = Field(ge=1, le=1000)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    sourceStart: int = Field(ge=0)
    sourceEnd: int = Field(gt=0)
    quote: str = Field(max_length=200000)
    matchedText: str = Field(max_length=200000)
    segments: list[Segment] = Field(max_length=200000)
    documentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    offsetEncoding: Literal["unicode-code-points"]


class PdfAnnotate(PdfIndex):
    op: Literal["annotate"]
    output: str
    hits: list[Hit] = Field(max_length=160)


SCHEMAS = {
    "ocr-prescription": TypeAdapter(Annotated[TextPrescription | FilePrescription, Field(discriminator="op")]),
    "drug-ingredient-resolver": TypeAdapter(Annotated[DetailRequest | LookupRequest, Field(discriminator="op")]),
    "pdf-iso32000-annotator": TypeAdapter(Annotated[PdfIndex | PdfSearch | PdfContext | PdfAnnotate, Field(discriminator="op")]),
}


def absolute_path(value):
    ensure(isinstance(value, str) and 0 < len(value) <= 4096 and Path(value).is_absolute(), "ABSOLUTE_PATH_REQUIRED")
    return str(Path(value).resolve())


async def _prescription(request, *, nim=None, operation=pdf_operation):
    from .agents.prescription import prescription_candidates
    owns_provider = nim is None
    if nim is None:
        from .providers import Nvidia
        nim = Nvidia()
    try:
        if request.op == "text":
            text, method = request.text, "provided-text"
        else:
            path = absolute_path(request.path)
            ensure(Path(path).stat().st_size <= 8 * 1024 * 1024, "PRESCRIPTION_SIZE_LIMIT", 413)
            data = Path(path).read_bytes()
            if not data.startswith(b"%PDF-"):
                ensure(request.cloudConsent and getattr(nim, "ocr_enabled", False), "OCR_CONSENT_OR_CONFIG_REQUIRED", 409)
                result = await nim.ocr(data)
                return {**result, "candidates": await prescription_candidates(result["text"], nim=nim, consent=request.cloudConsent), "requiresConfirmation": True}
            with TemporaryDirectory(prefix="concreteinsure-prescription-") as folder:
                index = str(Path(folder) / "index.json.gz")
                metadata = await operation({"op": "index", "pdf": path, "index": index})
                ensure(metadata["pages"] <= 8, "PRESCRIPTION_PAGE_LIMIT")
                if metadata["textPages"] == metadata["pages"]:
                    result = await operation({"op": "text", "pdf": path, "index": index})
                    text, method = result["text"], "pdf-text-layer"
                else:
                    ensure(request.cloudConsent and getattr(nim, "ocr_enabled", False), "OCR_CONSENT_OR_CONFIG_REQUIRED", 409)
                    result = await operation({"op": "render", "pdf": path})
                    parts = [await nim.ocr(base64.b64decode(image), "image/png") for image in result["images"]]
                    text, method = "\n".join(part["text"] for part in parts), "ocr"
        return {"text": text, "candidates": await prescription_candidates(text, nim=nim, consent=request.cloudConsent), "requiresConfirmation": True, "method": method}
    finally:
        if owns_provider:
            await nim.close()


async def execute(skill, value, *, nim=None, drugs=None, operation=pdf_operation):
    ensure(skill in SCHEMAS, "UNKNOWN_SKILL")
    request = SCHEMAS[skill].validate_python(value)
    if skill == "ocr-prescription":
        return await _prescription(request, nim=nim, operation=operation)
    if skill == "drug-ingredient-resolver":
        owns_provider = drugs is None
        if drugs is None:
            from .providers import Drugs
            drugs = Drugs()
        try:
            if request.op == 'detail':
                from .agents.drug_references import reference_from_detail, verify_drug_references
                detail = await drugs.detail(request.itemId)
                references = [reference_from_detail(detail)]
                verify_drug_references(references)
                return {'product': detail['product'], 'references': references}
            return await drugs.lookup(request.name)
        finally:
            if owns_provider:
                await drugs.close()
    payload = request.model_dump(exclude_none=True)
    payload["pdf"], payload["index"] = absolute_path(request.pdf), absolute_path(request.index)
    ensure(payload["pdf"] != payload["index"], "PATH_COLLISION")
    if request.op == "annotate":
        payload["output"] = absolute_path(request.output)
        ensure(payload["output"] not in {payload["pdf"], payload["index"]}, "PATH_COLLISION")
        # Preserve explicit null quads: the PDF worker validates every source span.
        payload["hits"] = [hit.model_dump() for hit in request.hits]
    return await operation(payload)


def main():
    try:
        ensure(len(sys.argv) == 2, "SKILL_ARGUMENT_REQUIRED")
        raw = sys.stdin.buffer.read(2_000_001)
        ensure(len(raw) <= 2_000_000, "SKILL_INPUT_LIMIT", 413)
        value = json.loads(raw)
        # Environment values are never returned. Existing shell values take precedence.
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        result = asyncio.run(execute(sys.argv[1], value))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError):
        code = "INVALID_REQUEST"
    except AppError as error:
        code = error.code if re.fullmatch(r"[A-Z_]{3,80}", error.code) else "SKILL_FAILED"
    except (OSError, ValueError, TypeError):
        code = "SKILL_FAILED"
    except KeyboardInterrupt:
        code = "CANCELLED"
    except Exception:
        code = "SKILL_FAILED"
    print(json.dumps({"error": code}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
