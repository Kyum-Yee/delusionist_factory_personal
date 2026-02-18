import os
from docx import Document

input_path = os.path.abspath('input/100000word.txt')
output_path = os.path.abspath('input/100000word.docx')

def convert():
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        return

    print(f"Creating Document...")
    doc = Document()
    
    print(f"Reading {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        # Read lazily to save memory during read (though list is fine for 4MB)
        count = 0
        for line in f:
            doc.add_paragraph(line.strip())
            count += 1
            if count % 10000 == 0:
                print(f"Processed {count} lines...")
    
    print(f"Saving to {output_path}... This may take a while.")
    doc.save(output_path)
    print(f"Successfully created {output_path}")

if __name__ == "__main__":
    convert()
