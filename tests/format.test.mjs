import test from 'node:test';
import assert from 'node:assert/strict';
import {monthName} from '../src/format.ts';
test('Kazakh care calendar has month names even without browser locale data',()=>{assert.equal(monthName(1,true),'қаңтар');assert.equal(monthName(10,true),'қазан');assert.equal(monthName(12,false),'декабрь')});
