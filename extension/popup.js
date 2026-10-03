const HOST = "com.kitty.download_manager";
const {
  NATIVE_PROTOCOL_VERSION,
  STATE_UI,
  modeLabel,
  sourceInfo,
  sourceIconSvg,
  jobPhase,
  playlistPosition,
  queuePosition,
  compactPosition
} = globalThis.KittyShared;
const I18N = globalThis.KittyI18n;

const FRONTEND_VERSION = browser.runtime.getManifest().version;
const NATIVE_CLIENT = Object.freeze({
  version: FRONTEND_VERSION,
  protocol: NATIVE_PROTOCOL_VERSION
});

const modeEl = document.getElementById("mode");
const modePickerEl = document.getElementById("modePicker");
const modeButtonEl = document.getElementById("modeButton");
const modeButtonLabelEl = document.getElementById("modeButtonLabel");
const modeMenuEl = document.getElementById("modeMenu");
const modeMenuItems = [...document.querySelectorAll(".modeMenuItem[data-mode]")];
const playlistModeToggleEl = document.getElementById("playlistModeToggle");
const playlistModeBadgeEl = document.getElementById("playlistModeBadge");
const playlistPanelEl = document.getElementById("playlistPanel");
const playlistUrlEl = document.getElementById("playlistUrl");
const playlistUrlStatusEl = document.getElementById("playlistUrlStatus");
const headerMascotEl = document.getElementById("headerMascot");
const currentSectionTitleEl = document.getElementById("currentSectionTitle");
const catGameEl = document.getElementById("catGame");
const downloadSummaryEl = document.getElementById("downloadSummary");
const historySummaryEl = document.getElementById("historySummary");
const downloadBtn = document.getElementById("download");
const openFolderBtn = document.getElementById("openFolder");
const cancelBtn = document.getElementById("cancel");
const activeControlsEl = document.getElementById("activeControls");
const pauseQueueBtn = document.getElementById("pauseQueue");
const clearQueueBtn = document.getElementById("clearQueue");
const clearHistoryBtn = document.getElementById("clearHistory");
const progressEl = document.getElementById("progress");
const titleEl = document.getElementById("currentTitle");
const activeSourceEl = document.getElementById("activeSource");
const percentEl = document.getElementById("percent");
const statsEl = document.getElementById("stats");
const statusEl = document.getElementById("status");
const queueEl = document.getElementById("queue");
const queueCountEl = document.getElementById("queueCount");
const queueOutcomeIndicatorEl = document.getElementById("queueOutcomeIndicator");
const historyEl = document.getElementById("history");
const downloadCardEl = document.getElementById("downloadCard");
const queueSectionEl = document.querySelector('.collapseSection[data-section="queue"]');
const pillEnabledEl = document.getElementById("pillEnabled");
const pillScopeEl = document.getElementById("pillScope");
const pillStylePickerEl = document.getElementById("pillStylePicker");
const pillStyleButtonEl = document.getElementById("pillStyleButton");
const pillStyleMenuEl = document.getElementById("pillStyleMenu");
const pillStyleCurrentPreviewEl = document.getElementById("pillStyleCurrentPreview");
const pillStyleCurrentLabelEl = document.getElementById("pillStyleCurrentLabel");
const pillStyleOptions = [...document.querySelectorAll(".pillStyleOption[data-pill-style]")];
const destinationPathEl = document.getElementById("destinationPath");
const chooseDestinationBtn = document.getElementById("chooseDestination");
const mainViewEl = document.getElementById("mainView");
const settingsViewEl = document.getElementById("settingsView");
const openSettingsBtn = document.getElementById("openSettings");
const backToMainBtn = document.getElementById("backToMain");
const openLogsBtn = document.getElementById("openLogs");
const copyDiagnosticsBtn = document.getElementById("copyDiagnostics");
const refreshDiagnosticsBtn = document.getElementById("refreshDiagnostics");
const runDiagnosticsBtn = document.getElementById("runDiagnostics");
const checkUpdatesBtn = document.getElementById("checkUpdates");
const downloadKittyUpdateBtn = document.getElementById("downloadKittyUpdate");
const backendUpdateMarkEl = document.getElementById("backendUpdateMark");
const dependencyStateEl = document.getElementById("dependencyState");
const dependencyStateTextEl = document.getElementById("dependencyStateText");
const dependencyListEl = document.getElementById("dependencyList");
const diagnosticFactsEl = document.getElementById("diagnosticFacts");
const cleanCacheBtn = document.getElementById("cleanCache");
const cacheMaintenanceSummaryEl = document.getElementById("cacheMaintenanceSummary");
const cacheMaintenanceHintEl = document.getElementById("cacheMaintenanceHint");
const resetKittyBtn = document.getElementById("resetKitty");
const settingsStatusEl = document.getElementById("settingsStatus");
const youtubeAuthStateEl = document.getElementById("youtubeAuthState");
const youtubeAuthStateTextEl = document.getElementById("youtubeAuthStateText");
const cookiesSectionEl = document.querySelector('[data-settings-section="cookies"]');
const cookiesHeaderMarkEl = document.getElementById("cookiesHeaderMark");
const dependenciesSectionEl = document.querySelector('[data-settings-section="dependencies"]');
const dependenciesHeaderMarkEl = document.getElementById("dependenciesHeaderMark");
const youtubeAuthDetailEl = document.getElementById("youtubeAuthDetail");
const youtubeAuthHintEl = document.getElementById("youtubeAuthHint");
const youtubeAuthConfigureBtn = document.getElementById("youtubeAuthConfigure");
const youtubeAuthDeleteBtn = document.getElementById("youtubeAuthDelete");
const youtubeAuthEnabledEl = document.getElementById("youtubeAuthEnabled");
const uiLanguageEl = document.getElementById("uiLanguage");


I18N.observe(document.body);

async function restoreUiLanguage() {
  let language = "fr";
  try {
    const saved = await browser.storage.local.get("uiLanguage");
    language = I18N.normalize(saved?.uiLanguage);
  } catch {}

  I18N.setLanguage(language);
  if (uiLanguageEl) uiLanguageEl.value = language;
  I18N.apply(document.body);
}

uiLanguageEl?.addEventListener("change", async () => {
  const language = I18N.normalize(uiLanguageEl.value);
  I18N.setLanguage(language);
  I18N.apply(document.body);

  try {
    await browser.storage.local.set({ uiLanguage: language });
    I18N.apply(document.body);
    renderBackendConnection();
    prepareBackendInstaller();
    render(latestState);
    resetDownloadButton();
    updatePlaylistUrlStatus();
    restorePillSettings();
    restoreYoutubeAuth();
    restoreDiagnostics(false).catch(() => {});
    setSettingsStatus("Langue de l’interface mise à jour.", "success");
  } catch {
    setSettingsStatus("Erreur : Impossible d'enregistrer la langue.", "error");
  }
});



const FORMAT_LONG_LABELS = Object.freeze({
  "1080": "Vidéo — jusqu’à 1080p",
  "720": "Vidéo — jusqu’à 720p",
  "best": "Vidéo — meilleure qualité",
  "audio": "Audio — format original",
  "mp3": "Audio — MP3"
});

let playlistModeEnabled = false;
let modeMenuOpen = false;

function classifyCollectionUrl(value) {
  try {
    const u = new URL(String(value || "").trim());
    if (!["http:", "https:"].includes(u.protocol)) {
      return { valid: false };
    }

    const host = u.hostname.replace(/^www\./, "").toLowerCase();

    if (host === "youtube.com" || host.endsWith(".youtube.com") || host === "youtu.be") {
      return {
        valid: true,
        label: u.searchParams.get("list")
          ? "✓ Playlist YouTube prête"
          : "✓ URL YouTube prête · yt-dlp vérifiera la collection"
      };
    }

    if (host === "soundcloud.com" || host.endsWith(".soundcloud.com")) {
      return {
        valid: true,
        label: "✓ URL SoundCloud prête · profil, playlist ou collection"
      };
    }

    if (
      host === "bandcamp.com" || host.endsWith(".bandcamp.com") ||
      host === "vimeo.com" || host.endsWith(".vimeo.com") ||
      host === "dailymotion.com" || host.endsWith(".dailymotion.com") ||
      host === "dai.ly" ||
      host === "audiomack.com" || host.endsWith(".audiomack.com") ||
      host === "audius.co" || host.endsWith(".audius.co")
    ) {
      return {
        valid: true,
        label: "✓ URL de collection prête · yt-dlp vérifiera son contenu"
      };
    }

    return {
      valid: true,
      label: "✓ URL prête · yt-dlp vérifiera si c’est une collection"
    };
  } catch {
    return { valid: false };
  }
}

function updatePlaylistUrlStatus(message = null, kind = null) {
  playlistUrlStatusEl.classList.remove("valid", "error");

  if (message !== null) {
    playlistUrlStatusEl.textContent = I18N.tr(message);
    if (kind) playlistUrlStatusEl.classList.add(kind);
    return;
  }

  const value = playlistUrlEl.value.trim();
  if (!value) {
    playlistUrlStatusEl.textContent =
      "YouTube, SoundCloud, Bandcamp, Vimeo, Dailymotion…";
    return;
  }

  const classified = classifyCollectionUrl(value);
  if (classified.valid) {
    playlistUrlStatusEl.textContent = I18N.tr(classified.label);
    playlistUrlStatusEl.classList.add("valid");
  } else {
    playlistUrlStatusEl.textContent = "Entre une URL HTTP/HTTPS valide.";
    playlistUrlStatusEl.classList.add("error");
  }
}

function updateModePickerUI() {
  const selectedMode = modeEl.value || "1080";
  modeButtonLabelEl.textContent = FORMAT_LONG_LABELS[selectedMode] || selectedMode;

  modeMenuItems.forEach(item => {
    const active = item.dataset.mode === selectedMode;
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", active ? "true" : "false");
  });

  playlistModeToggleEl.classList.toggle("active", playlistModeEnabled);
  playlistModeToggleEl.setAttribute("aria-pressed", playlistModeEnabled ? "true" : "false");
  playlistModeBadgeEl.hidden = !playlistModeEnabled;
  playlistPanelEl.hidden = !playlistModeEnabled;

  if (!pendingDuplicate) {
    downloadBtn.textContent = playlistModeEnabled
      ? "Ajouter la playlist"
      : "Ajouter au téléchargement";
  }
}

function setModeMenuOpen(open) {
  modeMenuOpen = Boolean(open);
  modeMenuEl.hidden = !modeMenuOpen;
  modeButtonEl.setAttribute("aria-expanded", modeMenuOpen ? "true" : "false");
}

function setPlaylistMode(enabled, { persist = true } = {}) {
  playlistModeEnabled = Boolean(enabled);
  pendingDuplicate = null;
  downloadBtn.classList.remove("duplicatePending");
  updateModePickerUI();

  if (playlistModeEnabled) {
    setModeMenuOpen(true);
    updatePlaylistUrlStatus();
  }

  if (persist) {
    browser.storage.local.set({
      playlistMode: playlistModeEnabled,
      playlistUrl: playlistUrlEl.value
    }).catch(() => {});
  }
}


const HEADER_MASCOTS = [
  "/ᐠ • ˕ •マ ?",
  "₍^. .^₎Ⳋ",
  ">^..^<",
  "≽ܫ≼",
  " /\\\\_/\\\\\n[ • - • ]",
  "A___A\n(ㅇㅅㅇ)\n/   >🐠",
  "ᵐᵉᵒʷ ₍^. .^₎⟆",
  "/'• ˕ •'\\",
  "/\\__/\\\n  • w •"
];

async function chooseHeaderMascot() {
  let lastIndex = null;

  try {
    const saved = await browser.storage.local.get("lastHeaderMascotIndex");
    if (typeof saved?.lastHeaderMascotIndex === "number") {
      lastIndex = saved.lastHeaderMascotIndex;
    }
  } catch {}

  let choices = HEADER_MASCOTS.map((_, index) => index);

  if (choices.length > 1 && lastIndex !== null) {
    choices = choices.filter(index => index !== lastIndex);
  }

  const nextIndex = choices[Math.floor(Math.random() * choices.length)];
  headerMascotEl.textContent = HEADER_MASCOTS[nextIndex];

  try {
    await browser.storage.local.set({ lastHeaderMascotIndex: nextIndex });
  } catch {}
}


let stickyActive = null;
let stickyJobId = null;
let idlePolls = 0;

const CAT_POOL = [
  "ᓚ₍ ^. .^₎",
  "/ᐠ｡ꞈ｡ᐟ\\",
  "ᓚᘏᗢ",
  "₍^. .^₎⟆"
];

let currentCatJobId = null;
let currentLeftCat = null;
let currentRightCat = null;

const catAnim = {
  rafId: 0,
  jobId: null,
  direction: 1,
  startTs: 0,
  holdUntil: 0,
  duration: 6200,
  arcHeight: 8,
  wobble: 0,
  wobbleFreq: 1.5,
  endScale: 1,
  impactDirection: 1,
  pendingDirection: null
};

function chooseCatsForJob(jobId) {
  if (!jobId) return null;

  if (currentCatJobId !== jobId || !currentLeftCat || !currentRightCat) {
    currentCatJobId = jobId;

    const leftIndex = Math.floor(Math.random() * CAT_POOL.length);
    let rightIndex = Math.floor(Math.random() * CAT_POOL.length);

    if (CAT_POOL.length > 1 && rightIndex === leftIndex) {
      rightIndex = (rightIndex + 1 + Math.floor(Math.random() * (CAT_POOL.length - 1))) % CAT_POOL.length;
    }

    currentLeftCat = CAT_POOL[leftIndex];
    currentRightCat = CAT_POOL[rightIndex];
  }

  return { left: currentLeftCat, right: currentRightCat };
}

function rand(min, max) {
  return min + Math.random() * (max - min);
}

function nextTrajectory() {
  return {
    duration: rand(3600, 5200),
    arcHeight: rand(4.5, 10.5),
    wobble: rand(-2.2, 2.2),
    wobbleFreq: rand(1.2, 2.4),
    endScale: rand(0.96, 1.04)
  };
}

function triggerCatReaction(side) {
  const selector = side === "left" ? ".catLeft" : ".catRight";
  const el = catGameEl.querySelector(selector);
  if (!el) return;
  el.classList.remove("react");
  void el.offsetWidth;
  el.classList.add("react");
  setTimeout(() => el.classList.remove("react"), 170);
}

function applyBallTransform(progress) {
  const field = catGameEl.querySelector(".catPlayField");
  const ball = catGameEl.querySelector(".catBall");
  if (!field || !ball) return;

  const travel = Math.max(60, field.clientWidth - 4);
  const u = catAnim.direction === 1 ? progress : 1 - progress;
  const x = travel * u;
  const y =
    -Math.sin(Math.PI * u) * catAnim.arcHeight +
    Math.sin(Math.PI * u * catAnim.wobbleFreq) * catAnim.wobble;
  const scale = 1 - 0.06 * Math.sin(Math.PI * u);

  ball.style.transform =
    `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) scale(${scale.toFixed(3)})`;
}

function applyImpactPose() {
  const field = catGameEl.querySelector(".catPlayField");
  const ball = catGameEl.querySelector(".catBall");
  if (!field || !ball) return;

  const travel = Math.max(60, field.clientWidth - 4);
  const x = catAnim.impactDirection === 1 ? travel : 0;
  ball.style.transform =
    `translate(${x.toFixed(1)}px, 0px) scale(${catAnim.endScale.toFixed(3)})`;
}

function prepareNextLeg() {
  Object.assign(catAnim, nextTrajectory());
  catAnim.startTs = 0;
}

function animateCatBall(ts) {
  if (!catAnim.jobId || !catGameEl.classList.contains("active")) {
    catAnim.rafId = 0;
    return;
  }

  if (catAnim.holdUntil && ts < catAnim.holdUntil) {
    applyImpactPose();
    catAnim.rafId = requestAnimationFrame(animateCatBall);
    return;
  }

  if (catAnim.holdUntil && ts >= catAnim.holdUntil) {
    catAnim.holdUntil = 0;

    if (catAnim.pendingDirection !== null) {
      catAnim.direction = catAnim.pendingDirection;
      catAnim.pendingDirection = null;
    }

    catAnim.startTs = ts;
  }

  if (!catAnim.startTs) {
    catAnim.startTs = ts;
  }

  const progress = Math.min(1, (ts - catAnim.startTs) / catAnim.duration);
  applyBallTransform(progress);

  if (progress >= 1) {
    // Conserver le sens du trajet terminé pendant toute la pause d'impact.
    // Le changement de direction n'est appliqué qu'après la pause, sinon
    // la balle saute visuellement à l'autre extrémité pendant une frame.
    catAnim.impactDirection = catAnim.direction;
    applyImpactPose();
    triggerCatReaction(catAnim.direction === 1 ? "right" : "left");

    catAnim.pendingDirection = -catAnim.direction;
    Object.assign(catAnim, nextTrajectory());
    catAnim.holdUntil = ts + rand(90, 170);
    catAnim.startTs = 0;
  }

  catAnim.rafId = requestAnimationFrame(animateCatBall);
}

function ensureCatAnimationRunning(jobId) {
  if (catAnim.jobId !== jobId) {
    catAnim.jobId = jobId;
    catAnim.direction = 1;
    catAnim.impactDirection = 1;
    catAnim.pendingDirection = null;
    catAnim.holdUntil = 0;
    catAnim.startTs = 0;
    Object.assign(catAnim, nextTrajectory());
  }

  if (!catAnim.rafId) {
    catAnim.rafId = requestAnimationFrame(animateCatBall);
  }
}

function showCatGame(active) {
  const previousJobId = currentCatJobId;
  const cats = chooseCatsForJob(active?.id);

  if (!cats || !active) {
    catGameEl.classList.remove("active");
    catGameEl.innerHTML = "";
    return;
  }

  const alreadyRenderedForThisJob =
    previousJobId === active.id &&
    catGameEl.dataset.jobId === String(active.id) &&
    catGameEl.children.length === 3;

  if (!alreadyRenderedForThisJob) {
    catGameEl.innerHTML =
      `<span class="catSprite catLeft">${escapeHtml(cats.left)}</span>` +
      `<span class="catPlayField"><span class="catBall">●</span></span>` +
      `<span class="catSprite catRight">${escapeHtml(cats.right)}</span>`;

    catGameEl.dataset.jobId = String(active.id);
  }

  catGameEl.classList.add("active");
  ensureCatAnimationRunning(active.id);
}

function hideCatGame() {
  if (catAnim.rafId) {
    cancelAnimationFrame(catAnim.rafId);
  }
  catAnim.rafId = 0;
  catAnim.jobId = null;
  catAnim.startTs = 0;
  catAnim.holdUntil = 0;
  catAnim.pendingDirection = null;
  catAnim.impactDirection = 1;
  catGameEl.classList.remove("active");
  catGameEl.innerHTML = "";
  delete catGameEl.dataset.jobId;
}

let lastQueueSignature = null;
let lastHistorySignature = null;
let latestState = { active: null, queue: [], history: [] };
let pendingDuplicate = null;
let popupPollTimer = 0;
let popupInitialized = false;
let backendConnection = {kind: "checking", version: ""};
let backendInstaller = null;
const backendControlIds = ["download", "openFolder", "cancel", "pauseQueue", "clearQueue", "clearHistory", "chooseDestination", "openLogs", "refreshDiagnostics", "runDiagnostics", "checkUpdates", "downloadKittyUpdate", "cleanCache", "resetKitty", "youtubeAuthConfigure", "youtubeAuthDelete", "youtubeAuthEnabled"];

function setBackendConnection(kind, version = "") {
  backendConnection = {kind, version};
  if (kind !== "ready") nativeCompatibilityCache = null;
  renderBackendConnection();
}

function renderBackendConnection() {
  const {kind, version} = backendConnection;
  const ready = kind === "ready";
  const connection = document.getElementById("backendConnection");
  const labels = {
    checking: "Vérification de la connexion…",
    ready: "Backend connecté",
    missing: "Backend non installé",
    unavailable: "Connexion au backend impossible",
    incompatible: "Backend à mettre à jour"
  };
  connection.dataset.state = kind;
  connection.textContent = I18N.tr(labels[kind]) + (version ? ` · v${version}` : "");
  const notice = document.getElementById("backendNotice");
  notice.hidden = ready || kind === "checking";
  document.getElementById("backendNoticeTitle").textContent = I18N.tr(
    kind === "missing" ? "Installer le backend Kitty" : labels[kind]
  );
  document.getElementById("backendNoticeText").textContent = I18N.tr(
    kind === "missing" ? "Le backend est nécessaire pour télécharger tes médias."
    : "Ouvre les réglages pour installer le backend ou vérifier la connexion."
  );
  // Restore only controls disabled by this connection gate. Renderers keep
  // ownership of empty queues, running jobs and in-flight action states.
  for (const id of backendControlIds) {
    const control = document.getElementById(id);
    if (!control) continue;
    if (!ready) {
      if (!control.hasAttribute("data-backend-disabled")) {
        control.dataset.backendDisabled = String(control.disabled);
      }
      control.disabled = true;
    } else if (control.hasAttribute("data-backend-disabled")) {
      control.disabled = control.dataset.backendDisabled === "true";
      delete control.dataset.backendDisabled;
    }
  }
}

async function prepareBackendInstaller() {
  const link = document.getElementById("downloadBackend");
  try { backendInstaller = KittyBackend.selectInstaller(await browser.runtime.getPlatformInfo()); }
  catch { backendInstaller = null; }
  link.hidden = !backendInstaller;
  if (backendInstaller) link.href = backendInstaller.url;
  else link.removeAttribute("href");
  document.getElementById("backendPlatform").textContent = backendInstaller?.label ||
    I18N.tr("Aucun installateur disponible pour ce système.");
  document.getElementById("backendInstallInstruction").textContent = backendInstaller
    ? I18N.tr(backendInstaller.instruction) : "";
}

document.getElementById("configureBackend").addEventListener("click", () => {
  showSettings();
  setSettingsSectionOpen("backend", true, false);
  document.getElementById("backendSettings").scrollIntoView({block: "start"});
});
document.getElementById("verifyBackend").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  nativeCompatibilityCache = null;
  nativeCompatibilityPromise = null;
  setBackendConnection("checking");
  try {
    const state = await refresh(false, 5000);
    if (backendConnection.kind === "ready") {
      restoreDestination();
      restoreYoutubeAuth();
      restoreDiagnostics(false).catch(() => {});
    }
    schedulePopupPoll(state?.active ? 750 : 1800);
  } finally { button.disabled = false; }
});
let lastObservedHistoryId = undefined;
let queueOutcomeTimer = 0;


function fmtBytes(value) {
  if (value === null || value === undefined || value === "") return "?";
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "?";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let x = n, i = 0;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  return `${x.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function fmtEta(value) {
  if (value === null || value === undefined || value === "") return "?";
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "?";
  const s = Math.max(0, Math.round(n));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return `${h}h ${m}m ${sec}s`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}


const NATIVE_SAFE_WITHOUT_HANDSHAKE = new Set([
  "status", "get_settings", "diagnostics", "compatibility", "check_updates",
  "check_kitty_update", "download_kitty_update", "open_logs", "youtube_auth_status"
]);
let nativeCompatibilityCache = null;
let nativeCompatibilityPromise = null;

async function rawNativeMessage(payload) {
  return await browser.runtime.sendNativeMessage(HOST, {
    ...payload,
    client: NATIVE_CLIENT
  });
}

async function ensureNativeCompatibility() {
  if (nativeCompatibilityCache?.compatible) return nativeCompatibilityCache;
  if (nativeCompatibilityPromise) return nativeCompatibilityPromise;

  nativeCompatibilityPromise = rawNativeMessage({ action: "compatibility" })
    .then(result => {
      const compatibility = result?.compatibility;
      if (!result?.ok || !compatibility?.compatible) {
        return {
          compatible: false,
          update_required: true,
          message: compatibility?.message ||
            "Backend Kitty ancien ou incompatible. Lance l’updater puis recharge l’extension."
        };
      }
      nativeCompatibilityCache = compatibility;
      return compatibility;
    })
    .catch(() => ({
      compatible: false,
      update_required: true,
      message: "Backend Kitty ancien ou incompatible. Lance l’updater puis recharge l’extension."
    }))
    .finally(() => {
      nativeCompatibilityPromise = null;
    });

  return nativeCompatibilityPromise;
}

async function nativeMessage(payload) {
  const action = String(payload?.action || "");
  if (!NATIVE_SAFE_WITHOUT_HANDSHAKE.has(action)) {
    const compatibility = await ensureNativeCompatibility();
    if (!compatibility?.compatible) {
      return {
        ok: false,
        code: "incompatible_frontend_backend",
        error: "Kitty doit être mise à jour",
        error_hint: compatibility?.message || "Mets à jour le backend puis recharge Firefox.",
        compatibility
      };
    }
  }
  return await rawNativeMessage(payload);
}


function resetDownloadButton() {
  pendingDuplicate = null;
  downloadBtn.classList.remove("duplicatePending");
  downloadBtn.textContent = playlistModeEnabled
    ? "Ajouter la playlist"
    : "Ajouter au téléchargement";
}

function setDownloadSectionPhase(phase, positionText = "") {
  const ui = STATE_UI[phase] || STATE_UI.idle;
  currentSectionTitleEl.textContent = I18N.tr(ui.label);
  currentSectionTitleEl.classList.remove(
    "downloaded", "metadataState", "downloadingState", "errorState", "duplicateState"
  );

  if (phase === "metadata") currentSectionTitleEl.classList.add("metadataState");
  if (phase === "downloading" || phase === "paused") currentSectionTitleEl.classList.add("downloadingState");
  if (phase === "finished") currentSectionTitleEl.classList.add("downloaded");
  if (phase === "error") currentSectionTitleEl.classList.add("errorState");
  if (phase === "duplicate") currentSectionTitleEl.classList.add("duplicateState");

  downloadSummaryEl.textContent = phase === "finished"
    ? ""
    : positionText ? `${I18N.tr(ui.short)} • ${I18N.tr(positionText)}` : I18N.tr(ui.short);

  downloadCardEl?.classList.remove("downloadStateMetadata", "downloadStateDownloading");
  if (phase === "metadata") downloadCardEl?.classList.add("downloadStateMetadata");
  if (phase === "downloading") downloadCardEl?.classList.add("downloadStateDownloading");
}


function clearDownloadResultTint() {
  downloadCardEl?.classList.remove(
    "downloadResultSuccess",
    "downloadResultError",
    "downloadStateMetadata",
    "downloadStateDownloading"
  );
}

function setDownloadResultTint(phase) {
  clearDownloadResultTint();
  if (phase === "finished") downloadCardEl?.classList.add("downloadResultSuccess");
  if (phase === "error") downloadCardEl?.classList.add("downloadResultError");
}

function setQueueOutcomeIndicator(history) {
  if (!queueOutcomeIndicatorEl) return;

  const lastRelevant = Array.isArray(history)
    ? history.find(job => {
        const phase = jobPhase(job);
        return phase === "finished" || phase === "error";
      })
    : null;

  queueOutcomeIndicatorEl.classList.remove("visible", "success", "error");

  if (!lastRelevant) {
    queueOutcomeIndicatorEl.textContent = "";
    queueOutcomeIndicatorEl.removeAttribute("title");
    return;
  }

  const phase = jobPhase(lastRelevant);
  const success = phase === "finished";

  queueOutcomeIndicatorEl.textContent = success ? "✓" : "!";
  queueOutcomeIndicatorEl.classList.add("visible", success ? "success" : "error");
  queueOutcomeIndicatorEl.title = success
    ? "Dernier téléchargement réussi"
    : "Dernier téléchargement en erreur";
}

function flashQueueOutcome(phase) {
  if (!queueSectionEl || (phase !== "finished" && phase !== "error")) return;

  queueSectionEl.classList.remove("queueOutcomeSuccess", "queueOutcomeError");
  void queueSectionEl.offsetWidth;
  queueSectionEl.classList.add(
    phase === "finished" ? "queueOutcomeSuccess" : "queueOutcomeError"
  );

  if (queueOutcomeTimer) clearTimeout(queueOutcomeTimer);
  queueOutcomeTimer = setTimeout(() => {
    queueSectionEl.classList.remove("queueOutcomeSuccess", "queueOutcomeError");
    queueOutcomeTimer = 0;
  }, 2200);
}

function observeLatestOutcome(history) {
  setQueueOutcomeIndicator(history);

  const latest = Array.isArray(history) && history.length ? history[0] : null;
  const latestId = latest?.id ?? null;

  // Première lecture : restaurer l'indicateur sans flasher un ancien résultat.
  if (lastObservedHistoryId === undefined) {
    lastObservedHistoryId = latestId;
    return;
  }

  if (latestId === lastObservedHistoryId) return;
  lastObservedHistoryId = latestId;

  if (!latest) return;
  const phase = jobPhase(latest);
  if (phase === "finished" || phase === "error") flashQueueOutcome(phase);
}

function renderActive(active, state = latestState) {
  if (!active) {
    setDownloadSectionPhase("idle");
    hideCatGame();
    titleEl.textContent = I18N.tr("Aucun téléchargement actif");
    titleEl.classList.remove("activeLoading");
    activeSourceEl.style.display = "none";
    clearSourceHost(activeSourceEl);
    percentEl.textContent = "—";
    progressEl.value = 0;
    statsEl.textContent = "";
    statusEl.textContent = I18N.tr("Prêt.");
    cancelBtn.disabled = true;
    activeControlsEl.classList.add("hidden");
    return;
  }

  clearDownloadResultTint();
  cancelBtn.disabled = false;
  activeControlsEl.classList.remove("hidden");
  const phase = jobPhase(active);
  const position = compactPosition(state, active.id);
  setDownloadSectionPhase(phase, position);

  const downloadedForControls = Number(active.downloaded);
  const totalForControls = Number(active.total ?? active.estimated_total);
  const reachedHundred =
    Number.isFinite(downloadedForControls) &&
    Number.isFinite(totalForControls) &&
    totalForControls > 0 &&
    downloadedForControls >= totalForControls;

  activeControlsEl.classList.toggle("hidden", reachedHundred);
  cancelBtn.disabled = reachedHundred;

  if (phase === "metadata" || phase === "downloading") showCatGame(active);
  else hideCatGame();

  const source = sourceInfo(active.url);
  activeSourceEl.style.display = "inline-flex";
  activeSourceEl.title = "";
  updateSourceHost(activeSourceEl, active.url, source);

  if (active.title) {
    titleEl.classList.remove("activeLoading");
    titleEl.textContent = active.title;
  } else if (["error", "unavailable"].includes(active.metadata_status)) {
    titleEl.classList.remove("activeLoading");
    titleEl.textContent = I18N.tr("Titre indisponible");
    titleEl.title = I18N.tr(active.metadata_error || "");
  } else if (!titleEl.classList.contains("activeLoading")) {
    titleEl.classList.add("activeLoading");
    titleEl.innerHTML = `<span class="spinner"></span><span>Récupération du titre…</span>`;
  }

  const downloaded = active.downloaded == null ? NaN : Number(active.downloaded);
  const rawTotal = active.total ?? active.estimated_total;
  const total = rawTotal == null ? NaN : Number(rawTotal);
  const speed = active.speed == null ? NaN : Number(active.speed);
  const eta = active.eta == null ? NaN : Number(active.eta);

  if (Number.isFinite(downloaded) && Number.isFinite(total) && total > 0) {
    const pct = Math.max(0, Math.min(100, downloaded / total * 100));
    percentEl.textContent = `${pct.toFixed(1)} %`;
    progressEl.value = pct;
    statsEl.textContent = `${fmtBytes(downloaded)} / ${fmtBytes(total)} • ${fmtBytes(speed)}/s • ETA ${fmtEta(eta)}`;
  } else {
    percentEl.textContent = phase === "metadata" ? "…" : "—";
    progressEl.removeAttribute("value");
    statsEl.textContent = `${fmtBytes(downloaded)} • ${fmtBytes(speed)}/s • ETA ${fmtEta(eta)}`;
  }

  statusEl.textContent = phase === "metadata"
    ? I18N.tr("Récupération des métadonnées…")
    : `${I18N.tr("Téléchargement")} • ${I18N.tr(modeLabel(active.mode))}`;
}

function itemTitle(job) {
  if (job.title) return job.title;
  return null;
}

function renderQueue(queue, active = latestState.active) {
  const signature = JSON.stringify(queue.map(j => [
    j.id, j.title || "", j.metadata_status || "", j.metadata_error || "",
    j.metadata_attempts || 0, j.metadata_pid || null, j.mode, j.url, Boolean(j.paused),
    j.playlist_position || null, j.playlist_total || null
  ])) + `|${active?.id || ""}|${Boolean(latestState.queue_paused)}`;

  if (signature === lastQueueSignature) return;
  lastQueueSignature = signature;

  queueEl.innerHTML = "";
  const pausedCount = queue.filter(job => job.paused).length;
  queueCountEl.textContent = queue.length
    ? I18N.tr(`${queue.length} en attente${pausedCount ? ` • ${pausedCount} pause` : ""}`)
    : I18N.tr("Vide");

  pauseQueueBtn.disabled = !queue.length;
  clearQueueBtn.disabled = !queue.length;
  if (!queue.length && clearQueueConfirming) resetClearQueueConfirmation();
  pauseQueueBtn.textContent = I18N.tr(latestState.queue_paused ? "▶ File" : "⏸ File");
  pauseQueueBtn.title = I18N.tr(latestState.queue_paused ? "Reprendre la file" : "Mettre la file en pause");

  if (!queue.length) {
    queueEl.innerHTML = '<div class="empty">La file est vide.</div>';
    return;
  }

  const total = queue.length + (active ? 1 : 0);

  queue.forEach((job, i) => {
    const row = document.createElement("div");
    row.className = "item queueItem";
    if (job.paused) row.classList.add("queuePaused");

    const text = document.createElement("div");
    text.className = "itemText";

    const knownTitle = itemTitle(job);
    let titleHtml;

    if (knownTitle) {
      titleHtml = `<div class="itemTitle">${escapeHtml(knownTitle)}</div>`;
    } else if (["error", "unavailable"].includes(job.metadata_status)) {
      const detail = job.metadata_error ? ` title="${escapeHtml(job.metadata_error)}"` : "";
      titleHtml =
        `<div class="itemTitle metadataUnavailable"${detail}>${escapeHtml(I18N.tr("Titre indisponible"))}</div>`;
    } else {
      titleHtml =
        `<div class="itemTitle loadingTitle"><span class="spinner"></span><span>${escapeHtml(I18N.tr("Récupération du titre…"))}</span></div>`;
    }

    const position = queuePosition({ active, queue }, job.id);
    const pauseLabel = job.paused ? ` • ${I18N.tr("pause")}` : "";

    let positionText = "";
    let positionKind = "file";

    if (position?.kind === "playlist") {
      positionText = `${position.current} / ${position.total} • `;
      positionKind = "playlist";
    } else if (position?.kind === "priority") {
      positionText = position.next
        ? `${I18N.tr("prochain")} • `
        : position.total > 1
          ? `${I18N.tr("priorité")} ${position.current} / ${position.total} • `
          : `${I18N.tr("prioritaire")} • `;
    } else if (position) {
      positionText = `${position.current} / ${position.total} • `;
    }

    text.innerHTML = `${titleHtml}
      <div class="itemMeta">${positionText}${escapeHtml(I18N.tr(modeLabel(job.mode)))} • ${escapeHtml(I18N.tr(positionKind))}${pauseLabel}</div>`;

    const source = sourceInfo(job.url);
    const sourceBadgeHost = document.createElement("div");
    sourceBadgeHost.className = "sourceBadgeHost";
    sourceBadgeHost.innerHTML = sourceButtonHtml(job.url, source);
    const sourceBadge = sourceBadgeHost.firstElementChild;

    const actions = document.createElement("div");
    actions.className = "queueRowActions";

    const pause = document.createElement("button");
    pause.className = "queueControl ghost";
    pause.type = "button";
    pause.textContent = job.paused ? "▶" : "⏸";
    pause.title = I18N.tr(job.paused ? "Reprendre cet élément" : "Mettre cet élément en pause");
    pause.onclick = async () => {
      pause.disabled = true;
      const r = await nativeMessage({ action: "toggle_queue_item_pause", job_id: job.id });
      if (r?.state) render(r.state);
      if (!r?.ok) statusEl.textContent = "Erreur : " + (r?.error || "Impossible de modifier la file.");
    };

    const remove = document.createElement("button");
    remove.className = "queueControl queueRemove";
    remove.type = "button";
    remove.textContent = "×";
    remove.title = I18N.tr("Ne pas télécharger cet élément");
    remove.onclick = async () => {
      remove.disabled = true;
      const r = await nativeMessage({ action: "remove_queued", job_id: job.id });
      if (r?.state) render(r.state);
    };

    actions.append(pause, remove);
    row.append(text, sourceBadge, actions);
    queueEl.append(row);
  });
}

function renderHistory(history) {
  const visible = history.slice(0, 10);
  const signature = JSON.stringify(visible.map(job => [
    job.id,
    job.status || "",
    job.title || "",
    job.url || "",
    job.mode || "",
    job.finished_at || null,
    Boolean(job.already_present),
    job.error || "",
    job.error_hint || "",
    job.filepath || ""
  ]));

  historySummaryEl.textContent = history.length
    ? I18N.tr(`${history.length} élément${history.length > 1 ? "s" : ""}`)
    : I18N.tr("Vide");

  if (signature === lastHistorySignature) return;
  lastHistorySignature = signature;
  historyEl.innerHTML = "";

  if (!history.length) {
    historyEl.innerHTML = `<div class="empty">${escapeHtml(I18N.tr("Aucun téléchargement terminé."))}</div>`;
    return;
  }

  visible.forEach(job => {
    const row = document.createElement("div");
    row.className = "item";

    const phase = jobPhase(job);
    if (phase === "finished") row.classList.add("historySuccess");
    if (phase === "error") row.classList.add("historyError");
    const symbol = phase === "finished" ? "✓" : phase === "cancelled" ? "×" : "!";
    const when = job.finished_at
      ? new Date(job.finished_at * 1000).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})
      : "";
    const existing = job.already_present ? ` • ${I18N.tr("déjà présent")}` : "";
    const source = sourceInfo(job.url);
    const safeTitle = itemTitle(job) || source.label;

    const text = document.createElement("div");
    text.className = "itemText";
    const errorLine = phase === "error"
      ? `<div class="itemError" title="${escapeHtml(I18N.tr(job.error_hint || ""))}">${escapeHtml(I18N.tr(job.error || "Erreur du backend"))}</div>`
      : "";

    text.innerHTML = `<div class="itemTitle">${symbol} ${escapeHtml(safeTitle)}</div>
      <div class="itemMeta">${escapeHtml(I18N.tr(modeLabel(job.mode)))} • ${escapeHtml(source.label)}${existing}${when ? " • " + when : ""}</div>
      ${errorLine}`;

    const sourceButtonWrap = document.createElement("div");
    sourceButtonWrap.className = "historySourceAction";
    sourceButtonWrap.innerHTML = sourceButtonHtml(job.url, source, true);
    row.append(text, sourceButtonWrap);

    if (phase === "error") {
      const retry = document.createElement("button");
      retry.className = "mini retryButton";
      retry.textContent = I18N.tr("Relancer");
      retry.onclick = async () => {
        retry.disabled = true;
        retry.textContent = "…";
        try {
          const r = await nativeMessage({ action: "retry", job_id: job.id });
          if (!r?.ok) throw new Error(backendErrorMessage(r, "Relance impossible."));
          resetDownloadButton();
          stickyJobId = r.job_id || stickyJobId;
          if (r.state) render(r.state);
        } catch (err) {
          statusEl.textContent = "Erreur : " + err.message;
        } finally {
          retry.disabled = false;
          retry.textContent = I18N.tr("Relancer");
        }
      };
      row.append(retry);
    }

    historyEl.append(row);
  });
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  })[c]);
}


function safeSourceUrl(raw) {
  try {
    const url = new URL(String(raw || ""));
    if (!["http:", "https:"].includes(url.protocol)) return "";
    return url.href;
  } catch {
    return "";
  }
}

function sourceButtonHtml(url, source = sourceInfo(url), compact = false) {
  const safe = safeSourceUrl(url);
  const title = safe
    ? `Ouvrir la source · ${source.label}`
    : `Source · ${source.label}`;
  const compactClass = compact ? " sourceBadgeCompact" : "";

  return `<button class="sourceBadge sourceLink${compactClass}" type="button" data-open-source="${escapeHtml(safe)}" data-source="${escapeHtml(source.key || "web")}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"${safe ? "" : " disabled"}>` +
    `<span class="sourceGlyph" aria-hidden="true">${sourceIconSvg(source.key)}</span>` +
    `<span class="sourceLabel">${escapeHtml(source.label)}</span>` +
    `</button>`;
}


function updateSourceHost(host, url, source = sourceInfo(url), compact = false) {
  if (!host) return;

  const safe = safeSourceUrl(url);
  const signature = JSON.stringify([
    safe,
    source?.key || "web",
    source?.label || "Web",
    Boolean(compact)
  ]);

  if (host.dataset.sourceSignature === signature && host.firstElementChild) {
    return;
  }

  host.dataset.sourceSignature = signature;
  host.innerHTML = sourceButtonHtml(url, source, compact);
}

function clearSourceHost(host) {
  if (!host) return;
  delete host.dataset.sourceSignature;
  host.innerHTML = "";
}

async function openSourceUrl(raw) {
  const safe = safeSourceUrl(raw);
  if (!safe) return false;

  try {
    await browser.tabs.create({ url: safe, active: true });
    return true;
  } catch (error) {
    console.warn("Kitty: impossible d'ouvrir la source", error);
    return false;
  }
}


function backendErrorMessage(source, fallback = "Erreur du backend") {
  if (!source) return I18N.tr(fallback);
  if (typeof source === "string") return I18N.tr(source || fallback);
  const message = I18N.tr(source.error || source.message || fallback);
  const hint = I18N.tr(source.error_hint || source.hint || "");
  return hint ? `${message} — ${hint}` : message;
}

function render(state) {
  latestState = {
    active: state.active || null,
    queue: Array.isArray(state.queue) ? state.queue : [],
    history: Array.isArray(state.history) ? state.history : [],
    queue_paused: Boolean(state.queue_paused)
  };

  const incomingActive = latestState.active;
  const history = latestState.history;
  observeLatestOutcome(history);

  // A real active job always wins and refreshes the sticky snapshot.
  if (incomingActive) {
    stickyActive = incomingActive;
    stickyJobId = incomingActive.id || stickyJobId;
    idlePolls = 0;
  } else if (stickyJobId) {
    // Only clear the sticky job when the backend explicitly reports this same
    // job in history as finished/cancelled/error.
    const completed = history.find(j => j.id === stickyJobId);
    if (completed) {
      stickyActive = null;
      stickyJobId = null;
      idlePolls = 0;
    } else {
      // Tolerate short transient empty snapshots without flashing back to "Prêt".
      idlePolls += 1;
      if (idlePolls >= 8) {
        // After ~6 seconds of no active job and no completion record, clear it
        // so a genuinely lost worker doesn't leave the UI stuck forever.
        stickyActive = null;
        stickyJobId = null;
        idlePolls = 0;
      }
    }
  }

  renderActive(stickyActive || incomingActive, latestState);

  if (!stickyActive && !incomingActive && !history.length) {
    clearDownloadResultTint();
  }

  if (!stickyActive && !incomingActive && history.length) {
    activeControlsEl.classList.add("hidden");
    const last = history[0];
    titleEl.classList.remove("activeLoading");
    titleEl.textContent = last.title || I18N.tr("Dernier téléchargement");
    const source = sourceInfo(last.url);
    activeSourceEl.style.display = "inline-flex";
    activeSourceEl.title = "";
    updateSourceHost(activeSourceEl, last.url, source);

    if (last.status === "finished") {
      setDownloadResultTint("finished");
      setDownloadSectionPhase("finished");
      hideCatGame();
      percentEl.textContent = "100 %";
      progressEl.value = 100;
      statsEl.textContent = last.filepath || "";
      statusEl.textContent = last.already_present
        ? I18N.tr("Déjà présent dans le dossier.")
        : I18N.tr("Téléchargement terminé.");
    } else if (last.status === "cancelled") {
      clearDownloadResultTint();
      setDownloadSectionPhase("cancelled");
      hideCatGame();
      percentEl.textContent = "—";
      progressEl.value = 0;
      statsEl.textContent = "";
      statusEl.textContent = I18N.tr("Dernier téléchargement annulé.");
    } else if (last.status === "error") {
      setDownloadResultTint("error");
      setDownloadSectionPhase("error");
      hideCatGame();
      percentEl.textContent = "—";
      progressEl.value = 0;
      statsEl.textContent = last.error_hint || "";
      statusEl.textContent = last.error || "Erreur du backend";
    }
  }

  renderQueue(latestState.queue, latestState.active);
  renderHistory(history);
}

async function refresh(force = false, timeoutMs = 0) {
  let timeout = 0;
  try {
    const request = (async () => {
      const response = await nativeMessage({ action: "status" });
      if (response?.ok) response.kittyCompatibility = await ensureNativeCompatibility();
      return response;
    })();
    const r = timeoutMs > 0
      ? await Promise.race([
          request,
          new Promise((_, reject) => {
            timeout = setTimeout(() => reject(new Error(
              I18N.tr("Le backend Kitty ne répond pas.")
            )), timeoutMs);
          })
        ])
      : await request;
    if (!r?.ok) throw new Error(backendErrorMessage(r, "Erreur du host."));
    setBackendConnection(r.kittyCompatibility?.compatible ? "ready" : "incompatible",
      r.kittyCompatibility?.backend_version || "");
    render(r.state || {});
    if (backendConnection.kind !== "ready") renderBackendConnection();
    return r.state || {};
  } catch (err) {
    const kind = KittyBackend.connectionFailure(err);
    setBackendConnection(kind);
    statusEl.textContent = I18N.tr(kind === "missing"
      ? "Installe le backend depuis les réglages pour commencer."
      : "Le backend Kitty ne répond pas. Vérifie la connexion dans les réglages.");
    return null;
  } finally {
    if (timeout) clearTimeout(timeout);
    if (force) schedulePopupPoll(250);
  }
}



const sectionDefaults = {
  download: true,
  queue: false,
  history: false,
};

async function setSectionOpen(name, open, persist = true) {
  const section = document.querySelector(`.collapseSection[data-section="${name}"]`);
  if (!section) return;
  section.classList.toggle("collapsed", !open);

  if (persist) {
    try {
      const current = await browser.storage.local.get("sectionStates");
      const states = { ...(current.sectionStates || {}), [name]: open };
      await browser.storage.local.set({ sectionStates: states });
    } catch {}
  }
}

async function restoreSectionStates() {
  try {
    const saved = await browser.storage.local.get("sectionStates");
    const states = saved.sectionStates || {};
    for (const [name, fallback] of Object.entries(sectionDefaults)) {
      await setSectionOpen(name, states[name] ?? fallback, false);
    }
  } catch {
    for (const [name, fallback] of Object.entries(sectionDefaults)) {
      await setSectionOpen(name, fallback, false);
    }
  }
}

document.querySelectorAll(".sectionToggle").forEach(toggle => {
  toggle.addEventListener("click", async () => {
    const section = toggle.closest(".collapseSection");
    const name = section?.dataset.section;
    if (!name) return;
    const willOpen = section.classList.contains("collapsed");
    await setSectionOpen(name, willOpen);
  });
});



const settingsSectionDefaults = Object.freeze({
  language: false,
  destination: false,
  backend: false,
  pill: false,
  cookies: false,
  dependencies: false,
  diagnostic: false,
  maintenance: false,
});

async function setSettingsSectionOpen(name, open, persist = true) {
  const section = document.querySelector(
    `.settingsCollapse[data-settings-section="${name}"]`
  );
  if (!section) return;

  section.classList.toggle("collapsed", !open);

  const toggle = section.querySelector(".settingsGroupToggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  if (persist) {
    try {
      const current = await browser.storage.local.get("settingsSectionStates");
      const states = {
        ...(current.settingsSectionStates || {}),
        [name]: Boolean(open),
      };
      await browser.storage.local.set({ settingsSectionStates: states });
    } catch {}
  }
}

async function restoreSettingsSectionStates() {
  try {
    const saved = await browser.storage.local.get("settingsSectionStates");
    const states = saved.settingsSectionStates || {};

    for (const [name, fallback] of Object.entries(settingsSectionDefaults)) {
      await setSettingsSectionOpen(name, states[name] ?? fallback, false);
    }
  } catch {
    for (const [name, fallback] of Object.entries(settingsSectionDefaults)) {
      await setSettingsSectionOpen(name, fallback, false);
    }
  }
}

document.querySelectorAll(".settingsGroupToggle").forEach(toggle => {
  toggle.addEventListener("click", async () => {
    const section = toggle.closest(".settingsCollapse");
    const name = section?.dataset.settingsSection;
    if (!name) return;

    const willOpen = section.classList.contains("collapsed");
    await setSettingsSectionOpen(name, willOpen);
  });
});



function setSettingsStatus(message = "", kind = "") {
  settingsStatusEl.textContent = I18N.tr(message);
  settingsStatusEl.classList.remove("success", "error");
  if (kind) settingsStatusEl.classList.add(kind);
}

function showSettings() {
  renderBackendConnection();
  prepareBackendInstaller();
  mainViewEl.classList.add("hidden");
  settingsViewEl.classList.remove("hidden");
  setSettingsStatus();
  restoreDestination();
  restorePillSettings();
  restoreYoutubeAuth();
  restoreDiagnostics(false).catch(() => {});
}

function showMain() {
  settingsViewEl.classList.add("hidden");
  mainViewEl.classList.remove("hidden");
}

openSettingsBtn.addEventListener("click", showSettings);
backToMainBtn.addEventListener("click", showMain);


function formatYoutubeAuthDate(timestamp) {
  if (!timestamp) return "";
  try {
    return new Date(timestamp * 1000).toLocaleString("fr-FR", {
      dateStyle: "short",
      timeStyle: "short"
    });
  } catch {
    return "";
  }
}

function updateCookiesHeaderState(active) {
  const isActive = Boolean(active);

  cookiesHeaderMarkEl?.classList.toggle("cookiesActive", isActive);
  cookiesHeaderMarkEl?.classList.toggle("cookiesInactive", !isActive);
  cookiesSectionEl?.classList.toggle("cookiesActive", isActive);
  cookiesSectionEl?.classList.toggle("cookiesInactive", !isActive);

  if (cookiesHeaderMarkEl) {
    cookiesHeaderMarkEl.title = isActive ? "Cookies actifs" : "Cookies inactifs";
  }
}

function updateDependenciesHeaderState(state) {
  const normalized = ["ready", "warning", "error"].includes(state) ? state : "unknown";
  const classes = [
    "dependencyUnknown",
    "dependencyReady",
    "dependencyWarning",
    "dependencyError",
  ];

  dependenciesHeaderMarkEl?.classList.remove(...classes);
  dependenciesSectionEl?.classList.remove(...classes);

  const className = {
    ready: "dependencyReady",
    warning: "dependencyWarning",
    error: "dependencyError",
    unknown: "dependencyUnknown",
  }[normalized];

  dependenciesHeaderMarkEl?.classList.add(className);
  dependenciesSectionEl?.classList.add(className);

  if (dependenciesHeaderMarkEl) {
    dependenciesHeaderMarkEl.title = {
      ready: "Dépendances prêtes",
      warning: "Dépendance optionnelle manquante",
      error: "Dépendance requise manquante",
      unknown: "État des dépendances inconnu",
    }[normalized];
  }
}


function renderYoutubeAuth(auth) {
  const configured = Boolean(auth?.configured);
  const pending = Boolean(auth?.pending);
  const state = auth?.state || (configured ? "configured" : "not_configured");

  youtubeAuthStateEl.classList.remove("ready", "pending", "error");
  updateCookiesHeaderState(
    configured &&
    Boolean(auth?.enabled) &&
    !pending &&
    state !== "error" &&
    auth?.ok !== false
  );
  youtubeAuthDeleteBtn.hidden = !configured;
  youtubeAuthEnabledEl.disabled = !configured || pending;
  youtubeAuthEnabledEl.checked = configured && Boolean(auth?.enabled);

  if (state === "browser_open") {
    youtubeAuthStateEl.classList.add("pending");
    youtubeAuthStateTextEl.textContent = "Configuration";
    youtubeAuthDetailEl.textContent = configured
      ? "Renouvellement en cours · ancienne session conservée"
      : "Fenêtre Firefox dédiée ouverte";
    youtubeAuthConfigureBtn.disabled = true;
    youtubeAuthConfigureBtn.textContent = "Firefox dédié ouvert";
    youtubeAuthHintEl.textContent =
      "Dans cette fenêtre : connecte-toi à YouTube, ouvre youtube.com/robots.txt dans le même onglet, puis ferme Firefox. Rouvre ensuite Kitty.";
    return;
  }

  if (state === "settling" || state === "ready_to_finalize") {
    youtubeAuthStateEl.classList.add("pending");
    youtubeAuthStateTextEl.textContent = "Finalisation";
    youtubeAuthDetailEl.textContent = "Firefox est fermé · préparation du snapshot…";
    youtubeAuthConfigureBtn.disabled = true;
    youtubeAuthConfigureBtn.textContent = "Finalisation…";
    youtubeAuthHintEl.textContent =
      "Kitty attend que Firefox ait terminé ses dernières écritures avant de lire les cookies.";
    return;
  }

  if (state === "error" || auth?.ok === false) {
    youtubeAuthStateEl.classList.add("error");
    youtubeAuthStateTextEl.textContent = configured ? "Ancienne session OK" : "Erreur";
    youtubeAuthDetailEl.textContent = auth?.error || "Configuration incomplète";
    youtubeAuthConfigureBtn.disabled = false;
    youtubeAuthConfigureBtn.textContent = configured ? "Renouveler…" : "Recommencer…";
    youtubeAuthHintEl.textContent =
      "L'ancien snapshot n'est jamais remplacé si une nouvelle configuration échoue.";
    return;
  }

  youtubeAuthConfigureBtn.disabled = false;

  if (configured) {
    youtubeAuthStateEl.classList.add("ready");
    youtubeAuthStateTextEl.textContent = auth?.enabled ? "Active" : "Prête";
    const created = formatYoutubeAuthDate(auth?.created_at);
    const count = Number.isFinite(auth?.cookie_count) ? ` · ${auth.cookie_count} cookies YouTube` : "";
    youtubeAuthDetailEl.textContent = `${created ? "Créée " + created : "Snapshot disponible"}${count}`;
    youtubeAuthConfigureBtn.textContent = "Renouveler…";
    youtubeAuthHintEl.textContent =
      "Le profil de connexion jetable a été supprimé. Seul le snapshot YouTube filtré reste, en permissions privées.";
  } else {
    youtubeAuthStateTextEl.textContent = "Non configurée";
    youtubeAuthDetailEl.textContent = "Aucune session YouTube dédiée";
    youtubeAuthConfigureBtn.textContent = "Configurer YouTube…";
    youtubeAuthHintEl.textContent =
      "Kitty ouvre un Firefox jetable dans un HOME séparé. Ton profil Firefox habituel n'est ni lu, ni copié, ni modifié.";
  }
}

async function restoreYoutubeAuth() {
  try {
    const auth = await nativeMessage({ action: "youtube_auth_status" });
    renderYoutubeAuth(auth);
    if (auth?.ok === false && auth?.error) {
      setSettingsStatus("YouTube : " + auth.error, "error");
    }
  } catch (err) {
    renderYoutubeAuth({ ok: false, state: "error", error: err.message });
  }
}

youtubeAuthConfigureBtn.addEventListener("click", async () => {
  youtubeAuthConfigureBtn.disabled = true;
  setSettingsStatus("Ouverture d'un Firefox YouTube isolé…");

  try {
    const auth = await browser.runtime.sendMessage({ type: "kitty-youtube-auth-start" });
    renderYoutubeAuth(auth);
    if (!auth?.ok) throw new Error(auth?.error || "Impossible de créer la session YouTube.");
    setSettingsStatus("Firefox dédié ouvert. Termine la connexion dans cette fenêtre.", "success");
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
    await restoreYoutubeAuth();
  }
});

youtubeAuthEnabledEl.addEventListener("change", async () => {
  youtubeAuthEnabledEl.disabled = true;
  try {
    const auth = await nativeMessage({
      action: "youtube_auth_set_enabled",
      enabled: youtubeAuthEnabledEl.checked
    });
    renderYoutubeAuth(auth);
    if (!auth?.ok) throw new Error(auth?.error || "Impossible de modifier la session YouTube.");
    setSettingsStatus(
      auth.enabled ? "Session YouTube activée." : "Session YouTube désactivée.",
      "success"
    );
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
    await restoreYoutubeAuth();
  }
});

let youtubeDeleteConfirmTimer = 0;
let youtubeDeleteConfirming = false;

function clearYoutubeDeleteConfirmation() {
  if (youtubeDeleteConfirmTimer) clearTimeout(youtubeDeleteConfirmTimer);
  youtubeDeleteConfirmTimer = 0;
  youtubeDeleteConfirming = false;
  youtubeAuthDeleteBtn.textContent = "Supprimer";
}

youtubeAuthDeleteBtn.addEventListener("click", async () => {
  if (!youtubeDeleteConfirming) {
    youtubeDeleteConfirming = true;
    youtubeAuthDeleteBtn.textContent = "Confirmer";
    setSettingsStatus("Clique une seconde fois pour supprimer uniquement la session YouTube Kitty.");
    youtubeDeleteConfirmTimer = setTimeout(clearYoutubeDeleteConfirmation, 4500);
    return;
  }

  clearYoutubeDeleteConfirmation();
  youtubeAuthDeleteBtn.disabled = true;
  try {
    const auth = await nativeMessage({ action: "youtube_auth_delete" });
    renderYoutubeAuth(auth);
    if (!auth?.ok) throw new Error(auth?.error || "Suppression impossible.");
    setSettingsStatus("Session YouTube Kitty supprimée.", "success");
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
    await restoreYoutubeAuth();
  } finally {
    youtubeAuthDeleteBtn.disabled = false;
  }
});



function compactVersion(dep) {
  const version = String(dep?.version || "").trim();
  if (!version) return dep?.ok ? "installé" : "absent";

  if (dep?.id === "ffmpeg" || dep?.id === "ffprobe") {
    const match = version.match(/\bversion\s+([^\s]+)/i);
    if (match) return match[1];
  }

  return version;
}

function formatBytes(bytes) {
  if (!Number.isFinite(Number(bytes))) return I18N.tr("inconnu");
  let value = Number(bytes);
  const units = I18N.getLanguage() === "en"
    ? ["B", "KiB", "MiB", "GiB", "TiB"]
    : ["o", "Kio", "Mio", "Gio", "Tio"];
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return i === 0 ? `${Math.round(value)} ${units[i]}` : `${value.toFixed(1)} ${units[i]}`;
}

function orphanPartialsText(cache) {
  const orphan = cache?.orphan_partials || {};
  const count = Number(orphan.count || 0);
  if (!count) return "aucun détecté";
  return `${count} détecté${count > 1 ? "s" : ""} · ${formatBytes(orphan.bytes || 0)} · conservé${count > 1 ? "s" : ""}`;
}

function renderCacheHealth(cache) {
  const info = cache || {};
  const total = formatBytes(info.total_bytes || 0);
  const reclaimable = Number(info.reclaimable_bytes || 0);

  if (cacheMaintenanceSummaryEl) {
    cacheMaintenanceSummaryEl.textContent = reclaimable > 0
      ? `${total} · ${formatBytes(reclaimable)} récupérables`
      : `${total} · rien à nettoyer`;
  }

  if (cacheMaintenanceHintEl) {
    const maxLog = formatBytes(info.log_max_file_bytes || (2 * 1024 * 1024));
    const files = Number(info.log_max_archives ?? 4) + 1;
    cacheMaintenanceHintEl.title = `Logs : rotation automatique à ${maxLog} · ${files} fichiers maximum`;
  }
}


function renderBackendUpdateMark(compatibility, updates, kittyRelease = null) {
  if (!backendUpdateMarkEl) return;

  backendUpdateMarkEl.hidden = true;
  backendUpdateMarkEl.className = "backendUpdateMark";
  backendUpdateMarkEl.textContent = "";
  backendUpdateMarkEl.title = "";

  const incompatible = !compatibility || compatibility.compatible === false;
  if (incompatible) {
    backendUpdateMarkEl.hidden = false;
    backendUpdateMarkEl.classList.add("incompatible");
    backendUpdateMarkEl.textContent = "!";
    backendUpdateMarkEl.title = compatibility?.message ||
      "Frontend/backend non vérifiés ou incompatibles · mise à jour requise";
    return;
  }

  const risky = Number(updates?.risky_updates || 0);
  const count = Number(updates?.updates_available || 0);
  const kittyUpdate = Boolean(kittyRelease?.update_available);
  if (risky > 0) {
    backendUpdateMarkEl.hidden = false;
    backendUpdateMarkEl.classList.add("review");
    backendUpdateMarkEl.textContent = "↑!";
    backendUpdateMarkEl.title = I18N.tr(`${risky} mise${risky > 1 ? "s" : ""} à jour à vérifier pour compatibilité`);
  } else if (kittyUpdate) {
    backendUpdateMarkEl.hidden = false;
    backendUpdateMarkEl.classList.add("available");
    backendUpdateMarkEl.textContent = "↑";
    backendUpdateMarkEl.title = `${I18N.tr("Mise à jour disponible")} · Kitty ${kittyRelease.latest_version || "?"}`;
  } else if (count > 0) {
    backendUpdateMarkEl.hidden = false;
    backendUpdateMarkEl.classList.add("available");
    backendUpdateMarkEl.textContent = "↑";
    backendUpdateMarkEl.title = I18N.tr(`${count} mise${count > 1 ? "s" : ""} à jour de dépendance disponible${count > 1 ? "s" : ""}`);
  }
}

function kittyReleaseStateText(release) {
  if (!release) return I18N.tr("Non vérifiée");
  if (release.ok === false || release.state === "error") return I18N.tr("Erreur");
  if (release.update_available) return I18N.tr("Mise à jour disponible");
  if (release.local_newer) return I18N.tr("Version locale plus récente");
  return I18N.tr("À jour");
}

function renderKittyUpdateButton(release) {
  if (!downloadKittyUpdateBtn) return;
  const available = Boolean(release?.update_available);
  downloadKittyUpdateBtn.hidden = !available;
  downloadKittyUpdateBtn.disabled = available && !release?.download_supported;
  downloadKittyUpdateBtn.textContent = I18N.tr("Télécharger la mise à jour");
  downloadKittyUpdateBtn.title = available && !release?.download_supported
    ? I18N.tr(release?.error || "SHA-256 de la release indisponible")
    : "";
}

function compatibilityText(compatibility) {
  if (!compatibility) return I18N.tr("backend ancien · update requis");
  const front = compatibility.frontend_version || FRONTEND_VERSION;
  const back = compatibility.backend_version || "?";
  return compatibility.compatible
    ? `${front} ↔ ${back} ✓`
    : `${front} ↔ ${back} · ${I18N.tr("update requis")}`;
}

function renderDiagnosticsHealth(response) {
  const r = response || {};
  const deps = Array.isArray(r.dependencies?.items) ? r.dependencies.items : [];
  const overall = ["ready", "warning", "error"].includes(r.overall)
    ? r.overall
    : "error";
  const updates = r.updates_cached || null;
  const kittyRelease = r.kitty_release_cached || null;
  const updateItems = new Map(
    (Array.isArray(updates?.items) ? updates.items : []).map(item => [item.id, item])
  );
  renderBackendUpdateMark(r.compatibility, updates, kittyRelease);
  renderKittyUpdateButton(kittyRelease);

  dependencyStateEl.classList.remove("ready", "warning", "error");
  dependencyStateEl.classList.add(overall);
  updateDependenciesHeaderState(overall);

  const missingRequired = Array.isArray(r.dependencies?.required_missing)
    ? r.dependencies.required_missing.length
    : 0;
  const missingOptional = Array.isArray(r.dependencies?.optional_missing)
    ? r.dependencies.optional_missing.length
    : 0;

  if (overall === "error") {
    dependencyStateTextEl.textContent =
      missingRequired > 0
        ? I18N.tr(`${missingRequired} dépendance${missingRequired > 1 ? "s" : ""} requise${missingRequired > 1 ? "s" : ""} absente${missingRequired > 1 ? "s" : ""}`)
        : I18N.tr("Kitty nécessite une intervention");
  } else if (overall === "warning") {
    dependencyStateTextEl.textContent =
      I18N.tr(missingOptional > 0 ? "Prêt · optionnel manquant" : "Prêt · attention");
  } else {
    dependencyStateTextEl.textContent = I18N.tr("Toutes les dépendances sont prêtes");
  }

  dependencyListEl.replaceChildren();

  if (!deps.length) {
    const empty = document.createElement("div");
    empty.className = "dependencyItem error";
    empty.innerHTML =
      `<span class="dependencyDot"></span>` +
      `<span class="dependencyName">Diagnostic</span>` +
      `<span class="dependencyValue">${escapeHtml(I18N.tr("indisponible"))}</span>`;
    dependencyListEl.appendChild(empty);
  } else {
    for (const dep of deps) {
      const row = document.createElement("div");
      const state = dep.ok ? "ready" : (dep.required ? "error" : "warning");
      row.className = `dependencyItem ${state}`;

      const update = updateItems.get(dep.id);
      const baseValue = dep.ok
        ? compactVersion(dep)
        : I18N.tr(dep.required ? "requis · absent" : "optionnel · absent");
      const value = update?.update_available
        ? `${baseValue} → ${update.available || "?"}${update.potential_incompatibility ? " ⚠" : " ↑"}`
        : baseValue;

      row.innerHTML =
        `<span class="dependencyDot" aria-hidden="true"></span>` +
        `<span class="dependencyName">${escapeHtml(dep.label || dep.id || "?")}</span>` +
        `<span class="dependencyValue" title="${escapeHtml(dep.error || dep.version || "")}">${escapeHtml(value)}</span>`;
      dependencyListEl.appendChild(row);
    }
  }

  const destination = r.system?.destination || {};
  const runtime = r.system?.runtime_files || {};
  const cache = r.system?.cache || {};
  renderCacheHealth(cache);
  const writeText = destination.writable
    ? (destination.write_tested ? "testée ✓" : "OK")
    : "erreur";
  const hostText = runtime.ok ? "OK" : "fichier manquant";
  const stateText = r.system?.state_ok ? "queue OK" : "erreur";

  const migration = r.system?.migration || {};
  const migrationText = migration.status === "completed"
    ? (migration.legacy_found ? "V7 → V8 ✓" : "installation fraîche")
    : (migration.status || "—");

  const updateText = updates
    ? (updates.updates_available
      ? `${updates.updates_available} disponible${updates.updates_available > 1 ? "s" : ""}${updates.risky_updates ? ` · ${updates.risky_updates} à vérifier` : ""}`
      : "aucune détectée")
    : "non vérifiées";
  const latestKitty = kittyRelease?.latest_version || "—";
  document.getElementById("backendCompatibility").textContent = compatibilityText(r.compatibility);
  document.getElementById("backendReleaseState").textContent = kittyReleaseStateText(kittyRelease);
  document.getElementById("backendLatestRelease").textContent = latestKitty;
  document.getElementById("backendDependencyUpdates").textContent = I18N.tr(updateText);

  diagnosticFactsEl.innerHTML =
    `<div class="diagnosticFact">Destination : <strong>${escapeHtml(writeText)}</strong></div>` +
    `<div class="diagnosticFact">Espace libre : <strong>${escapeHtml(formatBytes(destination.free_bytes))}</strong></div>` +
    `<div class="diagnosticFact">Fichiers du backend : <strong>${escapeHtml(hostText)}</strong></div>` +
    `<div class="diagnosticFact">Cache : <strong>${escapeHtml(formatBytes(cache.total_bytes || 0))}</strong></div>` +
    `<div class="diagnosticFact">Logs : <strong>${escapeHtml(formatBytes(cache.logs_bytes || 0))}</strong></div>` +
    `<div class="diagnosticFact">Récupérable : <strong>${escapeHtml(formatBytes(cache.reclaimable_bytes || 0))}</strong></div>` +
    `<div class="diagnosticFact">Partiels orphelins : <strong>${escapeHtml(orphanPartialsText(cache))}</strong></div>` +
    `<div class="diagnosticFact">État : <strong>${escapeHtml(stateText)}</strong></div>` +
    `<div class="diagnosticFact">Migration : <strong>${escapeHtml(migrationText)}</strong></div>`;
}

async function restoreDiagnostics(deep = false) {
  refreshDiagnosticsBtn.disabled = true;
  runDiagnosticsBtn.disabled = true;

  try {
    const r = await nativeMessage({ action: "diagnostics", deep: Boolean(deep) });
    if (!r?.ok) throw new Error(r?.error || "Diagnostic indisponible.");
    renderDiagnosticsHealth(r);
    return r;
  } catch (err) {
    dependencyStateEl.classList.remove("ready", "warning");
    dependencyStateEl.classList.add("error");
    updateDependenciesHeaderState("error");
    dependencyStateTextEl.textContent = "Diagnostic indisponible";
    dependencyListEl.innerHTML =
      `<div class="dependencyItem error">` +
      `<span class="dependencyDot"></span>` +
      `<span class="dependencyName">Native Host</span>` +
      `<span class="dependencyValue" title="${escapeHtml(err.message)}">erreur</span>` +
      `</div>`;
    throw err;
  } finally {
    refreshDiagnosticsBtn.disabled = false;
    runDiagnosticsBtn.disabled = false;
  }
}

function diagnosticCodeText(value) {
  const code = String(value ?? "");
  const language = I18N.getLanguage();
  const states = {
    ready: { fr: "prêt", en: "ready" },
    warning: { fr: "avertissement", en: "warning" },
    error: { fr: "erreur", en: "error" },
    active: { fr: "active", en: "active" },
    configured: { fr: "configurée", en: "configured" },
    "not configured": { fr: "non configurée", en: "not configured" },
    fresh: { fr: "installation fraîche", en: "fresh install" },
    completed: { fr: "terminée", en: "completed" },
    compatible: { fr: "compatible", en: "compatible" },
    incompatible: { fr: "incompatible", en: "incompatible" },
    up_to_date: { fr: "à jour", en: "up to date" },
    update_available: { fr: "mise à jour disponible", en: "update available" },
    local_newer: { fr: "version locale plus récente", en: "local version is newer" },
    aucun: { fr: "aucun", en: "none" },
  };
  return states[code]?.[language] || I18N.tr(code);
}

function diagnosticsToText(diagnostics) {
  const d = diagnostics || {};
  const line = (label, value, translateValue = true) =>
    `${I18N.tr(label)}: ${translateValue ? diagnosticCodeText(value) : String(value ?? "?")}`;

  const destinationFree = d.destination_free_bytes !== null && d.destination_free_bytes !== undefined
    ? formatBytes(d.destination_free_bytes)
    : (d.destination_free || "?");
  const cacheSize = d.cache_size_bytes !== null && d.cache_size_bytes !== undefined
    ? formatBytes(d.cache_size_bytes)
    : (d.cache_size || "?");
  const cacheReclaimable = d.cache_reclaimable_bytes !== null && d.cache_reclaimable_bytes !== undefined
    ? formatBytes(d.cache_reclaimable_bytes)
    : (d.cache_reclaimable || "?");
  const cacheTemporary = d.cache_temporary_bytes !== null && d.cache_temporary_bytes !== undefined
    ? formatBytes(d.cache_temporary_bytes)
    : (d.cache_temporary || "?");
  const updateBackups = d.update_backups_size_bytes !== null && d.update_backups_size_bytes !== undefined
    ? formatBytes(d.update_backups_size_bytes)
    : (d.update_backups_size || "?");
  const logsSize = d.log_size_bytes !== null && d.log_size_bytes !== undefined
    ? formatBytes(d.log_size_bytes)
    : (d.log_size || "?");
  const orphanSize = d.orphan_partials_size_bytes !== null && d.orphan_partials_size_bytes !== undefined
    ? formatBytes(d.orphan_partials_size_bytes)
    : (d.orphan_partials_size || "?");

  return [
    "Kitty Download Manager — diagnostic",
    line("Application", d.app_name || "Kitty Download Manager", false),
    line("Kitty backend", d.kitty_version || "?", false),
    line("Frontend", d.frontend_version || FRONTEND_VERSION, false),
    line("Compatibilité frontend/backend", d.frontend_backend || "?"),
    line("Protocole frontend/backend", `${d.frontend_protocol ?? "?"}/${d.backend_protocol ?? "?"}`, false),
    line("Dernière release", d.latest_kitty_version || "non vérifiée"),
    line("État release Kitty", d.kitty_release_state || "non vérifiée"),
    line("Mises à jour dépendances", d.updates_available ?? "non vérifiées"),
    line("Mises à jour à vérifier", d.risky_updates ?? "non vérifiées"),
    line("État global", d.overall || "?"),
    line("Migration", d.migration || "?"),
    line("Migration destination", d.migration_output || "?"),
    line("Schéma d’état", d.state_version ?? "?", false),
    line("Python", d.python || "?", false),
    line("yt-dlp", d.yt_dlp || "?", false),
    line("ffmpeg", d.ffmpeg || "?", false),
    line("ffprobe", d.ffprobe || "?", false),
    line("Mutagen", d.mutagen || "?", false),
    line("OS", d.os || "?", false),
    line("Bureau", d.desktop || "?", false),
    line("Host", d.host_path || "?", false),
    line("Worker", d.worker_path || "?", false),
    line("Worker métadonnées", d.metadata_path || "?", false),
    line("Destination", d.destination_status || "?"),
    line("Test écriture destination", d.destination_write_tested ? "oui" : "non"),
    line("Espace libre", destinationFree, false),
    line("Actif", d.active_status || "aucun"),
    line("Queue", d.queue_count ?? "?", false),
    line("Historique", d.history_count ?? "?", false),
    line("Cache total", cacheSize, false),
    line("Cache récupérable", cacheReclaimable, false),
    line("Cache temporaire", cacheTemporary, false),
    line("Backups update", updateBackups, false),
    line("Logs total", logsSize, false),
    line("Partiels orphelins", `${d.orphan_partials_count ?? 0} · ${orphanSize} · ${I18N.tr("non supprimés")}`, false),
    line("Log", d.log_path || "?", false),
    line("Backups état", d.backup_count ?? "?", false),
    line("YouTube auth", d.youtube_auth || "?"),
    "",
    I18N.tr("Confidentialité diagnostic:"),
    I18N.tr("- aucun accès réseau"),
    I18N.tr("- aucune URL/titre de téléchargement"),
    I18N.tr("- aucune valeur de cookie"),
  ].join("\n");
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {}

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch {}
  textarea.remove();
  return ok;
}

refreshDiagnosticsBtn.addEventListener("click", async () => {
  setSettingsStatus("Actualisation de l’état système…");
  try {
    await restoreDiagnostics(false);
    setSettingsStatus("État système actualisé.", "success");
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  }
});

runDiagnosticsBtn.addEventListener("click", async () => {
  setSettingsStatus("Auto-test local de Kitty…");
  try {
    const r = await restoreDiagnostics(true);
    if (r.overall === "error") {
      setSettingsStatus("Auto-test terminé : une intervention est nécessaire.", "error");
    } else if (r.overall === "warning") {
      setSettingsStatus("Auto-test terminé : Kitty fonctionne avec un avertissement.", "success");
    } else {
      setSettingsStatus("Auto-test terminé : tout est prêt.", "success");
    }
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  }
});

checkUpdatesBtn.addEventListener("click", async () => {
  checkUpdatesBtn.disabled = true;
  setSettingsStatus("Vérification réseau des mises à jour…");
  try {
    const result = await nativeMessage({ action: "check_updates" });
    if (!result?.ok) throw new Error(result?.error || "Vérification des mises à jour impossible.");
    const updates = result.updates || {};
    const kittyRelease = result.kitty_release || {};
    await restoreDiagnostics(false);

    if (kittyRelease.update_available) {
      if (kittyRelease.download_supported) {
        setSettingsStatus(`Kitty ${kittyRelease.latest_version} · ${I18N.tr("Mise à jour disponible")}.`, "success");
      } else {
        setSettingsStatus(`Kitty ${kittyRelease.latest_version} · ${I18N.tr(kittyRelease.error || "SHA-256 de la release indisponible")}.`, "error");
      }
    } else if (kittyRelease.ok === false) {
      setSettingsStatus(`Kitty · ${I18N.tr("Vérification de la mise à jour Kitty impossible")}.`, "error");
    } else if (updates.risky_updates > 0) {
      setSettingsStatus(
        `${updates.updates_available} mise(s) à jour · ${updates.risky_updates} demande(nt) une vérification de compatibilité.`,
        "error"
      );
    } else if (updates.updates_available > 0) {
      setSettingsStatus(`${updates.updates_available} mise(s) à jour disponible(s).`, "success");
    } else if (kittyRelease.local_newer) {
      setSettingsStatus(`Kitty ${FRONTEND_VERSION} · ${I18N.tr("Version locale plus récente")}.`, "success");
    } else {
      setSettingsStatus(`Kitty ${FRONTEND_VERSION} · ${I18N.tr("À jour")}.`, "success");
    }
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  } finally {
    checkUpdatesBtn.disabled = false;
  }
});

downloadKittyUpdateBtn?.addEventListener("click", async () => {
  downloadKittyUpdateBtn.disabled = true;
  setSettingsStatus("Téléchargement de la mise à jour Kitty…");
  try {
    const result = await nativeMessage({ action: "download_kitty_update" });
    if (!result?.ok) {
      const message = I18N.tr(result?.error || "Téléchargement de la mise à jour impossible");
      const hint = result?.error_hint ? ` · ${I18N.tr(result.error_hint)}` : "";
      throw new Error(message + hint);
    }
    downloadKittyUpdateBtn.textContent = `✓ ${I18N.tr("SHA-256 vérifié")}`;
    setSettingsStatus(
      `${I18N.tr("Archive de mise à jour téléchargée et SHA-256 vérifié.")} ${result.path || ""}`.trim(),
      "success"
    );
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  } finally {
    setTimeout(() => {
      if (downloadKittyUpdateBtn) {
        downloadKittyUpdateBtn.disabled = false;
        downloadKittyUpdateBtn.textContent = I18N.tr("Télécharger la mise à jour");
      }
    }, 1200);
  }
});

openLogsBtn.addEventListener("click", async () => {
  openLogsBtn.disabled = true;
  setSettingsStatus("Ouverture des logs…");
  try {
    const r = await nativeMessage({ action: "open_logs" });
    if (!r?.ok) throw new Error(r?.error || "Impossible d'ouvrir les logs.");
    setSettingsStatus("Logs ouverts.", "success");
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  } finally {
    openLogsBtn.disabled = false;
  }
});

copyDiagnosticsBtn.addEventListener("click", async () => {
  copyDiagnosticsBtn.disabled = true;
  setSettingsStatus("Préparation du diagnostic local…");
  try {
    const r = await nativeMessage({ action: "diagnostics", deep: true });
    if (!r?.ok) throw new Error(r?.error || "Diagnostic indisponible.");
    renderDiagnosticsHealth(r);
    const ok = await copyText(diagnosticsToText(r.diagnostics));
    if (!ok) throw new Error("Impossible de copier dans le presse-papiers.");
    setSettingsStatus("Diagnostic copié · sans URL, titre ni cookie.", "success");
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  } finally {
    copyDiagnosticsBtn.disabled = false;
  }
});


cleanCacheBtn?.addEventListener("click", async () => {
  cleanCacheBtn.disabled = true;
  setSettingsStatus("Nettoyage du cache…");
  try {
    const r = await nativeMessage({ action: "clean_cache" });
    if (!r?.ok) throw new Error(r?.error || "Nettoyage du cache impossible.");
    renderCacheHealth(r.cache || {});
    const freed = Number(r.freed_bytes || 0);
    const removed = Number(r.removed || 0);
    if (freed > 0 || removed > 0) {
      setSettingsStatus(`Cache nettoyé : ${formatBytes(freed)} libérés · ${removed} élément${removed > 1 ? "s" : ""} supprimé${removed > 1 ? "s" : ""}.`, "success");
    } else {
      setSettingsStatus("Rien à nettoyer dans le cache.", "success");
    }
    await restoreDiagnostics(false);
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  } finally {
    cleanCacheBtn.disabled = false;
  }
});


let resetConfirmTimer = 0;
let resetConfirming = false;

function clearResetConfirmation() {
  if (resetConfirmTimer) clearTimeout(resetConfirmTimer);
  resetConfirmTimer = 0;
  resetConfirming = false;
  resetKittyBtn.classList.remove("confirming");
  resetKittyBtn.textContent = "Réinitialiser Kitty";
}

resetKittyBtn.addEventListener("click", async () => {
  if (!resetConfirming) {
    resetConfirming = true;
    resetKittyBtn.classList.add("confirming");
    resetKittyBtn.textContent = "Confirmer la réinitialisation";
    setSettingsStatus("Clique une seconde fois pour confirmer.");
    resetConfirmTimer = setTimeout(clearResetConfirmation, 4500);
    return;
  }

  clearResetConfirmation();
  resetKittyBtn.disabled = true;
  setSettingsStatus("Réinitialisation de Kitty…");

  try {
    const r = await nativeMessage({ action: "reset_kitty" });
    if (!r?.ok) throw new Error(r?.error || "Réinitialisation impossible.");
    if (r.state) render(r.state);
    setSettingsStatus("Kitty a été réinitialisé. Tes vidéos et réglages sont conservés.", "success");
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  } finally {
    resetKittyBtn.disabled = false;
  }
});

function renderDestination(path) {
  const value = path || "Dossier inconnu";
  destinationPathEl.textContent = value;
  destinationPathEl.title = value;
  openFolderBtn.title = `Ouvrir : ${value}`;
}

async function restoreDestination() {
  // Affichage immédiat du dernier chemin confirmé, puis validation auprès
  // du backend. Le cache est utile si la popup a été fermée par le dialogue
  // natif pendant le changement de dossier.
  try {
    const cached = await browser.storage.local.get("kittyOutputDir");
    if (cached?.kittyOutputDir) renderDestination(cached.kittyOutputDir);
  } catch {}

  try {
    const r = await browser.runtime.sendMessage({ type: "kitty-get-output-dir" });
    if (!r?.ok) throw new Error(r?.error || "Impossible de lire les réglages.");
    renderDestination(r.settings?.output_dir || r.output_dir);
  } catch (err) {
    if (!destinationPathEl.textContent || I18N.matches(destinationPathEl.textContent, "Chargement…")) {
      destinationPathEl.textContent = "Destination indisponible";
      destinationPathEl.title = err.message;
    }
  }
}

chooseDestinationBtn.addEventListener("click", async () => {
  chooseDestinationBtn.disabled = true;
  const oldText = chooseDestinationBtn.textContent;
  chooseDestinationBtn.textContent = "…";
  setSettingsStatus("Choisis le nouveau dossier…");

  try {
    // Important : le dialogue natif peut fermer la popup Firefox. Le travail
    // réel est donc confié au background, qui reste propriétaire de la requête.
    const r = await browser.runtime.sendMessage({ type: "kitty-choose-output-dir" });

    if (!r?.ok) {
      throw new Error(r?.error || "Impossible de choisir le dossier.");
    }

    if (!r.cancelled) {
      const path = r.output_dir || r.settings?.output_dir;
      if (path) renderDestination(path);
      setSettingsStatus("Dossier de destination mis à jour.", "success");
    }
  } catch (err) {
    setSettingsStatus("Erreur : " + err.message, "error");
  } finally {
    chooseDestinationBtn.disabled = false;
    chooseDestinationBtn.textContent = oldText;
  }
});


const PILL_STYLE_META = Object.freeze({
  minimal: {
    label: "Minimal",
    preview: `<span class="pillPreviewMinimal">↓</span>`,
  },
  cat: {
    label: "Kitty",
    preview: `<span class="pillPreviewCat">ᓚᘏᗢ</span>`,
  },
  classic: {
    label: "Classique",
    preview:
      `<span class="pillPreviewClassic">` +
      `<span class="pillPreviewClassicCat">ᓚᘏᗢ</span>` +
      `<span class="pillPreviewClassicDownload">↓</span>` +
      `</span>`,
  },
});

let pillStyleMenuOpen = false;

function normalizePillStyle(value) {
  if (Object.prototype.hasOwnProperty.call(PILL_STYLE_META, value)) {
    return value;
  }
  return "cat";
}

function renderPillStyle(style) {
  const normalized = normalizePillStyle(style);
  const meta = PILL_STYLE_META[normalized];

  pillStyleButtonEl.dataset.pillStyle = normalized;
  pillStyleCurrentLabelEl.textContent = meta.label;
  pillStyleCurrentPreviewEl.innerHTML = meta.preview;

  pillStyleOptions.forEach(option => {
    const active = option.dataset.pillStyle === normalized;
    option.classList.toggle("active", active);
    option.setAttribute("aria-selected", active ? "true" : "false");
  });
}

function setPillStyleMenuOpen(open) {
  pillStyleMenuOpen = Boolean(open);
  pillStyleMenuEl.hidden = !pillStyleMenuOpen;
  pillStyleButtonEl.setAttribute(
    "aria-expanded",
    pillStyleMenuOpen ? "true" : "false"
  );
}

async function selectPillStyle(style, { persist = true } = {}) {
  const normalized = normalizePillStyle(style);
  renderPillStyle(normalized);
  setPillStyleMenuOpen(false);

  if (persist) {
    await browser.storage.local.set({ pillStyle: normalized });
    setSettingsStatus(`Style du pill : ${PILL_STYLE_META[normalized].label}.`, "success");
  }
}

pillStyleButtonEl.addEventListener("click", event => {
  event.stopPropagation();
  setPillStyleMenuOpen(!pillStyleMenuOpen);
});

pillStyleMenuEl.addEventListener("click", event => {
  event.stopPropagation();
});

pillStyleOptions.forEach(option => {
  option.addEventListener("click", async () => {
    try {
      await selectPillStyle(option.dataset.pillStyle);
    } catch {
      setSettingsStatus("Impossible d'enregistrer le style du pill.", "error");
    }
  });
});

async function restorePillSettings() {
  try {
    const saved = await browser.storage.local.get(["pillEnabled", "pillScope", "pillStyle"]);
    pillEnabledEl.checked = saved.pillEnabled !== false;
    pillScopeEl.value = saved.pillScope === "media" ? "media" : "all";
    renderPillStyle(normalizePillStyle(saved.pillStyle));
  } catch {}
}

pillEnabledEl.addEventListener("change", async () => {
  try {
    await browser.storage.local.set({ pillEnabled: pillEnabledEl.checked });
    setSettingsStatus("Réglage du pill mis à jour.", "success");
  } catch {
    setSettingsStatus("Impossible d'enregistrer le réglage du pill.", "error");
  }
});

pillScopeEl.addEventListener("change", async () => {
  try {
    await browser.storage.local.set({ pillScope: pillScopeEl.value });
    setSettingsStatus("Portée du pill mise à jour.", "success");
  } catch {
    setSettingsStatus("Impossible d'enregistrer la portée du pill.", "error");
  }
});


async function restoreModeSelection() {
  try {
    const saved = await browser.storage.local.get([
      "selectedMode",
      "playlistMode",
      "playlistUrl"
    ]);

    if (saved?.selectedMode && FORMAT_LONG_LABELS[saved.selectedMode]) {
      modeEl.value = saved.selectedMode;
    }

    playlistUrlEl.value =
      typeof saved?.playlistUrl === "string" ? saved.playlistUrl : "";
    playlistModeEnabled = Boolean(saved?.playlistMode);
  } catch {}

  updateModePickerUI();
  updatePlaylistUrlStatus();
}

modeButtonEl.addEventListener("click", (event) => {
  event.stopPropagation();
  setModeMenuOpen(!modeMenuOpen);
});

modeMenuEl.addEventListener("click", event => {
  event.stopPropagation();
});

modeMenuItems.forEach(item => {
  item.addEventListener("click", async () => {
    const nextMode = item.dataset.mode;
    if (!FORMAT_LONG_LABELS[nextMode]) return;

    modeEl.value = nextMode;
    resetDownloadButton();
    updateModePickerUI();

    try {
      await browser.storage.local.set({ selectedMode: nextMode });
    } catch {}

    // En mode Playlist, garder volontairement tout le menu ouvert afin de
    // montrer simultanément le format actif et le toggle Playlist actif.
    if (!playlistModeEnabled) setModeMenuOpen(false);
  });
});

playlistModeToggleEl.addEventListener("click", () => {
  setPlaylistMode(!playlistModeEnabled);
});

playlistUrlEl.addEventListener("input", () => {
  updatePlaylistUrlStatus();
  browser.storage.local.set({ playlistUrl: playlistUrlEl.value }).catch(() => {});
});

playlistUrlEl.addEventListener("keydown", event => {
  if (event.key === "Enter") {
    event.preventDefault();
    downloadBtn.click();
  }
});

document.addEventListener("click", event => {
  if (modeMenuOpen && !modePickerEl.contains(event.target)) {
    setModeMenuOpen(false);
  }
  if (pillStyleMenuOpen && !pillStylePickerEl.contains(event.target)) {
    setPillStyleMenuOpen(false);
  }
});

document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;

  if (modeMenuOpen) {
    setModeMenuOpen(false);
    modeButtonEl.focus();
  }

  if (pillStyleMenuOpen) {
    setPillStyleMenuOpen(false);
    pillStyleButtonEl.focus();
  }
});


async function resolveTabDownloadUrl(tab) {
  if (!tab?.url || !/^https?:\/\//i.test(tab.url)) {
    throw new Error("URL HTTP/HTTPS requise.");
  }

  // Le resolver vit dans la page : il voit le média réellement affiché,
  // contrairement à la popup qui ne voit que l'URL de l'onglet.
  let resolved = null;
  try {
    resolved = await browser.tabs.sendMessage(tab.id, {
      type: "kitty-resolve-media-url"
    });
  } catch {
    // Content script indisponible : comportement historique sûr.
    return tab.url;
  }

  if (resolved?.ok && resolved?.url) return resolved.url;
  if (resolved?.error) throw new Error(resolved.error);
  return tab.url;
}

async function submitPlaylistDownload() {
  const playlistUrl = playlistUrlEl.value.trim();

  if (!playlistUrl) {
    updatePlaylistUrlStatus("Colle d’abord l’URL de la playlist.", "error");
    playlistUrlEl.focus();
    return;
  }

  if (!classifyCollectionUrl(playlistUrl).valid) {
    updatePlaylistUrlStatus(
      "URL de playlist ou collection invalide.",
      "error"
    );
    playlistUrlEl.focus();
    return;
  }

  resetDownloadButton();
  downloadBtn.disabled = true;
  downloadBtn.textContent = "Lecture de la collection…";
  updatePlaylistUrlStatus("Analyse de la collection avec yt-dlp…");

  try {
    // Le background possède la requête : fermer la popup pendant l’analyse
    // ne doit pas couper le Native Messaging host.
    const r = await browser.runtime.sendMessage({
      type: "kitty-download-playlist",
      url: playlistUrl,
      mode: modeEl.value
    });

    if (!r?.ok) {
      throw new Error(backendErrorMessage(r, "Impossible d’ajouter cette playlist."));
    }

    stickyJobId = r.first_job_id || r.state?.active?.id || stickyJobId;
    if (r.state) render(r.state);

    const added = Number(r.added_count || 0);
    const skipped = Number(r.skipped_count || 0);
    const total = Number(r.detected_count || added + skipped);
    const title = r.playlist_title ? `« ${r.playlist_title} »` : "Collection";
    const provider = r.collection_provider || "";
    const kind = r.collection_kind || "Collection";
    const sourceLabel = provider ? `${provider} · ${kind}` : kind;

    if (added > 0) {
      updatePlaylistUrlStatus(
        `✓ ${sourceLabel} · ${title} · ${added}/${total} élément${total > 1 ? "s" : ""} ajouté${added > 1 ? "s" : ""}` +
        (skipped ? ` · ${skipped} déjà présent${skipped > 1 ? "s" : ""}` : ""),
        "valid"
      );
      statusEl.textContent =
        `${added} élément${added > 1 ? "s" : ""} ajouté${added > 1 ? "s" : ""} à la file.` +
        (skipped ? ` ${skipped} ignoré${skipped > 1 ? "s" : ""} car déjà pris${skipped > 1 ? "s" : ""} en charge.` : "");
    } else {
      updatePlaylistUrlStatus(
        `✓ ${sourceLabel} · ${title} · tous les éléments sont déjà pris en charge`,
        "valid"
      );
      statusEl.textContent = "Aucun nouvel élément à ajouter.";
    }
  } catch (err) {
    updatePlaylistUrlStatus("Erreur : " + err.message, "error");
    statusEl.textContent = "Erreur collection : " + err.message;
  } finally {
    downloadBtn.disabled = false;
    renderBackendConnection();
    resetDownloadButton();
  }
}

downloadBtn.addEventListener("click", async () => {
  if (playlistModeEnabled) {
    await submitPlaylistDownload();
    return;
  }

  try {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    const downloadUrl = await resolveTabDownloadUrl(tab);

    const samePending =
      pendingDuplicate &&
      pendingDuplicate.url === downloadUrl &&
      pendingDuplicate.mode === modeEl.value;

    const force = Boolean(samePending);
    statusEl.textContent = force ? "Nouveau téléchargement…" : "Démarrage…";

    const r = await nativeMessage({
      action: "download",
      url: downloadUrl,
      mode: modeEl.value,
      force
    });

    if (!r?.ok) {
      if (r?.code === "already_downloaded") {
        pendingDuplicate = { url: downloadUrl, mode: modeEl.value };
        downloadBtn.textContent = "Retélécharger quand même";
        downloadBtn.classList.add("duplicatePending");
        setDownloadSectionPhase("duplicate");
        titleEl.classList.remove("activeLoading");
        titleEl.textContent = r.previous?.title || "Ce média a déjà été téléchargé";
        percentEl.textContent = "✓";
        progressEl.value = 100;
        statsEl.textContent = r.previous?.filepath || "";
        statusEl.textContent = "Déjà téléchargé — clique à nouveau pour le retélécharger.";
        return;
      }

      if (r?.code === "already_active" || r?.code === "already_queued") {
        resetDownloadButton();
        stickyJobId = r.job_id || stickyJobId;
        if (r.state) render(r.state);
        statusEl.textContent = r.error || "Ce téléchargement est déjà pris en charge.";
        return;
      }

      throw new Error(backendErrorMessage(r, "Impossible d'ajouter le téléchargement."));
    }

    resetDownloadButton();
    stickyJobId = r.job_id || r.state?.active?.id || stickyJobId;
    if (r.state?.active && (!stickyJobId || r.state.active.id === stickyJobId)) {
      stickyActive = r.state.active;
    }
    idlePolls = 0;
    render(r.state || {});
  } catch (err) {
    statusEl.textContent = "Erreur : " + err.message;
  }
});



cancelBtn.addEventListener("click", async () => {
  cancelBtn.disabled = true;
  statusEl.textContent = "Annulation et nettoyage du fichier partiel…";
  const r = await nativeMessage({ action: "cancel" });
  if (r?.state) render(r.state);
  schedulePopupPoll(150);
});


let clearQueueConfirming = false;
let clearQueueConfirmTimer = 0;

function resetClearQueueConfirmation() {
  clearQueueConfirming = false;
  if (clearQueueConfirmTimer) {
    clearTimeout(clearQueueConfirmTimer);
    clearQueueConfirmTimer = 0;
  }
  clearQueueBtn.textContent = "Vider la file";
  clearQueueBtn.classList.remove("confirming");
}

clearQueueBtn.addEventListener("click", async () => {
  const queuedCount = Array.isArray(latestState?.queue) ? latestState.queue.length : 0;

  if (!queuedCount) {
    resetClearQueueConfirmation();
    statusEl.textContent = "La file d’attente est déjà vide.";
    return;
  }

  if (!clearQueueConfirming) {
    clearQueueConfirming = true;
    clearQueueBtn.textContent = `Confirmer (${queuedCount})`;
    clearQueueBtn.classList.add("confirming");
    clearQueueConfirmTimer = setTimeout(resetClearQueueConfirmation, 4500);
    return;
  }

  clearQueueBtn.disabled = true;

  try {
    const r = await nativeMessage({ action: "clear_queue" });
    if (!r?.ok) throw new Error(backendErrorMessage(r, "Impossible de vider la file."));

    resetClearQueueConfirmation();
    if (r?.state) render(r.state);

    const removed = Number(r?.removed_count || 0);
    statusEl.textContent = removed
      ? `${removed} élément${removed > 1 ? "s" : ""} retiré${removed > 1 ? "s" : ""} de la file.`
      : "La file d’attente est déjà vide.";
  } catch (err) {
    resetClearQueueConfirmation();
    statusEl.textContent = "Erreur : " + err.message;
  } finally {
    clearQueueBtn.disabled = !(Array.isArray(latestState?.queue) && latestState.queue.length);
  }
});


pauseQueueBtn.addEventListener("click", async () => {
  pauseQueueBtn.disabled = true;
  const action = latestState.queue_paused ? "resume_queue" : "pause_queue";
  const r = await nativeMessage({ action });
  if (r?.state) render(r.state);
  if (!r?.ok) statusEl.textContent = "Erreur : " + (r?.error || "Impossible de modifier la file.");
});

openFolderBtn.addEventListener("click", async () => {
  const r = await nativeMessage({ action: "open_folder" });
  if (!r?.ok) statusEl.textContent = "Erreur : " + (r?.error || "Impossible d'ouvrir le dossier.");
});

clearHistoryBtn.addEventListener("click", async () => {
  const r = await nativeMessage({ action: "clear_history" });
  if (r?.state) render(r.state);
});

function clearPopupPoll() {
  if (popupPollTimer) {
    clearTimeout(popupPollTimer);
    popupPollTimer = 0;
  }
}

function schedulePopupPoll(delay) {
  if (!popupInitialized) return;
  clearPopupPoll();
  popupPollTimer = setTimeout(async () => {
    popupPollTimer = 0;
    const state = await refresh(false, 5000);
    schedulePopupPoll(state?.active ? 750 : (backendConnection.kind === "ready" ? 1800 : 5000));
  }, delay);
}

document.addEventListener("click", async event => {
  const button = event.target.closest?.("[data-open-source]");
  if (!button) return;

  event.preventDefault();
  event.stopPropagation();

  const url = button.dataset.openSource || "";
  if (!url) return;
  await openSourceUrl(url);
});

document.addEventListener("visibilitychange", () => {
  if (!popupInitialized) return;
  if (document.visibilityState === "visible") schedulePopupPoll(100);
  else clearPopupPoll();
});

async function initializePopup() {
  let state = null;
  renderBackendConnection();
  try {
    // One startup owner. All visible preferences and the first fresh backend
    // render finish before the placeholder markup becomes visible.
    const results = await Promise.allSettled([
      restoreUiLanguage(),
      chooseHeaderMascot(),
      restoreSectionStates(),
      restoreSettingsSectionStates(),
      restorePillSettings(),
      restoreModeSelection(),
      prepareBackendInstaller(),
      refresh(false, 5000)
    ]);
    const firstStatus = results[results.length - 1];
    if (firstStatus.status === "fulfilled") state = firstStatus.value;
    I18N.apply(document.body);
  } finally {
    document.documentElement.classList.remove("popup-loading");
    document.body.setAttribute("aria-busy", "false");
    popupInitialized = true;
    schedulePopupPoll(state?.active ? 750 : 1800);
  }

  // Hidden settings do not block the first frame or compete with its status
  // request. Opening Settings still refreshes these values normally.
  restoreDestination();
  restoreYoutubeAuth();
}

initializePopup().catch(error => {
  statusEl.textContent = "Erreur : " + error.message;
});
