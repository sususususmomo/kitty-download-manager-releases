// Public GitHub downloads. Only an explicit click opens a URL; no native host
// or remote JavaScript is needed to obtain the first installer.
(() => {
  const BASE = "https://github.com/sususususmomo/kitty-download-manager-releases/raw/refs/heads/backend-installers-v8.31/";
  const INSTALLERS = Object.freeze({
    linux: Object.freeze({label: "Linux", file: "kitty-backend-v8.31-linux.zip", instruction: "Décompresse l’archive, puis lance install.sh dans un terminal."}),
    win: Object.freeze({label: "Windows x64", file: "kitty-backend-v8.31-windows-x64.zip", instruction: "Décompresse l’archive, puis double-clique sur Install.cmd."}),
    mac: Object.freeze({label: "macOS · Intel / Apple Silicon", file: "kitty-backend-v8.31-macos.zip", instruction: "Décompresse l’archive, puis double-clique sur Install.command."})
  });
  function selectInstaller(platform) {
    if (platform?.os === "win" && platform.arch !== "x86-64") return null;
    if (platform?.os === "mac" && !["x86-64", "aarch64", "arm"].includes(platform.arch)) return null;
    const item = Object.hasOwn(INSTALLERS, platform?.os) ? INSTALLERS[platform.os] : null;
    return item ? {...item, url: BASE + item.file} : null;
  }
  function connectionFailure(error) {
    const text = String(error?.message || error || "");
    return /No such native application|native application.*not found|native host.*not found/i.test(text)
      ? "missing" : "unavailable";
  }
  globalThis.KittyBackend = Object.freeze({selectInstaller, connectionFailure});
})();
