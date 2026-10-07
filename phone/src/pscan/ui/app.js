/* PScan phone UI: renders the controller's snapshot and sends actions back to Python. */
(() => {
  "use strict";

  const KEY = new URLSearchParams(location.search).get("k") || "";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  // ------------------------------------------------------------------ icons
  // 24x24 stroke icons (drawn for PScan).
  const ICONS = {
    camera: '<path d="M3 8.6A1.6 1.6 0 0 1 4.6 7h2.2l1.5-2.2h7.4L17.2 7h2.2A1.6 1.6 0 0 1 21 8.6v9.2a1.6 1.6 0 0 1-1.6 1.6H4.6A1.6 1.6 0 0 1 3 17.8z"/><circle cx="12" cy="13.2" r="3.6"/>',
    send: '<path d="M21.5 2.5 11 13"/><path d="M21.5 2.5 15 21l-4-8-8-4z"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    page: '<rect x="5.5" y="3" width="13" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    rotate: '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
    "chevron-left": '<path d="M15 5l-7 7 7 7"/>',
    "chevron-right": '<path d="M9 5l7 7-7 7"/>',
    crop: '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    trash: '<path d="M3.5 6.5h17"/><path d="M9 6.5V4.3c0-.7.6-1.3 1.3-1.3h3.4c.7 0 1.3.6 1.3 1.3v2.2"/><path d="M6 6.5l.9 13a2 2 0 0 0 2 1.9h6.2a2 2 0 0 0 2-1.9l.9-13"/><path d="M10 11v6M14 11v6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 16.5v-5"/><path d="M12 7.6h.01"/>',
    laptop: '<rect x="4" y="4.5" width="16" height="11" rx="1.8"/><path d="M2 19.5h20"/><path d="M10 12.5h4"/>',
    refresh: '<path d="M20.5 12a8.5 8.5 0 0 1-14.8 5.7L3.5 15.5"/><path d="M3.5 12A8.5 8.5 0 0 1 18.3 6.3l2.2 2.2"/><path d="M20.5 3.5v5h-5M3.5 20.5v-5h5"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    contrast: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor" stroke="none"/>',
    search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5"/><path d="M8 10.5h5"/>',
    wifi: '<path d="M2.5 8.8a14 14 0 0 1 19 0"/><path d="M5.5 12.3a9.5 9.5 0 0 1 13 0"/><path d="M8.7 15.7a4.8 4.8 0 0 1 6.6 0"/><path d="M12 19.3h.01"/>',
    shield: '<path d="M12 3l7.5 3v5.6c0 4.6-3.2 8-7.5 9.4-4.3-1.4-7.5-4.8-7.5-9.4V6z"/><path d="M9 12.2l2.1 2.1 4-4.1"/>',
    alert: '<path d="M10.3 4.2 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4"/><path d="M12 17h.01"/>',
    more: '<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>',
    logout: '<path d="M15 3.5h3.5a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H15"/><path d="M10 16.5 5.5 12 10 7.5"/><path d="M5.5 12h11"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    upload: '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4.5 16v2.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V16"/>',
  };
  const icon = (name) =>
    `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  $$("[data-icon]").forEach((el) => el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon)));
  $(".modal-hero .logo").innerHTML = $(".appbar .logo").innerHTML;

  // ------------------------------------------------------------- talking to Python
  let S = null; // latest snapshot

  async function act(name, args = {}) {
    try {
      const r = await fetch("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-PScan-Key": KEY },
        body: JSON.stringify({ name, args }),
      });
      if (!r.ok) throw new Error(r.status);
    } catch (e) {
      showToast("PScan is busy. Please try again.", "error");
    }
  }

  async function poll() {
    let since = 0;
    for (;;) {
      try {
        const r = await fetch(`/api/state?since=${since}`, { headers: { "X-PScan-Key": KEY }, cache: "no-store" });
        if (r.ok) {
          const s = await r.json();
          since = s.v;
          S = s;
          render(s);
          continue;
        }
      } catch (e) {
        /* app paused (camera open) or restarting: retry */
      }
      await new Promise((res) => setTimeout(res, 800));
    }
  }

  // ---------------------------------------------------------------- overlays
  const backdrop = $("#backdrop");
  let openSheet = null; // element
  let openModal = null;
  let pageKey = null; // page shown in the page sheet

  function showSheet(id) {
    if (openSheet && openSheet.id !== id) openSheet.classList.remove("show");
    openSheet = $("#" + id);
    openSheet.classList.add("show");
    openSheet.scrollTop = 0;
    backdrop.classList.add("show");
  }
  function closeSheet() {
    if (openSheet) openSheet.classList.remove("show");
    openSheet = null;
    pageKey = null;
    if (!openModal) backdrop.classList.remove("show");
    document.activeElement && document.activeElement.blur();
  }
  function showModal(id) {
    openModal = $("#" + id);
    openModal.classList.add("show");
    backdrop.classList.add("show");
  }
  function closeModal() {
    if (openModal) openModal.classList.remove("show");
    openModal = null;
    if (!openSheet) backdrop.classList.remove("show");
  }
  backdrop.addEventListener("click", () => {
    if (openModal) return closeModal();
    if (openSheet && openSheet.id === "sheet-save" && S && S.saving.state === "saving") return;
    if (openSheet && openSheet.id === "sheet-save" && S && S.saving.state !== "idle") act("save_dismiss");
    closeSheet();
  });
  $$("[data-close]").forEach((b) =>
    b.addEventListener("click", () => (b.closest(".modal") ? closeModal() : closeSheet()))
  );

  let confirmAction = null;
  function confirmBox(title, text, okText, onOk) {
    $("#confirm-title").textContent = title;
    $("#confirm-text").textContent = text;
    $("#confirm-ok").textContent = okText;
    confirmAction = onOk;
    showModal("modal-confirm");
  }
  $("#confirm-cancel").addEventListener("click", closeModal);
  $("#confirm-ok").addEventListener("click", () => {
    closeModal();
    if (confirmAction) confirmAction();
    confirmAction = null;
  });

  let toastTimer = null;
  let lastToast = 0;
  function showToast(text, kind = "info") {
    const t = $("#toast");
    $("#toast-icon").innerHTML = icon(kind === "error" ? "alert" : "info");
    $("#toast-text").textContent = text;
    t.className = "toast show" + (kind === "error" ? " error" : "");
    const bar = $("#bottombar");
    t.style.bottom = bar.hidden ? "" : bar.offsetHeight + 12 + "px";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 3800);
  }

  // ---------------------------------------------------------------- rendering
  const PAPER_RATIOS = { A4: "210 / 297", Letter: "8.5 / 11", Long: "8.5 / 13", Legal: "8.5 / 14", Original: "3 / 4" };
  const MODE_HELP = {
    color: "Keeps colours: stamps, signatures, photos.",
    gray: "Shades of gray. Smaller files.",
    bw: "Crisp black text on white. Smallest files.",
  };
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  function render(s) {
    const root = document.documentElement.style;
    root.setProperty("--safe-top", (s.insets.top || 0) + "px");
    root.setProperty("--safe-bottom", (s.insets.bottom || 0) + "px");
    root.setProperty("--paper-ratio", PAPER_RATIOS[s.options.paper] || PAPER_RATIOS.A4);

    $("#screen-connect").hidden = s.screen !== "connect";
    $("#screen-pair").hidden = s.screen !== "pair";
    $("#screen-scan").hidden = s.screen !== "scan";
    $("#bottombar").hidden = s.screen !== "scan";
    $("#btn-pc").hidden = !s.servers.length;

    renderStatus(s);
    if (s.screen === "connect") renderConnect(s);
    if (s.screen === "pair") renderPair(s);
    if (s.screen === "scan") renderScan(s);
    else if (openSheet) closeSheet();
    renderSheets(s);

    if (s.toast && s.toast.id > lastToast) {
      if (!firstRender) showToast(s.toast.text, s.toast.kind); // skip toasts from before the page loaded
      lastToast = s.toast.id;
    }
    firstRender = false;
  }
  let firstRender = true;

  function renderStatus(s) {
    let state = s.connection.state;
    let text = s.connection.text;
    if (s.screen !== "scan") {
      state = s.search.busy ? "connecting" : "idle";
      text = s.search.busy
        ? "Searching for PCs…"
        : s.screen === "pair"
          ? "Pairing…"
          : s.servers.length
            ? "Choose a PC to add"
            : "Not connected to a PC yet";
    }
    $("#status-dot").className = "dot " + state;
    $("#status-dot").hidden = state === "connecting";
    $("#status-spin").hidden = state !== "connecting";
    $("#status-text").textContent = text || "…";
    const busy = s.refreshing || s.search.busy || (s.screen === "scan" && (s.pending > 0 || state === "connecting"));
    $("#progress").hidden = !busy;
  }

  // ------------------------------------------------------------ connect screen
  function renderConnect(s) {
    $("#btn-connect-back").hidden = !s.servers.length;
    $("#hero-title").textContent = s.servers.length ? "Add another PC" : "Connect to your PC";
    $("#hero-art").classList.toggle("searching", s.search.busy);
    $("#search-spin").hidden = !s.search.busy;
    $("#btn-search").disabled = s.search.busy;
    $("#btn-manual").disabled = s.search.busy;
    const list = $("#found-list");
    const sig = JSON.stringify([s.search.found, s.search.busy, s.pair.busy]);
    if (list.dataset.sig !== sig) {
      list.dataset.sig = sig;
      if (!s.search.found.length) {
        list.innerHTML = `<div class="list-empty">${s.search.busy ? "Looking for PCs running PScan…" : "No PCs found yet."}</div>`;
      } else {
        list.innerHTML = s.search.found
          .map(
            (f) => `<button class="list-item" data-id="${esc(f.id)}"${s.pair.busy ? " disabled" : ""}>
              <span class="round-icon">${icon("laptop")}</span>
              <span class="grow"><b>${esc(f.name)}</b><small>${esc(f.host)} · ${f.paired ? "paired, tap to use" : "tap to pair"}</small></span>
              <span class="chev">${icon("chevron-right")}</span></button>`
          )
          .join("");
        $$(".list-item", list).forEach((b) =>
          b.addEventListener("click", () => {
            const f = s.search.found.find((x) => x.id === b.dataset.id);
            const go = () => {
              b.querySelector(".chev").innerHTML = '<span class="spinner"></span>';
              act("pair_start", { server_id: b.dataset.id });
            };
            if (f && f.paired) confirmSwitch(f.id, f.name, go);
            else go();
          })
        );
      }
    }
    const msg = $("#search-message");
    msg.hidden = !s.search.message;
    msg.textContent = s.search.message;
  }
  $("#btn-search").addEventListener("click", () => act("search"));
  $("#btn-connect-back").addEventListener("click", () => act("connect_back"));
  $("#manual-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const host = $("#manual-ip").value.trim();
    if (host) act("connect_manual", { host });
    $("#manual-ip").blur();
  });

  // --------------------------------------------------------------- pair screen
  let pairShownFor = null;
  function renderPair(s) {
    $("#pair-title").textContent = `Pair with ${s.pair.server}`;
    $("#pair-help").innerHTML = `A 6-digit code just appeared on <b>${esc(s.pair.server)}</b> as a notification (or right-click the PScan tray icon → <i>Show pairing code</i>). Type it below.`;
    $("#pair-spin").hidden = !s.pair.busy;
    $("#btn-pair").disabled = s.pair.busy;
    $("#btn-resend").disabled = s.pair.busy;
    const err = $("#pair-error");
    err.hidden = !s.pair.error;
    err.textContent = s.pair.error;
    if (pairShownFor !== s.pair.server) {
      pairShownFor = s.pair.server;
      $("#pair-code").value = "";
      setTimeout(() => $("#pair-code").focus(), 150);
    }
  }
  const codeInput = $("#pair-code");
  codeInput.addEventListener("input", () => {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
    if (codeInput.value.length === 6) submitCode();
  });
  function submitCode() {
    if (codeInput.value.length < 6) return;
    act("pair_finish", { code: codeInput.value });
  }
  $("#pair-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submitCode();
  });
  $("#btn-resend").addEventListener("click", () => {
    codeInput.value = "";
    act("pair_resend");
  });
  $("#btn-pair-back").addEventListener("click", () => {
    pairShownFor = null;
    act("pair_back");
  });

  // --------------------------------------------------------------- scan screen
  function renderScan(s) {
    const n = s.pages.length;
    const paper = s.options.paper === "Original" ? "original size" : s.options.paper;
    const mode = (s.options.modes.find((m) => m.id === s.options.mode) || {}).label || "";
    $("#count").innerHTML = n ? `<b>${n}</b> ${n === 1 ? "page" : "pages"} · ${esc(paper)} · ${esc(mode)}` : "";
    $("#toolbar").hidden = !n;
    $("#empty").hidden = n > 0;
    const saving = s.saving.state === "saving";
    $("#btn-clear").disabled = saving;
    $("#btn-add").disabled = saving;
    $("#btn-save").disabled = saving || !n;
    $("#chip-paper-text").textContent = s.options.paper === "Original" ? "Original size" : s.options.paper;
    $("#chip-mode-text").textContent = mode;
    $("#chip-ocr").classList.toggle("on", s.options.ocr);
    $("#chip-ocr").querySelector("span").textContent = s.options.ocr ? "Searchable" : "Not searchable";
    renderGrid(s);
  }

  function pageView(p) {
    if (p.status === "failed") return { overlay: "error", label: "Upload failed · retrying", status: ["err", "alert", "Not sent yet"] };
    if (p.status === "waiting") return { overlay: "busy", label: "Waiting to send…", status: ["", "upload", "In queue"] };
    if (p.status === "uploading") return { overlay: "busy", label: "Sending to PC…", status: ["", "upload", "Sending…"] };
    const status = !p.cropped ? "No edges found" : p.crop ? "Cropped" : "Full photo";
    if (p.busy) return { overlay: "busy", label: "Updating…", status: ["ok", "check", status] };
    return { overlay: null, label: "", status: ["ok", "check", status] };
  }

  function renderGrid(s) {
    const grid = $("#grid");
    const existing = new Map([...grid.children].map((el) => [el.dataset.key, el]));
    s.pages.forEach((p, i) => {
      let el = existing.get(p.key);
      if (!el) {
        el = document.createElement("div");
        el.className = "page-card";
        el.dataset.key = p.key;
        el.innerHTML = `<div class="thumb"><img alt="" hidden><span class="badge"></span><div class="overlay" hidden></div></div>
          <div class="card-meta"><span class="status"></span><span class="more">${icon("more")}</span></div>`;
        el.addEventListener("click", () => openPage(p.key));
        $("img", el).addEventListener("load", () => $(".thumb", el).classList.add("loaded"));
      }
      existing.delete(p.key);
      if (grid.children[i] !== el) grid.insertBefore(el, grid.children[i] || null);

      const img = $("img", el);
      if (p.thumb) {
        const src = `${p.thumb}&k=${KEY}`;
        if (img.dataset.src !== src) {
          img.dataset.src = src;
          img.src = src;
        }
        img.hidden = false;
      } else if (img.dataset.src) {
        delete img.dataset.src;
        img.removeAttribute("src");
        img.hidden = true;
        $(".thumb", el).classList.remove("loaded");
      }
      $(".badge", el).textContent = i + 1;
      const v = pageView(p);
      const ov = $(".overlay", el);
      ov.hidden = !v.overlay;
      ov.className = "overlay" + (v.overlay === "error" ? " error" : "");
      const ovHtml = v.overlay ? `${v.overlay === "error" ? icon("alert") : '<span class="spinner"></span>'}<span>${v.label}</span>` : "";
      if (ov.dataset.html !== ovHtml) ov.innerHTML = ov.dataset.html = ovHtml;
      const st = $(".status", el);
      st.className = "status " + v.status[0];
      const stHtml = `${icon(v.status[1])}<span>${v.status[2]}</span>`;
      if (st.dataset.html !== stHtml) st.innerHTML = st.dataset.html = stHtml;
    });
    existing.forEach((el) => el.remove());
  }

  $("#btn-add").addEventListener("click", () => act("add_page"));
  $("#btn-clear").addEventListener("click", () =>
    confirmBox("Clear all pages?", `This removes ${plural(S.pages.length, "page")} from this scan.`, "Clear all", () => act("clear_all"))
  );
  $("#chip-ocr").addEventListener("click", () => {
    act("set_option", { ocr: !S.options.ocr });
    showToast(S.options.ocr ? "Text won't be searchable (faster)." : "The PDF text will be searchable.");
  });
  $("#chip-paper").addEventListener("click", () => showSheet("sheet-paper"));
  $("#chip-mode").addEventListener("click", () => showSheet("sheet-mode"));
  $("#btn-save").addEventListener("click", () => {
    $("#save-name").value = "";
    showSheet("sheet-save");
  });
  $("#btn-about").addEventListener("click", () => showModal("modal-about"));
  $("#btn-pc").addEventListener("click", () => {
    showSheet("sheet-pc");
    act("search"); // refresh which paired PCs are on this network
  });
  $("#btn-add-pc").addEventListener("click", () => {
    const go = () => {
      closeSheet();
      act("add_pc");
    };
    const onPc = S.pages.filter((p) => p.status === "ready").length;
    if (!onPc || !S.server) return go();
    confirmBox(
      "Add another PC?",
      `After pairing, scans go to the new PC and the ${plural(onPc, "page")} already on ${S.server.name} will be left out of this scan. Save them first if you need them.`,
      "Continue",
      go
    );
  });

  // Switching PCs leaves out pages that were already sent to the old PC, so ask first.
  function confirmSwitch(id, name, onGo) {
    const active = S.servers.find((x) => x.active);
    const onPc = S.pages.filter((p) => p.status === "ready").length;
    if (!active || active.id === id || !onPc) return onGo();
    confirmBox(
      `Send scans to ${name}?`,
      `${plural(onPc, "page")} already on ${active.name} will be left out of this scan. Save them first if you need them.`,
      "Switch PC",
      onGo
    );
  }

  // ------------------------------------------------------------------ sheets
  function openPage(key) {
    pageKey = key;
    renderPageSheet(S);
    showSheet("sheet-page");
  }

  function renderPageSheet(s) {
    const i = s.pages.findIndex((p) => p.key === pageKey);
    if (i < 0) return closeSheet();
    const p = s.pages[i];
    const ready = p.status === "ready" && !p.busy && s.saving.state !== "saving";
    $("#page-title").textContent = `Page ${i + 1} of ${s.pages.length}`;
    const img = $("#page-preview-img");
    const src = p.thumb ? `${p.thumb}&k=${KEY}` : "";
    if (img.dataset.src !== src) {
      img.dataset.src = src;
      if (src) img.src = src;
      else img.removeAttribute("src");
    }
    $("#page-preview-overlay").hidden = ready || p.status === "failed";
    $("#page-note").textContent =
      p.status === "failed" ? `Not on the PC yet: ${p.error || "upload failed"}. Retrying automatically.`
      : p.status !== "ready" ? "Sending this page to the PC…"
      : !p.cropped ? "PScan couldn't find the page edges, so the whole photo is used."
      : p.crop ? "Cropped to the page edges. Tap Crop to use the whole photo."
      : "Using the whole photo. Tap Crop to cut it to the page edges.";
    $("#pa-rotate").disabled = !ready;
    $("#pa-left").disabled = i === 0;
    $("#pa-right").disabled = i === s.pages.length - 1;
    $("#pa-retake").disabled = p.status === "uploading";
    $("#pa-crop").disabled = !ready || !p.cropped;
    $("#pa-crop-text").textContent = !p.cropped ? "No edges" : p.crop ? "Crop: on" : "Crop: off";
    $("#pa-delete").disabled = p.status === "uploading";
  }
  $("#pa-rotate").addEventListener("click", () => act("rotate", { key: pageKey }));
  $("#pa-left").addEventListener("click", () => act("move", { key: pageKey, delta: -1 }));
  $("#pa-right").addEventListener("click", () => act("move", { key: pageKey, delta: 1 }));
  $("#pa-crop").addEventListener("click", () => act("toggle_crop", { key: pageKey }));
  $("#pa-retake").addEventListener("click", () => {
    const key = pageKey;
    closeSheet();
    act("retake", { key });
  });
  $("#pa-delete").addEventListener("click", () => {
    const key = pageKey;
    const n = S.pages.findIndex((p) => p.key === key) + 1;
    confirmBox("Delete this page?", `Page ${n} will be removed from this scan.`, "Delete", () => {
      closeSheet();
      act("delete", { key });
    });
  });

  function renderOptions(s) {
    const papers = $("#paper-options");
    const pSig = s.options.paper;
    if (papers.dataset.sig !== pSig) {
      papers.dataset.sig = pSig;
      papers.innerHTML = s.options.papers
        .map((o) => {
          const [name, size] = o.label.split(" · ");
          const ratio = { A4: 1.414, Letter: 1.294, Long: 1.529, Legal: 1.647 }[o.id];
          const shape = ratio ? `<i style="height:${Math.round(26 * ratio)}px"></i>` : `<i style="height:26px;border-style:dashed"></i>`;
          return `<button class="option${o.id === s.options.paper ? " selected" : ""}" data-paper="${o.id}">
            <span class="paper-shape">${shape}</span>
            <span class="grow"><b>${esc(name)}${o.id === "A4" ? " (default)" : ""}</b><small>${esc(size || "Each page keeps its own proportions")}</small></span>
            <span class="check">${icon("check")}</span></button>`;
        })
        .join("");
      $$("[data-paper]", papers).forEach((b) =>
        b.addEventListener("click", () => {
          act("set_option", { paper: b.dataset.paper });
          closeSheet();
        })
      );
    }
    const modes = $("#mode-options");
    if (modes.dataset.sig !== s.options.mode) {
      modes.dataset.sig = s.options.mode;
      modes.innerHTML = s.options.modes
        .map(
          (o) => `<button class="option${o.id === s.options.mode ? " selected" : ""}" data-mode="${o.id}">
            <span class="swatch ${o.id}"></span>
            <span class="grow"><b>${esc(o.label)}</b><small>${MODE_HELP[o.id] || ""}</small></span>
            <span class="check">${icon("check")}</span></button>`
        )
        .join("");
      $$("[data-mode]", modes).forEach((b) =>
        b.addEventListener("click", () => {
          act("set_option", { mode: b.dataset.mode });
          closeSheet();
        })
      );
    }
  }

  let lastSaveName = "";
  function renderSave(s) {
    const st = s.saving.state;
    if (st !== "idle" && (!openSheet || openSheet.id !== "sheet-save")) showSheet("sheet-save");
    $("#save-form").hidden = st !== "idle";
    $("#save-progress").hidden = st !== "saving";
    $("#save-done").hidden = st !== "done";
    $("#save-error").hidden = st !== "error";
    const server = s.server ? s.server.name : "your PC";
    $("#save-title").textContent = `Save to ${server}`;
    const mode = (s.options.modes.find((m) => m.id === s.options.mode) || {}).label || "";
    $("#save-summary").innerHTML =
      `<span>${icon("page")}${plural(s.pages.length, "page")}</span><span>${esc(s.options.paper === "Original" ? "Original size" : s.options.paper)}</span>` +
      `<span>${esc(mode)}</span>${s.options.ocr ? `<span>${icon("search")}Searchable</span>` : ""}`;
    const now = new Date();
    const pad = (x) => String(x).padStart(2, "0");
    $("#save-name").placeholder = `Scan_${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}`;
    if (st === "saving") {
      $("#save-server").textContent = s.saving.server || server;
      $("#save-progress-text").textContent = s.saving.ocr
        ? "Cleaning the pages and making the text searchable. This can take a minute."
        : "Cleaning the pages and building the PDF.";
    }
    if (st === "done") {
      $("#save-filename").textContent = s.saving.filename;
      $("#save-where").textContent = `${plural(s.saving.pages, "page")} · ${s.saving.paper} · saved in ${s.saving.folder} on ${s.saving.server}`;
      $("#save-note").hidden = !s.saving.note;
      $("#save-note").textContent = s.saving.note || "";
    }
    if (st === "error") $("#save-error-text").textContent = s.saving.message || "Something went wrong.";
  }
  function doSave() {
    lastSaveName = $("#save-name").value.trim();
    $("#save-name").blur();
    act("save", { name: lastSaveName });
  }
  $("#btn-save-go").addEventListener("click", doSave);
  $("#save-name").addEventListener("keydown", (e) => e.key === "Enter" && doSave());
  $("#btn-save-done").addEventListener("click", () => {
    act("save_dismiss");
    closeSheet();
  });
  $("#btn-save-close").addEventListener("click", () => {
    act("save_dismiss");
    closeSheet();
  });
  $("#btn-save-retry").addEventListener("click", () => act("save", { name: lastSaveName }));

  function pcStatus(s, pc) {
    if (pc.active) {
      const text = { online: "In use · connected", connecting: "In use · connecting…" }[s.connection.state];
      return [s.connection.state, "● " + (text || "In use · not found")];
    }
    return pc.nearby ? ["nearby", "● On this network · tap to use"] : ["away", "Not on this network"];
  }

  function renderPcs(s) {
    $("#pcs-spin").hidden = !s.search.busy;
    const list = $("#pc-list");
    const rows = s.servers.map((pc) => [pc, pcStatus(s, pc)]);
    const sig = JSON.stringify(rows);
    if (list.dataset.sig === sig) return;
    list.dataset.sig = sig;
    list.innerHTML = rows
      .map(
        ([pc, [cls, text]]) => `<div class="pc-row${pc.active ? " active" : ""}">
          <button class="pc-main" data-use="${esc(pc.id)}"><span class="round-icon">${icon("laptop")}</span>
            <span class="grow"><b>${esc(pc.name)}</b><small>${esc(pc.host)}</small><span class="pc-state ${cls}">${text}</span></span></button>
          <button class="icon-btn plain" data-forget="${esc(pc.id)}" aria-label="Forget ${esc(pc.name)}">${icon("trash")}</button></div>`
      )
      .join("");
    $$("[data-use]", list).forEach((b) =>
      b.addEventListener("click", () => {
        const pc = S.servers.find((x) => x.id === b.dataset.use);
        if (!pc || pc.active) return;
        confirmSwitch(pc.id, pc.name, () => {
          closeSheet();
          act("use_pc", { server_id: pc.id });
        });
      })
    );
    $$("[data-forget]", list).forEach((b) =>
      b.addEventListener("click", () => {
        const pc = S.servers.find((x) => x.id === b.dataset.forget);
        if (!pc) return;
        confirmBox(
          `Forget ${pc.name}?`,
          `This phone stops sending scans to ${pc.name} until you pair them again with a new code.` +
            (pc.active && S.pages.some((p) => p.status === "ready") ? " Pages already sent to it are left out of this scan." : ""),
          "Forget",
          () => act("forget_pc", { server_id: pc.id })
        );
      })
    );
  }

  function renderSheets(s) {
    renderOptions(s);
    renderPcs(s);
    if (s.screen === "scan") renderSave(s);
    if (pageKey && openSheet && openSheet.id === "sheet-page") renderPageSheet(s);
    $("#about-version").textContent = s.app.version;
    $("#about-year").textContent = s.app.year;
  }

  function esc(text) {
    return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  // Keep a focused text box visible above the keyboard.
  document.addEventListener("focusin", (e) => {
    if (e.target.matches("input")) setTimeout(() => e.target.scrollIntoView({ block: "center", behavior: "smooth" }), 300);
  });
  document.addEventListener("contextmenu", (e) => e.preventDefault());

  poll();
})();
