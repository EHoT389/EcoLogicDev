import test from 'node:test';
import assert from 'node:assert/strict';
import {parseMonitoringThreshold,monitoringSearch} from '../src/monitoringState.ts';

test('monitoring threshold reads finite bounded values from a shared URL',()=>{
 for(const value of ['0.45','.1','0.9'])assert.equal(parseMonitoringThreshold(value),Number(value));
 for(const value of [null,undefined,'',' ','NaN','Infinity','-Infinity','1','0.09','-0.3','hello'])assert.equal(parseMonitoringThreshold(value),.3);
});
test('threshold sync preserves zone and other query parameters, and stabilizes after one update',()=>{
 const search=monitoringSearch('?zone=osm-way-123&context=history',.45);
 const params=new URLSearchParams(search);
 assert.equal(params.get('zone'),'osm-way-123');assert.equal(params.get('context'),'history');assert.equal(params.get('threshold'),'0.45');
 assert.equal(monitoringSearch(search,.45),search);
});
test('switching between a zone and city centre keeps the selected threshold',()=>{
 const zoneSearch=monitoringSearch('?zone=osm-way-old&threshold=0.45',.45,'osm-way-next');
 assert.equal(new URLSearchParams(zoneSearch).get('zone'),'osm-way-next');
 const centreSearch=monitoringSearch(zoneSearch,.45,null);
 assert.equal(new URLSearchParams(centreSearch).get('zone'),null);assert.equal(new URLSearchParams(centreSearch).get('threshold'),'0.45');
 assert.equal(parseMonitoringThreshold(new URLSearchParams(centreSearch).get('threshold')),.45);
});
