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
from pymongo.errors import PyMongoError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .exam_questions import attempt_questions
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


def exam_deadline(attempt, exam_body):
    deadline = attempt["started"] + exam_body["minutes"] * 60000
    return min(deadline, exam_body["closesAt"]) if exam_body.get("closesAt") is not None else deadline


def check_exam_window(body):
    timestamp = now_ms()
    if body.get("opensAt") is not None and timestamp < body["opensAt"]:
        fail("ยังไม่ถึงเวลาเปิดสอบ", 403)
    if body.get("closesAt") is not None and timestamp >= body["closesAt"]:
        fail("ปิดรับการทำข้อสอบแล้ว", 403)


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
    expected_user = request.headers.get("x-examflow-user")
    if expected_user and expected_user != user["_id"]:
        fail("บัญชีผู้ใช้เปลี่ยนแล้ว กรุณาโหลดหน้าใหม่", 409)
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
    return {"id": user["_id"], "name": user["name"], "role": user["role"]}


@router.get("/courses")
def courses(request: Request):
    user = current(request, "teacher")
    return [{"id": c["_id"], "name": c["name"]}
            for c in database().exam_courses.find({"owner": user["_id"]}).sort("name", 1)]


@router.post("/courses")
async def create_course(request: Request):
    user = current(request, "teacher")
    body = await request.json()
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        fail("กรุณาระบุชื่อรายวิชาไม่เกิน 120 ตัวอักษร")
    name = " ".join(name.split())
    course_id = digest(user["_id"] + ":course:" + name.casefold())
    try:
        database().exam_courses.insert_one({"_id": course_id, "owner": user["_id"], "name": name, "created": now_ms()})
    except DuplicateKeyError:
        fail("มีรายวิชาชื่อนี้แล้ว", 409)
    return {"id": course_id, "name": name}


@router.get("/exams")
def exams(request: Request):
    user = current(request, "teacher")
    return [{"id": e["_id"], **e["body"], "code": e["code"], "created": e["created"]}
            for e in database().exam_exams.find({"owner": user["_id"]}).sort("created", -1)]


@router.post("/exams")
async def create_exam(request: Request):
    user = current(request, "teacher")
    body = await request.json()
    course_id = body.get("courseId")
    course = None
    if course_id is not None:
        if not isinstance(course_id, str):
            fail("รายวิชาไม่ถูกต้อง")
        course = database().exam_courses.find_one({"_id": course_id, "owner": user["_id"]})
        if not course:
            fail("ไม่พบรายวิชาหรือไม่มีสิทธิ์ใช้งาน", 403)
    questions = body.get("questions")
    device_mode = body.get("deviceMode", "pc")
    if device_mode not in ("pc", "mobile"):
        fail("กรุณาเลือกอุปกรณ์สอบ")
    if not isinstance(body.get("title"), str) or not body["title"].strip() or len(body["title"]) > 200 or type(body.get("minutes")) is not int or not 1 <= body["minutes"] <= 180 or not isinstance(questions, list) or not 1 <= len(questions) <= 100:
        fail("ตรวจสอบชื่อข้อสอบ เวลา และคำถาม")
    opens_at, closes_at = body.get("opensAt"), body.get("closesAt")
    if any(value is not None and (type(value) is not int or not 0 < value <= 8640000000000000) for value in (opens_at, closes_at)):
        fail("วันเวลาเปิด–ปิดสอบไม่ถูกต้อง")
    if opens_at is not None and closes_at is not None and closes_at <= opens_at:
        fail("เวลาปิดสอบต้องอยู่หลังเวลาเปิดสอบ")
    random_questions = body.get("randomQuestions", False)
    shuffle_options = body.get("shuffleOptions", False)
    question_count = body.get("questionCount", len(questions)) if random_questions else len(questions)
    if type(random_questions) is not bool or type(shuffle_options) is not bool or type(question_count) is not int or not 1 <= question_count <= len(questions):
        fail("ตรวจสอบจำนวนข้อที่ต้องการสุ่ม")
    if sum(len(q.get("image", "")) for q in questions if isinstance(q, dict) and isinstance(q.get("image", ""), str)) > 8000000:
        fail("รูปภาพรวมมีขนาดใหญ่เกินไป")
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("text"), str) or not q["text"].strip() or not isinstance(q.get("options"), list) or len(q["options"]) != 4 or any(not isinstance(o, str) or not o.strip() for o in q["options"]) or type(q.get("correct")) is not int or not 0 <= q["correct"] < 4:
            fail("ตรวจสอบคำถามและตัวเลือก")
    for q in questions:
        image = q.get("image", "")
        if not isinstance(image, str) or len(image) > 1400000 or (image and not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+", image)):
            fail("รูปคำถามต้องเป็น PNG, JPEG หรือ WebP ขนาดไม่เกิน 1 MB")
    exam_id = uuid.uuid4().hex
    code = secrets.token_hex(5).upper()
    database().exam_exams.insert_one({"_id": exam_id, "owner": user["_id"], "code": code,
                                     "body": {"title": body["title"], "courseId": course_id, "subject": course["name"] if course else str(body.get("subject", "ทั่วไป"))[:200], "minutes": body["minutes"], "deviceMode": device_mode, "opensAt": opens_at, "closesAt": closes_at, "questions": questions, "randomQuestions": random_questions, "questionCount": question_count, "shuffleOptions": shuffle_options}, "created": now_ms()})
    return {"id": exam_id, "code": code}


@router.post("/exams/{exam_id}/availability")
async def set_exam_availability(exam_id: str, request: Request):
    user = current(request, "teacher")
    body = await request.json()
    if type(body.get("acceptingAttempts")) is not bool:
        fail("สถานะเปิดรับเข้าสอบไม่ถูกต้อง")
    db = database()
    exam = db.exam_exams.find_one({"_id": exam_id, "owner": user["_id"]})
    if not exam:
        fail("ไม่พบข้อสอบหรือไม่มีสิทธิ์", 403)
    updates = {"acceptingAttempts": body["acceptingAttempts"]}
    if body["acceptingAttempts"] and ("opensAt" in body or "closesAt" in body):
        opens_at, closes_at = body.get("opensAt"), body.get("closesAt")
        if any(value is not None and (type(value) is not int or not 0 < value <= 8640000000000000) for value in (opens_at, closes_at)):
            fail("วันเวลาเปิด–ปิดสอบไม่ถูกต้อง")
        if opens_at is not None and closes_at is not None and closes_at <= opens_at:
            fail("เวลาปิดสอบต้องอยู่หลังเวลาเปิดสอบ")
        if closes_at is not None and closes_at <= now_ms():
            fail("กรุณากำหนดเวลาปิดสอบในอนาคต หรือเว้นว่างเพื่อไม่จำกัด")
        updates.update({"opensAt": opens_at, "closesAt": closes_at})
    result = db.exam_exams.update_one(
        {"_id": exam_id, "owner": user["_id"]},
        {"$set": {"body." + key: value for key, value in updates.items()}})
    if not result.matched_count:
        fail("ไม่พบข้อสอบหรือไม่มีสิทธิ์", 403)
    if body["acceptingAttempts"] is False:
        for attempt in db.exam_attempts.find({"exam": exam_id, "submitted": None}):
            finalize_attempt(db, attempt["_id"], exam["body"], forced=True)
    return updates


def check_admission(db, exam, user):
    if exam["body"].get("acceptingAttempts", True) is False:
        fail("อาจารย์ปิดสอบแล้ว", 403)


def finalize_attempt(db, attempt_id, exam_body, forced=False):
    # Compare the answer snapshot so a concurrent save cannot lose points.
    while True:
        attempt = db.exam_attempts.find_one({"_id": attempt_id})
        if attempt.get("submitted") is not None:
            return attempt
        questions = attempt.get("questions", exam_body["questions"])
        score = sum(attempt.get("answers", {}).get(str(i)) == q["correct"] for i, q in enumerate(questions))
        result = db.exam_attempts.find_one_and_update(
            {"_id": attempt_id, "submitted": None, "answers": attempt.get("answers", {})},
            {"$set": {"submitted": now_ms(), "score": score, "forcedSubmitted": forced}},
            return_document=ReturnDocument.AFTER)
        if result:
            return result


def attempt_result(attempt, exam_body):
    return {"score": attempt["score"], "total": len(attempt.get("questions", exam_body["questions"])),
            "forcedSubmitted": attempt.get("forcedSubmitted", False)}


@router.get("/attempt/{attempt_id}/status")
def attempt_status(attempt_id: str, request: Request):
    user = current(request, "student")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id, "student": user["_id"]})
    if not attempt:
        fail("ไม่พบการสอบหรือไม่มีสิทธิ์", 403)
    exam = db.exam_exams.find_one({"_id": attempt["exam"]})
    if exam["body"].get("acceptingAttempts", True) is False and attempt.get("submitted") is None:
        attempt = finalize_attempt(db, attempt_id, exam["body"], forced=True)
    return {"submitted": attempt.get("submitted"),
            **(attempt_result(attempt, exam["body"]) if attempt.get("submitted") is not None else {})}


@router.post("/join")
async def join(request: Request):
    user = current(request, "student")
    body = await request.json()
    exam = database().exam_exams.find_one({"code": str(body.get("code", "")).strip().upper()})
    if not exam:
        fail("ไม่พบรหัสข้อสอบ", 404)
    check_exam_window(exam["body"])
    check_admission(database(), exam, user)
    return {"opensAt": exam["body"].get("opensAt"), "closesAt": exam["body"].get("closesAt"), "id": exam["_id"], "title": exam["body"]["title"], "minutes": exam["body"]["minutes"], "count": exam["body"].get("questionCount", len(exam["body"]["questions"])), "deviceMode": exam["body"].get("deviceMode", "pc")}


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
    check_exam_window(exam["body"])
    check_admission(db, exam, user)
    if mode != exam["body"].get("deviceMode", "pc"):
        fail("อุปกรณ์ไม่ตรงกับที่อาจารย์กำหนด", 403)
    attempt_id = digest(exam["_id"] + ":" + user["_id"])
    attempt = db.exam_attempts.find_one_and_update({"_id": attempt_id}, {"$setOnInsert": {"exam": exam["_id"], "student": user["_id"], "name": str(body["name"])[:120], "deviceMode": mode, "started": now_ms(), "answers": {}, "questions": attempt_questions(exam["body"]), "events": [], "recordings": [], "cameraRecordings": [], "proctoringEvents": [], "submitted": None}}, upsert=True, return_document=ReturnDocument.AFTER)
    latest_exam = db.exam_exams.find_one({"_id": exam["_id"]})
    if latest_exam["body"].get("acceptingAttempts", True) is False:
        finalize_attempt(db, attempt_id, latest_exam["body"], forced=True)
        fail("อาจารย์ปิดสอบแล้ว", 403)
    if attempt["submitted"]:
        fail("คุณส่งข้อสอบนี้แล้ว", 409)
    if attempt.get("deviceMode", "pc") != mode:
        fail("การสอบนี้เริ่มด้วยอุปกรณ์อีกโหมด กรุณาเลือกโหมดเดิม", 409)
    return {"id": attempt_id, "deviceMode": attempt.get("deviceMode", "pc"), "deadline": exam_deadline(attempt, exam["body"]), "answers": attempt["answers"], "questions": [{k: v for k, v in q.items() if k != "correct"} for q in attempt.get("questions", exam["body"]["questions"])]}


def student_attempt(request: Request, attempt_id: str, allow_recent_submission: bool = False, allow_submitted: bool = False):
    user = current(request, "student")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id, "student": user["_id"]})
    if not attempt or (not allow_submitted and attempt.get("submitted") is not None and
                       (not allow_recent_submission or now_ms() - attempt["submitted"] > 120000)):
        fail("ไม่พบการสอบหรือไม่มีสิทธิ์", 403)
    return db, attempt, db.exam_exams.find_one({"_id": attempt["exam"]})


def store_screen_clip(db, attempt_id: str, data: bytes, content_type: str, timing: dict | None = None) -> str:
    bucket = GridFSBucket(db, bucket_name="screen_clips")
    file_id = bucket.upload_from_stream("screen-clip", data, metadata={"attempt_id": attempt_id, "content_type": content_type, "created_at": now_ms()})
    try:
        push = {"recordings": str(file_id)}
        if timing:
            push["recordingTimings"] = {"id": str(file_id), **timing}
        result = db.exam_attempts.update_one({"_id": attempt_id}, {"$push": push})
        if result.matched_count != 1:
            raise RuntimeError("Attempt no longer exists")
    except Exception:
        bucket.delete(file_id)
        raise
    return str(file_id)


@router.post("/attempt/{attempt_id}/{action}")
async def attempt_action(attempt_id: str, action: str, request: Request):
    db, attempt, exam = student_attempt(request, attempt_id, allow_recent_submission=action in ("camera", "camera-failure", "record", "record-failure"), allow_submitted=action == "submit")
    if action == "record-failure":
        db.exam_attempts.update_one({"_id": attempt_id}, {"$push": {"events": {"type": "อัปโหลดคลิปหน้าจอไม่สำเร็จ", "time": now_ms()}}})
        return {"ok": True}
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
            try:
                timing = None
                start_header = request.headers.get("x-clip-start")
                end_header = request.headers.get("x-clip-end")
                if start_header and end_header:
                    try:
                        start, end = int(start_header), int(end_header)
                    except ValueError:
                        fail("Invalid clip timing")
                    if not 0 < start <= end <= now_ms() + 60000:
                        fail("Invalid clip timing")
                    timing = {"start": start, "end": end}
                await run_in_threadpool(store_screen_clip, db, attempt_id, bytes(data), content_type, timing)
            except (PyMongoError, RuntimeError) as exc:
                logger.exception("Screen clip storage failed for attempt %s", attempt_id)
                raise HTTPException(status_code=503, detail="บันทึกคลิปหน้าจอไม่สำเร็จ") from exc
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
        if exam["body"].get("acceptingAttempts", True) is False:
            finalize_attempt(db, attempt_id, exam["body"], forced=True)
            fail("อาจารย์ปิดสอบแล้ว", 409)
        if now_ms() >= exam_deadline(attempt, exam["body"]):
            fail("หมดเวลาสอบแล้ว", 409)
        answers = body.get("answers", {})
        if not isinstance(answers, dict) or any(not str(k).isdigit() or int(k) >= len(attempt.get("questions", exam["body"]["questions"])) or type(v) is not int or not 0 <= v <= 3 for k, v in answers.items()):
            fail("คำตอบไม่ถูกต้อง")
        saved = db.exam_attempts.update_one({"_id": attempt_id, "submitted": None}, {"$set": {"answers": answers}})
        if not saved.matched_count:
            fail("การสอบสิ้นสุดแล้ว", 409)
        return {"ok": True}
    if action == "submit":
        result = finalize_attempt(db, attempt_id, exam["body"], forced=exam["body"].get("acceptingAttempts", True) is False)
        if body.get("analysisIncomplete") is True:
            db.exam_attempts.update_one({"_id": attempt_id}, {"$push": {"proctoringEvents": {"status": "analysis_failed", "reviewFlags": [], "segment": -1}}})
        return attempt_result(result, exam["body"])
    fail("ไม่พบรายการ", 404)


@router.get("/student/history")
def student_history(request: Request):
    user = current(request, "student")
    db = database()
    attempts = list(db.exam_attempts.find({"student": user["_id"]},
                    {"exam": 1, "started": 1, "submitted": 1, "score": 1, "questions": 1}).sort("started", -1))
    exam_ids = list({a["exam"] for a in attempts})
    exams = {e["_id"]: e["body"] for e in db.exam_exams.find({"_id": {"$in": exam_ids}}, {"body": 1})}
    history = []
    for a in attempts:
        exam = exams.get(a["exam"])
        submitted = a.get("submitted")
        expired = exam and now_ms() >= exam_deadline(a, exam)
        history.append({"id": a["_id"], "title": exam["title"] if exam else "ข้อสอบที่ไม่พร้อมใช้งาน",
                        "subject": exam.get("subject", "ทั่วไป") if exam else "",
                        "total": len(a["questions"]) if "questions" in a else exam.get("questionCount", len(exam["questions"])) if exam else None,
                        "started": a["started"], "submitted": submitted, "score": a.get("score") if submitted else None,
                        "status": "submitted" if submitted else "expired" if expired else "in_progress"})
    return history


@router.get("/results/{exam_id}")
def results(exam_id: str, request: Request):
    user = current(request, "teacher")
    db = database()
    if not db.exam_exams.find_one({"_id": exam_id, "owner": user["_id"]}):
        fail("ไม่มีสิทธิ์", 403)
    return [{"id": a["_id"], "name": a["name"], "email": a.get("student", ""), "total": len(a["questions"]) if "questions" in a else None, "deviceMode": a.get("deviceMode", "pc"), "started": a["started"], "submitted": a["submitted"], "score": a.get("score"), "events": a["events"], "recordings": a.get("recordings", []), "recordingTimings": a.get("recordingTimings", []), "cameraRecordings": a["cameraRecordings"], "proctoringEvents": a["proctoringEvents"], "review": a.get("review", {"status": "pending"}), "reviews": a.get("reviews", {})} for a in db.exam_attempts.find({"exam": exam_id}).sort("started", -1)]


def video_response(obj, request: Request):
    """Serve a single byte range so browsers can seek in stored recordings."""
    headers = {"Cache-Control": "private, no-store", "Accept-Ranges": "bytes"}
    media_type = (obj.metadata or {}).get("content_type", "video/webm")
    try:
        size = obj.length
        requested = request.headers.get("range")
        if not requested:
            return Response(obj.read(), media_type=media_type, headers=headers)
        match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", requested.strip())
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            start, end = max(0, size - int(last)), size - 1
        if start > end or start >= size:
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        obj.seek(start)
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(obj.read(end - start + 1), status_code=206, media_type=media_type, headers=headers)
    finally:
        obj.close()


@router.get("/video/{attempt_id}/{index}")
def screen_video(attempt_id: str, index: int, request: Request):
    user = current(request, "teacher")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id})
    if not attempt or not db.exam_exams.find_one({"_id": attempt["exam"], "owner": user["_id"]}):
        fail("ไม่มีสิทธิ์", 403)
    recordings = attempt.get("recordings", [])
    if index < 0 or index >= len(recordings):
        fail("ไม่พบคลิป", 404)
    obj = GridFSBucket(db, bucket_name="screen_clips").open_download_stream(ObjectId(recordings[index]))
    return video_response(obj, request)


@router.post("/review/{attempt_id}")
async def review_attempt(attempt_id: str, request: Request):
    user = current(request, "teacher")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id})
    if not attempt or not db.exam_exams.find_one({"_id": attempt["exam"], "owner": user["_id"]}):
        fail("ไม่มีสิทธิ์", 403)
    body = await request.json()
    status = body.get("status")
    if status not in ("pending", "normal", "misconduct"):
        fail("สถานะไม่ถูกต้อง")
    result = {"status": status, "updated": now_ms(), "reviewer": user["_id"]}
    db.exam_attempts.update_one({"_id": attempt_id}, {"$set": {"review": result}})
    return result


@router.post("/review/{attempt_id}/{clip_id}")
async def review(attempt_id: str, clip_id: str, request: Request):
    user = current(request, "teacher")
    db = database()
    attempt = db.exam_attempts.find_one({"_id": attempt_id})
    if not attempt or not db.exam_exams.find_one({"_id": attempt["exam"], "owner": user["_id"]}):
        fail("ไม่มีสิทธิ์", 403)
    is_clip = ObjectId.is_valid(clip_id) and clip_id in attempt.get("cameraRecordings", []) + attempt.get("recordings", [])
    is_event = re.fullmatch(r"event-[0-9]+", clip_id) and int(clip_id[6:]) < len(attempt.get("events", []))
    if not (is_clip or is_event):
        fail("ไม่พบคลิป", 404)
    body = await request.json()
    status = body.get("status")
    if status not in ("pending", "normal", "misconduct", "reviewed", "needs_followup"):
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
    return video_response(obj, request)
