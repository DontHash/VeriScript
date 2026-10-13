# Artemis reuse

Verified source: D:/Code/Project_auto/tools/artemis and mcp_server/README.md; Project Auto's docs/ARTEMIS-GUIDE.md documents its use. Artemis automates Android UI testing; Flutter builds the app.

Keep Project Auto and its credentials unchanged. tool/artemis_bootstrap.py creates a separate runtime; no .env, existing configuration or traces are copied. Runtime/venv directories are ignored. A configured model provider is required for autonomous AI scenarios; a working emulator alone does not establish readiness.

```powershell
python tool/artemis_bootstrap.py
./tool/artemis.ps1 doctor
./tool/artemis.ps1 mcp
```

APK acceptance scenarios:

1. First launch without network: import English/Nepali fixtures, recognize text, review a number, and confirm correction JSON retains both readings.
2. Capture three photos before conversion, reorder/exclude, rotate/crop and export PDF/DOCX. Restart and confirm draft/export persistence.
3. Switch both themes and system appearance; check narrow layouts and large text.
4. Import a two-spread synthetic video: exactly four pages in left/right/left/right order. Compare every output against a real book recording containing turns, blur, shadows and curved pages.
5. Cancel, deny camera permission, import damaged files and cross crop corners; check errors and retained saved drafts.

Record actual results in VERIFICATION.md. Unrun scenarios remain unverified. Flutter/ADB checks must not be described as an autonomous Artemis run; physical camera behavior and real-book completeness require an actual phone.

2026-10-13 setup: isolated dependencies installed; CLI help succeeds. `doctor --json` reports valid Python/configuration and connected ADB, but blocks autonomous readiness because the Gemini provider key is missing; scrcpy is also missing and the integration host reports a warning. No provider credentials were copied from Project Auto, and no autonomous AI scenario has been run. The provider is for the desktop test agent; it is not a dependency of VeriScript's offline Android processing.
