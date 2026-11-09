import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewSummary} from './review-summary.mjs';
test('clip ratio excludes incomplete analysis and counts observations once per clip', () => {
 const flag = {label:'cheating', observations:['no_face']};
 const s = reviewSummary({proctoringEvents:[{status:'analyzed',reviewFlags:[flag,flag]},{status:'analyzed',reviewFlags:[]},{status:'processing'},{status:'analysis_failed'}]});
 assert.equal(s.percent,50); assert.equal(s.high,1); assert.equal(s.processing,1); assert.equal(s.unavailable,1);
 assert.deepEqual(s.observations,[['no_face',1]]);
});
test('missing camera data is unknown, while browser events still request review', () => {
 const s = reviewSummary({deviceMode:'mobile',events:[{type:'blur'}]});
 assert.equal(s.percent,null); assert.equal(s.priority,'medium');
});
test('review status affects remaining work without hiding original signals', () => {
 const s = reviewSummary({cameraRecordings:['a','b'],reviews:{a:{status:'reviewed'},b:{status:'needs_followup'}},proctoringEvents:[{status:'analyzed',reviewFlags:[]}]});
 assert.equal(s.pending,1); assert.equal(s.percent,0);
});
test('observation drilldown selects matching times and validates recording indices', async () => {
 const {observationClips} = await import('./review-summary.mjs');
 const flag = {observations:['object_phone'],time_s:3};
 const clips = observationClips({cameraRecordings:['a'],proctoringEvents:[
  {status:'analyzed',segment:0,reviewFlags:[flag,{observations:['no_face'],time_s:5}]},
  {status:'analyzed',segment:-1,reviewFlags:[flag]},
  {status:'processing',segment:0,reviewFlags:[flag]}
 ]},'object_phone');
 assert.equal(clips.length,2); assert.equal(clips[0].flags.length,1);
 assert.equal(clips[0].playable,true); assert.equal(clips[1].playable,false);
});
test('legacy event mapping estimates 15-second ranges without clamping missing clips', async()=>{
 const {eventScreenClips}=await import('./review-summary.mjs');
 const attempt={started:1000,recordings:['a','b','c']};
 assert.equal(eventScreenClips(attempt,43000)[0].index,2);
 assert.equal(eventScreenClips(attempt,43000)[0].estimated,true);
 assert.deepEqual(eventScreenClips(attempt,60000),[]);
 assert.deepEqual(eventScreenClips({...attempt,recordingTimings:[{id:'a',start:1000,end:2000}]},43000),[]);
 assert.equal(eventScreenClips({...attempt,recordingTimings:[{id:'c',start:42000,end:45000}]},43000)[0].estimated,false);
});
