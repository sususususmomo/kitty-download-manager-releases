// A failed initial publication must not permanently suppress unchanged DOM.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=process.env.KITTY_TEST_EXTENSION||path.join(__dirname,'../extension');
(async()=>{
 let receiver,fail=true,count=0,serial=0;const timers=new Map();
 const browser={runtime:{onMessage:{addListener:f=>receiver=f},sendMessage:async()=>{count++;if(fail)throw Error('Background listener not ready');return {ok:true};}}};
 const context=vm.createContext({browser,console,location:{href:'https://site.test/page'},KittyMediaDOM:{scan:()=>[{domId:'main',sources:[]}],selection:()=>null},
  MutationObserver:class{observe(){}disconnect(){}},document:{documentElement:{},addEventListener(){}},window:{addEventListener(){}},
  setTimeout:(fn,delay)=>{const id=++serial;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(fs.readFileSync(path.join(root,'shared.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(root,'media-context.js'),'utf8'),context);
 const run=async()=>{const [id,timer]=timers.entries().next().value;timers.delete(id);await timer.fn();};
 await run();assert.equal(count,2);assert.ok(timers.size,'Startup failure schedules retry');
 fail=false;await run();assert.equal(count,4,'Unchanged DOM is republished');
 const result=await receiver({type:'kitty-media-rescan'});assert.equal(result.ok,true);
 fail=true;const failed=await receiver({type:'kitty-media-rescan'});assert.equal(failed.ok,false);assert.match(failed.error,/listener/);
 console.log('PASS media publication: startup retry, acknowledged rescan and preserved errors');
})().catch(e=>{console.error(e);process.exitCode=1;});
