import test from 'node:test';
import assert from 'node:assert/strict';
import {decisionActionTarget,boundedGuestHistory} from '../src/decisionModel.ts';

test('AI map actions use a fixed enum and preserve canonical zone and threshold',()=>{
 const target=decisionActionTarget('show_losses','osm-way-12',.42);
 const query=new URLSearchParams(target.split('?')[1]);
 assert.equal(query.get('zone'),'osm-way-12');assert.equal(query.get('threshold'),'0.42');
 assert.equal(query.get('change_filter'),'loss');assert.equal(query.get('mode'),'changes');
 assert.equal(decisionActionTarget('javascript:alert(1)','osm-way-12',.3),null);
 assert.equal(new URLSearchParams(decisionActionTarget('compare_years','z',.3).split('?')[1]).get('compare'),'1');
});
test('guest conversation context excludes system/error roles and remains bounded',()=>{
 const turns=boundedGuestHistory([{role:'system',text:'untrusted'},...Array.from({length:12},(_,i)=>({role:i%2?'assistant':'user',text:'x'.repeat(5000)})),{role:'error',text:'offline'}]);
 assert.equal(turns.length,8);assert.ok(turns.every(turn=>turn.text.length===2000));
 assert.ok(turns.every(turn=>['user','assistant'].includes(turn.role)));
});
