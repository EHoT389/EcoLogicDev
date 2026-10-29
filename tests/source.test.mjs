import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import path from 'node:path';
function files(dir){return readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(dir,e.name)):[path.join(dir,e.name)])}
test('browser source contains no OpenRouter secret or direct cloud chat requests',()=>{
 for(const file of files('src')){const content=readFileSync(file,'utf8');assert.ok(!/sk-or-v1-[a-z0-9]{30}/i.test(content),file);assert.ok(!content.includes('openrouter.ai/api/v1/chat/completions'),file)}
});
test('required publication and source documentation exists',()=>{for(const file of ['DATA_SOURCES.md','DECISIONS.md','PROGRESS.md','README.md','render.yaml','vercel.json'])assert.ok(readFileSync(file,'utf8').length>10)});
