// Outer dimensions avoid treating page zoom, browser chrome, or docked devtools as split view.
export function reducedExamWindow({width,height,availableWidth,availableHeight}) {
 if (![width,height,availableWidth,availableHeight].every(n=>Number.isFinite(n)&&n>0)) return false;
 return width/availableWidth<0.85 || height/availableHeight<0.80;
}
