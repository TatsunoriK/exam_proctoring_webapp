import test from 'node:test';
import assert from 'node:assert/strict';
import {reducedExamWindow} from './window-check.mjs';
const display={availableWidth:1440,availableHeight:900};
test('detects side-by-side and stacked windows',()=>{
 assert.equal(reducedExamWindow({...display,width:720,height:900}),true);
 assert.equal(reducedExamWindow({...display,width:1440,height:450}),true);
});
test('allows normal desktop margins and ignores unavailable dimensions',()=>{
 assert.equal(reducedExamWindow({...display,width:1400,height:850}),false);
 assert.equal(reducedExamWindow({...display,width:0,height:900}),false);
 assert.equal(reducedExamWindow({...display,width:1440,height:900}),false);
});
