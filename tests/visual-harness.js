// Added only to the temporary CI XPI. Never bundled in the distributed XPI.
// getViews controls the actual toolbar popup; it never replaces its renderer
// or the native/backend responses with a simulated browser object.
"use strict";

function popupView() {
  return browser.extension.getViews({ type: "popup" })
    .find(view => new URL(view.location.href).pathname === "/popup.html");
}

function popupState() {
  const view = popupView();
  if (!view) return { open: false };
  const doc = view.document;
  // Firefox can expose the popup view before parsing its document finishes.
  // Keep polling until the real DOM exists, including on fast ARM runners.
  if (!doc?.getElementById("settingsView") || !["interactive", "complete"].includes(doc.readyState)) {
    return { open: true, ready: false };
  }
  const text = id => doc.getElementById(id)?.textContent || "";
  const scroll = doc.body;
  return {
    open: true,
    ready: !doc.documentElement.classList.contains("popup-loading"),
    width: view.innerWidth,
    height: view.innerHeight,
    scrollHeight: scroll?.scrollHeight || 0,
    scrollTop: scroll?.scrollTop || 0,
    status: text("status"),
    title: text("currentTitle"),
    queueCount: doc.querySelectorAll("#queue .queueItem").length,
    historyCount: doc.querySelectorAll("#history .item").length,
    settings: !doc.getElementById("settingsView").classList.contains("hidden"),
    dependencies: text("dependencyStateText"),
    dependencyPhase: doc.querySelector('[data-settings-section="dependencies"]').className,
    diagnosticsBusy: doc.getElementById("refreshDiagnostics").disabled,
    dependencyCount: doc.querySelectorAll("#dependencyList .dependencyItem").length,
    dependencyDetails: [...doc.querySelectorAll("#dependencyList .dependencyItem")]
      .map(item => ({ text: item.textContent.trim(),
        detail: item.querySelector(".dependencyValue")?.title || "" })),
    destination: text("destinationPath"),
    language: doc.getElementById("uiLanguage").value,
    sections: Object.fromEntries([...doc.querySelectorAll(".collapseSection")]
      .map(section => [section.dataset.section, !section.classList.contains("collapsed")])),
    settingsSections: Object.fromEntries([...doc.querySelectorAll(".settingsCollapse")]
      .map(section => [section.dataset.settingsSection, !section.classList.contains("collapsed")])),
  };
}

async function command(request) {
  switch (request.action) {
    case "prepare":
      await browser.storage.local.set({
        uiLanguage: "fr", selectedMode: "1080",
        sectionStates: { download: true, queue: false, history: false },
        settingsSectionStates: { cookies: false, dependencies: false, diagnostic: false, maintenance: false },
      });
      return browser.runtime.sendNativeMessage("com.kitty.download_manager", { action: "status" });
    case "open": {
      const current = await browser.windows.getCurrent();
      await browser.windows.update(current.id, { focused: true });
      await browser.action.openPopup({ windowId: current.id });
      return popupState();
    }
    case "close":
      popupView()?.close();
      return { closing: true };
    case "state":
      return popupState();
    case "diagnostics":
      return browser.runtime.sendNativeMessage("com.kitty.download_manager", {
        action: "diagnostics",
        client: { version: browser.runtime.getManifest().version, protocol: 1 },
      });
    case "click": {
      const button = popupView()?.document.querySelector(request.selector);
      if (!button || button.disabled) throw new Error(`Bouton indisponible : ${request.selector}`);
      button.click();
      return popupState();
    }
    case "scroll": {
      const view = popupView();
      if (!view) throw new Error("Popup absente");
      const scroll = view.document.body;
      if (request.selector) {
        const target = view.document.querySelector(request.selector);
        if (!target) throw new Error(`Section absente : ${request.selector}`);
        target.scrollIntoView({ block: "center" });
      } else {
        scroll.scrollTop = request.bottom ? scroll.scrollHeight : 0;
      }
      return popupState();
    }
    default:
      throw new Error(`Commande de test inconnue : ${request.action}`);
  }
}

document.getElementById("run").addEventListener("click", async () => {
  const output = document.getElementById("result");
  output.removeAttribute("data-request-id");
  let request;
  let response;
  try {
    request = JSON.parse(document.getElementById("request").value);
    response = { ok: true, value: await command(request) };
  } catch (error) {
    response = { ok: false, error: String(error.stack || error) };
  }
  output.textContent = JSON.stringify(response);
  output.dataset.requestId = request?.id || "invalid";
});
