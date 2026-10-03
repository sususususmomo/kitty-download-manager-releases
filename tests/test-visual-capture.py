"""Regressions for completed diagnostic states in the Windows capture workflow."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name("capture-windows-firefox.py")
spec = importlib.util.spec_from_file_location("kitty_visual_capture", SCRIPT)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureDiagnosticTests(unittest.TestCase):
    def state(self, phase):
        return {"open": True, "ready": True, "settings": True,
                "settingsSections": {"dependencies": True}, "diagnosticsBusy": False,
                "dependencyCount": 7, "dependencyPhase": f"settingsGroup settingsCollapse {phase}"}

    def test_finished_warning_and_error_do_not_wait_for_green(self):
        for phase in ("dependencyReady", "dependencyWarning", "dependencyError"):
            with self.subTest(phase=phase):
                self.assertTrue(capture.diagnostics_rendered(self.state(phase)))

    def test_unfinished_or_hidden_diagnostic_still_waits(self):
        changes = ({"diagnosticsBusy": True}, {"dependencyCount": 0},
                   {"dependencyPhase": "dependencyUnknown"}, {"settings": False},
                   {"settingsSections": {"dependencies": False}}, {"ready": False}, {"open": False})
        for change in changes:
            with self.subTest(change=change):
                state = self.state("dependencyReady")
                state.update(change)
                self.assertFalse(capture.diagnostics_rendered(state))

    def diagnostic(self):
        return {"ok": True, "overall": "error", "dependencies": {
            "required_ok": True, "required_missing": [], "optional_missing": []},
            "system": {"runtime_files": {"ok": True}, "destination": {
                "exists": False, "directory": False, "writable": False,
                "error": "Le dossier de destination n’existe pas."}}}

    def test_new_destination_error_does_not_invalidate_captured_ui(self):
        response = self.diagnostic()
        capture.validate_capture_diagnostics(response)
        self.assertEqual(response["overall"], "error")
        self.assertFalse(response["system"]["destination"]["directory"])

    def test_optional_dependency_warning_is_preserved(self):
        response = self.diagnostic()
        response["overall"] = "warning"
        response["dependencies"]["optional_missing"] = ["mutagen"]
        capture.validate_capture_diagnostics(response)
        self.assertEqual(response["dependencies"]["optional_missing"], ["mutagen"])

    def test_required_dependency_or_runtime_failure_remains_an_error(self):
        response = self.diagnostic()
        response["dependencies"].update(required_ok=False, required_missing=["ffmpeg"])
        with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
            capture.validate_capture_diagnostics(response)
        response = self.diagnostic()
        response["system"]["runtime_files"]["ok"] = False
        with self.assertRaisesRegex(RuntimeError, "Runtime installé incomplet"):
            capture.validate_capture_diagnostics(response)
        with self.assertRaisesRegex(RuntimeError, "Diagnostic natif indisponible"):
            capture.validate_capture_diagnostics({"ok": False, "error": "native host failed"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
