"""Opt-in integration smoke test; creates and removes only its own test records."""
import uuid
from unittest.mock import patch

from bson import ObjectId
from fastapi.testclient import TestClient
from gridfs import GridFSBucket

from app.database import database
from app.main import app


def main():
    db = database()
    key = uuid.uuid4().hex
    teacher_email = f"test-teacher-{key}@example.invalid"
    student_email = f"test-student-{key}@example.invalid"
    teacher, student = TestClient(app), TestClient(app)
    exam_id = attempt_id = clip_id = None
    try:
        for client, email, role in [(teacher, teacher_email, "teacher"), (student, student_email, "student")]:
            response = client.post("/api/auth/register", json={"name": "Test account", "email": email, "password": "temporary-password", "role": role})
            response.raise_for_status()
        response = teacher.post("/api/exams", json={"title": "Integration test", "minutes": 10, "questions": [{"text": "Test?", "options": ["A", "B", "C", "D"], "correct": 1}]})
        response.raise_for_status()
        exam_id = response.json()["id"]
        response = student.post("/api/start", json={"exam": exam_id, "name": "Test", "cameraConsent": True})
        response.raise_for_status()
        attempt_id = response.json()["id"]
        fake_result = {"status": "analyzed", "review_flags": [{"time_s": 0, "label": "suspicious", "confidence": 0.8}], "frames_analyzed": 1, "model_version": "test"}
        with patch("app.examflow_api.analyze_video", return_value=fake_result), patch("app.examflow_api.clip_executor.submit", side_effect=lambda fn, *args: fn(*args)):
            response = student.post(f"/api/attempt/{attempt_id}/camera", content=b"synthetic-test-data", headers={"content-type": "video/webm"})
            response.raise_for_status()
        response = teacher.get(f"/api/results/{exam_id}")
        response.raise_for_status()
        clip_id = response.json()[0]["cameraRecordings"][0]
        response = teacher.get(f"/api/camera/{attempt_id}/0")
        response.raise_for_status()
        assert response.content == b"synthetic-test-data"
        print("Atlas accounts, exam, attempt, flagged clip write and authorized read: OK")
    finally:
        # Use the test's exact identifiers; never remove other users' data.
        if attempt_id:
            attempt = db.exam_attempts.find_one({"_id": attempt_id})
            for file_id in (attempt or {}).get("cameraRecordings", []):
                GridFSBucket(db, bucket_name="review_clips").delete(ObjectId(file_id))
            db.exam_attempts.delete_one({"_id": attempt_id})
        if exam_id:
            db.exam_exams.delete_one({"_id": exam_id})
        db.exam_sessions.delete_many({"user_id": {"$in": [teacher_email, student_email]}})
        db.exam_users.delete_many({"_id": {"$in": [teacher_email, student_email]}})


if __name__ == "__main__":
    main()
