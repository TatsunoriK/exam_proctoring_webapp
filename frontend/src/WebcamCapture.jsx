import { useEffect, useRef, useState } from "react";
import { apiUrl } from "./api";

export default function WebcamCapture({ onExtract }) {
  const video = useRef(null);
  const stream = useRef(null);
  const starting = useRef(false);
  const mounted = useRef(true);
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [frame, setFrame] = useState(null);
  const [error, setError] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [label, setLabel] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [details, setDetails] = useState("");
  const [consent, setConsent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("");

  function stop() {
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setActive(false);
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stream.current?.getTracks().forEach(track => track.stop());
      stream.current = null;
    };
  }, []);

  async function start() {
    if (starting.current) return;
    starting.current = true;
    setBusy(true);
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("เบราว์เซอร์ไม่รองรับกล้อง หรือหน้านี้ไม่ได้เปิดผ่าน localhost/HTTPS");
      const media = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      if (!mounted.current) { media.getTracks().forEach(track => track.stop()); return; }
      stream.current = media;
      video.current.srcObject = media;
      await video.current.play();
      setActive(true);
    } catch (e) {
      stream.current?.getTracks().forEach(track => track.stop());
      stream.current = null;
      if (mounted.current) setError(e.name === "NotAllowedError" ? "ไม่ได้รับอนุญาตให้ใช้กล้อง กรุณาอนุญาตในเบราว์เซอร์" : e.message || "เปิดกล้องไม่สำเร็จ");
    } finally {
      starting.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function capture() {
    const source = video.current;
    if (!source?.videoWidth || !source.videoHeight) { setError("กล้องยังไม่พร้อม กรุณาลองอีกครั้ง"); return; }
    const canvas = document.createElement("canvas");
    canvas.width = source.videoWidth;
    canvas.height = source.videoHeight;
    canvas.getContext("2d").drawImage(source, 0, 0);
    const captured = { captured_at: new Date().toISOString(), width: canvas.width, height: canvas.height, image: canvas.toDataURL("image/jpeg", 0.8) };
    setFrame(captured);
    setSaved("");
    setLabel("");
    setConsent(false);
    onExtract(null, captured);
    setError("");
    setExtracting(true);
    try {
      const response = await fetch(apiUrl("/api/extract-frame"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image: captured.image }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "สกัด feature ไม่สำเร็จ");
      onExtract(data.features, captured);
    } catch (e) { setError(e.message || "เชื่อมต่อ API ไม่สำเร็จ"); }
    finally { setExtracting(false); }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(frame, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "webcam-frame.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function saveSample() {
    if (!frame || !label || !sessionId.trim() || !consent) return;
    setSaving(true); setError(""); setSaved("");
    try {
      const response = await fetch(apiUrl("/api/dataset"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image: frame.image, captured_at: frame.captured_at, label, session_id: sessionId.trim(), details, consent }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "บันทึกไม่สำเร็จ");
      setSaved(`บันทึกแล้ว รหัส ${data.id}`);
    } catch (e) { setError(e.message || "บันทึกไม่สำเร็จ"); }
    finally { setSaving(false); }
  }

  return <section className="mb-7 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
    <h2 className="font-bold text-slate-900">เว็บแคม</h2>
    <p className="mt-2 text-sm text-slate-600">เปิดกล้องและส่งภาพที่จับไปยัง backend เพื่อสกัด feature</p>
    <video ref={video} muted playsInline className="mt-4 aspect-video w-full max-w-xl rounded-2xl bg-slate-950 object-contain" />
    <div className="mt-4 flex flex-wrap gap-2">
      {!active ? <button type="button" disabled={busy} onClick={start} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{busy ? "กำลังเปิดกล้อง..." : "เปิดกล้อง"}</button> : <><button type="button" disabled={extracting} onClick={capture} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{extracting ? "กำลังสกัด feature..." : "จับภาพและสกัด feature"}</button><button type="button" onClick={stop} className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold">ปิดกล้อง</button></>}
      {frame && <><button type="button" onClick={download} className="rounded-xl border border-indigo-200 px-4 py-2 text-sm font-semibold text-indigo-700">ดาวน์โหลด JSON</button><button type="button" onClick={() => setFrame(null)} className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold">ลบภาพที่จับ</button></>}
    </div>
    {frame && <p className="mt-3 text-xs text-slate-600">จับภาพแล้ว {frame.width} × {frame.height} พิกเซล เวลา {new Date(frame.captured_at).toLocaleString()}</p>}
    {frame && <div className="mt-5 max-w-xl rounded-2xl border border-slate-200 p-4">
      <h3 className="font-bold">เพิ่มภาพลงชุดข้อมูล</h3>
      <p className="mt-1 text-xs text-slate-500">ตรวจภาพและเลือก label ด้วยตนเอง ระบบจะบันทึกภาพและ feature ใน MongoDB เพื่อใช้ฝึกภายหลัง</p>
      <img src={frame.image} alt="ภาพที่จับสำหรับตรวจสอบก่อนบันทึก" className="mt-3 max-h-48 rounded-xl" />
      <label className="mt-3 block text-sm">Label <select value={label} onChange={e => setLabel(e.target.value)} className="ml-2 rounded border border-slate-300 p-2"><option value="">เลือก label</option><option value="normal">ปกติ</option><option value="suspicious">น่าสงสัย</option><option value="cheating">มีความเสี่ยงสูง</option></select></label>
      <label className="mt-3 block text-sm">รหัสรอบบันทึก <input value={sessionId} onChange={e => setSessionId(e.target.value)} maxLength={100} placeholder="เช่น session-01" className="ml-2 rounded border border-slate-300 p-2" /></label>
      <label className="mt-3 block text-sm">รายละเอียดเหตุการณ์ (ไม่บังคับ) <input value={details} onChange={e => setDetails(e.target.value)} maxLength={500} className="mt-1 w-full rounded border border-slate-300 p-2" /></label>
      <label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />ได้รับความยินยอมให้เก็บภาพนี้เพื่อสร้างชุดข้อมูลแล้ว</label>
      <button type="button" onClick={saveSample} disabled={saving || extracting || !!saved || !label || !sessionId.trim() || !consent} className="mt-3 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{saving ? "กำลังบันทึก..." : "บันทึกลงชุดข้อมูล"}</button>
      {saved && <p role="status" className="mt-2 text-sm text-emerald-700">{saved}</p>}
    </div>}
    {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
    <p className="mt-4 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-900">ภาพที่จับส่งไปยัง backend เพื่อสกัด feature จากนั้นกด “ทำนายผล” ด้านล่าง ค่า flag การหันหน้าใช้ค่ากลางของชุดข้อมูล ส่วนการพูดต้องใช้หลายเฟรมจึงแทนด้วยค่า null ผลจึงเป็นการประมาณและต้องตรวจสอบโดยผู้ดูแล</p>
  </section>;
}
