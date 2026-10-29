import test from 'node:test';
import assert from 'node:assert/strict';
import {wizardInput,settingsFor,sameCalculation} from '../src/wizardModel.ts';
import {inputForZone,zoneAddress,zoneOption} from '../src/zoneModel.ts';
import {localizeText} from '../src/localize.ts';
const zone={id:'osm-way-1',ru:'Участок 1',kk:'Аумақ 1',status:'planting_candidate',address_ru:'улица Лермонтова',address_kk:'Лермонтов көшесі',geometry:{type:'Polygon',coordinates:[]},soil:'sand',moisture:.3,salinity:.2,traffic:.4,temperature:-38,light:'sun',assessment_provenance:'synthetic'};
test('wizard preserves site data, enforces purpose, and explicitly replaces manual planting on generation',()=>{
 const previous={...inputForZone(zone,null,false),budget:0,plants:[{id:'pine',count:4}]};
 const settings={...settingsFor(previous),goal:'children'};
 const next=wizardInput(previous,settings);
 assert.equal(next.budget,0);assert.equal(next.site.soil,'sand');assert.equal(next.site.provenance,'synthetic');assert.equal(next.site.purpose,'children');assert.equal(next.plants,null);assert.equal(previous.plants[0].count,4);assert.equal(previous.site.purpose,'public');assert.equal(next.geometry,previous.geometry);
 assert.throws(()=>wizardInput(previous,{...settings,budget:NaN}));assert.throws(()=>wizardInput(previous,{...settings,years:4}));
});
test('street landmarks remain separate from personal names and are shown in zone selection',()=>{assert.equal(zoneAddress(zone,true),'Лермонтов көшесі');assert.match(zoneOption({...zone,kk:'Менің аулам'},true),/Менің аулам · Лермонтов көшесі/);assert.equal(zoneAddress({...zone,address_kk:undefined},true),'')});
test('saved calculations translate when language changes, and unknown text remains intact',()=>{const ru='Смета превышает заданный бюджет.';const kk=localizeText(ru,true);assert.equal(kk,'Смета белгіленген бюджеттен асады.');assert.equal(localizeText(kk,false),ru);assert.equal(localizeText('Жасыл аула №7',true),'Жасыл аула №7')});
test('renaming and language changes keep wizard result; changed budget or plants invalidate it',()=>{const input=inputForZone(zone,null,false);assert.equal(sameCalculation(input,{...input,zone_name:'Жасыл аула'}),true);assert.equal(sameCalculation(input,{...input,budget:0}),false);assert.equal(sameCalculation(input,{...input,plants:[{id:'pine',count:1}]}),false)});
