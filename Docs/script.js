function copyCommand() {
    const commandText = "python -m teverun_patcher.cli";
    navigator.clipboard
        .writeText(commandText)
        .then(() => {
            const btn = document.querySelector(".copy-btn");
            if (btn) {
                btn.innerText = "Kopiert!";
                setTimeout(() => {
                    btn.innerText = "Kopieren";
                }, 2000);
            }
        })
        .catch((err) => console.error("Fehler beim Kopieren: ", err));
}

function analyzeBleName() {
    const inputInput = document.getElementById("bleCalcInput");
    if (!inputInput) return;

    const input = inputInput.value.trim().toUpperCase();
    const resultBox = document.getElementById("bleCalcResult");
    const resRegion = document.getElementById("resRegion");
    const resModel = document.getElementById("resModel");
    const resCode = document.getElementById("resCode");
    const resDecomp = document.getElementById("resDecomp");

    if (!input || input.length < 8) {
        if (resultBox) resultBox.style.display = "none";
        return;
    }
    if (resultBox) resultBox.style.display = "block";

    let region = "Unbekannt";
    let model = "Unbekanntes Modell / Nicht im App-Filter gelistet";
    let code = "";
    let decomp = "";

    const MODELS_A = {
        FM: "FIGHTER MINI", FP: "FIGHTER MINI PRO", FE: "FIGHTER ELEVEN",
        FU: "FIGHTER ELEVEN+", SU: "SUPREME ULTRA", SR: "SUPREME 7260",
        T4: "TETRA 4 MOTOR", T2: "TETRA 2 MOTOR",
    };

    function regionName(s) {
        if (s.startsWith("TDEINT")) return "TDEINT (Deutschland International, erweitert)";
        if (s.startsWith("TDE")) return "TDE (Deutschland, striktes eKFV)";
        if (s.startsWith("T1IL")) return "T1IL (Israel)";
        if (s.startsWith("T1")) return "T1 (Standard International)";
        if (s.startsWith("TAT")) return "TAT (Österreich und Alpenraum)";
        if (s.startsWith("T2")) return "T2 (Global, vollständig offen)";
        return "Andere Standardkennung";
    }

    function modelFromCode3(c) {
        if (c.startsWith("GTE") || c.startsWith("GTP")) return "TEVERUN GT";
        if (c.startsWith("T40")) return "TETRA 4 MOTOR";
        if (c.startsWith("T20")) return "TETRA 2 MOTOR";
        if (c.startsWith("FTE")) return "FIGHTER TEN";
        if (c.startsWith("FEE") || c.startsWith("FEP")) return "FIGHTER ELEVEN";
        if (c.startsWith("SPP")) return "SUPREME PLUS";
        if (c.startsWith("SPU")) return "SUPREME ULTRA";
        if (c.startsWith("SPR")) return "SUPREME 7260R";
        if (c.startsWith("BME") || c.startsWith("BMP") || c.startsWith("BMU")) return "BLADE MINI";
        if (c.startsWith("FME") || c.startsWith("FMO") || c.startsWith("FMP") || c.startsWith("FMA")) return "FIGHTER MINI";
        if (c.startsWith("BQE") || c.startsWith("BQP")) return "BLADE Q";
        if (c.startsWith("FQ")) return "FIGHTER Q";
        if (c.startsWith("SE")) return "TEVERUN SPACE";
        return null;
    }

    const deMatch = input.match(/^([A-Z]+)(\d)([A-Z]{2}[A-Z0-9])(\d{2})([A-Z])(\d+)$/);

    if (input.startsWith("T2")) {
        region = regionName(input);
        code = input.substring(7, 9);
        model = MODELS_A[code] || model;
    } else if (deMatch) {
        const country = deMatch[1], gen = deMatch[2], mdl = deMatch[3];
        const year = deMatch[4], idLetter = deMatch[5], counter = deMatch[6];
        region = regionName(country);
        code = mdl;
        model = modelFromCode3(mdl) || MODELS_A[mdl.substring(0, 2)] || model;
        decomp =
            "Land: <b style='color:#a78bfa'>" + country + "</b> &nbsp;·&nbsp; " +
            "Generation: <b style='color:#f59e0b'>" + gen + "</b> &nbsp;·&nbsp; " +
            "Modell: <b style='color:#10b981'>" + mdl + "</b> &nbsp;·&nbsp; " +
            "Baujahr: <b style='color:#60a5fa'>20" + year + "</b> &nbsp;·&nbsp; " +
            "Identifikationsnummer: <b style='color:#f8fafc'>" + idLetter + counter + "</b>";
    } else {
        region = regionName(input);
        code = input.substring(6, 9);
        model = modelFromCode3(code) || model;
    }

    if (resRegion) resRegion.innerText = region;
    if (resModel) resModel.innerText = model;
    if (resCode) resCode.innerText = code || "Kein extrahierbarer Code";
    if (resDecomp) resDecomp.innerHTML = decomp;
}

document.addEventListener("DOMContentLoaded", () => {
    const mainContent = document.getElementById("mainContent");
    const sidebarNav = document.getElementById("sidebarNav");
    const searchInput = document.getElementById("searchInput");

    async function loadContent(source) {
        if (!source) return;

        mainContent.innerHTML = '<div class="card"><p>Inhalt wird geladen...</p></div>';

        try {
            const response = await fetch(source, { cache: "no-store" });
            if (!response.ok) throw new Error("Die Datei konnte nicht geladen werden.");

            const htmlText = await response.text();
            mainContent.innerHTML = htmlText;
            window.scrollTo(0, 0);
            if (typeof window.onFragmentLoaded === "function") window.onFragmentLoaded(source);

            const allNavItems = sidebarNav.querySelectorAll(".nav-item");
            allNavItems.forEach((nav) => {
                if (nav.getAttribute("data-source") === source) {
                    nav.classList.add("active");
                } else {
                    nav.classList.remove("active");
                }
            });
        } catch (error) {
            mainContent.innerHTML = `<div class="card"><p style="color: #ef4444;">Fehler: ${error.message}</p></div>`;
        }
    }

    async function initNavigation() {
        try {
            const response = await fetch("docs/navigation.html", { cache: "no-store" });
            if (!response.ok) throw new Error("Navigation konnte nicht geladen werden.");

            const navHtml = await response.text();
            sidebarNav.innerHTML = navHtml;

            const sidebarNavItems = sidebarNav.querySelectorAll(".nav-item");
            sidebarNavItems.forEach((item) => {
                item.addEventListener("click", (e) => {
                    e.preventDefault();
                    loadContent(item.getAttribute("data-source"));
                });
            });

            initSearch(sidebarNavItems);
            loadContent("docs/start.html");
        } catch (error) {
            sidebarNav.innerHTML = `<p style="color: #ef4444; font-size: 13px; padding: 10px;">Nav-Fehler: ${error.message}</p>`;
        }
    }

    mainContent.addEventListener("click", (e) => {
        const targetLink = e.target.closest(".nav-item");
        if (targetLink) {
            e.preventDefault();
            loadContent(targetLink.getAttribute("data-source"));
        }
    });

    function initSearch(navItems) {
        if (!searchInput) return;

        searchInput.addEventListener("input", () => {
            const query = searchInput.value.toLowerCase();
            navItems.forEach((item) => {
                const text = item.textContent.toLowerCase();
                item.style.display = text.includes(query) ? "block" : "none";
            });
        });
    }

    initNavigation();
});
