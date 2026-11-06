# Exam Vision — React + Tailwind + FastAPI

เว็บตัวอย่างสำหรับจับภาพจากเว็บแคม สกัด feature ด้วย MediaPipe และ YOLOv8s แล้วส่ง feature ให้โมเดล Random Forest จำแนกเฟรมเป็น `normal`, `suspicious` หรือ `cheating` ผู้ใช้สามารถนำเข้า feature JSON เองได้เช่นกัน

- `frontend/` — React, Vite และ Tailwind สำหรับเปิดกล้องและแสดงผล
- `backend/` — FastAPI สำหรับสกัด feature และทำนายผล
- `model/` — โมเดล Random Forest และไฟล์โมเดลที่ใช้สกัด feature

## ติดตั้งและเริ่มใช้งานบน Windows

ต้องมี Python 3.13, Node.js 20 หรือใหม่กว่า และอินเทอร์เน็ตสำหรับติดตั้งแพ็กเกจและดาวน์โหลดไฟล์โมเดล เปิด Command Prompt ที่โฟลเดอร์โปรเจกต์

### 1. ติดตั้ง backend และดาวน์โหลดโมเดล

```bat
cd backend
py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File setup_webcam_models.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

สคริปต์ดาวน์โหลด `face_landmarker.task`, `hand_landmarker.task` และ `yolov8s.pt` ลงใน `model/` ส่วน `exam_proctoring_model.joblib` ต้องมีอยู่ในโฟลเดอร์เดียวกันอยู่แล้ว ปล่อยหน้าต่าง backend เปิดไว้ระหว่างใช้งาน

- API: http://127.0.0.1:8000
- เอกสาร API: http://127.0.0.1:8000/docs

### 2. เริ่ม frontend

เปิด Command Prompt อีกหน้าต่างที่โฟลเดอร์โปรเจกต์:

```bat
cd frontend
npm install
npm run dev
```

เปิด http://127.0.0.1:5173 โดย Vite จะส่งคำขอ `/api` ไปยัง backend ที่พอร์ต 8000 หากต้องการให้ FastAPI เสิร์ฟหน้าเว็บ ให้รัน `npm run build` ใน `frontend` แล้วเปิด http://127.0.0.1:8000 แทน

## ใช้งานเว็บแคม

1. กด **เปิดกล้อง** และอนุญาตให้เบราว์เซอร์ใช้กล้อง โดยเปิดเว็บผ่าน localhost หรือ HTTPS
2. กด **จับภาพและสกัด feature** ระบบจะส่งภาพ JPEG ของเฟรมนั้นไปยัง backend และนำ feature JSON ที่ได้ไปใส่ในช่องข้อมูล
3. กด **ทำนายผล** เพื่อส่ง JSON เข้าโมเดล Random Forest แล้วดูผลและคะแนนแต่ละคลาส
4. กด **ปิดกล้อง** เมื่อใช้งานเสร็จ สามารถดาวน์โหลดภาพที่จับในรูปแบบ JSON ได้จากปุ่มดาวน์โหลด

ภาพที่ส่งไปสกัดถูกประมวลผลใน backend และ endpoint ไม่บันทึกภาพลงไฟล์ ปุ่มดาวน์โหลดเว็บแคมจะบันทึก JSON ที่มีภาพ JPEG แบบ data URL ส่วนช่อง **Feature payload** เป็น JSON ตัวเลขสำหรับการทำนาย ซึ่งสามารถแก้ไขหรือโหลดจากไฟล์แยกได้

สามารถเลือกไฟล์ JSON ภาพที่ดาวน์โหลดไว้ หรือวาง JSON ภาพในช่องข้อมูล แล้วกด **ทำนายผล** ได้เช่นกัน ระบบจะสกัด feature ก่อนทำนายโดยอัตโนมัติ

## API

- `GET /api/health` — ตรวจสถานะ backend และโมเดล Random Forest
- `GET /api/schema` — ดูชื่อ feature และคลาสที่โมเดลรองรับ
- `POST /api/extract-frame` — รับ JSON รูปแบบ `{"image": "data:image/jpeg;base64,..."}` และส่งคืน `features`, `objects` และหมายเหตุ เฟรมต้องมีขนาดไม่เกิน 12 ล้านพิกเซลและ data URL ไม่เกิน 4 ล้านตัวอักษร
- `POST /api/predict` — รับ JSON รูปแบบ `{"features": {...}}` และส่งคืนผลจำแนกกับความน่าจะเป็น

สำหรับ `/api/predict` ต้องส่งชื่อ feature ให้ครบตาม schema ทั้ง 67 ฟิลด์ ใช้ `null` สำหรับค่าที่ไม่มีได้ แต่ต้องมีค่าตัวเลขหรือ boolean อย่างน้อย 10 ค่า โมเดลจะแทน `null` ด้วย median จากชุดฝึก

## ข้อจำกัด

- การจับภาพเป็นแบบทีละเฟรม ไม่ใช่การติดตามต่อเนื่อง ค่า flag การหันหน้าและสายตาใช้ค่ากลางจากชุดข้อมูลที่ให้มา ส่วน flag การพูดใช้ `null` เพราะต้องอาศัยหลายเฟรม วิธีนี้ต่างจาก baseline และหน้าต่างเวลาของ notebook
- โหมด YOLO COCO ตาม notebook ตรวจได้เฉพาะคลาสที่โมเดลรองรับ จึงไม่ครอบคลุมวัตถุทุกประเภทใน schema
- ยังไม่ได้ยืนยันว่าไฟล์ Random Forest ฝึกจากชุดข้อมูลที่ให้มาโดยตรง และยังไม่ได้ทดสอบการสกัดและทำนายครบวงจรกับกล้องจริง ผลลัพธ์จึงต้องได้รับการตรวจสอบก่อนใช้งานจริง
- ผลโมเดลเป็นเพียงข้อมูลช่วยคัดกรอง ไม่ใช่ข้อสรุปว่ามีการทุจริต ก่อนเปิดให้ผู้ใช้ภายนอกเข้าถึงควรเพิ่ม authentication, HTTPS และ rate limiting
