// Set the ceiling before the body is parsed. The popup fits short content,
// while long content scrolls internally without exceeding this screen budget.
(() => {
  const reportedHeight = Number(globalThis.screen?.availHeight);
  const availableHeight = Number.isFinite(reportedHeight) && reportedHeight > 0
    ? reportedHeight
    : 720;
  // Leave room for browser chrome, the panel anchor and desktop bars. Values
  // are CSS pixels, so display scaling is already reflected by screen.
  const height = Math.max(120, Math.min(520, availableHeight - 200));
  document.documentElement.style.setProperty("--kitty-popup-max-height", `${height}px`);
})();
