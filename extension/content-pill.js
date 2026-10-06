(() => {
  if (window.top !== window) return;
  if (document.getElementById("kitty-download-manager-pill-host")) return;

  const {
    COLORS,
    jobPhase,
    jobPercent,
    findJob,
    queuePosition,
    compactPosition
  } = globalThis.KittyShared;
  const I18N = globalThis.KittyI18n;

  const MEDIA_HOSTS = [
    "youtube.com", "youtu.be", "vimeo.com", "tiktok.com", "instagram.com",
    "x.com", "twitter.com", "facebook.com", "reddit.com", "soundcloud.com",
    "twitch.tv", "dailymotion.com", "pinterest.com"
  ];

  let host;
  let shadow;
  let pill;
  let downloadButton;
  let closeButton;
  let statusText;
  let mascot;
  let pollTimer = 0;
  let dragState = null;
  let trackedJobId = null;
  let duplicatePending = false;
  let transientHidden = false;
  let resetTimer = 0;
  let currentVariant = "cat";
  let currentStateKind = "idle";
  let currentStateText = "Download";
  let suppressNextDownloadClick = false;

  function isMediaSite() {
    const hostname = location.hostname.replace(/^www\./, "").toLowerCase();

    // Pinterest utilise aussi pinterest.fr, pinterest.de, pinterest.co.uk, etc.
    if (/^(?:[^.]+\.)*pinterest\.[a-z.]+$/i.test(hostname)) return true;

    return MEDIA_HOSTS.some(domain => hostname === domain || hostname.endsWith("." + domain));
  }


  const {
    resolveMediaUrlForPage,
    comparableMediaUrl
  } = globalThis.KittyMediaResolver;


  const PILL_VARIANTS = new Set(["minimal", "cat", "classic"]);

  function normalizePillVariant(value) {
    return PILL_VARIANTS.has(value) ? value : "cat";
  }

  async function getSettings() {
    try {
      const saved = await browser.storage.local.get([
        "pillEnabled", "pillScope", "pillStyle", "uiLanguage", "kittyPillPosition"
      ]);
      return {
        enabled: saved.pillEnabled !== false,
        scope: saved.pillScope === "media" ? "media" : "all",
        variant: normalizePillVariant(saved.pillStyle),
        language: I18N.normalize(saved.uiLanguage),
        position: saved.kittyPillPosition || null
      };
    } catch {
      return { enabled: true, scope: "all", variant: "cat", language: "fr", position: null };
    }
  }

  function clampPosition(left, top) {
    const rect = pill?.getBoundingClientRect();
    const width = rect?.width || 190;
    const height = rect?.height || 44;
    return {
      left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
      top: Math.max(8, Math.min(top, window.innerHeight - height - 8))
    };
  }

  async function savePosition(left, top) {
    try {
      await browser.storage.local.set({
        kittyPillPosition: { left: Math.round(left), top: Math.round(top) }
      });
    } catch {}
  }

  function applyPosition(position) {
    requestAnimationFrame(() => {
      const fallback = {
        left: Math.max(8, window.innerWidth - pill.getBoundingClientRect().width - 14),
        top: 14
      };
      const p = position ? clampPosition(position.left, position.top) : fallback;
      pill.style.left = `${p.left}px`;
      pill.style.top = `${p.top}px`;
      pill.style.right = "auto";
    });
  }

  function clearResetTimer() {
    if (resetTimer) {
      clearTimeout(resetTimer);
      resetTimer = 0;
    }
  }

  function applyVariant(variant) {
    currentVariant = normalizePillVariant(variant);
    if (!pill) return;

    pill.dataset.variant = currentVariant;
    setVisualState(currentStateKind, currentStateText);

    requestAnimationFrame(() => {
      if (!pill?.isConnected) return;
      const rect = pill.getBoundingClientRect();
      const p = clampPosition(rect.left, rect.top);
      pill.style.left = `${p.left}px`;
      pill.style.top = `${p.top}px`;
    });
  }

  function setVisualState(kind, text = "") {
    clearResetTimer();
    currentStateKind = kind;
    currentStateText = text;
    pill.dataset.state = kind;
    statusText.textContent = I18N.tr(text);
    mascot.textContent = "ᓚᘏᗢ";

    const visual = {
      idle: { icon: "↓", title: "Télécharger cette page", disabled: false },
      duplicate: { icon: "↻", title: "Retélécharger quand même", disabled: false },
      queued: { icon: "•", title: text || "Téléchargement dans la file", disabled: true },
      metadata: { icon: "…", title: text || "Récupération des métadonnées", disabled: true },
      paused: { icon: "⏸", title: text || "En pause", disabled: true },
      downloading: { icon: "↓", title: text || "Téléchargement en cours", disabled: true },
      finished: { icon: "✓", title: text || "Téléchargement terminé", disabled: true },
      error: { icon: "!", title: text || "Erreur", disabled: false },
    }[kind] || { icon: "↓", title: text || "Télécharger", disabled: false };

    downloadButton.textContent = currentVariant === "cat" ? "ᓚᘏᗢ" : visual.icon;
    downloadButton.dataset.actionDisabled = visual.disabled ? "true" : "false";
    downloadButton.disabled = currentVariant === "classic" && visual.disabled;
    downloadButton.setAttribute("aria-disabled", visual.disabled ? "true" : "false");
    const visualTitle = I18N.tr(visual.title);
    downloadButton.title = visualTitle;
    downloadButton.setAttribute("aria-label", visualTitle);

    if (currentVariant === "classic") {
      pill.removeAttribute("title");
    } else {
      pill.title = visualTitle;
    }
  }

  function resetToIdleSoon(delay) {
    clearResetTimer();
    resetTimer = setTimeout(() => {
      duplicatePending = false;
      setVisualState("idle", "Download");
    }, delay);
  }

  function clearPollTimer() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = 0;
    }
  }

  function scheduleNextPoll(delay = 0) {
    clearPollTimer();
    if (!host?.isConnected || transientHidden) return;
    if (document.visibilityState !== "visible") return;

    pollTimer = window.setTimeout(async () => {
      pollTimer = 0;
      await refreshStatus();
    }, Math.max(0, delay));
  }

  function adoptMatchingJob(state) {
    if (trackedJobId) return;

    const resolved = resolveMediaUrlForPage();
    if (!resolved.ok || !resolved.url) return;

    const currentUrl = comparableMediaUrl(resolved.url);

    if (comparableMediaUrl(state.active?.media_source?.page_url || state.active?.url) === currentUrl) {
      trackedJobId = state.active.id;
      return;
    }

    const queue = Array.isArray(state.queue) ? state.queue : [];
    const matching = queue.find(job => comparableMediaUrl(job?.media_source?.page_url || job?.url) === currentUrl);
    if (matching) trackedJobId = matching.id;
  }

  async function refreshStatus() {
    if (document.visibilityState !== "visible" || transientHidden || !host?.isConnected) {
      clearPollTimer();
      return;
    }

    let nextDelay = trackedJobId ? 900 : 15000;

    try {
      const response = await browser.runtime.sendMessage({ type: "kitty-pill-status" });
      if (!response?.ok) {
        scheduleNextPoll(nextDelay);
        return;
      }

      const state = response.state || {};
      adoptMatchingJob(state);

      if (!trackedJobId) {
        if (!duplicatePending) setVisualState("idle", "Download");
        scheduleNextPoll(15000);
        return;
      }

      const located = findJob(state, trackedJobId);

      if (!located) {
        nextDelay = 1100;
        scheduleNextPoll(nextDelay);
        return;
      }

      if (located.place === "queue") {
        const qpos = queuePosition(state, trackedJobId);
        let label = "En file";

        if (qpos?.kind === "priority") {
          if (qpos.next) {
            label = "En file • prochain";
          } else if (qpos.total > 1) {
            label = `En file • priorité ${qpos.current}/${qpos.total}`;
          }
        } else {
          const pos = compactPosition(state, trackedJobId);
          if (pos) label = `En file • ${pos}`;
        }

        setVisualState("queued", label);
        scheduleNextPoll(1100);
        return;
      }

      if (located.place === "active") {
        const phase = jobPhase(located.job);
        const pos = compactPosition(state, trackedJobId);

        if (phase === "metadata") {
          setVisualState("metadata", pos ? `Métadonnées • ${pos}` : "Métadonnées…");
        } else if (phase === "paused") {
          setVisualState("paused", pos ? `Pause • ${pos}` : "En pause");
        } else {
          const pct = jobPercent(located.job);
          const label = pct === null ? "En cours" : `${pct.toFixed(0)} %`;
          setVisualState("downloading", pos ? `${label} • ${pos}` : label);
        }

        scheduleNextPoll(900);
        return;
      }

      const phase = jobPhase(located.job);

      if (phase === "finished") {
        setVisualState("finished", "Terminé");
        trackedJobId = null;
        duplicatePending = false;
        resetToIdleSoon(1600);
        nextDelay = 15000;
      } else if (phase === "error") {
        setVisualState("error", located.job.error || "Erreur");
        downloadButton.title = I18N.tr(located.job.error_hint || located.job.error || "Erreur");
        trackedJobId = null;
        duplicatePending = false;
        resetToIdleSoon(2200);
        nextDelay = 15000;
      } else if (phase === "cancelled") {
        trackedJobId = null;
        duplicatePending = false;
        setVisualState("idle", "Download");
        nextDelay = 15000;
      }
    } catch {
      nextDelay = trackedJobId ? 1400 : 15000;
    }

    scheduleNextPoll(nextDelay);
  }

  async function triggerDownload() {
    if (downloadButton.dataset.actionDisabled === "true") return;

    const resolved = resolveMediaUrlForPage(true);
    if (!resolved.ok || !resolved.url) {
      duplicatePending = false;
      trackedJobId = null;
      setVisualState("error", "Vidéo non détectée");
      downloadButton.title = I18N.tr(resolved.error || "Impossible de détecter la vidéo.");
      resetToIdleSoon(2600);
      return;
    }

    const downloadUrl = resolved.url;
    const force = Boolean(
      duplicatePending && comparableMediaUrl(duplicatePending.url) === comparableMediaUrl(downloadUrl)
    );
    setVisualState("metadata", force ? "Relance…" : "Ajout…");

    try {
      const response = await browser.runtime.sendMessage({
        type: "kitty-pill-download",
        url: downloadUrl,
        force
      });

      if (!response?.ok) {
        if (response?.code === "already_downloaded") {
          duplicatePending = { url: downloadUrl };
          trackedJobId = null;
          setVisualState("duplicate", "Déjà téléchargé");
          return;
        }

        if (response?.code === "already_active" || response?.code === "already_queued") {
          duplicatePending = false;
          trackedJobId = response.job_id || null;
          scheduleNextPoll(100);
          return;
        }

        throw new Error(response?.error || "Impossible d'ajouter le téléchargement.");
      }

      duplicatePending = false;
      trackedJobId = response.job_id || null;
      setVisualState("metadata", "Métadonnées…");
      scheduleNextPoll(100);
    } catch (error) {
      duplicatePending = false;
      trackedJobId = null;
      setVisualState("error", error?.message || "Erreur");
      downloadButton.title = I18N.tr(error?.message || "Erreur");
      resetToIdleSoon(2200);
    }
  }

  function beginDrag(event) {
    if (event.button !== 0) return;

    const onDownload = event.target === downloadButton || downloadButton.contains?.(event.target);
    const onClose = event.target === closeButton || closeButton.contains?.(event.target);

    if (currentVariant === "classic" && (onDownload || onClose)) return;

    const captureTarget = currentVariant === "classic" ? pill : downloadButton;
    const rect = pill.getBoundingClientRect();
    dragState = {
      pointerId: event.pointerId,
      dx: event.clientX - rect.left,
      dy: event.clientY - rect.top,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
      captureTarget
    };

    try {
      captureTarget.setPointerCapture(event.pointerId);
    } catch {}
  }

  function moveDrag(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;

    if (!dragState.moved) {
      const mx = event.clientX - dragState.startX;
      const my = event.clientY - dragState.startY;
      if (Math.hypot(mx, my) < 5) return;

      dragState.moved = true;
      pill.classList.add("dragging");
    }

    const p = clampPosition(event.clientX - dragState.dx, event.clientY - dragState.dy);
    pill.style.left = `${p.left}px`;
    pill.style.top = `${p.top}px`;
    event.preventDefault();
  }

  function endDrag(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;

    const { moved, captureTarget } = dragState;
    if (moved) {
      const rect = pill.getBoundingClientRect();
      savePosition(rect.left, rect.top);

      if (currentVariant !== "classic") {
        suppressNextDownloadClick = true;
      }
    }

    try {
      if (captureTarget?.hasPointerCapture?.(event.pointerId)) {
        captureTarget.releasePointerCapture(event.pointerId);
      }
    } catch {}

    dragState = null;
    pill.classList.remove("dragging");
  }

  async function build() {
    const settings = await getSettings();
    if (!settings.enabled) return;
    if (settings.scope === "media" && !isMediaSite()) return;
    I18N.setLanguage(settings.language);
    currentVariant = normalizePillVariant(settings.variant);

    host = document.createElement("div");
    host.id = "kitty-download-manager-pill-host";
    host.style.all = "initial";
    host.style.position = "fixed";
    host.style.inset = "0 auto auto 0";
    host.style.width = "0";
    host.style.height = "0";
    host.style.zIndex = "2147483647";
    host.style.pointerEvents = "none";

    shadow = host.attachShadow({ mode: "closed" });

    const style = document.createElement("style");
    style.textContent = `
      :host { all: initial; }
      #pill {
        position: fixed;
        left: 0;
        top: 0;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-height: 38px;
        padding: 4px 6px 4px 11px;
        border: 1px solid rgba(255,255,255,.13);
        border-radius: 999px;
        background: rgba(28,28,31,.95);
        color: ${COLORS.downloading};
        box-shadow: 0 5px 18px rgba(0,0,0,.30);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 12px;
        line-height: 1;
        user-select: none;
        cursor: grab;
        pointer-events: auto;
        transition:
          opacity .15s ease,
          transform .15s ease,
          border-color .15s ease,
          color .15s ease,
          background .15s ease,
          box-shadow .15s ease;
      }
      #pill.dragging { cursor: grabbing; transition: none; }
      #pill[data-state="metadata"] {
        color: ${COLORS.metadata};
        border-color: color-mix(in srgb, ${COLORS.metadata} 46%, transparent);
        background:
          linear-gradient(rgba(230, 184, 92, .08), rgba(230, 184, 92, .08)),
          rgba(28,28,31,.95);
        box-shadow: 0 5px 18px rgba(0,0,0,.30), inset 3px 0 0 rgba(230,184,92,.24);
      }
      #pill[data-state="downloading"] {
        color: ${COLORS.downloading};
        border-color: rgba(74,163,223,.28);
        background:
          linear-gradient(rgba(74, 163, 223, .08), rgba(74, 163, 223, .08)),
          rgba(28,28,31,.95);
        box-shadow: 0 5px 18px rgba(0,0,0,.30), inset 3px 0 0 rgba(74,163,223,.24);
      }
      #pill[data-state="queued"] {
        color: #BFD4F6;
        border-color: color-mix(in srgb, ${COLORS.blue} 60%, transparent);
      }
      #pill[data-state="finished"] {
        color: ${COLORS.success};
        border-color: color-mix(in srgb, ${COLORS.success} 50%, transparent);
        background: rgba(35, 70, 48, .96);
        box-shadow: 0 5px 18px rgba(0,0,0,.30), inset 3px 0 0 rgba(99,217,139,.34);
      }
      #pill[data-state="duplicate"] {
        color: ${COLORS.metadata};
        border-color: color-mix(in srgb, ${COLORS.metadata} 46%, transparent);
      }
      #pill[data-state="error"] {
        color: ${COLORS.error};
        border-color: color-mix(in srgb, ${COLORS.error} 50%, transparent);
        background: rgba(72, 38, 40, .96);
        box-shadow: 0 5px 18px rgba(0,0,0,.30), inset 3px 0 0 rgba(239,109,109,.36);
      }
      #mascot {
        font-family: ui-monospace, "DejaVu Sans Mono", monospace;
        font-size: 13px;
        opacity: .9;
        min-width: 37px;
      }
      #pill[data-state="metadata"] #mascot,
      #pill[data-state="downloading"] #mascot {
        animation: kittyBob .7s ease-in-out infinite alternate;
      }
      @keyframes kittyBob {
        from { transform: translateY(0); }
        to { transform: translateY(-2px); }
      }
      #status {
        max-width: 118px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        opacity: .86;
      }
      button {
        appearance: none;
        border: 0;
        margin: 0;
        padding: 0;
        color: inherit;
        font: inherit;
        cursor: pointer;
      }
      #download {
        display: grid;
        place-items: center;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background: ${COLORS.blue};
        color: #fff;
        font-size: 18px;
        font-weight: 800;
        transition: background .12s ease, transform .12s ease, opacity .12s ease;
      }
      #download:hover:not(:disabled) { background: ${COLORS.blueHover}; }
      #download:active:not(:disabled) { transform: scale(.90); }
      #download:disabled { cursor: default; opacity: .72; }
      #pill[data-state="duplicate"] #download {
        background: #6D5728;
        color: #FFE0A3;
      }
      #pill[data-state="finished"] #download {
        background: rgba(99,217,139,.18);
        color: ${COLORS.success};
      }
      #pill[data-state="error"] #download {
        background: rgba(239,109,109,.17);
        color: ${COLORS.error};
      }
      #close {
        display: grid;
        place-items: center;
        width: 22px;
        height: 22px;
        border-radius: 50%;
        background: transparent;
        opacity: .48;
        font-size: 15px;
      }
      #close:hover {
        opacity: 1;
        background: rgba(255,255,255,.08);
      }

      #pill[data-variant="minimal"],
      #pill[data-variant="cat"] {
        gap: 0;
        min-height: 0;
        padding: 0;
        border: 0;
        background: transparent !important;
        box-shadow: none !important;
        backdrop-filter: none;
        -webkit-backdrop-filter: none;
      }
      #pill[data-variant="minimal"] #mascot,
      #pill[data-variant="minimal"] #status,
      #pill[data-variant="minimal"] #close,
      #pill[data-variant="cat"] #mascot,
      #pill[data-variant="cat"] #status,
      #pill[data-variant="cat"] #close {
        display: none;
      }

      #pill[data-variant="minimal"] #download {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: ${COLORS.blue};
        color: #fff;
        box-shadow: 0 5px 16px rgba(0,0,0,.28);
        opacity: 1;
      }
      #pill[data-variant="minimal"] #download:hover {
        background: ${COLORS.blueHover};
      }
      #pill[data-variant="minimal"] #download[data-action-disabled="true"] {
        cursor: grab;
      }
      #pill[data-variant="minimal"][data-state="metadata"] #download,
      #pill[data-variant="minimal"][data-state="duplicate"] #download {
        background: #6D5728;
        color: #FFE0A3;
      }
      #pill[data-variant="minimal"][data-state="queued"] #download {
        background: #315B91;
        color: #E5EEFF;
      }
      #pill[data-variant="minimal"][data-state="paused"] #download {
        background: #354B67;
        color: #DCEBFF;
      }
      #pill[data-variant="minimal"][data-state="downloading"] #download {
        background: ${COLORS.blue};
        color: #fff;
      }
      #pill[data-variant="minimal"][data-state="finished"] #download {
        background: #294B34;
        color: ${COLORS.success};
      }
      #pill[data-variant="minimal"][data-state="error"] #download {
        background: #542F33;
        color: ${COLORS.error};
      }

      #pill[data-variant="cat"] #download {
        width: auto;
        height: auto;
        min-width: 0;
        padding: 7px 9px;
        border: 1px solid rgba(255,255,255,.13);
        border-radius: 10px;
        background: rgba(28,28,31,.94);
        box-shadow: 0 4px 14px rgba(0,0,0,.28);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        color: ${COLORS.blue};
        font-family: ui-monospace, "DejaVu Sans Mono", monospace;
        font-size: 15px;
        font-weight: 800;
        opacity: .94;
      }
      #pill[data-variant="cat"] #download:hover {
        background: rgba(36,36,40,.97);
        border-color: rgba(255,255,255,.20);
        color: ${COLORS.blueHover};
      }
      #pill[data-variant="cat"] #download[data-action-disabled="true"] {
        cursor: grab;
        opacity: .94;
      }
      #pill[data-variant="cat"][data-state="metadata"] #download,
      #pill[data-variant="cat"][data-state="duplicate"] #download {
        color: ${COLORS.metadata};
        background: rgba(70,57,31,.96);
        border-color: rgba(230,184,92,.25);
      }
      #pill[data-variant="cat"][data-state="queued"] #download {
        color: #BFD4F6;
        background: rgba(38,54,76,.96);
        border-color: rgba(77,126,190,.28);
      }
      #pill[data-variant="cat"][data-state="paused"] #download {
        color: #AFC9EA;
        background: rgba(38,50,66,.96);
        border-color: rgba(111,145,190,.24);
      }
      #pill[data-variant="cat"][data-state="downloading"] #download {
        color: ${COLORS.downloading};
        background: rgba(30,48,64,.96);
        border-color: rgba(74,163,223,.28);
      }
      #pill[data-variant="cat"][data-state="finished"] #download {
        color: ${COLORS.success};
        background: rgba(35,70,48,.96);
        border-color: rgba(99,217,139,.28);
      }
      #pill[data-variant="cat"][data-state="error"] #download {
        color: ${COLORS.error};
        background: rgba(72,38,40,.96);
        border-color: rgba(239,109,109,.30);
      }
      #pill[data-variant="cat"][data-state="metadata"] #download,
      #pill[data-variant="cat"][data-state="downloading"] #download {
        animation: kittyBob .7s ease-in-out infinite alternate;
      }

      @media (prefers-reduced-motion: reduce) {
        #pill, #mascot, #download { animation: none !important; transition: none !important; }
      }
    `;

    pill = document.createElement("div");
    pill.id = "pill";
    pill.dataset.state = "idle";
    pill.dataset.variant = currentVariant;
    pill.setAttribute("role", "group");
    pill.setAttribute("aria-label", "Kitty Download Manager");

    mascot = document.createElement("span");
    mascot.id = "mascot";
    mascot.textContent = "ᓚᘏᗢ";

    statusText = document.createElement("span");
    statusText.id = "status";
    statusText.textContent = "Download";

    downloadButton = document.createElement("button");
    downloadButton.id = "download";
    downloadButton.type = "button";
    downloadButton.title = I18N.tr("Télécharger cette page");
    downloadButton.setAttribute("aria-label", I18N.tr("Télécharger cette page"));
    downloadButton.textContent = "↓";

    closeButton = document.createElement("button");
    closeButton.id = "close";
    closeButton.type = "button";
    closeButton.title = I18N.tr("Masquer sur cette page");
    closeButton.setAttribute("aria-label", I18N.tr("Masquer"));
    closeButton.textContent = "×";

    pill.append(mascot, statusText, downloadButton, closeButton);
    shadow.append(style, pill);
    document.documentElement.appendChild(host);

    applyPosition(settings.position);

    downloadButton.addEventListener("click", event => {
      if (suppressNextDownloadClick) {
        suppressNextDownloadClick = false;
        event.preventDefault();
        event.stopPropagation();
        return;
      }

      if (downloadButton.dataset.actionDisabled === "true") {
        event.preventDefault();
        return;
      }

      triggerDownload();
    });
    closeButton.addEventListener("click", () => {
      transientHidden = true;
      host.remove();
      clearPollTimer();
      clearResetTimer();
    });

    pill.addEventListener("pointerdown", beginDrag);
    pill.addEventListener("pointermove", moveDrag);
    pill.addEventListener("pointerup", endDrag);
    pill.addEventListener("pointercancel", endDrag);

    window.addEventListener("resize", () => {
      if (!pill?.isConnected) return;
      const rect = pill.getBoundingClientRect();
      const p = clampPosition(rect.left, rect.top);
      pill.style.left = `${p.left}px`;
      pill.style.top = `${p.top}px`;
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") scheduleNextPoll(100);
      else clearPollTimer();
    });

    setVisualState("idle", "Download");
    scheduleNextPoll(100);
  }

  browser.runtime.onMessage.addListener((message) => {
    if (!message || typeof message !== "object") return;

    if (message.type === "kitty-resolve-media-url") {
      return Promise.resolve(resolveMediaUrlForPage(true));
    }
  });

  browser.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;

    if (changes.uiLanguage) {
      I18N.setLanguage(changes.uiLanguage.newValue);
      if (pill?.isConnected) {
        closeButton.title = I18N.tr("Masquer sur cette page");
        closeButton.setAttribute("aria-label", I18N.tr("Masquer"));
        setVisualState(currentStateKind, currentStateText);
        scheduleNextPoll(50);
      }
    }

    if (changes.pillStyle && pill?.isConnected) {
      applyVariant(changes.pillStyle.newValue);
    }

    if (changes.pillEnabled || changes.pillScope) {
      getSettings().then(settings => {
        const shouldExist =
          settings.enabled &&
          (settings.scope === "all" || isMediaSite());

        if (shouldExist && !host?.isConnected && !transientHidden) {
          build();
        } else if (!shouldExist && host?.isConnected) {
          host.remove();
          clearPollTimer();
          clearResetTimer();
        }
      });
    }
  });

  build();
})();
