import test from 'node:test';
import assert from 'node:assert/strict';
import {examAvailability} from './exam-availability.mjs';
test('scheduled window and manual closure determine actual availability',()=>{
 const exam={opensAt:100,closesAt:200};
 assert.equal(examAvailability(exam,99),'scheduled');
 assert.equal(examAvailability(exam,100),'open');
 assert.equal(examAvailability(exam,199),'open');
 assert.equal(examAvailability(exam,200),'expired');
 assert.equal(examAvailability({...exam,acceptingAttempts:false},150),'closed');
 assert.equal(examAvailability({...exam,acceptingAttempts:true},201),'expired');
 assert.equal(examAvailability({...exam,acceptingAttempts:false},201),'expired');
 assert.equal(examAvailability({},150),'open');
});
