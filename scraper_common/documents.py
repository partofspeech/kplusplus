"""Write Unicode DOCX documents from decision text."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ET.register_namespace('w', W)


def write_docx(path: Path, text: str) -> None:
    document = ET.Element(f'{{{W}}}document')
    body = ET.SubElement(document, f'{{{W}}}body')
    # XML 1.0 cannot represent some control characters found in copied text.
    text = ''.join(c for c in text if c in '\t\n\r' or '\u0020' <= c <= '\ud7ff' or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff')
    for line in text.splitlines():
        paragraph = ET.SubElement(body, f'{{{W}}}p')
        run = ET.SubElement(paragraph, f'{{{W}}}r')
        node = ET.SubElement(run, f'{{{W}}}t', {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'})
        node.text = line
    content_types = b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    relationships = b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
    # Use a temporary sibling so an interrupted write never leaves a broken DOCX.
    temporary = path.with_suffix('.docx.tmp')
    try:
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', content_types)
            archive.writestr('_rels/.rels', relationships)
            archive.writestr('word/document.xml', ET.tostring(document, encoding='utf-8', xml_declaration=True))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
