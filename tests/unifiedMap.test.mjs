import test from 'node:test';
import assert from 'node:assert/strict';
import {parseUnifiedMapState,unifiedMapSearch,legacyUnifiedLocation} from '../src/unifiedMapModel.ts';
test('unified modes retain zone, unrelated project and threshold query state',()=>{
 const search=unifiedMapSearch('?zone=osm-way-12&threshold=.45&project=demo',{mode:'planning'});
 const query=new URLSearchParams(search);assert.equal(query.get('zone'),'osm-way-12');assert.equal(query.get('project'),'demo');assert.equal(parseUnifiedMapState(search).threshold,.45);assert.equal(parseUnifiedMapState(search).mode,'planning');
});
test('unified URL validates raster controls without changing project inputs',()=>{
 const state=parseUnifiedMapState('?mode=invalid&year=1900&threshold=NaN&opacity=3&swipe=-10&layer=secret&compare=1');
 assert.deepEqual(state,{mode:'territories',year:'2026',threshold:.3,compare:true,layer:'vegetation',opacity:1,swipe:0,scope:'zone'});
});
test('city analysis scope keeps the selected project zone in the URL',()=>{
 const search=unifiedMapSearch('?zone=osm-way-12&mode=changes&threshold=.45',{scope:'city'});
 assert.equal(new URLSearchParams(search).get('zone'),'osm-way-12');assert.equal(parseUnifiedMapState(search).scope,'city');
 const back=unifiedMapSearch(search,{scope:'zone'});assert.equal(parseUnifiedMapState(back).scope,'zone');assert.equal(new URLSearchParams(back).get('zone'),'osm-way-12');
});
test('legacy monitoring and priority links preserve selected zone and source params',()=>{
 const target=legacyUnifiedLocation('/monitoring','?zone=osm-way-1&threshold=.5');assert.match(target,/^\/map\?/);assert.equal(new URLSearchParams(target.split('?')[1]).get('zone'),'osm-way-1');assert.equal(parseUnifiedMapState(target.split('?')[1]).mode,'changes');assert.equal(legacyUnifiedLocation('/assistant',''),null);
 assert.equal(new URLSearchParams(unifiedMapSearch('?zone=one&mode=changes',{zone:null})).has('zone'),false);
});
