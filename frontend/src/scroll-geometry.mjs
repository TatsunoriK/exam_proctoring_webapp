export function scrollGeometry(viewport, content, scroll, thumb=56) {
 const maxScroll=Math.max(0,content-viewport);
 const track=Math.max(0,viewport-16);
 const size=Math.min(thumb,track);
 const travel=Math.max(0,track-size);
 return {maxScroll,size,travel,top:maxScroll?Math.min(1,Math.max(0,scroll/maxScroll))*travel:0};
}
