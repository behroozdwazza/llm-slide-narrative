import html
import io
import base64
import mimetypes
import posixpath
import re
import zipfile
from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def validate_upload(file_storage, allowed_extensions):
    filename = Path(file_storage.filename or "").name
    suffix = Path(filename).suffix.lower().lstrip(".")
    if not filename:
        raise ValueError("One upload is missing a filename.")
    if suffix not in allowed_extensions:
        expected = ", ".join(sorted(f".{ext}" for ext in allowed_extensions))
        raise ValueError(f"{filename} is not supported. Use one of: {expected}.")
    return {"filename": filename, "extension": suffix}


def build_context_preview(source_name: str, source_bytes: bytes, deck_name: str, deck_bytes: bytes) -> Dict:
    source_text = extract_text(source_name, source_bytes)
    slides = extract_slides(deck_name, deck_bytes)
    return {
        "source_preview": trim_text(source_text, 9000),
        "slides": slides,
        "slide_count": len(slides),
        "source_extraction_note": extraction_note(source_name, source_text),
        "deck_extraction_note": deck_note(deck_name, slides),
    }


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        return data.decode("utf-8", errors="replace")
    if suffix == ".docx":
        return extract_docx_text(data)
    if suffix == ".pdf":
        return extract_pdf_text(data)
    return ""


def extract_slides(filename: str, data: bytes) -> List[Dict]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pptx":
        return extract_pptx_slides(data)
    if suffix == ".pdf":
        pages = extract_pdf_pages(data)
        return [
            {
                "slide_number": i + 1,
                "title": first_sentence(page) or f"Page {i + 1}",
                "text": trim_text(page, 1800),
                "notes": "",
            }
            for i, page in enumerate(pages)
        ]
    return []


def extract_docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        parts = ["word/document.xml"]
        parts.extend(name for name in zf.namelist() if re.match(r"word/(header|footer)\d+\.xml", name))
        paragraphs = []
        for part in parts:
            if part not in zf.namelist():
                continue
            root = ET.fromstring(zf.read(part))
            for para in root.findall(".//w:p", NS):
                text = "".join(node.text or "" for node in para.findall(".//w:t", NS)).strip()
                if text:
                    paragraphs.append(text)
        return "\n".join(paragraphs)


def extract_pptx_slides(data: bytes) -> List[Dict]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        slide_names = sorted(
            (name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)),
            key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),
        )
        notes_by_number = extract_pptx_notes(zf)
        slides = []
        for slide_name in slide_names:
            number = int(re.search(r"slide(\d+)\.xml$", slide_name).group(1))
            paragraphs = extract_pptx_paragraphs(zf.read(slide_name))
            visible_text = "\n".join(paragraphs)
            images = extract_pptx_slide_images(zf, number)
            slides.append(
                {
                    "slide_number": number,
                    "title": paragraphs[0] if paragraphs else f"Slide {number}",
                    "text": trim_text(visible_text, 2200),
                    "notes": trim_text(notes_by_number.get(number, ""), 2200),
                    "images": images,
                }
            )
        return slides


def extract_pptx_slide_images(zf: zipfile.ZipFile, slide_number: int) -> List[Dict]:
    rels_name = f"ppt/slides/_rels/slide{slide_number}.xml.rels"
    if rels_name not in zf.namelist():
        return []

    root = ET.fromstring(zf.read(rels_name))
    images = []
    for rel in root:
        target = rel.attrib.get("Target", "")
        rel_type = rel.attrib.get("Type", "")
        if "image" not in rel_type and "../media/" not in target:
            continue

        image_path = posixpath.normpath(posixpath.join("ppt/slides", target))
        if image_path not in zf.namelist():
            continue

        image_bytes = zf.read(image_path)
        mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
        if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            continue

        images.append(
            {
                "filename": posixpath.basename(image_path),
                "mime_type": mime_type,
                "data_url": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}",
            }
        )
    return images


def extract_pptx_notes(zf: zipfile.ZipFile) -> Dict[int, str]:
    notes = {}
    for name in zf.namelist():
        match = re.match(r"ppt/notesSlides/notesSlide(\d+)\.xml$", name)
        if not match:
            continue
        number = int(match.group(1))
        paragraphs = extract_pptx_paragraphs(zf.read(name))
        notes[number] = "\n".join(p for p in paragraphs if p.lower() != "slide image")
    return notes


def extract_pptx_paragraphs(xml_bytes: bytes) -> List[str]:
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for para in root.findall(".//a:p", NS):
        runs = [node.text or "" for node in para.findall(".//a:t", NS)]
        text = " ".join(piece.strip() for piece in runs if piece and piece.strip()).strip()
        if text:
            paragraphs.append(text)
    return dedupe_preserve_order(paragraphs)


def extract_pdf_text(data: bytes) -> str:
    return "\n\n".join(extract_pdf_pages(data))


def extract_pdf_pages(data: bytes) -> List[str]:
    raw_pages = re.split(rb"/Type\s*/Page\b", data)
    pages = []
    for chunk in raw_pages[1:] or [data]:
        page_text = extract_pdf_text_from_chunk(chunk)
        if page_text:
            pages.append(page_text)
    return pages or [""]


def extract_pdf_text_from_chunk(chunk: bytes) -> str:
    text_chunks = []
    for literal in re.findall(rb"\((?:\\.|[^\\)])*\)", chunk):
        decoded = decode_pdf_literal(literal[1:-1])
        if decoded.strip():
            text_chunks.append(decoded.strip())
    for hex_text in re.findall(rb"<([0-9A-Fa-f\s]{8,})>", chunk):
        decoded = decode_pdf_hex(hex_text)
        if decoded.strip():
            text_chunks.append(decoded.strip())
    text = " ".join(text_chunks)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def decode_pdf_literal(value: bytes) -> str:
    value = re.sub(rb"\\([nrtbf])", lambda m: {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"", b"f": b""}[m.group(1)], value)
    value = re.sub(rb"\\([\\()])", rb"\1", value)
    return value.decode("utf-8", errors="ignore") or value.decode("latin-1", errors="ignore")


def decode_pdf_hex(value: bytes) -> str:
    cleaned = re.sub(rb"\s+", b"", value)
    if len(cleaned) % 2:
        cleaned += b"0"
    try:
        raw = bytes.fromhex(cleaned.decode("ascii"))
    except ValueError:
        return ""
    for encoding in ("utf-16-be", "utf-8", "latin-1"):
        decoded = raw.decode(encoding, errors="ignore").strip("\ufeff\x00")
        if decoded:
            return decoded
    return ""


def dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = re.sub(r"\s+", " ", item.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def first_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    return re.split(r"(?<=[.!?])\s+", cleaned)[0][:90]


def trim_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def extraction_note(filename: str, text: str) -> str:
    if Path(filename).suffix.lower() == ".pdf" and len(text.strip()) < 100:
        return "Limited local PDF text was found. With an OpenAI API key, the original PDF is also sent as a file input."
    return "Local text preview extracted."


def deck_note(filename: str, slides: List[Dict]) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".ppt":
        return "Local preview for legacy .ppt is limited. With an OpenAI API key, the original deck is sent as a file input."
    if not slides:
        return "No local slide text was extracted. The model can still inspect the uploaded deck when an OpenAI API key is configured."
    return "Local slide text extracted."
