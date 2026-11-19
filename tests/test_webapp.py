"""Regression coverage for the real inline JS new-game request lifecycle."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_start_game_reports_failures_preserves_tiles_and_can_retry():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the frontend regression")
    html = Path(__file__).resolve().parents[1] / "src" / "webapp" / "index.html"
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8')
  .match(/<script>([\s\S]*)<\/script>/)[1]
  .replace(/\nrefresh\(\);\s*$/, '\n');
const hand = ['1万','1万','2万','5万','7万','2饼','3饼','5饼','6饼','6饼','1条','4条','西风'];
function setup(fetch) {
  const removed = [];
  const elements = new Map();
  const context = vm.createContext({
    location: {protocol:'http:'}, AbortController, setTimeout, clearTimeout,
    console: {error() {}}, fetch,
    document: {getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        disabled:false, hidden:true, textContent:'',
        classList:{remove(name){removed.push([id,name])}}
      });
      return elements.get(id);
    }}
  });
  vm.runInContext(source, context);
  vm.runInContext(`draftHand=${JSON.stringify(hand)};render=()=>{}`, context);
  return {context, elements, removed, run:()=>vm.runInContext('startGame()',context)};
}
const response = data=>({ok:true,status:200,json:async()=>data});
const success = path=>response(path==='/api/state'
  ? {ok:true,state:{hand},flow:{},analysis:{}}
  : {ok:true,pending:null,peng:false,chi:[],ron:false});
(async()=>{
  let calls = [];
  const failed = setup(async(path)=>{calls.push(path);throw new TypeError('offline')});
  await failed.run();
  assert.match(failed.elements.get('newGameError').textContent,/无法连接本机服务/);
  assert.equal(failed.elements.get('newGameError').hidden,false);
  assert.equal(failed.elements.get('startGameBtn').disabled,false);
  assert.equal(vm.runInContext('draftHand.length',failed.context),13);
  assert.equal(failed.removed.length,0);
  failed.context.fetch = async path=>{calls.push(path);return success(path)};
  await failed.run();
  assert.deepEqual(failed.removed,[['newOverlay','show']]);
  assert.equal(failed.elements.get('newGameError').hidden,true);

  const invalid = setup(async()=>({ok:false,status:500,json:async()=>{throw Error('html')}}));
  await invalid.run();
  assert.match(invalid.elements.get('newGameError').textContent,/HTTP 500/);
  assert.equal(invalid.elements.get('startGameBtn').disabled,false);

  let postCount = 0;
  const duplicate = setup(async path=>{if(path==='/api/new')postCount++;return success(path)});
  const first = duplicate.run();
  assert.equal(duplicate.elements.get('startGameBtn').disabled,true);
  await Promise.all([first,duplicate.run()]);
  assert.equal(postCount,1);
  assert.equal(duplicate.elements.get('startGameBtn').textContent,'开始对局');

  const stateFailure = setup(async path=>path==='/api/state'
    ? response({ok:false,error:'state unavailable'}) : success(path));
  stateFailure.context.openNewGame = ()=>{};
  await stateFailure.run();
  assert.match(stateFailure.elements.get('newGameError').textContent,/局面加载失败/);
  assert.equal(stateFailure.removed.length,0);

  const filePage = setup(async()=>{throw Error('must not fetch a file URL')});
  filePage.context.location.protocol = 'file:';
  await filePage.run();
  assert.match(filePage.elements.get('newGameError').textContent,/127\.0\.0\.1:8765/);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run([node, "-e", script, str(html)], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_risk_panel_discards_old_versions_and_flower_picker_filters():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the frontend regression")
    html = Path(__file__).resolve().parents[1] / "src" / "webapp" / "index.html"
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8').match(/<script>([\s\S]*)<\/script>/)[1]
  .replace(/\nrefresh\(\);\s*$/,'\n');
const elements=new Map();
let release;
const ctx=vm.createContext({location:{protocol:'http:'},AbortController,setTimeout,clearTimeout,
  fetch:()=>new Promise(resolve=>{release=resolve}),document:{getElementById(id){
    if(!elements.has(id))elements.set(id,{hidden:true,disabled:false,innerHTML:'',textContent:'',style:{},classList:{add(){},remove(){}}});
    return elements.get(id);
  }}});
vm.runInContext(source,ctx);
const run=s=>vm.runInContext(s,ctx);
const decision=(id,revision)=>({game_id:id,revision,samples:8,elapsed_ms:1,budget_exhausted:false,
  warnings:['未经校准'],candidates:[{tile:'西风',expected_immediate_loss:0,any_ron_interval_95:[0,0.3],
  opponents:{left:{ron_rate:0,ron_hits:0,mean_payment_if_ron:null}}}]});
const respond=d=>release({ok:true,json:async()=>({ok:true,decision:d})});
(async()=>{
  run("current={flow:{game_id:'a',revision:1,phase:'need_discard'}}");
  const old=run('analyzeRisk()');
  assert.equal(elements.get('riskBtn').disabled,true);
  run('current.flow.revision=2');respond(decision('a',1));await old;
  assert.equal(run('riskResult'),null);
  assert.equal(elements.get('riskReport').hidden,true);
  assert.equal(run('riskBusy'),false);
  const latest=run('analyzeRisk()');respond(decision('a',2));await latest;
  assert.equal(elements.get('riskReport').hidden,false);
  assert.match(elements.get('riskReport').innerHTML,/零次命中不代表安全/);
  run("current.flow.game_id='b';renderRisk()");
  assert.equal(elements.get('riskReport').hidden,true);
  run("current.flow.phase='need_draw';renderRisk()");
  assert.equal(elements.get('riskBtn').disabled,true);
  run("pickerRows=(ts)=>{globalThis.picked=ts;return ''};picker={mode:'opp-flower',count:1};renderPicker()");
  assert.equal(run('picked.length'),12);
  assert.equal(run('picked.every(t=>FLOWERS.has(t))'),true);
  run("picker={mode:'opp-discard',count:1};renderPicker()");
  assert.equal(run('picked.some(t=>FLOWERS.has(t))'),false);
  run("legal={pending:{id:7,player:'left',tile:'9条'},peng:false,gang:false,ron:false,chi:[]};renderClaim()");
  assert.equal(elements.get('claim').className,'claim show');
  assert.match(elements.get('claim').innerHTML,/send\('过',true\)/);
  run("current={flow:{phase:'need_draw'},analysis:{shanten:1,remaining_total:100,candidates:[],kong_opportunities:[{kind:'花牌单杠',tile:'中',hua:0,hua_basis:'flower_score_delta',note:'总分不是增量'}]}};renderAnalysis()");
  assert.match(elements.get('analysis').innerHTML,/本次花分增量 0花/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run([node, "-e", script, str(html)], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
