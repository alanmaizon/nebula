from __future__ import annotations

from io import BytesIO

from app.retrieval import build_parse_report, chunk_pages, extract_text_pages


def _build_pdf_bytes(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
    page[NameObject("/Resources")] = resources

    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content_stream = DecodedStreamObject()
    content_stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode("utf-8"))
    content_ref = writer._add_object(content_stream)
    page[NameObject("/Contents")] = content_ref

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _build_docx_bytes(text: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _build_rtf_bytes(text: str) -> bytes:
    return (
        "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Arial;}}\\f0\\fs24 "
        + text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        + "}"
    ).encode("utf-8")


def test_pdf_docx_rtf_parsers_extract_text() -> None:
    scenarios = [
        ("pdf", "sample.pdf", "application/pdf", _build_pdf_bytes("Need statement evidence text")),
        (
            "docx",
            "sample.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _build_docx_bytes("Program design timeline and milestones."),
        ),
        ("rtf", "sample.rtf", "application/rtf", _build_rtf_bytes("Attachment summary and budget rationale.")),
    ]

    for parser_id, file_name, content_type, content in scenarios:
        extraction = extract_text_pages(content=content, content_type=content_type, file_name=file_name)
        assert extraction.parser_id == parser_id
        assert extraction.text_extractable is True
        assert extraction.error is None
        assert extraction.pages
        assert extraction.pages[0].text

        chunks = chunk_pages(
            pages=extraction.pages,
            chunk_size_chars=80,
            chunk_overlap_chars=20,
            embedding_dim=64,
        )
        report = build_parse_report(
            content=content,
            content_type=content_type,
            file_name=file_name,
            extraction=extraction,
            chunks=chunks,
        )
        assert report["parser_id"] == parser_id
        assert report["reason"] in {"ok", "low_extracted_text", "low_text_density"}
        assert report["chunks_indexed"] >= 1


def test_malformed_pdf_reports_parser_error() -> None:
    malformed_pdf = b"%PDF-1.7\nthis-is-not-a-valid-pdf-structure"
    extraction = extract_text_pages(
        content=malformed_pdf,
        content_type="application/pdf",
        file_name="broken.pdf",
    )

    assert extraction.parser_id == "pdf"
    assert extraction.text_extractable is True
    assert extraction.error is not None
    assert extraction.pages == []

    report = build_parse_report(
        content=malformed_pdf,
        content_type="application/pdf",
        file_name="broken.pdf",
        extraction=extraction,
        chunks=[],
    )
    assert report["quality"] == "none"
    assert report["reason"] == "parser_error"
    assert report["parser_error"]


def test_unsupported_binary_content_is_graceful() -> None:
    payload = b"\x00\x10\x20\x30\x40binary"
    extraction = extract_text_pages(
        content=payload,
        content_type="application/octet-stream",
        file_name="blob.bin",
    )

    assert extraction.parser_id == "none"
    assert extraction.text_extractable is False
    assert extraction.pages == []

    report = build_parse_report(
        content=payload,
        content_type="application/octet-stream",
        file_name="blob.bin",
        extraction=extraction,
        chunks=[],
    )
    assert report["quality"] == "none"
    assert report["reason"] == "unsupported_file_type"
