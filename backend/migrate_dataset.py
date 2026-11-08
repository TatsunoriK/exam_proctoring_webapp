"""Import local JSON samples into MongoDB. Safe to rerun without duplicates."""
import json
from pathlib import Path

from pymongo.errors import PyMongoError

from app.database import samples_collection

directory = Path(__file__).resolve().parents[1] / "dataset" / "samples"


def main():
    if not directory.is_dir():
        print(f"No sample directory found: {directory}")
        return
    collection = samples_collection()
    inserted = skipped = failed = 0
    for path in sorted(directory.glob("*.json")):
        try:
            sample = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(sample, dict) or not isinstance(sample.get("id"), str) or not sample["id"]:
                raise ValueError("Missing sample id")
            sample["_id"] = sample["id"]
            result = collection.update_one({"_id": sample["id"]}, {"$setOnInsert": sample}, upsert=True)
            if result.upserted_id is None:
                skipped += 1
            else:
                inserted += 1
        except (OSError, ValueError, PyMongoError) as exc:
            failed += 1
            print(f"Failed to import {path.name}: {type(exc).__name__}")
    print(f"Imported: {inserted}; already present: {skipped}; failed: {failed}. Original files retained.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
