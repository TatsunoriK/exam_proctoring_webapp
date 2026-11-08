"""Local ExamFlow API backed by MongoDB. Not configured for public deployment."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from gridfs import GridFSBucket
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .database import database
from .clip_analysis import MAX_BYTES, analyze_video, store_flagged_clip
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/api")
logger = logging.getLogger("examflow")
clip_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="examflow-clips")
clip_capacity = BoundedSemaphore(12)
clip_result_lock = Lock()


def process_camera_clip(db, attempt_id: str, event_id: str, data: bytes, content_type: str):
    try:
        result = analyze_video(data, ".webm" if content_type == "video/webm" else ".mp4")
        clip_id = store_flagged_clip(data, content_type, attempt_id, result) if result["review_flags"] else None
        with clip_result_lock:
            attempt = db.exam_attempts.find_one({"_id": attempt_id})
            if not attempt:
                raise RuntimeError("Attempt no longer exists")
            event = {"id": event_id, "status": "analyzed", "reviewFlags": result["review_flags"],
                     "segment": len(attempt.get("cameraRecordings", [])) if clip_id else -1}
            update = {"$set": {"proctoringEvents.$": event}}
            if clip_id:
                update["$push"] = {"cameraRecordings": clip_id}
            db.exam_attempts.update_one({"_id": attempt_id, "proctoringEvents.id": event_id}, update)
    except Exception:
        logger.exception("Camera clip processing failed for attempt %s", attempt_id)
        try:
            db.exam_attempts.update_one({"_id": attempt_id, "proctoringEvents.id": event_id},
                                        {"$set": {"proctoringEvents.$.status": "analysis_failed"}})
        except Exception:
            logger.exception("Could not record clip failure for attempt %s", attempt_id)
    finally:
        clip_capacity.release()


def now_ms():
    return int(time.time() * 1000)


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str, salt: str):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 210000).hex()


def fail(message: str, status: int = 400):
    raise HTTPException(status_code=status, detail=message)


def current(request: Request, role: str | None = None):
    token = request.cookies.get("examflow_session", "")
    if not token:
        fail("กรุณาเข้าสู่ระบบก่อนใช้งาน", 401)
    db = database()
    session = db.exam_sessions.find_one({"_id": digest(token), "expires": {"$gt": now_ms()}})
    user = db.exam_users.find_one({"_id": session["user_id"]}) if session else None
    if not user:
        fail("กรุณาเข้าสู่ระบบก่อนใช้งาน", 401)
    if role and user["role"] != role:
        fail("บัญชีนี้ไม่มีสิทธิ์", 403)
    return user


@router.post("/auth/{action}")
async def auth(action: str, request: Request):
    if action == "logout":
        return logout(request)
    db = database()
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    password = body.get("password", "")
    min_password_length = 8 if action == "register" else 1
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254 or not isinstance(password, str) or not min_password_length <= len(password) <= 128:
        fail("กรุณากรอกอีเมลและรหัสผ่านให้ถูกต้อง")
    if action == "register":
        name = str(body.get("name", "")).strip()
        role = body.get("role")
        if not 2 <= len(name) <= 120 or role not in ("student", "teacher"):
            fail("กรุณากรอกชื่อและบทบาท")
        salt = secrets.token_hex(16)
        user = {"_id": email, "name": name, "role": role, "salt": salt,
                "password_hash": password_hash(password, salt)}
        try:
            db.exam_users.insert_one(user)
        except DuplicateKeyError:
            fail("อีเมลนี้มีบัญชีแล้ว", 409)
    elif action == "login":
        user = db.exam_users.find_one({"_id": email})
        if not user or not hmac.compare_digest(password_hash(password, user["salt"]), user["password_hash"]):
            fail("อีเมลหรือรหัสผ่านไม่ถูกต้อง", 401)
    else:
        fail("ไม่พบรายการ", 404)
    token = secrets.token_urlsafe(32)
    db.exam_sessions.insert_one({"_id": digest(token), "user_id": email, "expires": now_ms() + 86400000})
    response = JSONResponse({"user": {"name": user["name"], "role": user["role"]}})
    response.set_cookie("examflow_session", token, httponly=True, samesite="lax", max_age=86400, secure=request.url.scheme == "https")
    return response


@router.get("/auth/logout")
@router.post("/auth/logout")
def logout(request: Request):
    token = request.cookies.get("examflow_session", "")
    if token:
        database().exam_sessions.delete_one({"_id": digest(token)})
    response = RedirectResponse("/login", status_code=303) if request.method == "GET" else JSONResponse({"ok": True})
    response.delete_cookie("examflow_session")
    return response


@router.get("/me")
def me(request: Request):
    user = current(request)
    return {"name": user["name"], "role": user["role"]}


@router.get("/exams")
def exams(request: Request):
    user = current(request, "teacher")
    return [{"id": e["_id"], **e["body"], "code": e["code"], "created": e["created"]}
            for e in database().exam_exams.find({"owner": user["_id"]}).sort("created", -1)]


@router.post("/exams")
async def create_exam(request: Request):
    user = current(request, "teacher")
    body = await request.json()
    questions = body.get("questions")
    device_mode = body.get("deviceMode", "pc")
    if device_mode not in ("pc", "mobile"):
        fail("กรุณาเลือกอุปกรณ์สอบ")
    if not isinstance(body.get("title"), str) or not body["title"].strip() or len(body["title"]) > 200 or type(body.get("minutes")) is not int or not 1 <= body["minutes"] <= 180 or not isinstance(questions, list) or not 1 <= len(questions) <= 100:
        fail("ตรวจสอบชื่อข้อสอบ เวลา และคำถาม")
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("text"), str) or not q["text"].strip() or not isinstance(q.get("options"), list) or len(q["options"]) != 4 or any(not isinstance(o, str) or not o.strip() for o in q["options"]) or type(q.get("correct")) is not int or not 0 <= q["correct"] < 4:
            fail("ตรวจสอบคำถามและตัวเลือก")
    exam_id = uuid.uuid4().hex
    code = secrets.token_hex(5).upper()
    database().exam_exams.insert_one({"_id": exam_id, "owner": user["_id"], "code": code,
                                     "body": {"title": body["title"], "subject": str(body.get("subject", "ทั่วไป"))[:200], "minutes": body["minutes"], "deviceMode": device_mode, "questions": questions}, "created": now_ms()})
    return {"id": exam_id, "code": code}


@router.post("/join")
async def join(request: Request):
    current(request, "student")
    body = await request.json()
    exam = database().exam_exams.find_one({"code": str(body.get("code", "")).strip().upper()})
    if not exam:
        fail("ไม่พบรหัสข้อสอบ", 404)
    return {"id": exam["_id"], "title": exam["body"]["title"], "minutes": exam["body"]["minutes"], "count": len(exam["body"]["questions"]), "deviceMode": exam["body"].get("deviceMode", "pc")}


@router.post("/start")
async def start(request: Request):
    user = current(request, "student")
    body = await request.json()
    mode = body.get("deviceMode", "pc")
    if mode not in ("pc", "mobile") or body.get("cameraConsent") is not True or not str(body.get("name", "")).strip():
        fail("กรอกชื่อและยืนยันความยินยอม")
    db = database()
    exam = db.exam_exams.find_one({"_id": body.get("exam")})
    if not exam:
        fail("ไม่พบข้อสอบ", 404)
    if mode != exam["body"].get("deviceMode", "pc"):
        fail("อุปกรณ์ไม่ตรงกับที่อาจารย์กำหนด", 403)
    attempt_id = digest(exam["_id"] + ":" + user["_id"])
    attempt = db.exam_attempts.find_one_and_update({"_id": attempt_id}, {"$setOnInsert": {"exam": exam["_id"], "student": user["_id"], "name": str(body["name"])[:120], "deviceMode": mode, "started": now_ms(), "answers": {}, "events": [], "recordings": [], "cameraRecordings": [], "proctoringEvents": [], "submitted": None}}, upsert=True, return_document=ReturnDocument.AFTER)
    if attempt["submitted"]:
        fail("คุณส่งข้อสอบนี้แล้ว", 409)
    if attempt.get("deviceMode", "pc") != mode:
        fail("การสอบนี้เริ่มด้วยอุปกรณ์อีกโหมด กรุณาเลือกโหมดเดิม", 409)
    return {"id": attempt_id, "deviceMode": attempt.get("deviceMode", "pc"), "deadline": attempt["started"] + exam["body"]["minutes"] * 60000, "answers": attempt["answers"], "questions": [{k: v for k, v in q.items() if k != "correct"} for q in exam["body"]["questions"]]}


def student_attempt(request: Request, attempt_id: str, allow_recent_submission: bool = False):
    user = current(request, "student")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id, "student": user["_id"]})
    if not attempt or (attempt.get("submitted") is not None and
                       (not allow_recent_submission or now_ms() - attempt["submitted"] > 120000)):
        fail("ไม่พบการสอบหรือไม่มีสิทธิ์", 403)
    return db, attempt, db.exam_exams.find_one({"_id": attempt["exam"]})


@router.post("/attempt/{attempt_id}/{action}")
async def attempt_action(attempt_id: str, action: str, request: Request):
    db, attempt, exam = student_attempt(request, attempt_id, allow_recent_submission=action in ("camera", "camera-failure"))
    if action == "camera-failure":
        db.exam_attempts.update_one({"_id": attempt_id}, {"$push": {"proctoringEvents": {"status": "analysis_failed", "reviewFlags": [], "segment": -1}}})
        return {"ok": True}
    if action == "camera" and attempt.get("deviceMode", "pc") != "pc":
        fail("โหมดมือถือไม่ใช้กล้อง", 403)
    if action in ("camera", "record"):
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type not in ("video/webm", "video/mp4"):
            fail("ชนิดวิดีโอไม่รองรับ", 415)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                fail("คลิปมีขนาดใหญ่เกินไป", 413)
        if not data:
            fail("คลิปว่าง")
        if action == "record":
            return {"ok": True}
        if not clip_capacity.acquire(blocking=False):
            fail("คิววิเคราะห์เต็ม กรุณาลองส่งคลิปใหม่", 503)
        event_id = uuid.uuid4().hex
        try:
            db.exam_attempts.update_one({"_id": attempt_id}, {"$push": {"proctoringEvents": {"id": event_id, "status": "processing", "reviewFlags": [], "segment": -1}}})
            clip_executor.submit(process_camera_clip, db, attempt_id, event_id, bytes(data), content_type)
        except Exception:
            clip_capacity.release()
            db.exam_attempts.update_one({"_id": attempt_id, "proctoringEvents.id": event_id}, {"$set": {"proctoringEvents.$.status": "analysis_failed"}})
            raise
        return {"ok": True, "status": "processing"}
    body = await request.json()
    if action == "event":
        db.exam_attempts.update_one({"_id": attempt_id}, {"$push": {"events": {"type": str(body.get("type", ""))[:120], "time": now_ms()}}})
        return {"ok": True}
    if action == "answers":
        if now_ms() > attempt["started"] + exam["body"]["minutes"] * 60000:
            fail("หมดเวลาสอบแล้ว", 409)
        answers = body.get("answers", {})
        if not isinstance(answers, dict) or any(not str(k).isdigit() or int(k) >= len(exam["body"]["questions"]) or type(v) is not int or not 0 <= v <= 3 for k, v in answers.items()):
            fail("คำตอบไม่ถูกต้อง")
        db.exam_attempts.update_one({"_id": attempt_id}, {"$set": {"answers": answers}})
        return {"ok": True}
    if action == "submit":
        questions = exam["body"]["questions"]
        score = sum(attempt["answers"].get(str(i)) == q["correct"] for i, q in enumerate(questions))
        update = {"$set": {"submitted": now_ms(), "score": score}}
        if body.get("analysisIncomplete") is True:
            update["$push"] = {"proctoringEvents": {"status": "analysis_failed", "reviewFlags": [], "segment": -1}}
        db.exam_attempts.update_one({"_id": attempt_id, "submitted": None}, update)
        return {"score": score, "total": len(questions)}
    fail("ไม่พบรายการ", 404)


@router.get("/results/{exam_id}")
def results(exam_id: str, request: Request):
    user = current(request, "teacher")
    db = database()
    if not db.exam_exams.find_one({"_id": exam_id, "owner": user["_id"]}):
        fail("ไม่มีสิทธิ์", 403)
    return [{"id": a["_id"], "name": a["name"], "deviceMode": a.get("deviceMode", "pc"), "started": a["started"], "submitted": a["submitted"], "score": a.get("score"), "events": a["events"], "recordings": [], "cameraRecordings": a["cameraRecordings"], "proctoringEvents": a["proctoringEvents"], "reviews": a.get("reviews", {})} for a in db.exam_attempts.find({"exam": exam_id}).sort("started", -1)]


@router.post("/review/{attempt_id}/{clip_id}")
async def review(attempt_id: str, clip_id: str, request: Request):
    user = current(request, "teacher")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id})
    if not attempt or not db.exam_exams.find_one({"_id": attempt["exam"], "owner": user["_id"]}):
        fail("ไม่มีสิทธิ์", 403)
    if clip_id not in attempt["cameraRecordings"] or not ObjectId.is_valid(clip_id):
        fail("ไม่พบคลิป", 404)
    body = await request.json()
    status = body.get("status")
    if status not in ("pending", "reviewed", "needs_followup"):
        fail("สถานะไม่ถูกต้อง")
    db.exam_attempts.update_one({"_id": attempt_id}, {"$set": {"reviews." + clip_id: {"status": status, "updated": now_ms()}}})
    return {"ok": True, "status": status}


@router.get("/camera/{attempt_id}/{index}")
def camera(attempt_id: str, index: int, request: Request):
    user = current(request, "teacher")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id})
    if not attempt or not db.exam_exams.find_one({"_id": attempt["exam"], "owner": user["_id"]}):
        fail("ไม่มีสิทธิ์", 403)
    if index < 0 or index >= len(attempt["cameraRecordings"]):
        fail("ไม่พบคลิป", 404)
    obj = GridFSBucket(db, bucket_name="review_clips").open_download_stream(ObjectId(attempt["cameraRecordings"][index]))
    return Response(obj.read(), media_type=obj.metadata.get("content_type", "video/webm"), headers={"Cache-Control": "private, no-store"})
