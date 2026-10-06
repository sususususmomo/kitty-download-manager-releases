// Actual session UI handlers against delayed replies, transport failures and errors.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../extension/popup.js'), 'utf8');
const sessionSource = source.slice(source.indexOf('let youtubeAuthLastStatus'), source.indexOf('\nfunction compactVersion'));
function deferred() { let resolve; const promise = new Promise(r => resolve=r); return {resolve,promise}; }
function fixture() {
  const element = () => ({textContent:'',classList:{add(){},remove(){}},handlers:{},addEventListener(type,handler){this.handlers[type]=handler;}});
  let status = {ok:true,configured:false,enabled:false,state:'not_configured'};
  let reply = {ok:false,error:'Firefox introuvable sur le système.'};
  let starts = 0, reads = 0, actions = 0;
  const result = async value => { if(value instanceof Error)throw value;return value; };
  const context = {
    youtubeAuthStateEl:element(),youtubeAuthStateTextEl:element(),youtubeAuthDetailEl:element(),
    youtubeAuthDeleteBtn:element(),youtubeAuthEnabledEl:element(),youtubeAuthConfigureBtn:element(),youtubeAuthHintEl:element(),
    updateCookiesHeaderState(){},formatYoutubeAuthDate(){return '';},setTimeout:()=>1,clearTimeout(){},
    setSettingsStatus(message,kind){context.message=message;context.kind=kind;},
    nativeMessage:async payload=>{if(payload.action==='youtube_auth_status'){reads++;return result(status);}actions++;return result(reply);},
    browser:{runtime:{sendMessage:async()=>{starts++;return result(reply);}}}
  };
  vm.createContext(context);
  vm.runInContext(sessionSource,context);
  return {context,click:()=>context.youtubeAuthConfigureBtn.handlers.click(),
    toggle:()=>context.youtubeAuthEnabledEl.handlers.change(),delete:()=>context.youtubeAuthDeleteBtn.handlers.click(),
    setStatus:value=>status=value,setReply:value=>reply=value,starts:()=>starts,reads:()=>reads,actions:()=>actions};
}
(async()=>{
  const f=fixture();
  await f.context.restoreYoutubeAuth();
  const oldRead=deferred();f.setStatus(oldRead.promise);
  const stale=f.context.restoreYoutubeAuth();await f.click();
  assert.equal(f.context.youtubeAuthDetailEl.textContent,'Firefox introuvable sur le système.');
  assert.equal(f.context.youtubeAuthStateTextEl.textContent,'Erreur');
  assert.equal(f.context.youtubeAuthConfigureBtn.disabled,false);assert.equal(f.reads(),2);
  oldRead.resolve({ok:true,configured:false,state:'not_configured'});await stale;
  assert.equal(f.context.youtubeAuthStateTextEl.textContent,'Erreur');
  f.setReply(new Error('Backend indisponible'));await f.click();
  assert.equal(f.context.youtubeAuthDetailEl.textContent,'Backend indisponible');
  assert.equal(f.context.youtubeAuthConfigureBtn.disabled,false);
  const opening=deferred();f.setReply(opening.promise);const retry=f.click();
  await f.click();await f.context.restoreYoutubeAuth();
  assert.equal(f.starts(),3);assert.equal(f.reads(),2);
  opening.resolve({ok:true,pending:true,state:'browser_open',configured:false,enabled:false});await retry;
  assert.equal(f.context.youtubeAuthStateTextEl.textContent,'Configuration');assert.equal(f.context.youtubeAuthConfigureBtn.disabled,true);
  const configured={ok:true,configured:true,enabled:true,state:'configured',cookie_count:1};
  f.setStatus(configured);await f.context.restoreYoutubeAuth();
  assert.equal(f.context.youtubeAuthStateTextEl.textContent,'Active');
  f.setReply({ok:false,error:'Échec du renouvellement',error_hint:'Conserver la session'});await f.click();
  assert.equal(f.context.youtubeAuthStateTextEl.textContent,'Ancienne session OK');
  assert.equal(f.context.youtubeAuthHintEl.textContent,'Conserver la session');
  assert.equal(f.context.youtubeAuthEnabledEl.checked,true);assert.equal(f.context.youtubeAuthDeleteBtn.hidden,false);
  f.setStatus(new Error('Transport interrompu'));await f.context.restoreYoutubeAuth();
  assert.equal(f.context.youtubeAuthEnabledEl.checked,true);assert.equal(f.context.youtubeAuthDeleteBtn.hidden,false);
  // An enable/disable failure restores the actual backend state, not the clicked checkbox.
  f.setStatus(configured);await f.context.restoreYoutubeAuth();
  f.context.youtubeAuthEnabledEl.checked=false;
  f.setReply({ok:false,error:'Écriture refusée',configured:true,enabled:true,error_hint:'Réessayer'});await f.toggle();
  assert.equal(f.context.youtubeAuthEnabledEl.checked,true);assert.equal(f.context.youtubeAuthEnabledEl.disabled,false);
  assert.equal(f.context.youtubeAuthDetailEl.textContent,'Écriture refusée');assert.equal(f.context.youtubeAuthHintEl.textContent,'Réessayer');
  // Delete requires two clicks; failed deletion keeps the session and permits retry.
  const before=f.actions();await f.delete();assert.equal(f.actions(),before);
  f.setReply({ok:false,error:'Fenêtre ouverte',configured:true,enabled:true,pending:true});await f.delete();
  assert.equal(f.context.youtubeAuthDetailEl.textContent,'Fenêtre ouverte');assert.equal(f.context.youtubeAuthDeleteBtn.disabled,false);
  assert.equal(f.context.youtubeAuthDeleteBtn.hidden,false);assert.equal(f.actions(),before+1);
  // Late status replies and competing actions cannot reset an in-flight toggle.
  f.setStatus(configured);await f.context.restoreYoutubeAuth();
  const delayedRead=deferred();f.setStatus(delayedRead.promise);const old=f.context.restoreYoutubeAuth();
  const toggle=deferred();f.setReply(toggle.promise);f.context.youtubeAuthEnabledEl.checked=false;const toggling=f.toggle();
  const count=f.actions();await f.toggle();await f.delete();assert.equal(f.actions(),count);
  delayedRead.resolve({ok:true,configured:false,enabled:false});await old;
  assert.equal(f.context.youtubeAuthStateTextEl.textContent,'Active');
  toggle.resolve({...configured,enabled:false});await toggling;
  assert.equal(f.context.youtubeAuthStateTextEl.textContent,'Prête');assert.equal(f.context.youtubeAuthEnabledEl.checked,false);
  console.log('YouTube UI: configure/toggle/delete, stale replies, preserved session, transport errors, duplicate clicks and retry passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
