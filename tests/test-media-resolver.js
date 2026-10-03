#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const resolverPath = path.join(ROOT, "extension", "media-resolver.js");
const source = fs.readFileSync(resolverPath, "utf8");

let head = {};
let mediaElements = [];
let jsonLdScripts = [];
let tiktokContainers = [];
let wrapperElements = [];

function rect(top = 100, height = 400, left = 100, width = 600) {
  return { top, bottom: top + height, left, right: left + width, height, width };
}

function makeElement(options = {}) {
  const attrs = { ...(options.attrs || {}) };
  const qsa = options.qsa || {};
  const qs = options.qs || {};
  const closestMap = options.closestMap || {};

  return {
    href: options.href || "",
    id: options.id || "",
    textContent: options.textContent || "",
    parentElement: options.parentElement || null,
    getBoundingClientRect() {
      return options.rect || rect();
    },
    getAttribute(name) {
      if (name === "href" && options.href) return options.href;
      return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
    },
    matches(selector) {
      if (typeof options.matches === "function") return options.matches(selector);
      return false;
    },
    closest(selector) {
      if (typeof options.closest === "function") return options.closest(selector);
      return closestMap[selector] || null;
    },
    querySelectorAll(selector) {
      if (typeof options.querySelectorAll === "function") return options.querySelectorAll(selector);
      return qsa[selector] || [];
    },
    querySelector(selector) {
      if (typeof options.querySelector === "function") return options.querySelector(selector);
      return qs[selector] || null;
    }
  };
}

const documentMock = {
  querySelector(selector) {
    return head[selector] || null;
  },
  querySelectorAll(selector) {
    if (selector === "video, audio") return mediaElements;
    if (selector === 'script[type="application/ld+json"]') return jsonLdScripts;
    if (selector === '.xgplayer-container, [id^="xgwrapper-"]') return wrapperElements;
    if (selector.includes('[data-e2e="recommend-list-item-container"]')) return tiktokContainers;
    return [];
  }
};

const context = {
  URL,
  console,
  performance,
  location: new URL("https://example.com/"),
  window: {
    innerWidth: 1280,
    innerHeight: 720,
    scrollY: 0
  },
  document: documentMock
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: resolverPath });

const resolver = context.KittyMediaResolver;
if (!resolver) throw new Error("KittyMediaResolver non exporté");

let passed = 0;
function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`${label}\n  attendu: ${expected}\n  reçu:    ${actual}`);
  }
  passed += 1;
}

function assertTrue(value, label) {
  if (!value) throw new Error(label);
  passed += 1;
}

function resetPage(url) {
  context.location = new URL(url);
  head = {};
  mediaElements = [];
  jsonLdScripts = [];
  tiktokContainers = [];
  wrapperElements = [];
  context.window.scrollY = 0;
}

const canonicalCases = [
  [
    "TikTok query",
    "https://www.tiktok.com/@andreea_bostanica/video/7660560870455840021?is_from_webapp=1&sender_device=pc",
    "https://www.tiktok.com/@andreea_bostanica/video/7660560870455840021"
  ],
  [
    "Instagram Reel",
    "https://www.instagram.com/reels/ABC_123/?igshid=foo",
    "https://www.instagram.com/reel/ABC_123/"
  ],
  [
    "Instagram Post",
    "https://instagram.com/p/C0ffee-42/?utm_source=test",
    "https://www.instagram.com/p/C0ffee-42/"
  ],
  [
    "X status",
    "https://x.com/example/status/1234567890?s=20",
    "https://x.com/i/status/1234567890"
  ],
  [
    "Twitter legacy",
    "https://twitter.com/i/web/status/987654321",
    "https://x.com/i/status/987654321"
  ],
  [
    "Reddit post",
    "https://www.reddit.com/r/videos/comments/abc123/a_title/?utm_source=share",
    "https://www.reddit.com/comments/abc123"
  ],
  [
    "Facebook Reel",
    "https://www.facebook.com/reel/123456789/?mibextid=x",
    "https://www.facebook.com/reel/123456789"
  ],
  [
    "Facebook Watch",
    "https://www.facebook.com/watch/?v=123456789&ref=sharing",
    "https://www.facebook.com/watch/?v=123456789"
  ],
  [
    "YouTube watch",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=foo&t=4",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ],
  [
    "youtu.be",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ],
  [
    "Pinterest pin",
    "https://www.pinterest.com/pin/a-pretty-video--984881012265751603/?utm_source=share",
    "https://www.pinterest.com/pin/984881012265751603/"
  ],
  [
    "Pinterest France",
    "https://www.pinterest.fr/pin/664281013778109217/?utm_medium=social",
    "https://www.pinterest.com/pin/664281013778109217/"
  ],
  [
    "Dailymotion",
    "https://www.dailymotion.com/video/x9abcde?playlist=x",
    "https://www.dailymotion.com/video/x9abcde"
  ],
  [
    "Twitch clip",
    "https://clips.twitch.tv/FancyClipSlug?tt_content=url",
    "https://clips.twitch.tv/FancyClipSlug"
  ]
];

for (const [label, input, expected] of canonicalCases) {
  assertEqual(resolver.canonicalizeKnownMediaUrl(input), expected, label);
}

assertEqual(
  resolver.cleanTrackingUrl("https://example.com/watch/42?utm_source=x&feature=share&quality=hd#frag"),
  "https://example.com/watch/42?quality=hd",
  "Nettoyage tracking conserve les paramètres fonctionnels"
);

// Direct known URL
resetPage("https://www.tiktok.com/@user/video/7660560870455840021?sender_device=pc");
let result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "Resolver direct TikTok doit réussir");
assertEqual(result.url, "https://www.tiktok.com/@user/video/7660560870455840021", "Resolver direct TikTok");
assertEqual(result.resolver, "direct-known", "Resolver direct-known");

// canonical <link>
resetPage("https://example.com/feed");
head['link[rel~="canonical"][href]'] = { href: "https://example.com/video/42?utm_source=homepage" };
result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "canonical link doit réussir");
assertEqual(result.url, "https://example.com/video/42", "canonical link URL");
assertEqual(result.resolver, "universal:canonical", "canonical link source");

// og:url
resetPage("https://example.com/feed");
head['meta[property="og:url"][content]'] = { content: "https://example.com/watch/99?fbclid=123" };
result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "og:url doit réussir");
assertEqual(result.url, "https://example.com/watch/99", "og:url nettoyé");

// JSON-LD fallback
resetPage("https://example.com/feed");
jsonLdScripts = [{
  textContent: JSON.stringify({
    "@context": "https://schema.org",
    "@type": "VideoObject",
    "name": "Demo",
    "url": "https://example.com/video/777?utm_medium=social"
  })
}];
result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "JSON-LD VideoObject doit réussir");
assertEqual(result.url, "https://example.com/video/777", "JSON-LD URL");

// Problematic social feed must not silently use generic URL.
resetPage("https://www.instagram.com/reels/");
result = resolver.resolveMediaUrlForPage(true);
assertTrue(!result.ok && result.code === "media_not_detected", "Instagram feed générique doit échouer proprement");

// X/Twitter DOM adapter around visible video.
resetPage("https://x.com/home");
const statusAnchor = makeElement({
  href: "https://x.com/alice/status/111222333?utm_source=feed",
  rect: rect(140, 20, 200, 300)
});
const article = makeElement({
  rect: rect(80, 560, 100, 800),
  qsa: { "a[href]": [statusAnchor] }
});
const twitterMedia = makeElement({
  rect: rect(120, 420, 140, 740),
  parentElement: article,
  closest(selector) {
    if (selector === "article") return article;
    if (selector === "a[href]") return null;
    return null;
  }
});
mediaElements = [twitterMedia];
result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "Adapter X doit réussir");
assertEqual(result.url, "https://x.com/i/status/111222333", "Adapter X URL");
assertEqual(result.resolver, "site-adapter", "Adapter X source");

// TikTok cinema container: no permalink required, reconstruct from ID + profile.
resetPage("https://www.tiktok.com/foryou");
const profile = makeElement({ href: "https://www.tiktok.com/@kitty_user" });
const tikContainer = makeElement({
  rect: rect(40, 640, 120, 760),
  attrs: { "data-cinema-mode-snap-row": "7660560870455840021" },
  querySelectorAll(selector) {
    if (selector === 'a[href*="/video/"]') return [];
    if (selector === 'a[href^="/@"], a[href*="tiktok.com/@"]') return [profile];
    if (selector === '.xgplayer-container, [id^="xgwrapper-"]') return [];
    return [];
  }
});
tiktokContainers = [tikContainer];
result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "Adapter TikTok cinema doit réussir");
assertEqual(
  result.url,
  "https://www.tiktok.com/@kitty_user/video/7660560870455840021",
  "Adapter TikTok reconstruit le permalink"
);
assertEqual(result.resolver, "site-adapter", "Adapter TikTok source");

// Pinterest feed: visible video + nearby pin permalink.
resetPage("https://www.pinterest.com/");
const pinterestPinLink = makeElement({
  href: "https://www.pinterest.com/pin/something-nice--984881012265751603/?utm_source=feed",
  rect: rect(135, 24, 220, 320)
});
const pinterestCard = makeElement({
  rect: rect(70, 580, 100, 820),
  qsa: { "a[href]": [pinterestPinLink] }
});
const pinterestMedia = makeElement({
  rect: rect(100, 440, 150, 720),
  parentElement: pinterestCard,
  closest(selector) {
    if (selector === '[data-test-id="pin"], [data-test-id*="pin"], article, main') return pinterestCard;
    if (selector === "a[href]") return null;
    return null;
  }
});
mediaElements = [pinterestMedia];
result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "Adapter Pinterest doit réussir");
assertEqual(
  result.url,
  "https://www.pinterest.com/pin/984881012265751603/",
  "Adapter Pinterest URL"
);
assertEqual(result.resolver, "site-adapter", "Adapter Pinterest source");

// Generic non-social page: safe fallback and tracking removal.
resetPage("https://media.example.org/article/hello?utm_source=x&id=12#player");
result = resolver.resolveMediaUrlForPage(true);
assertTrue(result.ok, "Fallback page générique doit réussir");
assertEqual(result.url, "https://media.example.org/article/hello?id=12", "Fallback générique nettoyé");
assertEqual(result.resolver, "page-fallback", "Fallback generic source");

console.log(`Resolver: ${passed} assertions OK`);
