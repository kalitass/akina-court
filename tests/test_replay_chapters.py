"""Exercise the page's chapter controller against hearing records and navigation races."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is needed to exercise the replay controller")

HARNESS = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('web/replay.js', 'utf8');
function controller() {
  const sections = [], handlers = {}, writes = [];
  const buttons = [1,2,3,4].map(n => ({dataset:{stage:String(n)},disabled:true,
    classList:{toggle(key,on){if(on) writes.push(n);}},setAttribute(){},removeAttribute(){}}));
  const sectionQuery = selector => {
    const match = selector.match(/data-stage="(\d+)"/);
    return match ? sections.filter(s=>s.dataset.stage===match[1]) : sections;
  };
  const courtEl = {scrollTop:0,scrollHeight:1000,get lastElementChild(){return sections.at(-1);},
    appendChild(s){sections.push(s);},querySelectorAll:sectionQuery,
    getBoundingClientRect:()=>({top:0}),scrollTo(){},addEventListener:(name,fn)=>handlers[name]=fn};
  const document = {querySelectorAll:()=>buttons,querySelector(selector){return buttons[+selector.match(/data-stage="(\d+)"/)[1]-1];}};
  function el(tag, cls, html) {const children=[];return {dataset:{},children,style:{setProperty(){}},
    getBoundingClientRect:()=>({top:100}),querySelector:()=>({appendChild(node){children.push(node);}})};}
  const ctx = {document,courtEl,el,clearTimeout,setTimeout}; vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('let hearingStage = 1'),source.indexOf('\nfunction courtStep(){')),ctx);
  return {ctx,sections,handlers,buttons,writes,add(e,id){ctx.event=e;ctx.node={id,prepend(){}};vm.runInContext('appendChapter(node,event)',ctx);},
    active(){return vm.runInContext('activeHearingStage',ctx);}};
}
"""


def run_js(body):
    subprocess.run([NODE, "-e", HARNESS + body], cwd=ROOT, check=True, capture_output=True, text=True)


def test_stored_hearings_keep_every_event_in_order():
    run_js(r"""
let checked=0;
for(const file of fs.readdirSync('runs').filter(n=>n.endsWith('.json'))) {
  const record=JSON.parse(fs.readFileSync('runs/'+file,'utf8'));
  if(!Array.isArray(record.events)) continue;
  const c=controller(); record.events.forEach((e,i)=>c.add(e,i));
  assert.deepEqual(c.sections.flatMap(s=>s.children.map(n=>n.id)),record.events.map((_,i)=>i),file);
  assert(c.sections.every(s=>[1,2,3,4].includes(+s.dataset.stage)),file); checked++;
}
assert(checked>=15);
const safety=controller();
[{kind:'intake'},{kind:'facts'},{kind:'escalate'},{kind:'notify'}].forEach((e,i)=>safety.add(e,i));
assert.deepEqual(safety.sections.map(s=>+s.dataset.stage),[1,4]);
assert(safety.buttons[1].disabled && safety.buttons[2].disabled);
""")


def test_scroll_cannot_override_playback_or_manual_selection():
    run_js(r"""
const c=controller();
c.add({kind:'ruling'},0);c.add({kind:'check',title:'Ruling verification'},1);
assert.equal(c.active(),4); const before=c.writes.length;
c.handlers.scroll();assert.equal(c.active(),4);
c.add({kind:'notify'},2);assert.equal(c.writes.length,before);
c.buttons[2].onclick();assert.equal(c.active(),3);
c.add({kind:'notify'},3);assert.equal(c.active(),3);c.handlers.scroll();assert.equal(c.active(),3);
vm.runInContext('resumeHearingFollow()',c.ctx);assert.equal(c.active(),4);
""")


def test_returned_ruling_stays_after_failed_verification():
    run_js(r"""
const c=controller();
[{kind:'ruling'},{kind:'check',title:'Ruling verification failed'},
 {kind:'check',title:'Ruling citation check failed — returned to judge for correction'},
 {kind:'ruling'},{kind:'check',title:'Ruling verification passed'},{kind:'notify'}].forEach((e,i)=>c.add(e,i));
assert.deepEqual(c.sections.map(s=>+s.dataset.stage),[3,4,3,4]);
assert.deepEqual(c.sections.flatMap(s=>s.children.map(n=>n.id)),[0,1,2,3,4,5]);
assert.equal(new Set(c.sections.map(s=>s.id)).size,c.sections.length);
""")
