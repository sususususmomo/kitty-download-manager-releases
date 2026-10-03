const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../extension/backend-installer.js'), 'utf8'), context);
const {selectInstaller, connectionFailure} = context.KittyBackend;
for (const [os, arch, filename] of [
  ['win','x86-64','windows-x64'], ['linux','x86-64','linux'],
  ['linux','arm','linux'], ['mac','arm','macos'], ['mac','x86-64','macos']
]) {
  const selected = selectInstaller({os, arch});
  assert.equal(new URL(selected.url).hostname, 'github.com');
  assert.ok(selected.url.endsWith(`kitty-backend-v8.31-${filename}.zip`));
  assert.ok(selected.instruction.includes('install.sh') || selected.instruction.includes('Install.'));
}
for (const platform of [{os:'win',arch:'arm'}, {os:'win',arch:'x86-32'}, {os:'android',arch:'arm'}, {}, null]) {
  assert.equal(selectInstaller(platform), null);
}
assert.equal(selectInstaller({os:'__proto__',arch:'arm'}), null);
assert.equal(connectionFailure(new Error('No such native application com.kitty.download_manager')), 'missing');
assert.equal(connectionFailure(new Error('Native application exited')), 'unavailable');
assert.equal(connectionFailure(new Error('timeout')), 'unavailable');
console.log('Installation initiale : systèmes supportés, liens GitHub et erreurs natifs OK');

const {releaseForVersion} = context.KittyBackend;
const oldCache = {ok:true,current_version:'8.16',latest_version:'8.18',state:'update_available',update_available:true};
assert.equal(releaseForVersion(oldCache, '8.31').state, 'local_newer');
assert.equal(releaseForVersion(oldCache, '8.31').update_available, false);
assert.equal(oldCache.update_available, true); // Do not mutate cached input.
assert.equal(releaseForVersion(oldCache, '8.18.0').state, 'up_to_date');
assert.equal(releaseForVersion(oldCache, '8.9').state, 'update_available');
assert.equal(releaseForVersion({ok:true,latest_version:'8.40',update_available:false}, '8.31').update_available, true);
assert.equal(releaseForVersion({ok:true,latest_version:'invalid',update_available:true}, '8.31').update_available, false);
assert.equal(releaseForVersion({ok:false,latest_version:'8.40',update_available:true}, '8.31').update_available, false);
assert.equal(releaseForVersion(null, '8.31'), null);
// Exercise the actual popup renderer for the four user-visible states.
class Element {
  constructor() {this.hidden=false;this.disabled=false;this.dataset={};this.attrs={};this.textContent='';}
  removeAttribute(name) {delete this.attrs[name];}
  setAttribute(name,value) {this.attrs[name]=value;}
}
const elements=Object.fromEntries(['backendReleaseStatus','verifyBackend','backendInstallInstruction'].map(id=>[id,new Element()]));
const ui={backendConnection:{kind:'ready',version:'8.31'},backendInstaller:selectInstaller({os:'linux',arch:'x86-64'}),backendReleaseReport:oldCache,
  backendDownloadBusy:false,backendUpdateBusy:false,KittyBackend:context.KittyBackend,
  document:{getElementById:id=>elements[id]},I18N:{tr:text=>text},downloadBackendEl:new Element(),checkKittyUpdateBtn:new Element(),backendUpdateMarkEl:new Element()};
vm.createContext(ui);
const popup=fs.readFileSync(path.join(__dirname,'../extension/popup.js'),'utf8');
vm.runInContext(popup.slice(popup.indexOf('function renderBackendActions()'),popup.indexOf('async function prepareBackendInstaller()')),ui);
ui.renderBackendActions();
assert.equal(ui.downloadBackendEl.hidden,true);
assert.equal(ui.checkKittyUpdateBtn.hidden,false);
assert.match(elements.backendReleaseStatus.textContent,/plus récente/);
ui.backendConnection={kind:'missing',version:''};ui.renderBackendActions();
assert.equal(ui.downloadBackendEl.hidden,false);
assert.match(ui.downloadBackendEl.textContent,/installateur Linux/);
assert.equal(ui.checkKittyUpdateBtn.hidden,true);
assert.equal(elements.verifyBackend.hidden,true);
ui.backendConnection={kind:'unavailable',version:''};ui.renderBackendActions();
assert.equal(elements.verifyBackend.hidden,false);
assert.equal(ui.downloadBackendEl.hidden,true);
ui.backendConnection={kind:'ready',version:'8.31'};
ui.backendReleaseReport={ok:true,latest_version:'8.40',download_supported:true,asset_sha256:'0'.repeat(64),asset_url:'https://github.com/sususususmomo/kitty-download-manager-releases/releases/download/v8.40/kitty-download-manager-v8.40.zip'};
ui.renderBackendActions();
assert.equal(ui.downloadBackendEl.hidden,false);
assert.equal(ui.downloadBackendEl.dataset.action,'update');
assert.equal(ui.downloadBackendEl.textContent,'Télécharger v8.40');
assert.equal(ui.checkKittyUpdateBtn.hidden,true);
ui.backendReleaseReport.asset_url='https://example.com/installer.zip';ui.renderBackendActions();
assert.equal(ui.downloadBackendEl.attrs['aria-disabled'],'true');
console.log('Release cache recalculation and contextual backend actions: OK');
