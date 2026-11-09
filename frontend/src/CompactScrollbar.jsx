import {useEffect,useRef,useState} from 'react';
import {scrollGeometry} from './scroll-geometry.mjs';
import './compact-scrollbar.css';

export default function CompactScrollbar(){
 const [metrics,setMetrics]=useState({maxScroll:0,size:56,travel:0,top:0});
 const drag=useRef(null);
 useEffect(()=>{
  let frame=0;
  const measure=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{
   const page=document.scrollingElement;
   setMetrics(scrollGeometry(window.innerHeight,page.scrollHeight,window.scrollY));
  })};
  document.documentElement.classList.add('compact-page-scroll');
  const observer=new ResizeObserver(measure);observer.observe(document.body);
  window.addEventListener('scroll',measure,{passive:true});window.addEventListener('resize',measure);measure();
  return()=>{observer.disconnect();cancelAnimationFrame(frame);window.removeEventListener('scroll',measure);window.removeEventListener('resize',measure);document.documentElement.classList.remove('compact-page-scroll')};
 },[]);
 if(!metrics.maxScroll)return null;
 const scrollToTop=top=>window.scrollTo({top:metrics.travel?Math.max(0,Math.min(metrics.travel,top))/metrics.travel*metrics.maxScroll:0,behavior:'instant'});
 return <div className="compact-page-track" onPointerDown={e=>{if(e.target!==e.currentTarget)return;scrollToTop(e.clientY-8-metrics.size/2)}}>
  <div className="compact-page-thumb" role="scrollbar" aria-label="เลื่อนหน้า" aria-orientation="vertical" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(metrics.travel?metrics.top/metrics.travel*100:0)} tabIndex={0} style={{height:metrics.size,transform:`translateY(${metrics.top}px)`}}
   onPointerDown={e=>{e.preventDefault();drag.current={y:e.clientY,top:metrics.top};e.currentTarget.setPointerCapture(e.pointerId)}}
   onPointerMove={e=>{if(drag.current)scrollToTop(drag.current.top+e.clientY-drag.current.y)}}
   onPointerUp={e=>{drag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId)}}
   onPointerCancel={()=>{drag.current=null}}
   onLostPointerCapture={()=>{drag.current=null}}
   onKeyDown={e=>{const actions={ArrowDown:window.scrollY+40,ArrowUp:window.scrollY-40,PageDown:window.scrollY+window.innerHeight*.9,PageUp:window.scrollY-window.innerHeight*.9,Home:0,End:metrics.maxScroll};if(e.key in actions){e.preventDefault();window.scrollTo({top:actions[e.key],behavior:'instant'})}}}/>
 </div>;
}
