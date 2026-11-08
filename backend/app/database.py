import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@lru_cache(maxsize=1)
def samples_collection():
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI is not configured. See README for setup.")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[os.getenv("MONGODB_DATABASE", "exam_proctoring")]["samples"]
