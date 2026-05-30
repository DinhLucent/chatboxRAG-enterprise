import json
import sys
from pathlib import Path

# Ensure UTF-8 output encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parent.parent
records_path = root / "manifest" / "records.json"

if not records_path.exists():
    print(f"Error: records.json not found at {records_path}")
    sys.exit(1)

data = json.loads(records_path.read_text(encoding="utf-8"))
active_records = [r for r in data if r["status"] == "active"]

print(f"Auditing {len(active_records)} active records...")
missing_sources = 0
missing_normalized = 0

for r in active_records:
    doc_id = r["doc_id"]
    version = r["version"]
    
    # Check source path
    src_path_str = r.get("source_path")
    if src_path_str:
        src_path = Path(src_path_str)
        # Handle relative/absolute path resolving
        if not src_path.is_absolute():
            src_path = root / src_path
        if not src_path.exists():
            print(f"[-] Missing source file for {doc_id} {version}: {src_path_str}")
            missing_sources += 1
    else:
        print(f"[-] No source_path metadata for {doc_id} {version}")
        missing_sources += 1
        
    # Check normalized path
    norm_path_str = r.get("normalized_path")
    if norm_path_str:
        norm_path = Path(norm_path_str)
        if not norm_path.is_absolute():
            norm_path = root / norm_path
        if not norm_path.exists():
            print(f"[-] Missing normalized Markdown for {doc_id} {version}: {norm_path_str}")
            missing_normalized += 1
    else:
        print(f"[-] No normalized_path metadata for {doc_id} {version}")
        missing_normalized += 1

print("\nAudit Summary:")
print(f"Total active records: {len(active_records)}")
print(f"Missing source files: {missing_sources}")
print(f"Missing normalized files: {missing_normalized}")

if missing_sources > 0 or missing_normalized > 0:
    print("WARNING: Some files are missing from disk!")
else:
    print("SUCCESS: All active source and normalized files exist on disk.")
