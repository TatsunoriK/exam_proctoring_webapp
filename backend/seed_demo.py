"""Create demo accounts and an LLM quiz without changing existing accounts."""
import secrets

from fastapi.testclient import TestClient
from app.database import database
from app.main import app

QUESTIONS = [
    ("LLM ย่อมาจากอะไร?", ["Large Language Model", "Local Learning Machine", "Long Logic Memory", "Linked Language Method"], 0),
    ("LLM แบบสร้างข้อความมักทำนายสิ่งใดในขั้นตอนพื้นฐาน?", ["อุณหภูมิของเครื่อง", "โทเคนถัดไปจากบริบท", "รหัสผ่านของผู้ใช้", "ผลลัพธ์ที่ถูกต้องเสมอ"], 1),
    ("Prompt ในการใช้ LLM หมายถึงอะไร?", ["ข้อมูลหรือคำสั่งที่ส่งให้โมเดล", "อุปกรณ์เก็บข้อมูล", "ชื่อฐานข้อมูล", "ระบบปฏิบัติการ"], 0),
    ("อาการ hallucination ของโมเดลหมายถึงอะไร?", ["โมเดลปิดตัวลง", "โมเดลสร้างคำตอบที่ดูน่าเชื่อแต่ไม่ถูกต้องหรือไม่มีหลักฐาน", "โมเดลเข้ารหัสข้อมูล", "โมเดลเรียนรู้ทุกอย่างแบบเรียลไทม์"], 1),
    ("การใช้ RAG โดยทั่วไปเกี่ยวข้องกับอะไร?", ["ค้นข้อมูลที่เกี่ยวข้องแล้วส่งเป็นบริบทให้โมเดล", "ลบข้อมูลฝึกทั้งหมด", "ปิดการใช้เอกสาร", "เพิ่มความเร็วอินเทอร์เน็ต"], 0),
    ("Token ในบริบทของ LLM คืออะไร?", ["หน่วยข้อมูลข้อความที่ tokenizer แบ่งเพื่อให้โมเดลประมวลผล", "คำภาษาอังกฤษหนึ่งคำเสมอ", "บัญชีผู้ใช้", "ไฟล์ภาพชนิดหนึ่ง"], 0),
    ("วิธีใดเหมาะสมเมื่อต้องใช้คำตอบ AI ในงานที่ต้องการความถูกต้อง?", ["เชื่อทุกคำตอบทันที", "ตรวจสอบกับแหล่งข้อมูลที่เชื่อถือได้", "ใช้คำตอบโดยไม่อ่าน", "ละเว้นข้อจำกัดของโมเดล"], 1),
    ("ข้อมูลใดไม่ควรส่งให้บริการ AI สาธารณะโดยไม่ได้รับอนุญาต?", ["ข้อความประชาสัมพันธ์ที่เผยแพร่แล้ว", "รหัสผ่านและข้อมูลส่วนบุคคลที่อ่อนไหว", "ชื่อสีทั่วไป", "คำถามคณิตศาสตร์ทั่วไป"], 1),
    ("Fine-tuning โดยทั่วไปหมายถึงอะไร?", ["ฝึกต่อโมเดลที่มีอยู่ด้วยข้อมูลเพิ่มเติมสำหรับงานที่ต้องการ", "เปลี่ยนชื่อไฟล์", "ค้นเว็บทุกครั้งโดยไม่ใช้โมเดล", "ลบพารามิเตอร์ทุกตัว"], 0),
    ("เหตุใดผลลัพธ์ของ AI จึงอาจมีอคติ?", ["เพราะข้อมูลฝึกหรือกระบวนการออกแบบอาจสะท้อนอคติ", "เพราะ AI ไม่มีข้อมูลฝึก", "เพราะผลลัพธ์เป็นกลางเสมอ", "เพราะ AI ไม่ใช้ข้อมูล"], 0),
]


def main():
    db = database()
    client = TestClient(app)
    users = [("student01@example.test", "student01", "student"), ("teacher01@example.test", "teacher01", "teacher")]
    if any(db.exam_users.find_one({"_id": email}) for email, _, _ in users):
        print("A demo account already exists; no accounts or passwords were changed.")
        return
    credentials = []
    for email, name, role in users:
        password = secrets.token_urlsafe(15)
        response = client.post("/api/auth/register", json={"email": email, "name": name, "role": role, "password": password})
        response.raise_for_status()
        credentials.append((email, password))
        print(f"Account: {email} | Password: {password}", flush=True)
        if role == "teacher":
            quiz = {"title": "ความรู้พื้นฐาน LLM และ AI", "subject": "Artificial Intelligence", "minutes": 20,
                    "questions": [{"text": text, "options": options, "correct": correct} for text, options, correct in QUESTIONS]}
            result = client.post("/api/exams", json=quiz)
            result.raise_for_status()
            print(f"Exam code: {result.json()['code']}", flush=True)


if __name__ == "__main__":
    main()
