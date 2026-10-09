(() => {
  "use strict";

  // Kitty Universal Media Resolver
  // --------------------------------
  // Objectif : retrouver un permalink de page média, pas une URL CDN brute.
  // Tout est fait à la demande, sans requête réseau ni MutationObserver.

  const CACHE_MS = 300;
  const MAX_NEARBY_LINKS = 48;
  const MAX_ANCESTOR_DEPTH = 9;
  const MAX_JSONLD_SCRIPTS = 6;
  const MAX_JSONLD_SCRIPT_CHARS = 48000;
  const MAX_JSONLD_TOTAL_CHARS = 120000;
  const MAX_JSONLD_NODES = 180;

  const TRACKING_PARAMS = new Set([
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid",
    "ref_src", "ref_url", "referrer", "source", "share", "shared",
    "share_id", "share_app_id", "share_item_id", "share_link_id",
    "is_from_webapp", "sender_device", "sender_web_id", "rdid", "mibextid",
    "feature", "si"
  ]);

  const PROBLEMATIC_FEED_HOSTS = [
    "tiktok.com", "instagram.com", "x.com", "twitter.com",
    "facebook.com", "reddit.com"
  ];

  let resolveCache = { key: "", at: 0, value: null };

  function hostMatches(hostname, domain) {
    const host = String(hostname || "").toLowerCase().replace(/^www\./, "");
    const target = String(domain || "").toLowerCase().replace(/^www\./, "");
    return host === target || host.endsWith(`.${target}`);
  }

  function isPinterestHostname(hostname) {
    const host = String(hostname || "")
      .toLowerCase()
      .replace(/^www\./, "");
    return /^(?:[^.]+\.)*pinterest\.[a-z.]+$/i.test(host);
  }

  function normalizedHostname(hostname) {
    return String(hostname || "")
      .toLowerCase()
      .replace(/^(?:www|m|mobile|old|new)\./, "");
  }

  function sameSite(rawA, rawB) {
    try {
      const a = normalizedHostname(new URL(rawA, location.href).hostname);
      const b = normalizedHostname(new URL(rawB, location.href).hostname);
      return a === b || a.endsWith(`.${b}`) || b.endsWith(`.${a}`);
    } catch {
      return false;
    }
  }

  function toHttpUrl(rawUrl, base = location.href) {
    try {
      const parsed = new URL(rawUrl, base);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
      return parsed;
    } catch {
      return null;
    }
  }

  function cleanTrackingUrl(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed) return null;

    parsed.hash = "";
    for (const key of [...parsed.searchParams.keys()]) {
      const lower = key.toLowerCase();
      if (lower.startsWith("utm_") || TRACKING_PARAMS.has(lower)) {
        parsed.searchParams.delete(key);
      }
    }
    return parsed.href;
  }

  function canonicalTikTokPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed || !hostMatches(parsed.hostname, "tiktok.com")) return null;
    const match = parsed.pathname.match(/^\/@([^/]*)\/video\/(\d+)(?:\/|$)/i);
    if (match) return `https://www.tiktok.com/@${match[1] || "_"}/video/${match[2]}`;
    const embedded = parsed.pathname.match(/^\/(?:embed\/v2|player\/v1)\/(\d+)(?:\/|$)/i);
    return embedded ? `https://www.tiktok.com/@_/video/${embedded[1]}` : null;
  }

  function canonicalInstagramPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed || !hostMatches(parsed.hostname, "instagram.com")) return null;

    const parts = parsed.pathname.split("/").filter(Boolean);
    const mediaIndex = parts.findIndex(part => /^(?:p|reel|reels|tv)$/i.test(part));
    if (mediaIndex < 0 || !parts[mediaIndex + 1]) return null;

    let type = parts[mediaIndex].toLowerCase();
    if (type === "reels") type = "reel";
    const shortcode = parts[mediaIndex + 1].match(/^[A-Za-z0-9_-]+/)?.[0];
    if (!shortcode) return null;
    return `https://www.instagram.com/${type}/${shortcode}/`;
  }

  function canonicalTwitterPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed || !(hostMatches(parsed.hostname, "x.com") || hostMatches(parsed.hostname, "twitter.com"))) {
      return null;
    }

    const match = parsed.pathname.match(
      /^\/(?:i\/web\/status|statuses|[^/]+\/status)\/(\d+)/i
    );
    if (!match) return null;
    return `https://x.com/i/status/${match[1]}`;
  }

  function canonicalRedditPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed || !(hostMatches(parsed.hostname, "reddit.com") || hostMatches(parsed.hostname, "redditmedia.com"))) {
      return null;
    }

    const match = parsed.pathname.match(/\/(?:r\/[^/]+\/|user\/[^/]+\/)?comments\/([^/?#&]+)/i);
    if (!match) return null;
    return `https://www.reddit.com/comments/${match[1]}`;
  }

  function canonicalPinterestPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed || !isPinterestHostname(parsed.hostname)) return null;

    // yt-dlp reconnait /pin/ID/ et /pin/slug--ID.
    const match = parsed.pathname.match(/^\/pin\/(?:[\w-]+--)?(\d+)(?:\/|$)/i);
    if (!match) return null;

    return `https://www.pinterest.com/pin/${match[1]}/`;
  }

  function canonicalFacebookPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed || !hostMatches(parsed.hostname, "facebook.com")) return null;

    let match = parsed.pathname.match(/^\/reel\/(\d+)/i);
    if (match) return `https://www.facebook.com/reel/${match[1]}`;

    if (/^\/watch\/?$/i.test(parsed.pathname)) {
      const id = parsed.searchParams.get("v") || parsed.searchParams.get("video_id");
      if (id && /^\d+$/.test(id)) return `https://www.facebook.com/watch/?v=${id}`;
    }

    if (/^\/(?:video(?:\/video)?\.php|story\.php|permalink\.php)$/i.test(parsed.pathname)) {
      const id =
        parsed.searchParams.get("v") ||
        parsed.searchParams.get("video_id") ||
        parsed.searchParams.get("story_fbid");
      if (id && /^(?:\d+|pfbid[A-Za-z0-9]+)$/.test(id)) {
        if (/permalink\.php$/i.test(parsed.pathname)) {
          return `https://www.facebook.com/permalink.php?story_fbid=${id}`;
        }
        return `https://www.facebook.com/video.php?v=${id}`;
      }
    }

    match = parsed.pathname.match(/\/videos\/(?:[^/]+\/)?(\d+)(?:\/|$)/i);
    if (match) return `https://www.facebook.com/video.php?v=${match[1]}`;

    match = parsed.pathname.match(/\/posts\/(pfbid[A-Za-z0-9]+|\d+)(?:\/|$)/i);
    if (match) return `https://www.facebook.com/permalink.php?story_fbid=${match[1]}`;

    return null;
  }

  function canonicalYouTubePermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed) return null;

    if (hostMatches(parsed.hostname, "youtu.be")) {
      const id = parsed.pathname.split("/").filter(Boolean)[0];
      if (id && /^[A-Za-z0-9_-]{6,}$/.test(id)) {
        return `https://www.youtube.com/watch?v=${id}`;
      }
      return null;
    }

    if (!hostMatches(parsed.hostname, "youtube.com")) return null;

    if (/^\/watch$/i.test(parsed.pathname)) {
      const id = parsed.searchParams.get("v");
      if (id) return `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
    }

    let match = parsed.pathname.match(/^\/(shorts|live)\/([A-Za-z0-9_-]+)/i);
    if (match) return `https://www.youtube.com/${match[1].toLowerCase()}/${match[2]}`;

    return null;
  }

  function canonicalDailymotionPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed || !hostMatches(parsed.hostname, "dailymotion.com")) return null;
    const match = parsed.pathname.match(/^\/video\/([A-Za-z0-9]+)/i);
    if (!match) return null;
    return `https://www.dailymotion.com/video/${match[1]}`;
  }

  function canonicalTwitchPermalink(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed) return null;

    if (hostMatches(parsed.hostname, "clips.twitch.tv")) {
      const slug = parsed.pathname.split("/").filter(Boolean)[0];
      return slug ? `https://clips.twitch.tv/${slug}` : null;
    }

    if (!hostMatches(parsed.hostname, "twitch.tv")) return null;
    const match = parsed.pathname.match(/^\/[^/]+\/clip\/([^/?#]+)/i);
    if (!match) return null;
    return `https://clips.twitch.tv/${match[1]}`;
  }

  function canonicalizeKnownMediaUrl(rawUrl) {
    return (
      canonicalTikTokPermalink(rawUrl) ||
      canonicalInstagramPermalink(rawUrl) ||
      canonicalTwitterPermalink(rawUrl) ||
      canonicalRedditPermalink(rawUrl) ||
      canonicalPinterestPermalink(rawUrl) ||
      canonicalFacebookPermalink(rawUrl) ||
      canonicalYouTubePermalink(rawUrl) ||
      canonicalDailymotionPermalink(rawUrl) ||
      canonicalTwitchPermalink(rawUrl) ||
      null
    );
  }

  function isRawMediaUrl(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed) return false;
    return /\.(?:mp4|webm|mov|m4v|m3u8|mpd|mp3|m4a|aac|opus|ogg|flac)(?:$|[?#])/i.test(parsed.href);
  }

  function isGenericFeedLikeUrl(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed) return true;
    const path = parsed.pathname.replace(/\/+$/, "") || "/";
    return /^(?:\/|\/home|\/feed|\/feeds|\/explore|\/discover|\/search|\/following|\/foryou|\/reels?|\/shorts?)$/i.test(path);
  }

  function pathLooksMediaLike(rawUrl) {
    const parsed = toHttpUrl(rawUrl);
    if (!parsed) return false;
    return /\/(?:video(?:s)?|reel(?:s)?|shorts?|watch|status(?:es)?|posts?|comments|clips?|tv|p|pin)\b/i.test(parsed.pathname) ||
      parsed.searchParams.has("v") || parsed.searchParams.has("video_id") || parsed.searchParams.has("story_fbid");
  }

  function viewportScore(element, referenceY = window.innerHeight / 2) {
    if (!element || typeof element.getBoundingClientRect !== "function") return -Infinity;
    const rect = element.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return -Infinity;

    const vw = Math.max(1, window.innerWidth);
    const vh = Math.max(1, window.innerHeight);
    const visibleWidth = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
    const visibleHeight = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
    const visibleArea = visibleWidth * visibleHeight;
    if (visibleArea <= 0) return -Infinity;

    const area = Math.max(1, rect.width * rect.height);
    const visibility = Math.min(1, visibleArea / area);
    const centerY = rect.top + rect.height / 2;
    const distance = Math.abs(centerY - referenceY) / vh;
    return visibility * 100 - distance * 28;
  }

  function bestVisibleMedia(preferPlaying = false) {
    let best = null;
    let bestScore = -Infinity;
    for (const media of document.querySelectorAll("video, audio")) {
      const style = preferPlaying ? window.getComputedStyle?.(media) : null;
      if (style && (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')) continue;
      const score = viewportScore(media) + (preferPlaying && media.paused === false && !media.ended ? 200 : 0);
      if (score > bestScore) {
        best = media;
        bestScore = score;
      }
    }
    return bestScore > -Infinity ? best : null;
  }

  function nearbyAnchors(media, rootSelector = null) {
    if (!media) return [];
    const found = [];
    const seen = new Set();

    function add(anchor) {
      if (!anchor || seen.has(anchor) || found.length >= MAX_NEARBY_LINKS) return;
      if (!anchor.href && !anchor.getAttribute?.("href")) return;
      seen.add(anchor);
      found.push(anchor);
    }

    add(media.closest?.("a[href]"));

    if (rootSelector) {
      const root = media.closest?.(rootSelector);
      if (root) {
        for (const anchor of root.querySelectorAll?.("a[href]") || []) {
          add(anchor);
          if (found.length >= MAX_NEARBY_LINKS) break;
        }
      }
    }

    let node = media.parentElement;
    for (let depth = 0; node && depth < MAX_ANCESTOR_DEPTH && found.length < MAX_NEARBY_LINKS; depth += 1) {
      if (node.matches?.("a[href]")) add(node);

      const links = node.querySelectorAll?.("a[href]") || [];
      for (const anchor of links) {
        add(anchor);
        if (found.length >= MAX_NEARBY_LINKS) break;
      }

      const rect = node.getBoundingClientRect?.();
      if (depth >= 3 && rect?.height > window.innerHeight * 3) break;
      node = node.parentElement;
    }

    return found;
  }

  function bestCanonicalFromAnchors(anchors, canonicalizer) {
    let best = null;
    let bestScore = -Infinity;
    const centerY = window.innerHeight / 2;

    for (const anchor of anchors) {
      const href = anchor.href || anchor.getAttribute?.("href");
      const canonical = canonicalizer(href);
      if (!canonical) continue;
      const score = viewportScore(anchor, centerY);
      const normalizedScore = Number.isFinite(score) ? score : 0;
      if (!best || normalizedScore > bestScore) {
        best = canonical;
        bestScore = normalizedScore;
      }
    }
    return best;
  }

  // ---- TikTok adapter --------------------------------------------------
  const TIKTOK_CONTAINER_SELECTOR = [
    '[data-e2e="recommend-list-item-container"]',
    '[data-e2e="feed-item"]',
    '[data-cinema-mode-snap-row]',
    '[data-cinema-mode-player-scroller="true"] [data-cinema-mode-snap-row]'
  ].join(", ");

  function bestVisibleTikTokContainer() {
    let best = null;
    let bestScore = -Infinity;
    for (const container of document.querySelectorAll(TIKTOK_CONTAINER_SELECTOR)) {
      const score = viewportScore(container);
      if (score > bestScore) {
        best = container;
        bestScore = score;
      }
    }
    if (best) return best;
    return bestVisibleMedia()?.closest?.(TIKTOK_CONTAINER_SELECTOR) || null;
  }

  function extractTikTokVideoIdFromContainer(container) {
    if (!container) return null;

    const cinemaAttr =
      container.getAttribute?.("data-cinema-mode-snap-row") ||
      container.querySelector?.("[data-cinema-mode-snap-row]")?.getAttribute("data-cinema-mode-snap-row");
    if (cinemaAttr && /^\d{15,}$/.test(cinemaAttr.trim())) return cinemaAttr.trim();

    const players = [];
    if (container.matches?.('.xgplayer-container, [id^="xgwrapper-"]')) players.push(container);
    players.push(...(container.querySelectorAll?.('.xgplayer-container, [id^="xgwrapper-"]') || []));

    for (const player of players) {
      const id = player?.id || "";
      const match = id.match(/xgwrapper-\d+-(\d{15,})/i) || id.match(/(\d{15,})/);
      if (match?.[1]) return match[1];
    }
    return null;
  }

  function extractTikTokUsernameFromContainer(container) {
    if (!container) return null;
    const videoId = extractTikTokVideoIdFromContainer(container);

    for (const link of container.querySelectorAll?.('a[href*="/video/"]') || []) {
      const canonical = canonicalTikTokPermalink(link.href || link.getAttribute("href"));
      if (!canonical || videoId && !canonical.endsWith(`/video/${videoId}`)) continue;
      const match = new URL(canonical).pathname.match(/^\/@([^/]+)\/video\//i);
      if (match?.[1] && match[1] !== "_") return match[1];
    }

    for (const link of container.querySelectorAll?.('a[href^="/@"], a[href*="tiktok.com/@"]') || []) {
      const parsed = toHttpUrl(link.href || link.getAttribute("href"));
      const match = parsed?.pathname.match(/^\/@([^/]+)/i);
      if (match?.[1] && match[1] !== "_") return match[1];
    }

    const text =
      container.querySelector?.('[data-e2e="video-author-uniqueid"]')?.textContent ||
      container.querySelector?.('[data-e2e="browse-username"]')?.textContent || "";
    const username = text.trim().replace(/^@/, "");
    return /^[\w.-]+$/.test(username) ? username : null;
  }

  function permalinkFromTikTokContainer(container) {
    if (!container) return null;
    const videoId = extractTikTokVideoIdFromContainer(container);
    for (const link of container.querySelectorAll?.('a[href*="/video/"]') || []) {
      const canonical = canonicalTikTokPermalink(link.href || link.getAttribute("href"));
      // Comment/recommendation links can belong to another post in this card.
      if (canonical && (!videoId || canonical.endsWith(`/video/${videoId}`))) return canonical;
    }

    if (!videoId) return null;
    const username = extractTikTokUsernameFromContainer(container) || "_";
    return `https://www.tiktok.com/@${username}/video/${videoId}`;
  }

  function resolveTikTokMedia(media, pageUrl = location.href) {
    const page = toHttpUrl(pageUrl);
    if (!media || !page || !hostMatches(page.hostname, 'tiktok.com')) return null;
    const card = media.closest?.(TIKTOK_CONTAINER_SELECTOR);
    if (card && (card.querySelectorAll?.('video') || []).length <= 1) {
      const permalink = permalinkFromTikTokContainer(card);
      if (permalink) return permalink;
    }
    // Bind each snapshot to this player, never to a different visible card.
    let node = media;
    for (let depth = 0; node && depth < MAX_ANCESTOR_DEPTH; depth++, node = node.parentElement) {
      if ((node.querySelectorAll?.('video') || []).length > 1) break;
      const permalink = permalinkFromTikTokContainer(node);
      if (permalink) return permalink;
    }
    return null;
  }

  function resolveTikTokFromDom(media) {
    const own = resolveTikTokMedia(media);
    if (own) return own;
    if (media) return null;
    const active = bestVisibleTikTokContainer();
    const direct = permalinkFromTikTokContainer(active);
    if (direct) return direct;

    let node = media;
    for (let depth = 0; node && depth < 14; depth += 1, node = node.parentElement) {
      const permalink = permalinkFromTikTokContainer(node);
      if (permalink) return permalink;
      const rect = node.getBoundingClientRect?.();
      if (depth >= 4 && rect?.height > window.innerHeight * 3) break;
    }

    let bestWrapper = null;
    let bestScore = -Infinity;
    for (const wrapper of document.querySelectorAll('.xgplayer-container, [id^="xgwrapper-"]')) {
      const score = viewportScore(wrapper);
      if (score > bestScore) {
        bestWrapper = wrapper;
        bestScore = score;
      }
    }
    if (bestWrapper) {
      const videoId = extractTikTokVideoIdFromContainer(bestWrapper);
      if (videoId) return `https://www.tiktok.com/@_/video/${videoId}`;
    }
    return null;
  }

  function resolveKnownSiteFromDom(media) {
    const host = location.hostname;

    if (hostMatches(host, "tiktok.com")) {
      return resolveTikTokFromDom(media);
    }

    if (hostMatches(host, "instagram.com")) {
      return bestCanonicalFromAnchors(
        nearbyAnchors(media, "article, main"),
        canonicalInstagramPermalink
      );
    }

    if (hostMatches(host, "x.com") || hostMatches(host, "twitter.com")) {
      return bestCanonicalFromAnchors(
        nearbyAnchors(media, "article"),
        canonicalTwitterPermalink
      );
    }

    if (hostMatches(host, "facebook.com")) {
      return bestCanonicalFromAnchors(
        nearbyAnchors(media, '[role="article"]'),
        canonicalFacebookPermalink
      );
    }

    if (hostMatches(host, "reddit.com")) {
      return bestCanonicalFromAnchors(
        nearbyAnchors(media, "shreddit-post, article"),
        canonicalRedditPermalink
      );
    }

    if (isPinterestHostname(host)) {
      return bestCanonicalFromAnchors(
        nearbyAnchors(
          media,
          '[data-test-id="pin"], [data-test-id*="pin"], article, main'
        ),
        canonicalPinterestPermalink
      );
    }

    if (hostMatches(host, "youtube.com") || hostMatches(host, "youtu.be")) {
      return bestCanonicalFromAnchors(
        nearbyAnchors(media, "ytd-rich-item-renderer, ytd-reel-video-renderer, ytd-watch-flexy"),
        canonicalYouTubePermalink
      );
    }

    return null;
  }

  function candidateScore(url, source, mediaElement = null) {
    const sourceBase = {
      "near-media": 82,
      canonical: 72,
      "og:url": 69,
      "twitter:url": 65,
      jsonld: 61,
      location: 48
    }[source] || 40;

    let score = sourceBase;
    if (canonicalizeKnownMediaUrl(url)) score += 22;
    if (pathLooksMediaLike(url)) score += 12;
    if (sameSite(url, location.href)) score += 8;
    if (isGenericFeedLikeUrl(url)) score -= 32;
    if (isRawMediaUrl(url)) score -= 60;
    if (/\/(?:login|signup|help|privacy|terms)(?:\/|$)/i.test(new URL(url).pathname)) score -= 40;

    if (source === "near-media" && mediaElement) {
      // La proximité avec le média visible est un signal très fort sur les SPA.
      score += 7;
    }
    return score;
  }

  function normalizeCandidate(rawUrl) {
    return canonicalizeKnownMediaUrl(rawUrl) || cleanTrackingUrl(rawUrl);
  }

  function addCandidate(candidates, seen, rawUrl, source, mediaElement = null) {
    const url = normalizeCandidate(rawUrl);
    if (!url || isRawMediaUrl(url) || seen.has(url)) return;

    // Pour les heuristiques universelles, éviter de suivre un lien externe
    // quelconque présent à côté de la vidéo (pub, profil, réseau social...).
    const knownCanonical = canonicalizeKnownMediaUrl(url);
    if (!knownCanonical && !sameSite(url, location.href)) return;

    // Sur les feeds sociaux connus, un lien de profil/navigation proche du
    // player ne doit jamais battre un vrai permalink. On exige donc soit une
    // forme média reconnue, soit au minimum un chemin clairement média.
    if (
      isProblematicFeedHost(location.hostname) &&
      !knownCanonical &&
      source === "near-media" &&
      !pathLooksMediaLike(url)
    ) return;

    seen.add(url);
    candidates.push({
      url,
      source,
      score: candidateScore(url, source, mediaElement)
    });
  }

  function collectNearbyCandidates(candidates, seen, media) {
    if (!media) return;
    for (const anchor of nearbyAnchors(media)) {
      addCandidate(candidates, seen, anchor.href || anchor.getAttribute?.("href"), "near-media", media);
    }
  }

  function collectHeadCandidates(candidates, seen) {
    const canonical = document.querySelector('link[rel~="canonical"][href]')?.href;
    if (canonical) addCandidate(candidates, seen, canonical, "canonical");

    const ogUrl = document.querySelector('meta[property="og:url"][content]')?.content;
    if (ogUrl) addCandidate(candidates, seen, ogUrl, "og:url");

    const twitterUrl =
      document.querySelector('meta[name="twitter:url"][content]')?.content ||
      document.querySelector('meta[property="twitter:url"][content]')?.content;
    if (twitterUrl) addCandidate(candidates, seen, twitterUrl, "twitter:url");
  }

  function jsonLdValueToUrl(value) {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") {
      if (typeof value["@id"] === "string") return value["@id"];
      if (typeof value.url === "string") return value.url;
    }
    return null;
  }

  function collectJsonLdCandidates(candidates, seen) {
    const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .slice(0, MAX_JSONLD_SCRIPTS);
    let totalChars = 0;
    let visited = 0;

    for (const script of scripts) {
      const text = script.textContent || "";
      if (!text || text.length > MAX_JSONLD_SCRIPT_CHARS) continue;
      totalChars += text.length;
      if (totalChars > MAX_JSONLD_TOTAL_CHARS) break;

      let data;
      try {
        data = JSON.parse(text);
      } catch {
        continue;
      }

      const stack = [{ value: data, depth: 0 }];
      while (stack.length && visited < MAX_JSONLD_NODES) {
        const { value, depth } = stack.pop();
        visited += 1;
        if (!value || depth > 5) continue;

        if (Array.isArray(value)) {
          for (let i = Math.min(value.length, 16) - 1; i >= 0; i -= 1) {
            stack.push({ value: value[i], depth: depth + 1 });
          }
          continue;
        }
        if (typeof value !== "object") continue;

        const types = Array.isArray(value["@type"]) ? value["@type"] : [value["@type"]];
        const isMediaObject = types.some(type =>
          typeof type === "string" && /(?:VideoObject|AudioObject|MediaObject|Clip)$/i.test(type)
        );

        if (isMediaObject) {
          for (const field of ["url", "mainEntityOfPage", "@id", "embedUrl"]) {
            const candidate = jsonLdValueToUrl(value[field]);
            if (candidate) addCandidate(candidates, seen, candidate, "jsonld");
          }
        }

        for (const key of ["@graph", "mainEntity", "subjectOf", "video", "audio", "itemListElement"]) {
          if (value[key] != null) stack.push({ value: value[key], depth: depth + 1 });
        }
      }
      if (visited >= MAX_JSONLD_NODES) break;
    }
  }

  function bestCandidate(candidates) {
    if (!candidates.length) return null;
    return candidates.reduce((best, current) =>
      !best || current.score > best.score ? current : best, null
    );
  }

  function isProblematicFeedHost(hostname) {
    return (
      isPinterestHostname(hostname) ||
      PROBLEMATIC_FEED_HOSTS.some(domain => hostMatches(hostname, domain))
    );
  }

  function cacheKey() {
    // Le bucket de scroll évite de réutiliser le résultat de la vidéo précédente
    // dans un feed, tout en amortissant les appels de polling du pill.
    const bucket = Math.round((window.scrollY || 0) / 80);
    return `${location.href}|${bucket}`;
  }

  function makeResult(url, resolver, confidence, extra = {}) {
    return { ok: true, url, resolver, confidence, ...extra };
  }

  function resolveMediaUrlForPage(forceFresh = false) {
    const now = performance.now?.() ?? Date.now();
    const key = cacheKey();
    if (!forceFresh && resolveCache.value && resolveCache.key === key && now - resolveCache.at < CACHE_MS) {
      return resolveCache.value;
    }

    const started = performance.now?.() ?? Date.now();
    // TikTok can retain the previous permalink while its SPA changes players.
    // Prefer the playing/visible post's own DOM identity when it is available.
    const tiktok = hostMatches(location.hostname, 'tiktok.com')
      ? resolveTikTokFromDom(bestVisibleMedia(true)) : null;
    if (tiktok) {
      const result = makeResult(tiktok, "site-adapter", 96);
      resolveCache = { key, at: now, value: result };
      return result;
    }
    const directKnown = canonicalizeKnownMediaUrl(location.href);
    if (directKnown) {
      const result = makeResult(directKnown, "direct-known", 100);
      resolveCache = { key, at: now, value: result };
      return result;
    }

    const media = bestVisibleMedia();
    const siteSpecific = resolveKnownSiteFromDom(media);
    if (siteSpecific) {
      const result = makeResult(siteSpecific, "site-adapter", 96);
      resolveCache = { key, at: now, value: result };
      return result;
    }

    const candidates = [];
    const seen = new Set();
    addCandidate(candidates, seen, location.href, "location");
    collectNearbyCandidates(candidates, seen, media);
    collectHeadCandidates(candidates, seen);

    let best = bestCandidate(candidates);
    // JSON-LD demande un JSON.parse : on ne le touche que si les signaux
    // légers n'ont pas déjà produit une très bonne réponse.
    if (!best || best.score < 82) {
      collectJsonLdCandidates(candidates, seen);
      best = bestCandidate(candidates);
    }

    const elapsed = Math.max(0, (performance.now?.() ?? Date.now()) - started);

    if (best && best.score >= 60) {
      // Sur les feeds sociaux, location.href générique n'est pas une réponse
      // acceptable : il faut un permalink suffisamment précis.
      const weakFeedFallback =
        isProblematicFeedHost(location.hostname) &&
        isGenericFeedLikeUrl(best.url) &&
        best.score < 82;

      if (!weakFeedFallback) {
        const result = makeResult(best.url, `universal:${best.source}`, Math.min(95, Math.round(best.score)), {
          elapsed_ms: Math.round(elapsed * 10) / 10
        });
        resolveCache = { key, at: now, value: result };
        return result;
      }
    }

    if (!isProblematicFeedHost(location.hostname)) {
      const fallback = cleanTrackingUrl(location.href) || location.href;
      const result = makeResult(fallback, "page-fallback", 35, {
        elapsed_ms: Math.round(elapsed * 10) / 10
      });
      resolveCache = { key, at: now, value: result };
      return result;
    }

    const result = {
      ok: false,
      code: "media_not_detected",
      error: "Média non détecté sur cette page. Place le média à télécharger au centre de l’écran.",
      elapsed_ms: Math.round(elapsed * 10) / 10
    };
    resolveCache = { key, at: now, value: result };
    return result;
  }

  function comparableMediaUrl(rawUrl) {
    if (!rawUrl) return null;
    return canonicalizeKnownMediaUrl(rawUrl) || cleanTrackingUrl(rawUrl) || rawUrl;
  }

  globalThis.KittyMediaResolver = Object.freeze({
    resolveMediaUrlForPage,
    comparableMediaUrl,
    canonicalizeKnownMediaUrl,
    cleanTrackingUrl,
    resolveTikTokMedia,
    // Exposées pour les tests/diagnostic, sans dépendre du backend.
    _canonicalizers: Object.freeze({
      tiktok: canonicalTikTokPermalink,
      instagram: canonicalInstagramPermalink,
      twitter: canonicalTwitterPermalink,
      reddit: canonicalRedditPermalink,
      pinterest: canonicalPinterestPermalink,
      facebook: canonicalFacebookPermalink,
      youtube: canonicalYouTubePermalink,
      dailymotion: canonicalDailymotionPermalink,
      twitch: canonicalTwitchPermalink
    })
  });
})();
