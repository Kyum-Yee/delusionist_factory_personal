import json
import os

result_path = "staging/step1_result.json"
output_path = "output/section_a_chains.txt"

if os.path.exists(result_path):
    with open(result_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        sentences = data.get("response", "")
        
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(sentences.strip() + "\n")
    print(f"Successfully appended sentences to {output_path}")
else:
    print(f"Error: {result_path} not found")
