import zipfile
import os
import io

input_path = os.path.abspath('input/100000word.txt')
output_path = os.path.abspath('input/100000word.docx')

# Minimal content for valid docx
content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

document_xml_start = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>"""

document_xml_end = """</w:body>
</w:document>"""

def clean_text(text):
    # Escape XML characters
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')

def convert():
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        return

    print("Starting fast conversion...")
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types_xml)
        zf.writestr('_rels/.rels', rels_xml)
        
        # Build document.xml content
        # We'll buffer it in chunks if possible, but simple string join is easiest for validity
        
        xml_chunks = [document_xml_start]
        
        with open(input_path, 'r', encoding='utf-8') as f:
            count = 0
            for line in f:
                text = clean_text(line.strip())
                # Just basic paragraph
                xml_chunks.append(f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>')
                count += 1
                if count % 50000 == 0:
                    print(f"Processed {count} lines...")
        
        xml_chunks.append(document_xml_end)
        
        print("Writing document.xml to zip...")
        zf.writestr('word/document.xml', "".join(xml_chunks))
        
    print(f"Finished writing {output_path}")

if __name__ == "__main__":
    convert()
