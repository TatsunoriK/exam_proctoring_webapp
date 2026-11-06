from __future__ import annotations

import math
import base64
import binascii
import threading
import json
import uuid
from datetime import datetime, timezone
from typing import Literal
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "model" / "exam_proctoring_model.joblib"
STATIC_DIR = ROOT / "backend" / "static"

if not MODEL_PATH.exists():
    raise RuntimeError(f"Model file not found: {MODEL_PATH}")

bundle = joblib.load(MODEL_PATH)
model = bundle["model"]
FEATURE_COLS: list[str] = bundle["feature_cols"]
LABELS: list[str] = bundle["labels"]

app = FastAPI(title="Exam Proctoring Model API", version="1.0.0",
              description="Predicts a class from the model's 67 numeric frame features.")


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, Any]


class FrameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str


class DatasetRequest(FrameRequest):
    label: Literal["normal", "suspicious", "cheating"]
    session_id: str
    details: str = ""
    captured_at: str
    consent: Literal[True]


_extract_lock = threading.Lock()
_face_extractor = None


@app.post("/api/extract-frame")
def extract_frame(request: FrameRequest) -> dict[str, Any]:
    """Extract notebook features from one JPEG frame; temporal features remain unknown."""
    global _face_extractor
    prefix = "data:image/jpeg;base64,"
    if not request.image.startswith(prefix) or len(request.image) > 4_000_000:
        raise HTTPException(status_code=422, detail="Expected a JPEG data URL under 3 MB.")
    try:
        image_bytes = base64.b64decode(request.image[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Invalid base64 image.")
    try:
        import cv2
        from . import extractor
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Install webcam dependencies: {exc}") from exc
    frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[0] * frame.shape[1] > 12_000_000:
        raise HTTPException(status_code=422, detail="Invalid or oversized image.")
    paths = [Path(extractor.MODEL_DIR) / name for name in ("face_landmarker.task", "hand_landmarker.task", "yolov8s.pt")]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise HTTPException(status_code=503, detail=f"Missing model files: {', '.join(missing)}. See README webcam setup.")
    with _extract_lock:
        if _face_extractor is None:
            _face_extractor = extractor.FaceExtractor()
        if extractor.YOLO_MODEL is None:
            extractor.YOLO_MODEL = extractor.YOLO(str(paths[2]))
        frame = extractor._resize(frame, 640)
        record = _face_extractor(frame)
        face_box = [record[f"face_{k}"] for k in ("x1", "y1", "x2", "y2")] if record["n_faces"] else None
        record.update(extractor.detect_objects(frame, face_box))

    record["flag_multi_person"] = int(record["n_faces"] >= 2 or record["n_person"] >= 2)
    for name in extractor.OBJ_CANON:
        if name != "person":
            record[f"flag_{name}"] = int(record[f"{name}_conf"] > 0)
    record["flag_no_face"] = int(record["n_faces"] == 0)
    # Global medians from the provided dataset's frames with one detected face.
    if record["n_faces"]:
        yaw_dev = abs(record["yaw"] - (-0.01432515541))
        record["flag_look_away_strong"] = int(yaw_dev > 0.20)
        record["flag_look_away"] = int(0.10 < yaw_dev <= 0.20)
        record["flag_head_pitch"] = int(abs(record["pitch"] - 0.54439491035) > 0.07)
        if math.isfinite(record["gaze_h"]):
            record["flag_gaze_away"] = int(abs(record["gaze_h"] - 0.50943788885) > 0.12)
    record["flag_talking"] = None
    record["flag_hand_mouth"] = int(record["hand_near_mouth"])
    record["flag_hand_face"] = int(record["hand_near_face"] and not record["hand_near_mouth"])
    features = {}
    for name in FEATURE_COLS:
        value = record.get(name)
        if isinstance(value, (int, float, bool, np.number)):
            value = float(value)
            value = value if math.isfinite(value) else None
        features[name] = value
    return {"features": features, "objects": record["objects_json"], "note": "Single-frame estimate: dataset-wide medians used for pose flags; talking requires a temporal window."}


def validate_features(features: dict[str, Any]) -> tuple[pd.DataFrame, int]:
    expected = set(FEATURE_COLS)
    given = set(features)
    missing = sorted(expected - given)
    extra = sorted(given - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(f"Missing {len(missing)} feature(s): {', '.join(missing[:8])}")
        if extra:
            details.append(f"Unknown {len(extra)} feature(s): {', '.join(extra[:8])}")
        raise HTTPException(status_code=422, detail="; ".join(details))

    values: dict[str, float] = {}
    supplied = 0
    for name in FEATURE_COLS:
        value = features[name]
        if value is None:
            values[name] = np.nan
            continue
        if isinstance(value, bool):
            values[name] = float(value)
            supplied += 1
            continue
        if not isinstance(value, (int, float)):
            raise HTTPException(status_code=422, detail=f"Feature '{name}' must be a number, boolean, or null.")
        if not math.isfinite(float(value)):
            raise HTTPException(status_code=422, detail=f"Feature '{name}' must be finite.")
        values[name] = float(value)
        supplied += 1

    if supplied < 10:
        raise HTTPException(status_code=422, detail="At least 10 populated feature values are required. Provide extracted frame features, not an empty template.")
    return pd.DataFrame([values], columns=FEATURE_COLS), len(FEATURE_COLS) - supplied


@app.post("/api/dataset")
def save_dataset_sample(request: DatasetRequest) -> dict[str, str]:
    session_id = request.session_id.strip()
    if not session_id or len(session_id) > 100 or len(request.details) > 500 or len(request.captured_at) > 50:
        raise HTTPException(status_code=422, detail="Provide a session ID (1–100 characters) and details under 500 characters.")
    extracted = extract_frame(FrameRequest(image=request.image))
    validate_features(extracted["features"])
    sample_id = uuid.uuid4().hex
    directory = ROOT / "dataset" / "samples"
    directory.mkdir(parents=True, exist_ok=True)
    sample = {"id": sample_id, "session_id": session_id, "label": request.label,
              "details": request.details.strip(), "captured_at": request.captured_at,
              "saved_at": datetime.now(timezone.utc).isoformat(), "image": request.image,
              "features": extracted["features"], "extraction_note": extracted["note"]}
    with (directory / f"{sample_id}.json").open("x", encoding="utf-8") as output:
        json.dump(sample, output, ensure_ascii=False, allow_nan=False)
    return {"id": sample_id, "message": "Saved locally for later review and training."}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model_loaded": True, "feature_count": len(FEATURE_COLS)}


@app.get("/api/schema")
def schema() -> dict[str, Any]:
    return {"features": FEATURE_COLS, "labels": LABELS, "required_feature_count": len(FEATURE_COLS),
            "null_policy": "Null values are imputed with training medians; supply extracted values for reliable predictions."}


@app.post("/api/predict")
def predict(request: PredictRequest) -> dict[str, Any]:
    X, imputed_count = validate_features(request.features)
    prediction = str(model.predict(X)[0])
    probabilities_raw = model.predict_proba(X)[0]
    classes = model[-1].classes_
    probabilities = {str(label): float(prob) for label, prob in zip(classes, probabilities_raw)}
    return {"prediction": prediction, "probabilities": probabilities,
            "provided_feature_count": len(FEATURE_COLS) - imputed_count,
            "imputed_feature_count": imputed_count,
            "note": "This model predicts from extracted frame features. It does not analyze raw images or prove misconduct."}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def frontend() -> Any:
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<h2>Frontend not built yet</h2><p>Run <code>npm install</code> and <code>npm run build</code> in the frontend folder.</p>", status_code=503)


@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str) -> Any:
    candidate = STATIC_DIR / path
    if candidate.is_file():
        return FileResponse(candidate)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not found")
