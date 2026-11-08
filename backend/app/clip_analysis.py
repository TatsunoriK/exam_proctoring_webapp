"""Authenticated clip analysis adapter for ExamFlow's proctoring service contract."""
from __future__ import annotations

import base64
import os
import secrets
import io
import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from gridfs import GridFSBucket
from pymongo.errors import PyMongoError

from .database import database

router = APIRouter()
MAX_BYTES = 20 * 1024 * 1024
MAX_SECONDS = 30
MAX_SOURCE_FRAMES = 1800


def analyze_video(data: bytes, suffix: str) -> dict:
    import av
    import cv2
    from .main import FrameRequest, PredictRequest, extract_frame, predict

    flags = []
    analyzed = 0
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            stream = container.streams.video[0]
            fps = float(stream.average_rate or 5)
            if not math.isfinite(fps) or fps <= 0 or fps > 240:
                fps = 5.0
            start_time = None
            last_time = -1.0
            next_sample = 0.0
            for index, frame in enumerate(container.decode(stream)):
                if index >= MAX_SOURCE_FRAMES or frame.width * frame.height > 12_000_000:
                    raise HTTPException(status_code=413, detail="Video exceeds frame limits")
                timestamp = float(frame.time) if frame.time is not None else index / fps
                if not math.isfinite(timestamp):
                    raise HTTPException(status_code=422, detail="Invalid video timestamp")
                if start_time is None:
                    start_time = timestamp
                timestamp -= start_time
                if timestamp < last_time or timestamp > MAX_SECONDS:
                    raise HTTPException(status_code=422, detail="Video duration or timestamp is invalid")
                last_time = timestamp
                if timestamp + 1e-6 < next_sample:
                    continue
                next_sample = timestamp + 1.0
                encoded, jpeg = cv2.imencode(".jpg", frame.to_ndarray(format="bgr24"))
                if not encoded:
                    raise HTTPException(status_code=422, detail="Video frame cannot be decoded")
                image = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
                extracted = extract_frame(FrameRequest(image=image))
                result = predict(PredictRequest(features=extracted["features"]))
                analyzed += 1
                label = result["prediction"]
                if label in ("suspicious", "cheating"):
                    flags.append({"time_s": round(timestamp, 2), "label": label,
                                  "confidence": result["probabilities"][label]})
    except (av.FFmpegError, IndexError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Video cannot be decoded") from exc
    if not analyzed:
        raise HTTPException(status_code=422, detail="Video contains no readable frames")
    return {"status": "analyzed", "review_flags": flags[:20],
            "frames_analyzed": analyzed, "model_version": "exam-proctoring-67-features"}


async def read_clip(request: Request) -> tuple[bytes, str, str]:
    token = os.getenv("PROCTORING_API_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Analysis service is not configured")
    auth = request.headers.get("authorization", "")
    if not secrets.compare_digest(auth, "Bearer " + token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in ("video/webm", "video/mp4"):
        raise HTTPException(status_code=415, detail="Only WebM and MP4 are supported")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Video exceeds the upload limit")
    if not data:
        raise HTTPException(status_code=400, detail="Video is empty")
    return bytes(data), content_type, ".webm" if content_type == "video/webm" else ".mp4"


@router.post("/analyze")
async def analyze(request: Request) -> dict:
    data, _, suffix = await read_clip(request)
    return await run_in_threadpool(analyze_video, data, suffix)


def store_flagged_clip(data: bytes, content_type: str, attempt_id: str, result: dict) -> str:
    bucket = GridFSBucket(database(), bucket_name="review_clips")
    file_id = bucket.upload_from_stream(
        "review-clip", data,
        metadata={"attempt_id": attempt_id, "content_type": content_type,
                  "created_at": datetime.now(timezone.utc), "analysis": result},
    )
    return str(file_id)


@router.post("/analyze-and-store")
async def analyze_and_store(request: Request) -> dict:
    data, content_type, suffix = await read_clip(request)
    attempt_id = request.headers.get("x-attempt-id", "")
    if not attempt_id or len(attempt_id) > 100 or not all(c.isalnum() or c in "-_" for c in attempt_id):
        raise HTTPException(status_code=400, detail="Invalid attempt ID")
    result = await run_in_threadpool(analyze_video, data, suffix)
    if not result["review_flags"]:
        return {**result, "clip_id": None}
    try:
        clip_id = await run_in_threadpool(store_flagged_clip, data, content_type, attempt_id, result)
    except (PyMongoError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Could not store the flagged clip") from exc
    return {**result, "clip_id": clip_id}
