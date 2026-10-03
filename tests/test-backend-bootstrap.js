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
