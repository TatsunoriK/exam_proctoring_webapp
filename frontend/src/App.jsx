import { useEffect, useMemo, useRef, useState } from "react";
import WebcamCapture from "./WebcamCapture";
import { Activity, ArrowUpRight, BadgeCheck, Braces, Check, ChevronRight, CircleAlert, CloudUpload, FileJson2, Gauge, LoaderCircle, RotateCcw, ShieldCheck, Sparkles, TriangleAlert, X } from "lucide-react";

const labelText = { normal: "ปกติ", suspicious: "น่าสงสัย", cheating: "มีความเสี่ยงสูง" };
const labelStyle = { normal: "text-emerald-700 bg-emerald-50 ring-emerald-200", suspicious: "text-amber-700 bg-amber-50 ring-amber-200", cheating: "text-rose-700 bg-rose-50 ring-rose-200" };

export default function App() {
  const [schema, setSchema] = useState(null);
  const [jsonText, setJsonText] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState("checking");
  const fileRef = useRef(null);

  useEffect(() => {
    Promise.all([fetch("/api/schema").then(r => { if (!r.ok) throw new Error("API unavailable"); return r.json(); }), fetch("/api/health").then(r => r.json())])
      .then(([s]) => { setSchema(s); setApiStatus("online"); })
      .catch(() => setApiStatus("offline"));
  }, []);

  const populated = useMemo(() => {
    try { const p = JSON.parse(jsonText); const f = p.features ?? p; return Object.values(f).filter(v => v !== null && (typeof v === "number" && Number.isFinite(v)) || typeof v === "boolean").length; }
    catch { return 0; }
  }, [jsonText]);

  function downloadTemplate() {
    if (!schema) return;
    const features = Object.fromEntries(schema.features.map(name => [name, null]));
    const blob = new Blob([JSON.stringify({ features }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = "exam-frame-features.template.json"; a.click(); URL.revokeObjectURL(url);
  }

  async function loadFile(event) {
    const file = event.target.files?.[0]; if (!file) return;
    try { setJsonText(await file.text()); setError(""); setResult(null); }
    catch { setError("อ่านไฟล์ไม่สำเร็จ ลองเลือกไฟล์ JSON ใหม่อีกครั้ง"); }
    event.target.value = "";
  }

  async function submit(event) {
    event.preventDefault(); setError(""); setResult(null);
    let body;
    try { body = JSON.parse(jsonText); } catch { setError("รูปแบบ JSON ไม่ถูกต้อง กรุณาตรวจวงเล็บและเครื่องหมายคำพูด"); return; }
    if (!body || typeof body !== "object" || Array.isArray(body)) { setError("ข้อมูลต้องเป็น JSON object"); return; }
    setLoading(true);
    try {
      if (typeof body.image === "string") {
        const extracted = await fetch("/api/extract-frame", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image: body.image }) });
        const extractedData = await extracted.json();
        if (!extracted.ok) throw new Error(extractedData.detail || "สกัด feature จากภาพไม่สำเร็จ");
        body = { features: extractedData.features };
        setJsonText(JSON.stringify(body, null, 2));
      } else if (!body.features) body = { features: body };
      const response = await fetch("/api/predict", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "ทำนายไม่สำเร็จ");
      setResult(data);
    } catch (e) { setError(e.message || "เชื่อมต่อ API ไม่สำเร็จ"); }
    finally { setLoading(false); }
  }

  function clear() { setJsonText(""); setResult(null); setError(""); }

  return <div className="min-h-screen bg-[#f7f8fc] text-slate-800">
    <header className="border-b border-slate-200/80 bg-white/90">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 sm:px-8">
        <div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-200"><ShieldCheck size={21}/></div><div><p className="text-sm font-bold tracking-tight">Exam Vision</p><p className="text-xs text-slate-500">Proctoring model console</p></div></div>
        <div className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${apiStatus === "online" ? "bg-emerald-50 text-emerald-700" : apiStatus === "offline" ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-500"}`}><span className={`h-2 w-2 rounded-full ${apiStatus === "online" ? "bg-emerald-500" : apiStatus === "offline" ? "bg-rose-500" : "bg-slate-400"}`}/>{apiStatus === "online" ? "API พร้อมใช้งาน" : apiStatus === "offline" ? "API ไม่ตอบสนอง" : "กำลังเชื่อมต่อ"}</div>
      </div>
    </header>

    <main className="mx-auto max-w-7xl px-5 py-9 sm:px-8 sm:py-12">
      <div className="mb-8 flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div><div className="mb-3 inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700"><Sparkles size={14}/> ระบบจำแนกพฤติกรรมจาก feature</div><h1 className="max-w-2xl text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">วิเคราะห์เฟรมการสอบ<br className="hidden sm:block"/>ด้วยโมเดลของคุณ</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">ส่งค่า feature ที่สกัดจากภาพให้ API เพื่อรับผลจำแนกและคะแนนความน่าจะเป็น</p></div>
        <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 self-start rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm hover:border-indigo-200 hover:text-indigo-700 md:self-auto">ดู API docs <ArrowUpRight size={16}/></a>
      </div>

      <div className="mb-7 grid gap-3 sm:grid-cols-3">
        {[{icon:Braces,title:"67 frame features",sub:"ตัวเลขและ flag จากระบบสกัด feature"},{icon:Activity,title:"Stratified 80/20",sub:"ประเมินบน label ที่ตรวจด้วยคน"},{icon:Gauge,title:"Random Forest",sub:"3 ระดับ: ปกติ / น่าสงสัย / เสี่ยงสูง"}].map((x,i)=><div key={i} className="flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm"><span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-50 text-indigo-600"><x.icon size={19}/></span><div><p className="text-sm font-bold">{x.title}</p><p className="mt-0.5 text-xs text-slate-500">{x.sub}</p></div></div>)}
      </div>

      <WebcamCapture onExtract={(features, frame) => { setJsonText(JSON.stringify(features ? { features } : frame, null, 2)); setResult(null); setError(""); }} />
      <div className="grid items-start gap-6 lg:grid-cols-[1.05fr_.95fr]">
        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-start justify-between border-b border-slate-100 px-6 py-5"><div><div className="flex items-center gap-2"><span className="grid h-8 w-8 place-items-center rounded-xl bg-indigo-50 text-indigo-600"><FileJson2 size={17}/></span><h2 className="font-bold text-slate-900">ข้อมูล feature</h2></div><p className="mt-2 text-xs text-slate-500">JSON ที่ได้จาก feature extractor ของระบบ</p></div><button onClick={downloadTemplate} disabled={!schema} className="text-xs font-semibold text-indigo-700 hover:text-indigo-900 disabled:opacity-40">ดาวน์โหลด template</button></div>
          <form onSubmit={submit} className="p-6">
            <button type="button" onClick={() => fileRef.current?.click()} className="group flex w-full flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 px-5 py-6 text-center transition hover:border-indigo-400 hover:bg-indigo-50/40"><span className="mb-2 grid h-11 w-11 place-items-center rounded-2xl bg-white text-indigo-600 shadow-sm group-hover:bg-indigo-100"><CloudUpload size={21}/></span><span className="text-sm font-bold text-slate-800">เลือกไฟล์ JSON</span><span className="mt-1 text-xs text-slate-500">หรือวางข้อมูล JSON ในช่องด้านล่าง</span></button>
            <input ref={fileRef} className="hidden" type="file" accept=".json,application/json" onChange={loadFile}/>
            <div className="mt-5 flex items-center justify-between"><label htmlFor="features" className="text-xs font-bold uppercase tracking-wider text-slate-500">Feature payload</label><span className="text-xs tabular-nums text-slate-500">{populated}{schema ? ` / ${schema.required_feature_count}` : ""} ค่า</span></div>
            <textarea id="features" value={jsonText} onChange={e=>{setJsonText(e.target.value);setResult(null);setError("");}} spellCheck="false" placeholder={"{\n  \"features\": {\n    \"n_faces\": 1,\n    \"n_person\": 0,\n    \"...\": \"กรอก feature ให้ครบ 67 ค่า\"\n  }\n}"} className="mt-2 min-h-[290px] w-full resize-y rounded-2xl border border-slate-200 bg-slate-950 p-4 font-mono text-xs leading-5 text-emerald-200 outline-none placeholder:text-slate-600 focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100"/>
            {error && <div className="mt-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"><CircleAlert size={17} className="mt-0.5 shrink-0"/><span>{error}</span></div>}
            <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row"><button type="button" onClick={clear} className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-600 hover:bg-slate-50"><RotateCcw size={16}/>ล้างข้อมูล</button><button disabled={loading || apiStatus !== "online"} className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-bold text-white shadow-md shadow-indigo-200 transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">{loading ? <><LoaderCircle size={17} className="animate-spin"/>กำลังประมวลผล</> : <><Sparkles size={17}/>ทำนายผล<ChevronRight size={17}/></>}</button></div>
            <p className="mt-4 text-[11px] leading-5 text-slate-400">ระบบต้องใช้ feature ที่สกัดแล้ว ไม่สามารถวิเคราะห์ไฟล์ภาพหรือวิดีโอโดยตรงได้</p>
          </form>
        </section>

        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-6 py-5"><div className="flex items-center gap-2"><span className="grid h-8 w-8 place-items-center rounded-xl bg-emerald-50 text-emerald-600"><BadgeCheck size={17}/></span><h2 className="font-bold text-slate-900">ผลการทำนาย</h2></div><p className="mt-2 text-xs text-slate-500">คำทำนายจากโมเดลและคะแนนแต่ละคลาส</p></div>
          {!result ? <div className="flex min-h-[440px] flex-col items-center justify-center px-8 py-12 text-center"><div className="mb-4 grid h-16 w-16 place-items-center rounded-3xl bg-slate-50 text-slate-300"><Activity size={28}/></div><p className="text-sm font-semibold text-slate-600">ยังไม่มีผลลัพธ์</p><p className="mt-1 max-w-xs text-xs leading-5 text-slate-400">อัปโหลด feature JSON แล้วกด “ทำนายผล” เพื่อดูผลจากโมเดล</p><div className="mt-7 flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-left text-[11px] leading-5 text-amber-800"><TriangleAlert size={15} className="shrink-0"/>เป็นเครื่องมือช่วยคัดกรอง ไม่ใช่ข้อสรุปการทุจริต</div></div> : <div className="p-6"><div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-5"><div className="flex items-center justify-between"><span className="text-xs font-bold uppercase tracking-wider text-slate-500">ผลประเมิน</span><span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700"><Check size={14}/>สำเร็จ</span></div><div className="mt-3 flex items-end justify-between gap-3"><div><p className="text-xs text-slate-500">โมเดลจัดอยู่ในกลุ่ม</p><span className={`mt-2 inline-flex rounded-full px-3 py-1.5 text-sm font-bold ring-1 ring-inset ${labelStyle[result.prediction] || "bg-slate-100 text-slate-700"}`}>{labelText[result.prediction] || result.prediction}</span></div><span className="text-3xl font-bold tabular-nums text-slate-900">{Math.round((result.probabilities[result.prediction] || 0)*100)}<small className="text-lg">%</small></span></div></div>
            <div className="mt-6"><div className="mb-3 flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">ความน่าจะเป็นรายคลาส</h3><span className="text-[11px] text-slate-400">รวม 100%</span></div><div className="space-y-4">{["normal","suspicious","cheating"].map(k=><div key={k}><div className="mb-1.5 flex justify-between text-xs"><span className="font-semibold text-slate-700">{labelText[k]}</span><span className="tabular-nums text-slate-500">{((result.probabilities[k]||0)*100).toFixed(1)}%</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full transition-all duration-700 ${k==="normal"?"bg-emerald-500":k==="suspicious"?"bg-amber-400":"bg-rose-500"}`} style={{width:`${(result.probabilities[k]||0)*100}%`}}/></div></div>)}</div></div>
            <div className="mt-6 flex items-start gap-2 rounded-xl border border-indigo-100 bg-indigo-50/70 px-4 py-3 text-xs leading-5 text-indigo-800"><Activity size={15} className="mt-0.5 shrink-0"/><span>ใช้ {result.provided_feature_count} ค่า และแทนค่า {result.imputed_feature_count} ค่าที่ว่างด้วยค่ามัธยฐานจากชุดฝึก</span></div>
            <p className="mt-4 text-[11px] leading-5 text-slate-400">คะแนนสะท้อนรูปแบบที่โมเดลเรียนรู้จากข้อมูล label ที่ตรวจเอง ควรให้ผู้ดูแลตรวจสอบก่อนดำเนินการใด ๆ</p>
          </div>}
        </section>
      </div>
      <footer className="mt-8 flex flex-col justify-between gap-2 border-t border-slate-200 pt-5 text-[11px] leading-5 text-slate-400 sm:flex-row"><span>Exam Vision · Local model interface</span><span>โมเดลรองรับเฉพาะ feature vector ตาม schema ที่กำหนด</span></footer>
    </main>
  </div>;
}
