import unittest
from unittest.mock import patch

import mongomock
from bson import ObjectId
from types import SimpleNamespace
from fastapi.testclient import TestClient

from app.main import app


class ExamFlowTest(unittest.TestCase):
    def test_student_history_is_private_and_excludes_answers(self):
        db = mongomock.MongoClient().exam_test
        student, other, teacher = TestClient(app), TestClient(app), TestClient(app)
        with patch("app.examflow_api.database", return_value=db):
            for client, email, role in [(student, "first@example.test", "student"),
                                        (other, "other@example.test", "student"),
                                        (teacher, "teacher@example.test", "teacher")]:
                self.assertEqual(client.post("/api/auth/register", json={"name": "Test user", "email": email,
                                 "password": "password123", "role": role}).status_code, 200)
            db.exam_exams.insert_one({"_id": "exam", "body": {"title": "History exam", "minutes": 10,
                                      "questions": [{"correct": 2}]}})
            db.exam_attempts.insert_many([
                {"_id": "mine", "student": "first@example.test", "exam": "exam", "started": 1,
                 "submitted": 2, "score": 0, "reviews": {"private": "data"}, "answers": {"0": 1}},
                {"_id": "missing", "student": "first@example.test", "exam": "deleted", "started": 3,
                 "submitted": None},
                {"_id": "theirs", "student": "other@example.test", "exam": "exam", "started": 4}])
            response = student.get("/api/student/history")
            self.assertEqual(response.status_code, 200)
            history = response.json()
            self.assertEqual([a["id"] for a in history], ["missing", "mine"])
            self.assertEqual(history[1]["score"], 0)
            self.assertEqual(history[1]["total"], 1)
            self.assertNotIn("reviews", history[1])
            self.assertNotIn("answers", history[1])
            self.assertNotIn("correct", response.text)
            self.assertEqual(len(other.get("/api/student/history").json()), 1)
            self.assertEqual(teacher.get("/api/student/history").status_code, 403)
            self.assertEqual(TestClient(app).get("/api/student/history").status_code, 401)

    def test_screen_clip_is_stored_and_only_exam_owner_can_view(self):
        db = mongomock.MongoClient().exam_test
        teacher, student, other = TestClient(app), TestClient(app), TestClient(app)
        stored = {}
        class FakeBucket:
            def __init__(self, *args, **kwargs): pass
            def upload_from_stream(self, name, data, metadata):
                file_id = ObjectId()
                stored[file_id] = (data, metadata)
                return file_id
            def open_download_stream(self, file_id):
                data, metadata = stored[file_id]
                return SimpleNamespace(read=lambda: data, metadata=metadata)
            def delete(self, file_id): stored.pop(file_id, None)
        with patch("app.examflow_api.database", return_value=db), patch("app.examflow_api.GridFSBucket", FakeBucket):
            for client, name, role in [(teacher, "teacher", "teacher"), (student, "student", "student"), (other, "other", "teacher")]:
                response = client.post("/api/auth/register", json={"name": name + " user", "email": name + "@example.test", "password": "password123", "role": role})
                self.assertEqual(response.status_code, 200)
            exam = teacher.post("/api/exams", json={"title": "Test", "minutes": 10, "questions": [{"text": "Question", "options": ["A", "B", "C", "D"], "correct": 0}]}).json()
            attempt_id = student.post("/api/start", json={"exam": exam["id"], "name": "Student", "cameraConsent": True}).json()["id"]
            base = "/api/attempt/" + attempt_id
            self.assertEqual(student.post(base + "/record", content=b"screen segment", headers={"content-type": "video/webm"}).status_code, 200)
            self.assertEqual(student.post(base + "/submit", json={}).status_code, 200)
            self.assertEqual(student.post(base + "/record", content=b"last segment", headers={"content-type": "video/webm"}).status_code, 200)
            records = teacher.get("/api/results/" + exam["id"]).json()[0]["recordings"]
            self.assertEqual(len(records), 2)
            path = "/api/video/" + attempt_id + "/0"
            self.assertEqual(other.get(path).status_code, 403)
            response = teacher.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"screen segment")

    def test_exam_and_flagged_clip_flow(self):
        db = mongomock.MongoClient().exam_test
        teacher = TestClient(app)
        student = TestClient(app)
        other = TestClient(app)
        with patch("app.examflow_api.database", return_value=db), \
             patch("app.examflow_api.analyze_video", return_value={"status": "analyzed", "review_flags": [{"time_s": 1.0, "label": "suspicious", "confidence": 0.7}], "frames_analyzed": 1, "model_version": "test"}), \
             patch("app.examflow_api.store_flagged_clip", return_value="0123456789abcdef01234567"), \
             patch("app.examflow_api.clip_executor.submit", side_effect=lambda fn, *args: fn(*args)):
            for client, email, role in [(teacher, "teacher@example.test", "teacher"), (student, "student@example.test", "student"), (other, "other@example.test", "teacher")]:
                r = client.post("/api/auth/register", json={"name": role + " user", "email": email, "password": "password123", "role": role})
                self.assertEqual(r.status_code, 200, r.text)
            exam = teacher.post("/api/exams", json={"title": "Test", "minutes": 10, "questions": [{"text": "Question", "options": ["A", "B", "C", "D"], "correct": 1}]}).json()
            self.assertEqual(other.get("/api/results/" + exam["id"]).status_code, 403)
            self.assertEqual(student.post("/api/join", json={"code": exam["code"]}).status_code, 200)
            r = student.post("/api/start", json={"exam": exam["id"], "name": "Student", "cameraConsent": True})
            self.assertEqual(r.status_code, 200, r.text)
            attempt = r.json()
            self.assertNotIn("correct", attempt["questions"][0])
            base = "/api/attempt/" + attempt["id"]
            self.assertEqual(student.post(base + "/answers", json={"answers": {"0": 1}}).status_code, 200)
            self.assertEqual(student.post(base + "/camera", content=b"fake clip", headers={"content-type": "video/webm"}).status_code, 200)
            self.assertEqual(student.post(base + "/submit", json={}).json()["score"], 1)
            results = teacher.get("/api/results/" + exam["id"]).json()
            self.assertEqual(len(results[0]["cameraRecordings"]), 1)
            self.assertEqual(results[0]["proctoringEvents"][0]["reviewFlags"][0]["label"], "suspicious")
            self.assertEqual(other.get("/api/camera/" + attempt["id"] + "/0").status_code, 403)
            path = "/api/review/" + attempt["id"] + "/0123456789abcdef01234567"
            self.assertEqual(other.post(path, json={"status": "reviewed"}).status_code, 403)
            self.assertEqual(teacher.post(path, json={"status": "reviewed"}).status_code, 200)
            self.assertEqual(teacher.get("/api/results/" + exam["id"]).json()[0]["reviews"]["0123456789abcdef01234567"]["status"], "reviewed")

    def test_clip_processing_continues_after_submission(self):
        db = mongomock.MongoClient().exam_test
        teacher, student = TestClient(app), TestClient(app)
        tasks = []
        with patch("app.examflow_api.database", return_value=db), \
             patch("app.examflow_api.analyze_video", return_value={"status": "analyzed", "review_flags": [{"time_s": 1, "label": "suspicious", "confidence": 0.8}]}), \
             patch("app.examflow_api.store_flagged_clip", return_value="0123456789abcdef01234567"), \
             patch("app.examflow_api.clip_executor.submit", side_effect=lambda fn, *args: tasks.append((fn, args))):
            for client, role in [(teacher, "teacher"), (student, "student")]:
                self.assertEqual(client.post("/api/auth/register", json={"name": role + " user", "email": role + "@example.test", "password": "password123", "role": role}).status_code, 200)
            exam = teacher.post("/api/exams", json={"title": "Async", "minutes": 10, "questions": [{"text": "Question", "options": ["A", "B", "C", "D"], "correct": 0}]}).json()
            attempt = student.post("/api/start", json={"exam": exam["id"], "name": "Student", "cameraConsent": True}).json()
            base = "/api/attempt/" + attempt["id"]
            self.assertEqual(student.post(base + "/camera", content=b"video", headers={"content-type": "video/webm"}).json()["status"], "processing")
            self.assertEqual(student.post(base + "/submit", json={}).status_code, 200)
            self.assertEqual(teacher.get("/api/results/" + exam["id"]).json()[0]["proctoringEvents"][0]["status"], "processing")
            fn, args = tasks.pop()
            fn(*args)
            result = teacher.get("/api/results/" + exam["id"]).json()[0]
            self.assertEqual(result["proctoringEvents"][0]["status"], "analyzed")
            self.assertEqual(len(result["cameraRecordings"]), 1)
            self.assertEqual(student.post(base + "/camera", content=b"video", headers={"content-type": "video/webm"}).status_code, 200)
            fn, args = tasks.pop()
            fn(*args)

    def test_mobile_attempt_does_not_accept_camera(self):
        db = mongomock.MongoClient().exam_test
        teacher, student = TestClient(app), TestClient(app)
        with patch("app.examflow_api.database", return_value=db):
            for client, role in [(teacher, "teacher"), (student, "student")]:
                response = client.post("/api/auth/register", json={"name": role + " user", "email": role + "@example.test", "password": "password123", "role": role})
                self.assertEqual(response.status_code, 200)
            exam = teacher.post("/api/exams", json={"title": "Mobile", "minutes": 10, "deviceMode": "mobile", "questions": [{"text": "Question", "options": ["A", "B", "C", "D"], "correct": 0}]}).json()
            body = {"exam": exam["id"], "name": "Student", "cameraConsent": True, "deviceMode": "mobile"}
            self.assertEqual(student.post("/api/join", json={"code": exam["code"]}).json()["deviceMode"], "mobile")
            response = student.post("/api/start", json=body)
            self.assertEqual(response.status_code, 200)
            attempt_id = response.json()["id"]
            self.assertEqual(response.json()["deviceMode"], "mobile")
            self.assertEqual(student.post(f"/api/attempt/{attempt_id}/camera", content=b"data", headers={"content-type": "video/webm"}).status_code, 403)
            self.assertEqual(student.post("/api/start", json={**body, "deviceMode": "pc"}).status_code, 403)
            self.assertEqual(teacher.get("/api/results/" + exam["id"]).json()[0]["deviceMode"], "mobile")
            self.assertEqual(student.post(f"/api/attempt/{attempt_id}/submit", json={"analysisIncomplete": True}).status_code, 200)
            self.assertEqual(teacher.get("/api/results/" + exam["id"]).json()[0]["proctoringEvents"][-1]["status"], "analysis_failed")


if __name__ == "__main__":
    unittest.main()
