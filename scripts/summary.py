"""Print a summary of the last run."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config, resolve

cfg = load_config()
out = resolve(cfg, "output_dir")
for name in ("file_index", "scada_hits", "object_hits", "block_summary"):
    p = out / "csv" / f"{name}.csv"
    if p.exists():
        with open(p, encoding="utf-8-sig") as f:
            print(f"{name}.csv: {sum(1 for _ in csv.reader(f)) - 1} rows")
err = out / "logs" / "errors.log"
if err.exists():
    with open(err, encoding="utf-8") as f:
        print("errors.log lines:", sum(1 for _ in f))
else:
    print("errors.log lines: 0")
