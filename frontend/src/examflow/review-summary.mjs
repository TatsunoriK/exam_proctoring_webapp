// Review coverage is a clip ratio, never a probability of misconduct.
export function reviewSummary(attempt) {
  const events = attempt.proctoringEvents || [];
  const analyzed = events.filter(e => e.status === 'analyzed');
  const flagged = analyzed.filter(e => e.reviewFlags?.length);
  const high = flagged.filter(e => e.reviewFlags.some(f => f.label === 'cheating')).length;
  const observations = {};
  for (const event of flagged) {
    const codes = new Set(event.reviewFlags.flatMap(f => f.observations || []));
    for (const code of codes) observations[code] = (observations[code] || 0) + 1;
  }
  const percent = analyzed.length ? Math.round(flagged.length / analyzed.length * 100) : null;
  const processing = events.filter(e => e.status === 'processing').length;
  const unavailable = events.length - analyzed.length - processing;
  const browserEvents = attempt.events?.length || 0;
  const priority = high || (percent !== null && percent >= 50) ? 'high' : flagged.length || browserEvents ? 'medium' : 'low';
  return {analyzed: analyzed.length, flagged: flagged.length, high, percent, processing, unavailable, browserEvents, priority,
    observations: Object.entries(observations).sort((a, b) => b[1] - a[1]),
    pending: (attempt.cameraRecordings || []).filter(id => !['reviewed','normal','misconduct'].includes(attempt.reviews?.[id]?.status)).length};
}

export function observationClips(attempt, code) {
  return (attempt.proctoringEvents || []).flatMap((event, index) => {
    if (event.status !== 'analyzed') return [];
    const flags = (event.reviewFlags || []).filter(flag => flag.observations?.includes(code));
    if (!flags.length) return [];
    const segment = event.segment;
    const playable = Number.isInteger(segment) && segment >= 0 && segment < (attempt.cameraRecordings || []).length;
    return [{index, segment, playable, flags}];
  });
}

export function eventScreenClips(attempt, time) {
 const recordings=attempt.recordings||[];
 const timings=attempt.recordingTimings||[];
 const exact=timings.filter(t=>t.start<=time&&time<=t.end)
   .map(t=>({...t,index:recordings.indexOf(t.id),estimated:false})).filter(t=>t.index>=0);
 if(exact.length||timings.length)return exact;
 // Legacy recordings rotated every 15 seconds. Gaps/restarts can shift this estimate.
 const elapsed=time-attempt.started;
 if(!Number.isFinite(elapsed)||elapsed<0)return [];
 const index=Math.floor(elapsed/15000);
 if(index>=recordings.length)return [];
 return [{index,start:attempt.started+index*15000,end:attempt.started+(index+1)*15000,estimated:true}];
}
