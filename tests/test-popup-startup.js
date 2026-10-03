// Exercise the real startup coordinator with controlled asynchronous dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../extension/popup.js'), 'utf8');
const startupSource = source.slice(source.indexOf('async function initializePopup()'), source.indexOf('\ninitializePopup().catch'));
const refreshSource = source.slice(source.indexOf('async function refresh('), source.indexOf('\nconst sectionDefaults'));
const nextTurn = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function startupContext(preferences, status) {
  const events = [];
  const context = {
    popupInitialized: false,
    renderBackendConnection: () => {},
    prepareBackendInstaller: () => Promise.resolve(),
    document: {
      documentElement: {classList: {remove: name => events.push(`reveal:${name}`)}},
      body: {setAttribute: (name, value) => events.push(`${name}:${value}`)}
    },
    I18N: {apply: () => events.push('translate')},
    restoreUiLanguage: () => preferences,
    chooseHeaderMascot: () => preferences,
    restoreSectionStates: () => preferences,
    restoreSettingsSectionStates: () => preferences,
    restorePillSettings: () => preferences,
    restoreModeSelection: () => preferences,
    refresh: (_force, timeout) => {
      assert.equal(timeout, 5000);
      return status;
    },
    schedulePopupPoll: delay => events.push(`poll:${delay}`),
    restoreDestination: () => events.push('hidden:destination'),
    restoreYoutubeAuth: () => events.push('hidden:auth')
  };
  vm.createContext(context);
  vm.runInContext(startupSource, context);
  return { context, events };
}

function refreshContextForTest(status, compatibility) {
  const events = [];
  const context = {
    nativeMessage: payload => {
      assert.equal(payload.action, 'status');
      events.push('status:start');
      return status;
    },
    ensureNativeCompatibility: () => {
      events.push('compatibility:start');
      return compatibility;
    },
    backendConnection: {kind:'checking'},
    setBackendConnection: kind => {context.backendConnection.kind=kind;},
    renderBackendConnection: () => events.push('connection:render'),
    KittyBackend: {connectionFailure: () => 'unavailable'},
    I18N: {tr: value => value},
    backendErrorMessage: () => 'unavailable',
    render: () => events.push('state:render'),
    statusEl: {textContent:''},
    schedulePopupPoll: () => {},
    setTimeout, clearTimeout
  };
  vm.createContext(context);
  vm.runInContext(refreshSource, context);
  return {context,events};
}
(async () => {
  // A quick status must not reveal the default layout while storage is pending.
  const pref = deferred();
  const fastStatus = startupContext(pref.promise, Promise.resolve({active: {id:'active'}}));
  const first = fastStatus.context.initializePopup();
  await nextTurn();
  assert.deepEqual(fastStatus.events, []);
  assert.equal(fastStatus.context.popupInitialized, false);
  pref.resolve();
  await first;
  assert.deepEqual(fastStatus.events, ['translate','reveal:popup-loading','aria-busy:false','poll:750','hidden:destination','hidden:auth']);

  // A quick preference restore must not reveal white/default state before status.
  const backend = deferred();
  const slowStatus = startupContext(Promise.resolve(), backend.promise);
  const second = slowStatus.context.initializePopup();
  await nextTurn();
  assert.deepEqual(slowStatus.events, []);
  backend.resolve({active:null, history:[{status:'finished'}]});
  await second;
  assert.equal(slowStatus.context.popupInitialized, true);
  assert.ok(slowStatus.events.includes('poll:1800'));

  // Failed storage/backend restores still release the loading UI and allow retry.
  const failed = startupContext(Promise.reject(new Error('storage unavailable')), Promise.reject(new Error('native unavailable')));
  await failed.context.initializePopup();
  assert.equal(failed.context.popupInitialized, true);
  assert.ok(failed.events.includes('reveal:popup-loading'));
  assert.ok(failed.events.includes('poll:1800'));

  // Exercise the real initial status timeout, then a successful later retry.
  let renders = 0;
  let answer = new Promise(() => {});
  const refreshContext = {
    nativeMessage: () => answer,
    ensureNativeCompatibility: () => Promise.resolve({compatible:true,backend_version:"8.31"}),
    setBackendConnection: () => {},
    renderBackendConnection: () => {},
    backendConnection: {kind:"ready"},
    KittyBackend: {connectionFailure: () => "unavailable"},
    I18N: {tr: value => value},
    backendErrorMessage: () => 'unavailable',
    render: () => { renders++; },
    statusEl: {textContent:''},
    schedulePopupPoll: () => {},
    setTimeout, clearTimeout
  };
  vm.createContext(refreshContext);
  vm.runInContext(refreshSource, refreshContext);
  const noStatus = await refreshContext.refresh(false, 5);
  assert.equal(noStatus, null);
  assert.equal(renders, 0);
  assert.match(refreshContext.statusEl.textContent, /ne répond pas/);
  answer = Promise.resolve({ok:true,state:{active:null,history:[{status:'finished'}]}});
  await refreshContext.refresh(false, 5);
  assert.equal(renders, 1);

  // Both native calls must start before either answer, in either completion
  // order. A fast status alone must not expose a false ready state.
  for (const firstAnswer of ['status','compatibility']) {
    const status=deferred();
    const compatibility=deferred();
    const probe=refreshContextForTest(status.promise,compatibility.promise);
    const request=probe.context.refresh(false,5000);
    await nextTurn();
    assert.ok(probe.events.includes('status:start'));
    assert.ok(probe.events.includes('compatibility:start'));
    const responses={status:{ok:true,state:{active:null}},compatibility:{compatible:true,backend_version:'8.31'}};
    const answers={status,compatibility};
    answers[firstAnswer].resolve(responses[firstAnswer]);
    await nextTurn();
    assert.equal(probe.events.includes('state:render'),false);
    const lastAnswer=firstAnswer==='status'?'compatibility':'status';
    answers[lastAnswer].resolve(responses[lastAnswer]);
    await request;
    assert.equal(probe.events.filter(event=>event==='state:render').length,1);
    assert.equal(probe.context.backendConnection.kind,'ready');
  }

  // A failed status should finish promptly even if the parallel compatibility
  // call never responds. A failed compatibility check must not mark ready.
  const statusError=refreshContextForTest(Promise.resolve({ok:false}),new Promise(()=>{}));
  let failedStatusFinished=false;
  const errorRequest=statusError.context.refresh(false,5000).then(()=>{failedStatusFinished=true;});
  await nextTurn();
  assert.equal(failedStatusFinished,true);
  await errorRequest;
  assert.equal(statusError.events.includes('state:render'),false);
  const incompatible=refreshContextForTest(Promise.resolve({ok:true,state:{}}),Promise.resolve({compatible:false}));
  await incompatible.context.refresh(false,5000);
  assert.equal(incompatible.context.backendConnection.kind,'incompatible');

  // A late compatibility answer after the deadline cannot paint its old state.
  const lateAnswer=deferred();
  const late=refreshContextForTest(Promise.resolve({ok:true,state:{active:{id:'old'}}}),lateAnswer.promise);
  assert.equal(await late.context.refresh(false,5),null);
  lateAnswer.resolve({compatible:true,backend_version:'8.31'});
  await nextTurn();
  assert.equal(late.events.includes('state:render'),false);

  console.log('Démarrage popup : 9 scénarios asynchrones OK');
})().catch(error => { console.error(error); process.exitCode=1; });
