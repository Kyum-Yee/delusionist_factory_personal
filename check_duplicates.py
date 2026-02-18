
import sys
import os

def normalize_text(text):
    return text.strip()

def load_existing_korean_words(output_path):
    korean_words = {} # value -> set of keys (english words)
    if not os.path.exists(output_path):
        return korean_words
        
    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    eng = parts[0].strip()
                    kor = parts[1].strip()
                    
                    if kor not in korean_words:
                        korean_words[kor] = []
                    korean_words[kor].append(eng)
    except Exception as e:
        print(f"Error reading output: {e}")
        
    return korean_words

def check_candidates_from_file(candidates_path, output_path, research_log_path):
    """
    candidates_path: path to file with "eng\\tkor" lines
    """
    existing = load_existing_korean_words(output_path)
    
    duplicates = []
    checked_pairs = []
    
    with open(candidates_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or '\t' not in line:
                continue
            
            eng, kor = line.split('\t', 1)
            eng = eng.strip()
            kor = kor.strip()
            
            # Basic validation
            if not eng or not kor:
                continue

            checked_pairs.append((eng, kor))
            
            if kor in existing:
                # Check if this exact pair already exists (idempotency)
                if eng in existing[kor]:
                    continue # Already recorded
                    
                # Conflict found: Same Korean word used for different English word
                duplicates.append((eng, kor, existing[kor]))
                
            # Local duplicate check (within the current batch)
            # We add to 'existing' temporarily to catch duplicates within the batch
            if kor not in existing:
                existing[kor] = []
            existing[kor].append(eng)

    if duplicates:
        # Log to research file
        with open(research_log_path, 'a', encoding='utf-8') as f:
            for eng, kor, conflict_engs in duplicates:
                f.write(f"{kor}\n")
                f.write(f"- {eng}\n")
                for c in conflict_engs:
                    if c != eng: # Avoid self-reference if logic slips
                        f.write(f"- {c}\n")
                f.write("\n")
        
        return "DUPLICATE_FOUND"
    
    return "OK"

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python check_duplicates.py <candidates_file_path> <output_file_path> <research_log_path>")
        sys.exit(1)
        
    result = check_candidates_from_file(sys.argv[1], sys.argv[2], sys.argv[3])
    print(result)
