"""Capture the real toolbar popup on a fresh GitHub Actions Windows or macOS runner.

Requires KITTY_VISUAL_TEST=1 and GITHUB_ACTIONS=true; writes example queue data,
then restores the original queue after quitting the isolated Firefox profile.
Only the temporary test XPI gains a controller page. Production popup assets,
manifest permissions and Native Messaging registration are unchanged.
"""
import base64
import html
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import struct
import sys
import tempfile
import time
import traceback
import uuid
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
OUTPUT = SOURCE / ("artifacts/macos-firefox" if sys.platform == "darwin" else "artifacts/windows-firefox")
sys.path.insert(0, str(SOURCE / "native-host"))

# Capture the visible viewport of the real popup browser, including scrollbars.
# Gecko's drawSnapshot works with the normal, separate extension process and
# needs no interactive Windows desktop or OS-level screenshot permission.
CAPTURE_SCRIPT = r"""
const [host, done] = arguments;
(async () => {
  const popup = [...document.querySelectorAll("browser.webextension-popup-browser")]
    .find(node => {
      const panel = node.closest("panel");
      const url = node.currentURI?.spec || "";
      return panel?.state === "open" && url === `moz-extension://${host}/popup.html`;
    });
  if (!popup) throw new Error("La vraie popup Firefox n'est pas ouverte");
  const rect = popup.getBoundingClientRect();
  if (rect.width < 100 || rect.height < 100) throw new Error("Popup sans dimensions visibles");
  const bitmap = await popup.browsingContext.currentWindowGlobal.drawSnapshot(
    new DOMRect(0, 0, rect.width, rect.height), window.devicePixelRatio,
    "rgb(255,255,255)", { drawView: true });
  try {
    const canvas = document.createElementNS("http://www.w3.org/1999/xhtml", "canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    canvas.getContext("2d").drawImage(bitmap, 0, 0);
    return { png: canvas.toDataURL("image/png").split(",")[1],
      width: bitmap.width, height: bitmap.height,
      cssWidth: rect.width, cssHeight: rect.height, panel: popup.closest("panel").id };
  } finally { bitmap.close(); }
})().then(value => done({ok:true, value}), error => done({ok:false, error:String(error.stack || error)}));
"""


def build_test_xpi(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for source in sorted((SOURCE / "extension").rglob("*")):
            if source.is_file():
                package.write(source, source.relative_to(SOURCE / "extension").as_posix())
        for name in ("visual-harness.html", "visual-harness.js"):
            package.write(SOURCE / "tests" / name, name)


def example_state(root, populated):
    import queue_store
    state = queue_store.default_state()
    state["queue_paused"] = True
    if not populated:
        return state
    now = time.time()
    # Complete titles prevent metadata probes; pause prevents media downloads.
    state["queue"] = [
        {"id": f"visual-queue-{index}", "title": title,
         "url": f"https://example.com/kitty-ci/{index}", "mode": "1080",
         "status": "queued", "metadata_status": "ready", "created_at": now - index,
         "updated_at": now, "paused": False}
        for index, title in enumerate((
            "Exemple CI — vidéo en attente", "Exemple CI — français, accents & 100 %",
            "Exemple CI — un titre assez long pour vérifier le retour à la ligne dans la file",
            "Exemple CI — quatrième vidéo", "Exemple CI — cinquième vidéo"), 1)]
    state["history"] = [
        {"id": "visual-finished", "title": "Exemple CI — téléchargement terminé",
         "url": "https://example.com/kitty-ci/finished", "mode": "1080",
         "status": "finished", "progress": 100, "finished_at": now,
         "filepath": str(root / "exemple-ci.mp4")},
        {"id": "visual-cancelled", "title": "Exemple CI — téléchargement annulé",
         "url": "https://example.com/kitty-ci/cancelled", "mode": "audio",
         "status": "cancelled", "finished_at": now - 60},
    ]
    return state


def diagnostics_rendered(state):
    """A finished diagnostic may be ready, warning or error; capture all three."""
    phases = set(str(state.get("dependencyPhase", "")).split())
    return bool(
        state.get("open") and state.get("ready") and state.get("settings")
        and state.get("settingsSections", {}).get("dependencies")
        and state.get("diagnosticsBusy") is False
        and state.get("dependencyCount", 0) > 0
        and phases.intersection({"dependencyReady", "dependencyWarning", "dependencyError"})
    )


def settings_rendered(state):
    destination = str(state.get("destination") or "")
    return bool(state.get("settings") and destination and
                (PurePosixPath(destination).is_absolute() or PureWindowsPath(destination).is_absolute()))


def validate_capture_diagnostics(response):
    """Keep capture success separate from health; fail on broken native dependencies."""
    if not response.get("ok"):
        raise RuntimeError(f"Diagnostic natif indisponible : {response}")
    dependencies = response.get("dependencies", {})
    if dependencies.get("required_ok") is not True:
        raise RuntimeError(f"Dépendances requises indisponibles : {dependencies}")
    if response.get("system", {}).get("runtime_files", {}).get("ok") is not True:
        raise RuntimeError(f"Runtime installé incomplet : {response.get('system')}")


def write_report(report):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "rapport.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    figures = "\n".join(
        f'<figure><figcaption>{html.escape(item["label"])}</figcaption>'
        f'<img src="{html.escape(item["file"])}" alt="{html.escape(item["label"])}"></figure>'
        for item in report["captures"])
    error = html.escape(report.get("error", ""))
    health = report.get("diagnostics")
    diagnostic_note = ""
    if health:
        destination = health.get("system", {}).get("destination", {})
        diagnostic_note = (f'<p>Diagnostic réel du backend : <strong>{html.escape(str(health.get("overall")))}</strong>. '
                           f'{html.escape(str(destination.get("error") or ""))} '
                           'Les détails complets sont dans rapport.json.</p>')
    (OUTPUT / "index.html").write_text(
        '<!doctype html><html lang="fr"><meta charset="utf-8"><title>Kitty — captures Firefox</title>'
        '<style>body{font:16px system-ui;background:#181b22;color:#e9edf5;margin:32px}'
        'main{display:flex;flex-wrap:wrap;gap:24px}figure{margin:0}figcaption{margin:0 0 12px}'
        'img{max-width:100%;border:1px solid #555;border-radius:12px}pre{white-space:pre-wrap}</style>'
        '<h1>Kitty — Firefox sur ' + ('macOS' if sys.platform == 'darwin' else 'Windows') + '</h1><p>Captures de la vraie popup dans un profil Firefox CI isolé. '
        'La file et l’historique utilisent des exemples; aucune vidéo réseau n’est téléchargée. '
        'Ces images montrent des états stabilisés et ne mesurent pas les flashs très brefs.</p>'
        f'<p>Captures : {html.escape(report["status"])}</p>{diagnostic_note}<pre>{error}</pre><main>{figures}</main></html>',
        encoding="utf-8")


def run():
    if not (sys.platform in ("win32", "darwin") and os.environ.get("KITTY_VISUAL_TEST") == "1"
            and os.environ.get("GITHUB_ACTIONS") == "true"):
        print("Captures ignorées : réservées au runner Windows/macOS CI avec KITTY_VISUAL_TEST=1.")
        return 0
    import platform_support
    import queue_store
    import installer_support
    from app_paths import macos_root, windows_root
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import WebDriverWait

    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"status": "en cours", "captures": [], "platform": sys.platform,
              "commit": os.environ.get("GITHUB_SHA"), "examples": True, "headless": True}
    write_report(report)
    driver = None
    scratch_dir = None
    original = None
    root = macos_root() if sys.platform == "darwin" else windows_root()
    queue_file = root / "cache/queue.json"
    lock_file = root / "cache/queue.lock"
    seeded = False
    try:
        current = installer_support.current_install(root)
        if not current:
            raise RuntimeError("Installation Kitty absente")
        firefox = os.environ.get("KITTY_FIREFOX_BINARY") or platform_support.find_firefox()
        if not firefox or not Path(firefox).is_file():
            raise RuntimeError("Firefox absent du runner")
        report["kitty_version"] = current["version"]
        with queue_store.queue_lock(lock_file):
            original = queue_file.read_bytes() if queue_file.exists() else None
            queue_store.atomic_json(queue_file, example_state(root, False))
            seeded = True
        options = Options()
        options.binary_location = str(firefox)
        options.add_argument("-headless")
        options.set_preference("browser.shell.checkDefaultBrowser", False)
        options.set_preference("browser.startup.homepage_override.mstone", "ignore")
        options.set_preference("ui.popup.disable_autohide", True)
        # This preference supports older runner Firefox releases too.
        options.set_preference("extensions.openPopupWithoutUserGesture.enabled", True)
        service = Service(service_args=["--allow-system-access"], log_output=str(OUTPUT / "geckodriver.log"))
        scratch_dir = tempfile.TemporaryDirectory(prefix="kitty-visual-")
        scratch = scratch_dir.name
        xpi = Path(scratch) / "kitty-visual.xpi"
        build_test_xpi(xpi)
        driver = webdriver.Firefox(options=options, service=service)
        driver.set_script_timeout(30)
        driver.set_window_size(1100, 800)
        report["firefox_version"] = driver.capabilities.get("browserVersion")
        report["geckodriver_version"] = driver.capabilities.get("moz:geckodriverVersion")
        addon_id = driver.install_addon(str(xpi), temporary=True)
        if addon_id != "kitty-download-manager@local":
            raise RuntimeError(f"Identité inattendue : {addon_id}")
        with driver.context(driver.CONTEXT_CHROME):
            host = WebDriverWait(driver, 30).until(lambda browser: browser.execute_script(
                "return WebExtensionPolicy.getByID(arguments[0])?.mozExtensionHostname || null", addon_id))
            # Pin the real action in the toolbar of this temporary profile.
            driver.execute_script("""
                let module;
                try {
                  module = ChromeUtils.importESModule("moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs");
                } catch {
                  module = ChromeUtils.importESModule("resource:///modules/CustomizableUI.sys.mjs");
                }
                const {CustomizableUI} = module;
                CustomizableUI.addWidgetToArea("kitty-download-manager_local-browser-action", CustomizableUI.AREA_NAVBAR);
            """)
        driver.get(f"moz-extension://{host}/visual-harness.html")

        def command(action, **fields):
            request_id = uuid.uuid4().hex
            driver.execute_script("""
                document.getElementById("request").value = arguments[0];
                document.getElementById("run").click();
            """, json.dumps({"id": request_id, "action": action, **fields}))
            result = WebDriverWait(driver, 35).until(lambda browser: browser.execute_script("""
                const output = document.getElementById("result");
                return output.dataset.requestId === arguments[0] ? JSON.parse(output.textContent) : null;
            """, request_id))
            if not result["ok"]:
                raise RuntimeError(result["error"])
            if action == "state":
                report["last_popup_state"] = result["value"]
            return result["value"]

        def wait_state(predicate, label="état de la popup"):
            def check(_):
                state = command("state")
                return state if predicate(state) else False
            return WebDriverWait(driver, 30, poll_frequency=.2).until(
                check, message=f"Attente de {label}; dernier état détaillé dans rapport.json")

        def stable_state():
            # Stable geometry and completed startup, not a blind long delay.
            previous = None
            stable_since = None
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                state = command("state")
                geometry = (state.get("width"), state.get("height"), state.get("scrollHeight"),
                            state.get("scrollTop"), state.get("settings"))
                if state.get("ready") and geometry == previous:
                    stable_since = stable_since or time.monotonic()
                    if time.monotonic() - stable_since > .6:
                        return state
                else:
                    stable_since = None
                previous = geometry
                time.sleep(.1)
            raise RuntimeError("La popup n'a pas stabilisé ses dimensions")

        def capture(name, label):
            state = stable_state()
            with driver.context(driver.CONTEXT_CHROME):
                result = driver.execute_async_script(CAPTURE_SCRIPT, host)
            if not result["ok"]:
                raise RuntimeError(result["error"])
            image = result["value"]
            png = base64.b64decode(image.pop("png"), validate=True)
            if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("Capture PNG invalide")
            width, height = struct.unpack(">II", png[16:24])
            if (width, height) != (image["width"], image["height"]):
                raise RuntimeError("Dimensions PNG incohérentes")
            filename = name + ".png"
            (OUTPUT / filename).write_bytes(png)
            report["captures"].append({"file": filename, "label": label, "state": state, **image})
            write_report(report)
            print(f"Capture : {filename} ({width} x {height})", flush=True)

        response = command("prepare")
        if not response.get("ok") or response.get("state", {}).get("queue_paused") is not True:
            raise RuntimeError(f"Native Messaging Firefox ne répond pas correctement : {response}")
        report["native_messaging"] = "ok"
        command("open")
        wait_state(lambda state: state.get("ready"))
        capture("01-principal-vide", "Principal — file et historique vides")
        command("close")
        wait_state(lambda state: not state.get("open"))
        with queue_store.queue_lock(lock_file):
            queue_store.atomic_json(queue_file, example_state(root, True))
        command("open")
        wait_state(lambda state: state.get("ready") and state.get("queueCount") == 5
                   and "terminé" in state.get("status", ""))
        capture("02-principal-termine", "Principal — dernier téléchargement terminé (exemple)")
        command("click", selector="#queueToggle")
        wait_state(lambda state: state.get("sections", {}).get("queue"))
        capture("03-file-ouverte", "File ouverte — cinq exemples en pause")
        command("scroll", bottom=True)
        wait_state(lambda state: state.get("scrollTop", 0) > 0)
        capture("04-file-bas", "File ouverte — bas de la popup après défilement")
        command("click", selector="#queueToggle")
        command("click", selector="#historyToggle")
        command("scroll", bottom=True)
        capture("05-historique", "Historique ouvert — terminé et annulé (exemples)")
        command("click", selector="#openSettings")
        wait_state(settings_rendered)
        command("scroll", bottom=False)
        capture("06-reglages", "Réglages — groupes repliés")
        command("click", selector='[data-settings-section="dependencies"] .settingsGroupToggle')
        wait_state(diagnostics_rendered, label="la fin du diagnostic, quel que soit son état de santé")
        report["diagnostics"] = command("diagnostics")
        command("scroll", selector='[data-settings-section="dependencies"]')
        capture("07-dependances", "Réglages — dépendances du backend")
        validate_capture_diagnostics(report["diagnostics"])
        report["status"] = "réussi"
    except Exception:
        report["status"] = "échec"
        report["error"] = traceback.format_exc()
        print(report["error"], file=sys.stderr)
        if report.get("last_popup_state"):
            print("Dernier état popup : " + json.dumps(report["last_popup_state"], ensure_ascii=False), file=sys.stderr)
        if driver:
            try:
                with driver.context(driver.CONTEXT_CHROME):
                    (OUTPUT / "firefox-erreur.png").write_bytes(driver.get_screenshot_as_png())
                    (OUTPUT / "firefox-erreur.html").write_text(driver.page_source, encoding="utf-8")
            except Exception:
                pass
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                report["cleanup_error"] = traceback.format_exc()
                report["status"] = "échec"
        if seeded:
            try:
                with queue_store.queue_lock(lock_file):
                    if original is None:
                        queue_file.unlink(missing_ok=True)
                    else:
                        installer_support.atomic_bytes(queue_file, original)
                report["queue_restored"] = True
            except Exception:
                report["restore_error"] = traceback.format_exc()
                report["status"] = "échec"
        if scratch_dir:
            try:
                scratch_dir.cleanup()
            except Exception:
                report["temporary_cleanup_error"] = traceback.format_exc()
                report["status"] = "échec"
        write_report(report)
    return 0 if report["status"] == "réussi" else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(run())
