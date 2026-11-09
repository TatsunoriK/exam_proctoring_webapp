import test from 'node:test';
import assert from 'node:assert/strict';
import {scrollGeometry} from './scroll-geometry.mjs';
test('thumb length stays fixed as page grows and tracks endpoints',()=>{
 const top=scrollGeometry(900,1800,0),end=scrollGeometry(900,9000,8100);
 assert.equal(top.size,56);assert.equal(end.size,56);assert.equal(top.top,0);assert.equal(end.top,end.travel);
});
test('short page and out of range scroll remain bounded',()=>{
 assert.equal(scrollGeometry(900,500,0).maxScroll,0);
 assert.equal(scrollGeometry(900,1800,-20).top,0);
 const s=scrollGeometry(900,1800,9999);assert.equal(s.top,s.travel);
});
