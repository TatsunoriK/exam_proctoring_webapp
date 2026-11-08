import unittest
from unittest.mock import patch

import mongomock
from fastapi.testclient import TestClient

from app.main import app


class ExamFlowTest(unittest.TestCase):
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
