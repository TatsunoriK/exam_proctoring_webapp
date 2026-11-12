"""Frame features adapted from exam_proctoring_v2.ipynb."""
import json, math, os
from pathlib import Path
import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from ultralytics import YOLO

MODEL_DIR = str(Path(__file__).resolve().parents[2] / "model")
OBJ_CANON = ["person", "phone", "tablet", "book", "paper", "earphone", "watch", "laptop", "tv", "remote"]
# ชื่อคลาสของโมเดล -> ชื่อกลาง
ALIAS = {"person": "person", "cell phone": "phone", "mobile phone": "phone", "tablet": "tablet",
         "book": "book", "paper": "paper", "earphones": "earphone", "headphones": "earphone",
         "smartwatch": "watch", "laptop": "laptop", "tv": "tv", "remote": "remote"}
COCO_IDS = [0, 62, 63, 65, 67, 73]     # person, tv, laptop, remote, cell phone, book
WORLD_PROMPTS = ["person", "mobile phone", "tablet", "book", "paper", "earphones",
                 "headphones", "smartwatch", "laptop"]

CFG = dict(
    sample_fps=5, max_width=640, max_frames_per_video=600, save_frames=True,
    run_yolo=True,
    yolo_backend="coco",        # "coco" = COCO (คน/มือถือ/หนังสือ/แล็ปท็อป/ทีวี/รีโมต) เสถียร
                                # "world" = YOLO-World (เพิ่ม หูฟัง/กระดาษโน้ต/แท็บเล็ต/นาฬิกา) ต้องทดสอบเองก่อนใช้จริง
    yolo_weights={"coco": "yolov8s.pt", "world": "yolov8s-worldv2.pt"},
    yolo_imgsz=960,
    yolo_min_conf=0.12,         # Keep lower-score detections for per-class filtering below.
    obj_conf=dict(person=0.40, phone=0.15, tablet=0.30, book=0.30, paper=0.30,
                  earphone=0.25, watch=0.30, laptop=0.40, tv=0.45, remote=0.35),
    window_sec=3.0,
    base=dict(yaw=0.18, mar=0.25),
    cand=dict(
        yaw_sus=0.10, yaw_strong=0.20, pitch=0.07, gaze_h=0.12, talk_std=0.03,
        w=dict(multi_person=1.0, phone=1.0, tablet=1.0, book=0.5, paper=0.4, earphone=0.4,
               watch=0.15, laptop=0.3, tv=0.3, remote=0.2,
               no_face=0.5, look_away=0.4, look_away_strong=0.6, head_pitch=0.3,
               gaze_away=0.3, talking=0.3, hand_mouth=0.3, hand_face=0.15),
        t_sus=0.30, t_cheat=0.65,
    ),
    verify=dict(
        n_splits=5,          # จำนวน fold (แบ่งตามวิดีโอ)
        p_correct=0.70,      # โมเดลต้องมั่นใจอย่างน้อยเท่านี้จึงแก้ label
        p_suspect=0.30,      # และ label เดิมต้องได้ความน่าจะเป็นไม่เกินเท่านี้
        hard_obj_conf=0.50,  # มือถือ/แท็บเล็ตที่ conf ถึงเท่านี้ถือเป็นหลักฐานแข็ง
        hard_persist=0.60,   # และต้องเจอต่อเนื่องในหน้าต่างเวลาอย่างน้อยสัดส่วนนี้
    ),
    split=dict(val=0.15, test=0.15, seed=0),   # แบ่ง train/val/test ตามวิดีโอ
)
def _resize(img, max_w):
    h, w = img.shape[:2]
    if w <= max_w: return img
    s = max_w / w
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

def iter_frames(path):
    """yield (frame_idx, time_s, bgr_frame)"""
    if Path(path).suffix.lower() in IMG_EXT:
        img = cv2.imread(path)
        if img is not None: yield 0, 0.0, _resize(img, CFG["max_width"])
        return
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(int(round(fps / CFG["sample_fps"])), 1)
    i = n = 0
    while True:
        if not cap.grab(): break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok: break
            yield i, i / fps, _resize(frame, CFG["max_width"])
            n += 1
            if n >= CFG["max_frames_per_video"]: break
        i += 1
    cap.release()

L_EYE = [33,7,163,144,145,153,154,155,133,173,157,158,159,160,161,246]
R_EYE = [362,382,381,380,374,373,390,249,263,466,388,387,386,385,384,398]
MOUTH = [61,146,91,181,84,17,314,405,321,375,291,409,270,269,267,0,37,39,40,185,
         78,95,88,178,87,14,317,402,318,324,308,415,310,311,312,13,82,81,80,191]
L_EYE6 = [33,160,158,133,153,144]; R_EYE6 = [362,385,387,263,373,380]

def box_of(pts, idx, pad, w, h):
    p = pts if idx is None else pts[idx]
    x1, y1 = p.min(0); x2, y2 = p.max(0)
    bw, bh = x2 - x1, y2 - y1
    x1 -= bw*pad; x2 += bw*pad; y1 -= bh*pad; y2 += bh*pad
    return [float(max(x1, 0)), float(max(y1, 0)), float(min(x2, w-1)), float(min(y2, h-1))]

def put_box(d, name, b):
    for k, v in zip(("x1", "y1", "x2", "y2"), b): d[f"{name}_{k}"] = v

def ear(p, i):
    a = np.linalg.norm(p[i[1]]-p[i[5]]); b = np.linalg.norm(p[i[2]]-p[i[4]])
    c = np.linalg.norm(p[i[0]]-p[i[3]])
    return float((a+b) / (2*c + 1e-6))

def face_features(pts, w, h):
    f = {}
    fb = box_of(pts, None, 0.05, w, h); put_box(f, "face", fb)
    put_box(f, "leye", box_of(pts, L_EYE, 0.35, w, h))
    put_box(f, "reye", box_of(pts, R_EYE, 0.35, w, h))
    mb = box_of(pts, MOUTH, 0.15, w, h); put_box(f, "mouth", mb)
    fw = pts[454, 0] - pts[234, 0] + 1e-6
    f["yaw"] = float((pts[1, 0] - (pts[234, 0] + pts[454, 0]) / 2) / fw)
    f["pitch"] = float((pts[1, 1] - pts[10, 1]) / (pts[152, 1] - pts[10, 1] + 1e-6))
    f["roll"] = float(math.degrees(math.atan2(pts[263, 1]-pts[33, 1], pts[263, 0]-pts[33, 0])))
    f["ear"] = (ear(pts, L_EYE6) + ear(pts, R_EYE6)) / 2
    f["mar"] = float(np.linalg.norm(pts[13]-pts[14]) / (np.linalg.norm(pts[78]-pts[308]) + 1e-6))
    f["face_area"] = float((fb[2]-fb[0]) * (fb[3]-fb[1]) / (w*h))
    if len(pts) >= 478:
        il, ir = pts[468], pts[473]
        gl = (il[0]-pts[33][0]) / (pts[133][0]-pts[33][0] + 1e-6)
        gr = (ir[0]-pts[362][0]) / (pts[263][0]-pts[362][0] + 1e-6)
        vl = (il[1]-pts[159][1]) / (pts[145][1]-pts[159][1] + 1e-6)
        vr = (ir[1]-pts[386][1]) / (pts[374][1]-pts[386][1] + 1e-6)
        f["gaze_h"], f["gaze_v"] = float((gl+gr)/2), float((vl+vr)/2)
    else:
        f["gaze_h"] = f["gaze_v"] = np.nan
    return f, fb, mb

def _inside(p, b, m=0.0):
    bw, bh = b[2]-b[0], b[3]-b[1]
    return bool(((p[:, 0] >= b[0]-m*bw) & (p[:, 0] <= b[2]+m*bw) &
                 (p[:, 1] >= b[1]-m*bh) & (p[:, 1] <= b[3]+m*bh)).any())

class FaceExtractor:
    def __init__(self):
        self.fm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=f"{MODEL_DIR}/face_landmarker.task"),
            running_mode=vision.RunningMode.IMAGE, num_faces=3,
            min_face_detection_confidence=0.5, min_face_presence_confidence=0.5))
        self.hd = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=f"{MODEL_DIR}/hand_landmarker.task"),
            running_mode=vision.RunningMode.IMAGE, num_hands=2, min_hand_detection_confidence=0.5))
    def close(self): self.fm.close(); self.hd.close()
    def __call__(self, bgr):
        h, w = bgr.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = self.fm.detect(mp_img)
        faces = [face_features(np.array([[p.x*w, p.y*h] for p in lm], dtype=np.float32), w, h)
                 for lm in res.face_landmarks]
        rec = dict(img_w=w, img_h=h, n_faces=len(faces),
                   hand_near_face=False, hand_near_mouth=False, n_hands=0)
        if faces:
            f, fb, mb = max(faces, key=lambda t: t[0]["face_area"])
            rec.update(f)
            hres = self.hd.detect(mp_img)
            if hres.hand_landmarks:
                rec["n_hands"] = len(hres.hand_landmarks)
                hp = np.concatenate([[[p.x*w, p.y*h] for p in hl]
                                     for hl in hres.hand_landmarks]).astype(np.float32)
                rec["hand_near_face"] = _inside(hp, fb, 0.1)
                rec["hand_near_mouth"] = _inside(hp, mb, 0.3)
        return rec
YOLO_MODEL = None
YOLO_CLASS_IDS = COCO_IDS
def _ctr(b): return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

def detect_objects(frame, face_box=None):
    """คืน dict ของจำนวน/ความมั่นใจสูงสุดรายวัตถุ + กรอบทั้งหมดเป็น JSON"""
    out = {"n_person": 0, "phone_face_dist": 9.0}
    for c in OBJ_CANON:
        if c != "person": out[f"{c}_n"] = 0
        out[f"{c}_conf"] = 0.0
    dets = []
    kw = dict(conf=CFG["yolo_min_conf"], imgsz=CFG["yolo_imgsz"], verbose=False)
    if YOLO_CLASS_IDS is not None: kw["classes"] = YOLO_CLASS_IDS
    r = YOLO_MODEL.predict(frame, **kw)[0]
    for b in r.boxes:
        name = ALIAS.get(r.names[int(b.cls[0])]); s = float(b.conf[0])
        if name is None or s < CFG["obj_conf"][name]: continue
        box = [float(v) for v in b.xyxy[0]]
        dets.append([name, round(s, 3)] + [round(v, 1) for v in box])
        out[f"{name}_conf"] = max(out[f"{name}_conf"], s)
        if name == "person": out["n_person"] += 1
        else: out[f"{name}_n"] += 1
        if name in ("phone", "tablet") and face_box is not None:
            (ox, oy), (fx, fy) = _ctr(box), _ctr(face_box)
            fw = max(face_box[2] - face_box[0], 1.0)
            out["phone_face_dist"] = min(out["phone_face_dist"], math.hypot(ox - fx, oy - fy) / fw)
    out["objects_json"] = json.dumps(dets)
    return out

def ensure_obj_cols(df):
    """เติมคอลัมน์วัตถุที่ขาด (กรณีปิด YOLO) เพื่อให้ขั้นตอนถัดไปทำงานได้เสมอ"""
    for c in OBJ_CANON:
        if c != "person" and f"{c}_n" not in df: df[f"{c}_n"] = 0
        if f"{c}_conf" not in df: df[f"{c}_conf"] = 0.0
    if "n_person" not in df: df["n_person"] = 0
    if "phone_face_dist" not in df: df["phone_face_dist"] = 9.0
    if "objects_json" not in df: df["objects_json"] = "[]"
    return df
