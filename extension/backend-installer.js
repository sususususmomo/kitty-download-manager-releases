// Public GitHub downloads. Only an explicit click opens a URL; no native host
// or remote JavaScript is needed to obtain the first installer.
(() => {
  const BASE = "https://github.com/sususususmomo/kitty-download-manager-releases/raw/refs/heads/backend-installers-v8.31/";
  const INSTALLERS = Object.freeze({
    linux: Object.freeze({label: "Linux", file: "kitty-backend-v8.31-linux.zip", instruction: "Décompresse l’archive, puis lance install.sh dans un terminal."}),
    win: Object.freeze({label: "Windows x64", actionLabel: "Windows", file: "kitty-backend-v8.31-windows-x64.zip", instruction: "Décompresse l’archive, puis double-clique sur Install.cmd."}),
    mac: Object.freeze({label: "macOS · Intel / Apple Silicon", actionLabel: "macOS", file: "kitty-backend-v8.31-macos.zip", instruction: "Décompresse l’archive, puis double-clique sur Install.command."})
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
  // Cached release flags describe the version installed when the check ran.
  // Recompute them against the backend connected now, without network access.
  function versionParts(value) {
    const text = String(value || "").trim().replace(/^v/i, "");
    if (!/^\d+(?:\.\d+){1,3}$/.test(text)) return null;
    const parts = text.split(".").map(Number);
    return parts.every(Number.isSafeInteger) ? parts : null;
  }
  function releaseForVersion(release, installedVersion) {
    if (!release || typeof release !== "object") return null;
    const result = {...release, current_version: installedVersion,
      update_available: false, local_newer: false, up_to_date: false};
    if (release.ok === false || release.state === "error") return {...result, state: "error"};
    const current = versionParts(installedVersion);
    const latest = versionParts(release.latest_version);
    if (!current || !latest) return {...result, ok: false, state: "error", error: "Version de release invalide."};
    let comparison = 0;
    for (let i = 0; i < Math.max(current.length, latest.length); i++) {
      const delta = (latest[i] || 0) - (current[i] || 0);
      if (delta) { comparison = Math.sign(delta); break; }
    }
    result.state = comparison > 0 ? "update_available" : comparison < 0 ? "local_newer" : "up_to_date";
    result.update_available = comparison > 0;
    result.local_newer = comparison < 0;
    result.up_to_date = comparison === 0;
    return result;
  }
  globalThis.KittyBackend = Object.freeze({selectInstaller, connectionFailure, releaseForVersion});
})();
