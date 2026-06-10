const PYODIDE_VERSION = "0.26.4";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.js`;

const WP_PY_FILES = [
  "teverun_patcher/__init__.py",
  "teverun_patcher/core/__init__.py",
  "teverun_patcher/core/checksum.py",
  "teverun_patcher/core/thumb2_modimm.py",
  "teverun_patcher/core/hex_loader.py",
  "teverun_patcher/core/patch_engine.py",
  "teverun_patcher/core/fingerprint.py",
  "teverun_patcher/core/auto_unlock.py",
  "teverun_patcher/core/ble_name_patch.py",
  "teverun_patcher/core/settings_persist.py",
  "teverun_patcher/core/cruise_persist.py",
  "teverun_patcher/core/bin_to_hex.py",
  "teverun_patcher/webpatch.py",
];
// Alle Profile werden ins virtuelle FS geschrieben; das Profil wird beim Patchen
// per Fingerprint automatisch erkannt (5.4.14, 5.4.19, ...).
const WP_PROFILE_FILES = [
  "teverun_patcher/profiles/d5_4_14_11.json",
  "teverun_patcher/profiles/r5_4_19.json",
];

const WP_FIRMWARES = {
  r519: { path: "firmwares/AWIVCU_APP_R5_4_19.hex",   base: "AWIVCU_APP_R5_4_19",   kind: "d5",  ble: true,  blinkerFix: true, settingsPersist: true, cruisePersist: true },
  d5:   { path: "firmwares/AWIVCU_APP_D5_4_14_11.hex", base: "AWIVCU_APP_D5_4_14_11", kind: "d5",  ble: true },
  ali:  { path: "firmwares/ALIVCU_APP_D3.4.12.bin",    base: "ALIVCU_APP_D3.4.12",    kind: "ali", ble: false },
  auto: { path: null, base: null, kind: "auto", ble: false },
};

const wpState = {
  pyodide: null,
  ready: false,
  loading: false,
  results: null,
};

function wpEl(id) { return document.getElementById(id); }

function wpToggleAccept() {
  const cb = wpEl("wpAgree");
  const btn = wpEl("wpAcceptBtn");
  if (btn && cb) btn.disabled = !cb.checked;
}
function wpAcceptDisclaimer() {
  try { sessionStorage.setItem("wpDisclaimerAccepted", "1"); } catch (e) {}
  const m = wpEl("wpDisclaimer");
  if (m) m.style.display = "none";
}
window.onFragmentLoaded = function (source) {
  if (!source || source.indexOf("web-patcher") === -1) return;
  let accepted = false;
  try { accepted = sessionStorage.getItem("wpDisclaimerAccepted") === "1"; } catch (e) {}
  const m = document.getElementById("wpDisclaimer");
  if (m && accepted) m.style.display = "none";
};

function wpStatus(msg, kind) {
  const el = wpEl("wpStatus");
  if (!el) return;
  const colors = { info: "#cbd5e1", work: "#60a5fa", ok: "#10b981", err: "#ef4444" };
  el.style.color = colors[kind] || colors.info;
  el.innerHTML = msg;
}

function wpFetchText(url) {
  return fetch(url).then((r) => {
    if (!r.ok) throw new Error(`${url} (${r.status})`);
    return r.text();
  });
}

function wpFetchBytes(url) {
  return fetch(url).then((r) => {
    if (!r.ok) throw new Error(`${url} (${r.status})`);
    return r.arrayBuffer();
  }).then((b) => new Uint8Array(b));
}

function wpLoadPyodideScript() {
  if (window.loadPyodide) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = PYODIDE_CDN;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Pyodide-CDN nicht erreichbar (Internet nötig)."));
    document.head.appendChild(s);
  });
}

async function wpInit() {
  if (wpState.ready || wpState.loading) return;
  wpState.loading = true;
  const btn = wpEl("wpInitBtn");
  if (btn) btn.disabled = true;

  try {
    wpStatus("Lade Pyodide-Laufzeit (einmalig, ~10&nbsp;MB) …", "work");
    await wpLoadPyodideScript();
    wpState.pyodide = await loadPyodide();

    wpStatus("Installiere <code>intelhex</code> …", "work");
    await wpState.pyodide.loadPackage("micropip");
    const micropip = wpState.pyodide.pyimport("micropip");
    await micropip.install("intelhex");

    wpStatus("Lade Patch-Module …", "work");
    const fs = wpState.pyodide.FS;
    fs.mkdirTree("/patcher/teverun_patcher/core");
    fs.mkdirTree("/patcher/teverun_patcher/profiles");
    fs.mkdirTree("/work");

    for (const rel of WP_PY_FILES) {
      const txt = await wpFetchText("patcher-core/" + rel);
      fs.writeFile("/patcher/" + rel, txt);
    }
    for (const rel of WP_PROFILE_FILES) {
      const prof = await wpFetchText("patcher-core/" + rel);
      fs.writeFile("/patcher/" + rel, prof);
    }

    wpState.pyodide.runPython("import sys; sys.path.insert(0, '/patcher')");
    wpState.pyodide.pyimport("teverun_patcher.webpatch");

    wpState.ready = true;
    wpStatus("Bereit. Firmware auswählen, Optionen konfigurieren und Datei erstellen.", "ok");
    const panel = wpEl("wpPanel");
    if (panel) panel.style.display = "block";
  } catch (e) {
    wpStatus("Fehler beim Start: " + e.message, "err");
    if (btn) btn.disabled = false;
  } finally {
    wpState.loading = false;
  }
}

function wpOnFirmwareChange() {
  const fw = WP_FIRMWARES[wpEl("wpFirmware").value];
  const isPatch = fw.kind === "d5";
  wpEl("wpD5Options").style.display = isPatch ? "block" : "none";
  wpEl("wpAliNote").style.display = (fw.kind === "ali") ? "block" : "none";
  const up = wpEl("wpUploadBlock");
  if (up) up.style.display = (fw.kind === "auto") ? "block" : "none";
  const bleBlock = wpEl("wpBleBlock");
  if (bleBlock) bleBlock.style.display = (isPatch && fw.ble) ? "block" : "none";
  const blinkerBlock = wpEl("wpBlinkerBlock");
  if (blinkerBlock) blinkerBlock.style.display = (isPatch && fw.blinkerFix) ? "block" : "none";
  const persistBlock = wpEl("wpPersistBlock");
  if (persistBlock) persistBlock.style.display = (isPatch && fw.settingsPersist) ? "block" : "none";
  const cruiseBlock = wpEl("wpCruiseBlock");
  if (cruiseBlock) cruiseBlock.style.display = (isPatch && fw.cruisePersist) ? "block" : "none";
  wpUpdateFinVisibility();
}

// FIN-Eingabe nur zeigen, wenn eine Länderkennung gewählt ist (Name wird geändert).
function wpUpdateFinVisibility() {
  const sel = wpEl("wpBle");
  const finBlock = wpEl("wpFinBlock");
  if (finBlock) finBlock.style.display = (sel && sel.value) ? "block" : "none";
}

function wpPreviewBle() {
  wpUpdateFinVisibility();
  if (!wpState.ready) return;
  const variant = wpEl("wpBle").value;
  const serial = (wpEl("wpFin").value || "").trim().toUpperCase();
  const out = wpEl("wpBlePreview");
  if (!variant || serial.length < 8) { out.textContent = ""; return; }
  try {
    const wp = wpState.pyodide.pyimport("teverun_patcher.webpatch");
    out.textContent = "→ Neuer BLE-Name: " + wp.ble_preview(variant, serial);
  } catch (e) { out.textContent = ""; }
}

function wpTimestamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

function wpBuildName(fw, speed, variant, blinkerFix, settingsPersist, cruisePersist) {
  if (fw.kind === "ali") return fw.base;
  const parts = [fw.base];
  if (speed > 20) parts.push("Unlocked");
  if (variant) parts.push(`BLE${variant}`);
  if (blinkerFix) parts.push("BlinkerFix");
  if (settingsPersist) parts.push("Persist");
  if (cruisePersist) parts.push("Cruise");
  if (parts.length === 1) parts.push("UNPATCHED");
  return parts.join("_") + "_" + wpTimestamp();
}

async function wpRun() {
  if (!wpState.ready) { wpStatus("Bitte zuerst den Patcher starten.", "err"); return; }
  const runBtn = wpEl("wpRunBtn");
  if (runBtn) runBtn.disabled = true;
  wpEl("wpDownloads").style.display = "none";

  try {
    const fwKey = wpEl("wpFirmware").value;
    const fw = WP_FIRMWARES[fwKey];
    const pyodide = wpState.pyodide;
    const wp = pyodide.pyimport("teverun_patcher.webpatch");

    let speed = 20, variant = "", serial = "", blinkerFix = false, settingsPersist = false, cruisePersist = false;
    if (fw.kind === "d5") {
      speed = parseInt(wpEl("wpSpeed").value || "20", 10);
      if (fw.blinkerFix) {
        const cb = wpEl("wpBlinkerFix");
        blinkerFix = !!(cb && cb.checked);
      }
      if (fw.settingsPersist) {
        const cb = wpEl("wpPersist");
        settingsPersist = !!(cb && cb.checked);
      }
      if (fw.cruisePersist) {
        const cb = wpEl("wpCruise");
        cruisePersist = !!(cb && cb.checked);
      }
      if (fw.ble) {
        variant = wpEl("wpBle").value || "";
        serial = (wpEl("wpFin").value || "").trim().toUpperCase();
        if (variant && serial.length < 8) {
          wpStatus("Für die BLE-Namensänderung wird die FIN benötigt (min. 8 Zeichen).", "err");
          if (runBtn) runBtn.disabled = false;
          return;
        }
      }
    }

    let resProxy, autoName = null;
    if (fw.kind === "auto") {
      const fi = wpEl("wpUpload");
      if (!fi || !fi.files || !fi.files[0]) {
        wpStatus("Bitte zuerst eine Firmware-Datei (.hex) auswählen.", "err");
        if (runBtn) runBtn.disabled = false;
        return;
      }
      const file = fi.files[0];
      autoName = file.name.replace(/\.[^.]+$/, "");
      wpStatus("Auto-Unlock im Browser …", "work");
      const buf = new Uint8Array(await file.arrayBuffer());
      pyodide.FS.writeFile("/work/in.hex", buf);
      resProxy = wp.patch_auto();
    } else {
      wpStatus(`Lade Firmware <code>${fw.path}</code> …`, "work");
      const fwBytes = await wpFetchBytes(fw.path);
      wpStatus("Verarbeitung im Browser …", "work");
      if (fw.kind === "ali") {
        pyodide.FS.writeFile("/work/dump.bin", fwBytes);
        resProxy = wp.passthrough();
      } else {
        pyodide.FS.writeFile("/work/in.hex", fwBytes);
        resProxy = wp.patch_d5(speed, variant || null, serial || null, blinkerFix, settingsPersist, cruisePersist);
      }
    }

    const hexText = resProxy.get("hex");
    const binProxy = resProxy.get("bin");
    const binBytes = binProxy.toJs();
    const crc = resProxy.get("crc");
    const applied = resProxy.get("applied");
    const targetName = resProxy.get("target_name");
    const detected = (fw.kind === "d5") ? resProxy.get("profile") : null;
    const blinkerApplied = (fw.kind === "d5") ? resProxy.get("blinker_fix") : false;
    const persistApplied = (fw.kind === "d5") ? resProxy.get("settings_persist") : false;
    const cruiseApplied = (fw.kind === "d5") ? resProxy.get("cruise_persist") : false;
    binProxy.destroy();
    resProxy.destroy();

    const base = (fw.kind === "auto")
      ? (autoName + "_Unlocked_AUTO_" + wpTimestamp())
      : wpBuildName(fw, speed, variant, blinkerFix, settingsPersist, cruisePersist);
    wpState.results = {
      hexText,
      binBytes,
      hexName: base + ".hex",
      binName: base + ".bin",
    };

    wpEl("wpDlHex").textContent = base + ".hex";
    wpEl("wpDlBin").textContent = base + ".bin";
    wpEl("wpDownloads").style.display = "block";

    const crcHex = "0x" + crc.toString(16).toUpperCase().padStart(4, "0");
    let summary = `Fertig. CRC16-Modbus <code>${crcHex}</code>`;
    if (detected) summary += ` · erkannt: <code>${detected}</code>`;
    if (fw.kind === "d5") summary += ` · ${applied} Patches angewendet`;
    if (fw.kind === "auto") summary += ` · ${applied} Clamps automatisch entfernt`;
    if (blinkerApplied) summary += ` · Blinker-Fix aktiv`;
    if (persistApplied) summary += ` · Settings-Speicherung aktiv`;
    if (cruiseApplied) summary += ` · CruiseMode-Speicherung aktiv`;
    if (targetName) summary += ` · neuer BLE-Name <code>${targetName}</code>`;
    wpStatus(summary + ".", "ok");
  } catch (e) {
    wpStatus("Patch-Fehler: " + e.message, "err");
  } finally {
    if (runBtn) runBtn.disabled = false;
  }
}

function wpDownload(which) {
  const r = wpState.results;
  if (!r) return;
  let data, name, mime;
  if (which === "hex") { data = r.hexText; name = r.hexName; mime = "text/plain"; }
  else { data = r.binBytes; name = r.binName; mime = "application/octet-stream"; }
  const blob = new Blob([data], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
