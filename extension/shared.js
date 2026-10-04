(() => {
  const NATIVE_PROTOCOL_VERSION = 1;

  const COLORS = Object.freeze({
    blue: "#2A62BB",
    blueHover: "#3471D4",
    metadata: "#E6B85C",
    downloading: "#F4F4F4",
    success: "#63D98B",
    error: "#EF6D6D",
    muted: "#A0A0A0"
  });

  const STATE_UI = Object.freeze({
    idle: { label: "Téléchargement", short: "Prêt", color: COLORS.downloading },
    queued: { label: "En file", short: "En file", color: COLORS.blue },
    paused: { label: "En pause", short: "Pause", color: COLORS.blue },
    metadata: { label: "Récupération des métadonnées…", short: "Métadonnées", color: COLORS.metadata },
    downloading: { label: "En cours", short: "Téléchargement", color: COLORS.downloading },
    finished: { label: "Téléchargé", short: "Terminé", color: COLORS.success },
    duplicate: { label: "Déjà téléchargé", short: "Déjà présent", color: COLORS.metadata },
    error: { label: "Erreur", short: "Erreur", color: COLORS.error },
    cancelled: { label: "Annulé", short: "Annulé", color: COLORS.muted }
  });

  function modeLabel(mode) {
    return ({
      "1080": "1080p",
      "720": "720p",
      "best": "Meilleure qualité",
      "audio": "Audio",
      "mp3": "MP3"
    })[mode] || mode || "?";
  }

  function sourceInfo(url) {
    try {
      const u = new URL(url);
      const host = u.hostname.replace(/^www\./, "").toLowerCase();

      const known = [
        { test: h => h === "youtube.com" || h.endsWith(".youtube.com") || h === "youtu.be", label: "YouTube", key: "youtube" },
        { test: h => h === "soundcloud.com" || h.endsWith(".soundcloud.com"), label: "SoundCloud", key: "soundcloud" },
        { test: h => h === "tiktok.com" || h.endsWith(".tiktok.com"), label: "TikTok", key: "tiktok" },
        { test: h => h === "instagram.com" || h.endsWith(".instagram.com"), label: "Instagram", key: "instagram" },
        { test: h => h === "twitter.com" || h.endsWith(".twitter.com") || h === "x.com" || h.endsWith(".x.com"), label: "X", key: "x" },
        { test: h => h === "vimeo.com" || h.endsWith(".vimeo.com"), label: "Vimeo", key: "vimeo" },
        { test: h => h === "twitch.tv" || h.endsWith(".twitch.tv"), label: "Twitch", key: "twitch" },
        { test: h => h === "dailymotion.com" || h.endsWith(".dailymotion.com") || h === "dai.ly", label: "Dailymotion", key: "dailymotion" },
        { test: h => h === "pinterest.com" || h.endsWith(".pinterest.com") || /^pinterest\.[a-z.]+$/.test(h) || h === "pin.it", label: "Pinterest", key: "pinterest" },
        { test: h => h === "bandcamp.com" || h.endsWith(".bandcamp.com"), label: "Bandcamp", key: "bandcamp" },
        { test: h => h === "reddit.com" || h.endsWith(".reddit.com") || h === "redd.it", label: "Reddit", key: "reddit" },
        { test: h => h === "facebook.com" || h.endsWith(".facebook.com") || h === "fb.watch", label: "Facebook", key: "facebook" },
        { test: h => h === "audiomack.com" || h.endsWith(".audiomack.com"), label: "Audiomack", key: "audiomack" },
        { test: h => h === "audius.co" || h.endsWith(".audius.co"), label: "Audius", key: "audius" }
      ];

      const match = known.find(entry => entry.test(host));
      if (match) return { label: match.label, key: match.key, host };

      const parts = host.split(".");
      const base = parts.length > 1 ? parts[parts.length - 2] : host;
      return {
        label: base ? base.charAt(0).toUpperCase() + base.slice(1) : "Web",
        key: "web",
        host
      };
    } catch {
      return { label: "Web", key: "web", host: "" };
    }
  }

  // Local SVG geometry only; never parse strings supplied by a site or host.
  const SOURCE_ICONS = Object.freeze({
    youtube: [["rect",{"class":"sourceIconLine","x":"3","y":"6","width":"18","height":"12","rx":"4"}],["path",{"class":"sourceIconFill","d":"m10 9 6 3-6 3z"}]],
    soundcloud: [["path",{"class":"sourceIconLine","d":"M3 14v2M6 12v4M9 9v7M12 7v9M15 10v6"}],["path",{"class":"sourceIconLine","d":"M15 10.5a4.3 4.3 0 0 1 7 3.3A2.2 2.2 0 0 1 19.8 16H15"}]],
    tiktok: [["path",{"class":"sourceIconLine","d":"M14 4v10.2a4 4 0 1 1-3-3.9"}],["path",{"class":"sourceIconLine","d":"M14 4c.7 2 2.2 3.4 4.5 3.8"}]],
    instagram: [["rect",{"class":"sourceIconLine","x":"4","y":"4","width":"16","height":"16","rx":"5"}],["circle",{"class":"sourceIconLine","cx":"12","cy":"12","r":"3.5"}],["circle",{"class":"sourceIconFill","cx":"17.2","cy":"6.8","r":"1"}]],
    x: [["path",{"class":"sourceIconLine","d":"M5 4h4.2L19 20h-4.2zM19 4 5 20"}]],
    vimeo: [["path",{"class":"sourceIconLine","d":"M4 8c2-2.4 5-3 6-.8.7 1.5.7 5.5 1.7 7.4.4.8.8 1.2 1.3 1.2 1.4 0 4.3-3.8 5-5.5.5-1.2-.2-1.8-1-1.8-.7 0-1.5.4-2.2 1"}]],
    twitch: [["path",{"class":"sourceIconLine","d":"M5 4h15v10l-4 4h-4l-3 2v-2H5z"}],["path",{"class":"sourceIconLine","d":"M10 8v5M15 8v5"}]],
    dailymotion: [["circle",{"class":"sourceIconLine","cx":"12","cy":"13","r":"5"}],["path",{"class":"sourceIconLine","d":"M17 4v9"}]],
    pinterest: [["circle",{"class":"sourceIconLine","cx":"12","cy":"12","r":"8.5"}],["path",{"class":"sourceIconLine","d":"M10 18c1-2 1.6-4.2 2-6.6.2-1.5 1-2.4 2-2.4 1.2 0 1.8 1 1.5 2.4-.4 1.7-1.2 3-2.7 3-1.7 0-2.7-1.4-2.7-3.2 0-2.7 2-4.7 4.7-4.7"}]],
    bandcamp: [["path",{"class":"sourceIconFill","d":"M7 6h13l-4 12H3z"}]],
    reddit: [["circle",{"class":"sourceIconLine","cx":"12","cy":"13","r":"7"}],["circle",{"class":"sourceIconFill","cx":"9.5","cy":"12.5","r":"1"}],["circle",{"class":"sourceIconFill","cx":"14.5","cy":"12.5","r":"1"}],["path",{"class":"sourceIconLine","d":"M9.5 15.5c1.5.9 3.5.9 5 0M14 6l.7-2.5 3 .6"}],["circle",{"class":"sourceIconLine","cx":"18.5","cy":"4.3","r":"1.2"}]],
    facebook: [["path",{"class":"sourceIconFill","d":"M14 21v-8h2.8l.4-3H14V8.2c0-.9.3-1.6 1.7-1.6H17V4.1c-.5-.1-1.4-.1-2.3-.1-2.4 0-4 1.5-4 4.1V10H8v3h2.7v8z"}]],
    audiomack: [["path",{"class":"sourceIconLine","d":"M4 17 9 7l3 5 2-3 6 8M7 17l2-4.5L12 17l2-3.4 3 3.4"}]],
    audius: [["path",{"class":"sourceIconLine","d":"m12 3 7 5-2.5 8L12 21l-4.5-5L5 8z"}],["circle",{"class":"sourceIconLine","cx":"12","cy":"12","r":"3"}]],
    web: [["circle",{"class":"sourceIconLine","cx":"12","cy":"12","r":"8.5"}],["path",{"class":"sourceIconLine","d":"M3.5 12h17M12 3.5c2.2 2.3 3.3 5.1 3.3 8.5S14.2 18.2 12 20.5M12 3.5C9.8 5.8 8.7 8.6 8.7 12s1.1 6.2 3.3 8.5"}]],
  });

  function sourceIconElement(key, ownerDocument = document) {
    const namespace = "http://www.w3.org/2000/svg";
    const svg = ownerDocument.createElementNS(namespace, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const shapes = Object.prototype.hasOwnProperty.call(SOURCE_ICONS, key)
      ? SOURCE_ICONS[key] : SOURCE_ICONS.web;
    for (const [tag, attributes] of shapes) {
      const shape = ownerDocument.createElementNS(namespace, tag);
      for (const [name, value] of Object.entries(attributes)) {
        shape.setAttribute(name, value);
      }
      svg.append(shape);
    }
    return svg;
  }

  function jobPhase(job) {
    if (!job) return "idle";
    if (job.status === "queued") return "queued";
    if (job.status === "paused") return "paused";
    if (job.status === "finished" || job.status === "done") return "finished";
    if (job.status === "error") return "error";
    if (job.status === "cancelled") return "cancelled";

    const downloaded = job.downloaded;
    if (
      job.status === "starting" ||
      job.status === "metadata" ||
      downloaded === null ||
      downloaded === undefined
    ) {
      return "metadata";
    }

    return "downloading";
  }

  function jobPercent(job) {
    if (!job) return null;
    const downloaded = Number(job.downloaded);
    const total = Number(job.total ?? job.estimated_total);
    if (!Number.isFinite(downloaded) || !Number.isFinite(total) || total <= 0) return null;
    return Math.max(0, Math.min(100, downloaded / total * 100));
  }

  function findJob(state, jobId) {
    if (!state || !jobId) return null;
    if (state.active?.id === jobId) return { place: "active", job: state.active, index: 0 };

    const queue = Array.isArray(state.queue) ? state.queue : [];
    const queueIndex = queue.findIndex(job => job?.id === jobId);
    if (queueIndex >= 0) return { place: "queue", job: queue[queueIndex], index: queueIndex };

    const history = Array.isArray(state.history) ? state.history : [];
    const historyIndex = history.findIndex(job => job?.id === jobId);
    if (historyIndex >= 0) return { place: "history", job: history[historyIndex], index: historyIndex };

    return null;
  }

  function playlistPosition(job) {
    const current = Number(job?.playlist_position);
    const total = Number(job?.playlist_total);

    if (
      Number.isInteger(current) &&
      Number.isInteger(total) &&
      current >= 1 &&
      total >= 1 &&
      current <= total
    ) {
      return { current, total, kind: "playlist" };
    }

    return null;
  }

  function queuePosition(state, jobId) {
    if (!state || !jobId) return null;

    const queue = Array.isArray(state.queue) ? state.queue : [];
    const active = state.active || null;
    const located = findJob(state, jobId);

    if (!located || (located.place !== "active" && located.place !== "queue")) {
      return null;
    }

    const playlistPos = playlistPosition(located.job);
    if (playlistPos) return playlistPos;

    const hasPlaylistBacklog =
      Boolean(playlistPosition(active)) ||
      queue.some(job => Boolean(playlistPosition(job)));

    if (hasPlaylistBacklog) {
      const activeIsInteractive = Boolean(active) && !playlistPosition(active);
      const interactiveQueue = queue.filter(job => !playlistPosition(job));

      if (located.place === "active") {
        return {
          current: 1,
          total: 1 + interactiveQueue.length,
          kind: "priority",
          next: false
        };
      }

      const interactiveIndex = interactiveQueue.findIndex(job => job?.id === jobId);
      if (interactiveIndex >= 0) {
        return {
          current: interactiveIndex + (activeIsInteractive ? 2 : 1),
          total: interactiveQueue.length + (activeIsInteractive ? 1 : 0),
          kind: "priority",
          next: !activeIsInteractive && interactiveIndex === 0
        };
      }
    }

    const hasActive = Boolean(active);
    const total = queue.length + (hasActive ? 1 : 0);
    if (!total) return null;

    if (located.place === "active") {
      return { current: 1, total, kind: "queue", next: false };
    }

    return {
      current: located.index + (hasActive ? 2 : 1),
      total,
      kind: "queue",
      next: !hasActive && located.index === 0
    };
  }

  function compactPosition(state, jobId) {
    const pos = queuePosition(state, jobId);
    if (!pos) return "";

    if (pos.kind === "priority") {
      if (pos.next) return "prochain";
      return pos.total > 1 ? `${pos.current} / ${pos.total}` : "";
    }

    return pos.total > 1 ? `${pos.current} / ${pos.total}` : "";
  }

  globalThis.KittyShared = Object.freeze({
    NATIVE_PROTOCOL_VERSION,
    COLORS,
    STATE_UI,
    modeLabel,
    sourceInfo,
    sourceIconElement,
    jobPhase,
    jobPercent,
    findJob,
    playlistPosition,
    queuePosition,
    compactPosition
  });
})();
