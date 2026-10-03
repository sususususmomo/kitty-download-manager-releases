const HOST = "com.kitty.download_manager";
const FRONTEND_VERSION = browser.runtime.getManifest().version;
const NATIVE_PROTOCOL_VERSION = globalThis.KittyShared?.NATIVE_PROTOCOL_VERSION || 1;
const NATIVE_CLIENT = Object.freeze({ version: FRONTEND_VERSION, protocol: NATIVE_PROTOCOL_VERSION });
const SAFE_NATIVE_ACTIONS = new Set(["status", "get_settings", "compatibility", "diagnostics", "check_updates", "youtube_auth_status", "open_logs"]);
let compatibilityCache = null;
let compatibilityPromise = null;

let cachedStatus = null;
let cachedAt = 0;
let statusPromise = null;

const CONTEXT_MENU_ID = "kitty-download-with-kitty";
const CONTEXT_MENU_CONTEXTS = Object.freeze([
  "page", "frame", "selection", "link", "editable", "image", "video", "audio"
]);

function httpUrl(value) {
  const raw = typeof value === "string" ? value.trim() : "";
  return /^https?:\/\//i.test(raw) ? raw : null;
}

function knownMediaPage(url) {
  if (!url) return false;
  try {
    const key = globalThis.KittyShared?.sourceInfo?.(url)?.key;
    return Boolean(key && key !== "web");
  } catch {
    return false;
  }
}

function resolveContextDownloadUrl(info, tab) {
  const linkUrl = httpUrl(info?.linkUrl);
  const srcUrl = httpUrl(info?.srcUrl);
  const frameUrl = httpUrl(info?.frameUrl);
  const pageUrl = httpUrl(info?.pageUrl) || httpUrl(tab?.url);

  // Un clic droit sur un lien doit viser ce lien : pratique depuis un feed ou une page de résultats.
  if (linkUrl) return linkUrl;

  const mediaType = String(info?.mediaType || "").toLowerCase();
  if (mediaType === "video" || mediaType === "audio") {
    // Sur YouTube/TikTok/etc., l'URL du lecteur est souvent blob:/CDN/temporaire :
    // on laisse yt-dlp travailler à partir de la vraie page.
    if (knownMediaPage(frameUrl)) return frameUrl;
    if (knownMediaPage(pageUrl)) return pageUrl;
    // Sur une page générique, une vraie URL HTTP du média reste utile.
    if (srcUrl) return srcUrl;
  }

  // Images, sélection, champ éditable, zone vide, iframe… => page visitée.
  return frameUrl || pageUrl || srcUrl;
}

function contextMenuTitle(language) {
  return language === "en" ? "Download with Kitty" : "Télécharger avec Kitty";
}

async function refreshKittyContextMenu() {
  if (!browser.menus?.create) return;
  const saved = await browser.storage.local.get("uiLanguage");
  try { await browser.menus.remove(CONTEXT_MENU_ID); } catch {}
  browser.menus.create({
    id: CONTEXT_MENU_ID,
    title: contextMenuTitle(saved?.uiLanguage),
    contexts: [...CONTEXT_MENU_CONTEXTS]
  });
}

async function downloadFromContextMenu(info, tab) {
  const url = resolveContextDownloadUrl(info, tab);
  if (!url) return { ok: false, error: "URL HTTP/HTTPS requise." };

  const saved = await browser.storage.local.get("selectedMode");
  const mode = saved?.selectedMode || "1080";
  const result = await nativeMessage({
    action: "download",
    url,
    mode,
    force: false
  });

  invalidateStatus();
  return { ...result, selectedMode: mode, url };
}


async function rawNativeMessage(payload) {
  return browser.runtime.sendNativeMessage(HOST, { ...payload, client: NATIVE_CLIENT });
}

async function ensureCompatibility() {
  if (compatibilityCache?.compatible) return compatibilityCache;
  if (compatibilityPromise) return compatibilityPromise;
  compatibilityPromise = rawNativeMessage({ action: "compatibility" })
    .then(result => {
      const comp = result?.compatibility;
      if (result?.ok && comp?.compatible) compatibilityCache = comp;
      return comp || { compatible: false, message: "Backend Kitty ancien ou incompatible." };
    })
    .catch(() => ({ compatible: false, message: "Backend Kitty ancien ou incompatible." }))
    .finally(() => { compatibilityPromise = null; });
  return compatibilityPromise;
}

async function nativeMessage(payload) {
  const action = String(payload?.action || "");
  if (!SAFE_NATIVE_ACTIONS.has(action)) {
    const comp = await ensureCompatibility();
    if (!comp?.compatible) {
      return {
        ok: false,
        code: "incompatible_frontend_backend",
        error: "Kitty doit être mise à jour",
        error_hint: comp?.message || "Lance l’updater puis recharge l’extension."
      };
    }
  }
  return rawNativeMessage(payload);
}

async function getStatusCached(force = false) {
  const now = Date.now();
  const active = Boolean(cachedStatus?.state?.active);
  const ttl = active ? 450 : 1800;

  if (!force && cachedStatus && now - cachedAt < ttl) return cachedStatus;
  if (statusPromise) return statusPromise;

  statusPromise = nativeMessage({ action: "status" })
    .then(result => {
      cachedStatus = result;
      cachedAt = Date.now();
      return result;
    })
    .finally(() => {
      statusPromise = null;
    });

  return statusPromise;
}

function invalidateStatus() {
  cachedStatus = null;
  cachedAt = 0;
}

browser.runtime.onMessage.addListener((message) => {
  if (!message || typeof message !== "object") return;

  if (message.type === "kitty-pill-download") {
    return (async () => {
      const url = message.url;
      if (!url || !/^https?:\/\//i.test(url)) {
        return { ok: false, error: "URL HTTP/HTTPS requise." };
      }

      const saved = await browser.storage.local.get("selectedMode");
      const mode = saved?.selectedMode || "1080";
      const result = await nativeMessage({
        action: "download",
        url,
        mode,
        force: Boolean(message.force)
      });

      invalidateStatus();
      return { ...result, selectedMode: mode };
    })();
  }


  if (message.type === "kitty-get-output-dir") {
    return (async () => {
      const result = await nativeMessage({ action: "get_settings" });
      const outputDir = result?.settings?.output_dir || result?.output_dir || null;
      if (result?.ok && outputDir) {
        try { await browser.storage.local.set({ kittyOutputDir: outputDir }); } catch {}
      }
      return result;
    })();
  }

  if (message.type === "kitty-choose-output-dir") {
    return (async () => {
      // Le sélecteur natif prend le focus et Firefox peut fermer la popup.
      // Le background possède donc toute l'opération jusqu'à la persistance
      // du nouveau chemin côté Native Messaging host.
      const result = await nativeMessage({ action: "choose_output_dir" });
      const outputDir = result?.output_dir || result?.settings?.output_dir || null;

      if (result?.ok && !result?.cancelled && outputDir) {
        try { await browser.storage.local.set({ kittyOutputDir: outputDir }); } catch {}
      }

      return result;
    })();
  }

  if (message.type === "kitty-youtube-auth-start") {
    return nativeMessage({ action: "youtube_auth_start" });
  }

  if (message.type === "kitty-download-playlist") {
    return (async () => {
      const url = message.url;
      const mode = message.mode || "1080";

      if (!url || !/^https?:\/\//i.test(url)) {
        return { ok: false, error: "URL HTTP/HTTPS requise." };
      }

      const result = await nativeMessage({
        action: "download_playlist",
        url,
        mode
      });

      invalidateStatus();
      return result;
    })();
  }

  if (message.type === "kitty-pill-status") {
    return getStatusCached(Boolean(message.force));
  }
});

if (browser.menus?.onClicked?.addListener) {
  browser.menus.onClicked.addListener((info, tab) => {
    if (info?.menuItemId !== CONTEXT_MENU_ID) return;
    return downloadFromContextMenu(info, tab).catch(() => undefined);
  });

  refreshKittyContextMenu().catch(() => undefined);
}

if (browser.storage?.onChanged?.addListener) {
  browser.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === "local" && changes?.uiLanguage && browser.menus?.create) {
      refreshKittyContextMenu().catch(() => undefined);
    }
  });
}

