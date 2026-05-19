(() => {
  "use strict";

  const initialData = document.getElementById("all-decks");
  const clientName = document.getElementById("client-name");
  const locationList = document.getElementById("location-list");
  const locationTitle = document.getElementById("location-title");
  const deckSummary = document.getElementById("deck-summary");
  const slideList = document.getElementById("slide-list");
  const pendingFiles = document.getElementById("pending-files");
  const pendingCount = document.getElementById("pending-count");
  const saveStatus = document.getElementById("save-status");
  const mediaUpload = document.getElementById("media-upload");
  const saveDecks = document.getElementById("save-decks");
  const themeToggle = document.getElementById("theme-toggle");
  const themeStorageKey = "promocaster-admin-theme";
  const legacyThemeStorageKeys = ["promocaster-editor-theme", "promocaster-inspector-theme"];
  const controlClient = document.body.dataset.client || "phgi";

  let data = { locations: [] };
  let selectedLocation = "";
  let dragIndex = -1;
  let dateFocus = null;

  function refreshIcons() {
    window.lucide?.createIcons({
      attrs: {
        "stroke-width": 2,
      },
    });
  }

  function icon(name) {
    const element = document.createElement("i");
    element.setAttribute("data-lucide", name);
    element.setAttribute("aria-hidden", "true");
    return element;
  }

  function parseJson(text) {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  function preferredTheme() {
    const stored = window.localStorage.getItem(themeStorageKey);
    if (stored === "light" || stored === "dark") return stored;
    for (const legacyKey of legacyThemeStorageKeys) {
      const legacyTheme = window.localStorage.getItem(legacyKey);
      if (legacyTheme === "light" || legacyTheme === "dark") {
        window.localStorage.setItem(themeStorageKey, legacyTheme);
        return legacyTheme;
      }
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function setTheme(theme, persist = true) {
    const nextTheme = theme === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = nextTheme;
    document.documentElement.dataset.bsTheme = nextTheme;
    themeToggle.setAttribute("aria-label", `Switch to ${nextTheme === "dark" ? "light" : "dark"} mode`);
    if (persist) window.localStorage.setItem(themeStorageKey, nextTheme);
  }

  function normalizeInitialData(payload) {
    const locations = Array.isArray(payload?.locations) ? payload.locations : [];
    return {
      activeLocation: payload?.activeLocation || locations[0]?.name || "",
      locations: locations.map((location) => ({
        name: location.name,
        slides: (location.slides || []).map((slide) => ({
          name: slide.name,
          src: slide.src,
          type: slide.type,
          durationMs: slide.type === "video" ? null : Number(slide.durationMs) || 10000,
          maxDurationMs: slide.type === "video" ? Number(slide.maxDurationMs || slide.durationMs) || null : null,
          startsOn: slide.startsOn || slide.starts || "",
          expiresOn: slide.expiresOn || slide.expires || "",
          pendingFile: null,
          objectUrl: "",
        })),
      })),
    };
  }

  function setClientName(payload) {
    const name = payload?.client?.name || controlClient;
    clientName.textContent = name;
  }

  function getLocation(name = selectedLocation) {
    return data.locations.find((location) => location.name === name) || data.locations[0] || null;
  }

  function markChanged() {
    saveStatus.textContent = "Unsaved changes";
    renderAll();
  }

  function sanitizeFileName(name) {
    return name.trim().replace(/\s+/g, "-").replace(/[^A-Za-z0-9._-]/g, "");
  }

  function srcForName(name) {
    return `/api/clients/${encodeURIComponent(controlClient)}/media/${encodeURIComponent(name)}`;
  }

  function msToSeconds(ms) {
    return Math.round((Number(ms) || 0) / 1000);
  }

  function formatDuration(ms) {
    const seconds = Math.round((Number(ms) || 0) / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    if (minutes === 0) return `${remainder}s`;
    return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
  }

  function scheduleLabel(slide) {
    const labels = [];
    if (slide.startsOn) labels.push(`starts ${slide.startsOn}`);
    if (slide.expiresOn) labels.push(`expires ${slide.expiresOn}`);
    return labels.join(" / ");
  }

  function secondsToMs(seconds, fallbackSeconds = 10) {
    return Math.max(Math.round((Number(seconds) || fallbackSeconds) * 1000), 1000);
  }

  function renderLocations() {
    locationList.replaceChildren();
    data.locations.forEach((location) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "location-button btn";
      button.classList.toggle("is-active", location.name === selectedLocation);

      const name = document.createElement("span");
      name.textContent = location.name;
      const count = document.createElement("span");
      count.textContent = String(location.slides.length);
      button.append(name, count);
      button.addEventListener("click", () => {
        selectedLocation = location.name;
        window.location.hash = encodeURIComponent(location.name);
        renderAll();
      });

      locationList.append(button);
    });
  }

  function renderSlides() {
    const location = getLocation();
    slideList.replaceChildren();
    if (!location) {
      locationTitle.textContent = "No locations";
      deckSummary.textContent = "0 slides";
      return;
    }

    locationTitle.textContent = location.name;
    const estimatedRuntime = location.slides.reduce((sum, slide) => (
      sum + (slide.type === "video" ? Number(slide.maxDurationMs) || 0 : Number(slide.durationMs) || 0)
    ), 0);
    deckSummary.textContent = `${location.slides.length} slides · ${formatDuration(estimatedRuntime)} scheduled`;

    location.slides.forEach((slide, index) => {
      const row = document.createElement("div");
      row.className = "slide-row";
      row.draggable = true;
      row.dataset.index = String(index);

      row.addEventListener("dragstart", () => {
        dragIndex = index;
        row.classList.add("is-dragging");
      });
      row.addEventListener("dragend", () => {
        dragIndex = -1;
        row.classList.remove("is-dragging");
      });
      row.addEventListener("dragover", (event) => {
        event.preventDefault();
        row.classList.add("is-drag-over");
      });
      row.addEventListener("dragleave", () => row.classList.remove("is-drag-over"));
      row.addEventListener("drop", (event) => {
        event.preventDefault();
        row.classList.remove("is-drag-over");
        moveSlide(dragIndex, index);
      });

      const thumb = document.createElement("div");
      thumb.className = "thumb";
      const indexBadge = document.createElement("span");
      indexBadge.className = "thumb-index";
      indexBadge.textContent = String(index + 1);
      thumb.append(mediaElement(slide), indexBadge);

      const details = document.createElement("div");
      details.className = "slide-name";
      const title = document.createElement("strong");
      title.textContent = slide.name;
      const meta = document.createElement("div");
      meta.className = "slide-meta";
      const typeBadge = document.createElement("span");
      typeBadge.className = "slide-type";
      typeBadge.textContent = slide.type;
      const timing = document.createElement("span");
      timing.textContent = slide.type === "video"
        ? `timeout ${slide.maxDurationMs ? formatDuration(slide.maxDurationMs) : "auto"}`
        : `duration ${formatDuration(slide.durationMs)}`;
      meta.append(typeBadge, timing);
      const schedule = scheduleLabel(slide);
      if (schedule) {
        const scheduleMeta = document.createElement("span");
        scheduleMeta.textContent = schedule;
        meta.append(scheduleMeta);
      }
      details.append(title, meta);

      const timingControls = timingControl(slide);
      const scheduleControls = scheduleControl(slide, index);
      const controls = document.createElement("div");
      controls.className = "slide-controls";
      controls.append(timingControls, scheduleControls);

      const actions = document.createElement("div");
      actions.className = "row-actions";
      actions.append(
        rowButton("arrow-up", "Move up", () => moveSlide(index, index - 1)),
        rowButton("arrow-down", "Move down", () => moveSlide(index, index + 1)),
        rowButton("trash-2", "Remove", () => removeSlide(index)),
      );

      row.append(thumb, details, controls, actions);
      slideList.append(row);
    });

    if (dateFocus?.location === selectedLocation) {
      const input = slideList.querySelector(`[data-date-field="${dateFocus.field}"][data-date-index="${dateFocus.index}"]`);
      dateFocus = null;
      input?.focus();
      input?.showPicker?.();
    }
  }

  function timingControl(slide) {
    const wrapper = document.createElement("div");
    wrapper.className = "timing-control";

    if (slide.type === "video" && !slide.maxDurationMs) {
      const enable = document.createElement("button");
      enable.type = "button";
      enable.className = "timeout-enable btn btn-outline-secondary btn-sm";
      enable.append(icon("timer"), document.createTextNode("Timeout"));
      enable.addEventListener("click", () => {
        slide.maxDurationMs = 5 * 60 * 1000;
        markChanged();
      });
      wrapper.append(enable);
      return wrapper;
    }

    const input = document.createElement("input");
    input.className = "slide-duration";
    input.classList.add("form-control", "form-control-sm");
    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.value = slide.type === "video" ? String(msToSeconds(slide.maxDurationMs)) : String(msToSeconds(slide.durationMs));
    input.ariaLabel = slide.type === "video" ? "Fallback timeout in seconds" : "Duration in seconds";
    input.addEventListener("change", () => {
      if (slide.type === "video") {
        slide.maxDurationMs = secondsToMs(input.value, 300);
      } else {
        slide.durationMs = secondsToMs(input.value, 10);
      }
      markChanged();
    });
    wrapper.append(input);

    const unit = document.createElement("span");
    unit.className = "time-unit";
    unit.textContent = "sec";
    wrapper.append(unit);

    if (slide.type === "video") {
      const clear = document.createElement("button");
      clear.type = "button";
      clear.className = "timeout-clear btn btn-outline-secondary btn-sm";
      clear.append(icon("rotate-ccw"), document.createTextNode("Auto"));
      clear.addEventListener("click", () => {
        slide.maxDurationMs = null;
        markChanged();
      });
      wrapper.append(clear);
    }

    return wrapper;
  }

  function todayYmd() {
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${now.getFullYear()}-${month}-${day}`;
  }

  function scheduleControl(slide, index) {
    const wrapper = document.createElement("div");
    wrapper.className = "schedule-control";
    wrapper.append(
      dateControl(slide, index, "startsOn", "Enable start", "Start date"),
      dateControl(slide, index, "expiresOn", "Enable expiration", "Expiration date"),
    );
    return wrapper;
  }

  function dateControl(slide, index, field, enableLabel, ariaLabel) {
    const wrapper = document.createElement("div");
    wrapper.className = "date-control";

    if (!slide[field]) {
      const enable = document.createElement("button");
      enable.type = "button";
      enable.className = "date-enable btn btn-outline-secondary btn-sm";
      enable.append(icon(field === "startsOn" ? "calendar-plus" : "calendar-x"), document.createTextNode(enableLabel.replace("Enable ", "")));
      enable.addEventListener("click", () => {
        slide[field] = todayYmd();
        dateFocus = { location: selectedLocation, index, field };
        markChanged();
      });
      wrapper.append(enable);
      return wrapper;
    }

    const input = document.createElement("input");
    input.className = "slide-date";
    input.classList.add("form-control", "form-control-sm");
    input.type = "date";
    input.value = slide[field];
    input.dataset.dateField = field;
    input.dataset.dateIndex = String(index);
    input.ariaLabel = `${ariaLabel} for ${slide.name}`;
    input.addEventListener("change", () => {
      slide[field] = input.value;
      markChanged();
    });

    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "date-clear btn btn-outline-secondary btn-sm";
    clear.append(icon("x"), document.createTextNode("Clear"));
    clear.addEventListener("click", () => {
      slide[field] = "";
      markChanged();
    });

    wrapper.append(input, clear);
    return wrapper;
  }

  function mediaElement(slide) {
    const media = document.createElement(slide.type === "video" ? "video" : "img");
    const src = slide.objectUrl || slide.src;
    media.src = src;

    if (slide.type === "video") {
      media.muted = true;
      media.defaultMuted = true;
      media.playsInline = true;
      media.preload = "metadata";
      media.controls = true;
    } else {
      media.alt = slide.name;
      media.loading = "lazy";
      media.decoding = "async";
    }

    return media;
  }

  function rowButton(iconName, title, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-outline-secondary btn-sm icon-only";
    button.append(icon(iconName));
    button.title = title;
    button.setAttribute("aria-label", title);
    button.addEventListener("click", onClick);
    return button;
  }

  function moveSlide(from, to) {
    const location = getLocation();
    if (!location) return;
    if (from < 0 || from >= location.slides.length || to < 0 || to >= location.slides.length || from === to) return;
    const [slide] = location.slides.splice(from, 1);
    location.slides.splice(to, 0, slide);
    markChanged();
  }

  function removeSlide(index) {
    const location = getLocation();
    if (!location) return;
    const [slide] = location.slides.splice(index, 1);
    if (slide?.objectUrl) URL.revokeObjectURL(slide.objectUrl);
    markChanged();
  }

  function renderPendingFiles() {
    const files = data.locations.flatMap((location) => location.slides.filter((slide) => slide.pendingFile));
    pendingFiles.replaceChildren();
    pendingCount.textContent = `${files.length} files`;

    if (files.length === 0) {
      const empty = document.createElement("div");
      empty.className = "pending-file";
      empty.textContent = "No pending uploads";
      pendingFiles.append(empty);
      return;
    }

    files.forEach((slide) => {
      const item = document.createElement("div");
      item.className = "pending-file";
      const name = document.createElement("strong");
      name.textContent = slide.name;
      const detail = document.createElement("span");
      detail.textContent = `${slide.type} - ${(slide.pendingFile.size / 1024 / 1024).toFixed(1)}MB`;
      item.append(name, detail);
      pendingFiles.append(item);
    });
  }

  function renderAll() {
    renderLocations();
    renderSlides();
    renderPendingFiles();
    refreshIcons();
  }

  function addFiles(files) {
    const location = getLocation();
    if (!location) return;

    Array.from(files).forEach((file) => {
      const name = sanitizeFileName(file.name);
      if (!name) return;
      const type = file.type === "video/mp4" || name.toLowerCase().endsWith(".mp4") ? "video" : "image";
      location.slides.push({
        name,
        src: srcForName(name),
        type,
        durationMs: type === "video" ? null : 10000,
        maxDurationMs: null,
        startsOn: "",
        expiresOn: "",
        pendingFile: file,
        objectUrl: URL.createObjectURL(file),
      });
    });

    mediaUpload.value = "";
    markChanged();
  }

  function savePayload() {
    return {
      activeLocation: selectedLocation,
      locations: data.locations.map((location) => ({
        name: location.name,
        slides: location.slides.map((slide) => ({
          name: slide.name,
          type: slide.type,
          durationMs: slide.type === "video" ? null : slide.durationMs,
          maxDurationMs: slide.type === "video" ? slide.maxDurationMs : null,
          startsOn: slide.startsOn || "",
          expiresOn: slide.expiresOn || "",
        })),
      })),
    };
  }

  function pendingUploadSlides() {
    return data.locations.flatMap((location) => location.slides.filter((slide) => slide.pendingFile));
  }

  function clearPendingUploads() {
    pendingUploadSlides().forEach((slide) => {
      if (slide.objectUrl) URL.revokeObjectURL(slide.objectUrl);
      slide.pendingFile = null;
      slide.objectUrl = "";
      slide.src = srcForName(slide.name);
    });
  }

  async function saveToRepo() {
    saveDecks.disabled = true;
    const uploads = pendingUploadSlides();
    saveStatus.textContent = uploads.length > 0 ? `Saving ${uploads.length} files` : "Saving";
    try {
      const formData = new FormData();
      formData.append("deck", JSON.stringify(savePayload()));
      uploads.forEach((slide) => {
        formData.append("media", slide.pendingFile, slide.name);
      });
      const response = await fetch(`/api/clients/${encodeURIComponent(controlClient)}/decks`, {
        method: "POST",
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        saveStatus.textContent = payload.message || `Save failed (${response.status})`;
        return;
      }
      clearPendingUploads();
      saveStatus.textContent = payload.state === "no_changes" ? "No changes" : `Pushed ${payload.commit}`;
      renderAll();
    } catch {
      saveStatus.textContent = "Save failed";
    } finally {
      saveDecks.disabled = false;
    }
  }

  async function loadRemoteDecks() {
    saveStatus.textContent = "Loading repo data";
    try {
      const response = await fetch(`/api/clients/${encodeURIComponent(controlClient)}/decks`, { cache: "no-store" });
      if (!response.ok) {
        const message = response.status === 409 ? "Repo not synced" : `Load failed (${response.status})`;
        saveStatus.textContent = message;
        return;
      }
      const payload = await response.json();
      setClientName(payload);
      data = normalizeInitialData(payload);
      selectedLocation = decodeURIComponent(window.location.hash.replace(/^#/, "")) || data.activeLocation || data.locations[0]?.name || "";
      if (!getLocation(selectedLocation)) selectedLocation = data.locations[0]?.name || "";
      saveStatus.textContent = "Loaded from repo";
      renderAll();
    } catch {
      saveStatus.textContent = "Load failed";
    }
  }

  mediaUpload.addEventListener("change", () => addFiles(mediaUpload.files));
  saveDecks.addEventListener("click", () => saveToRepo());
  themeToggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    setTheme(currentTheme === "dark" ? "light" : "dark");
  });
  window.addEventListener("hashchange", () => {
    const hashLocation = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (hashLocation && getLocation(hashLocation)) {
      selectedLocation = hashLocation;
      renderAll();
    }
  });

  setTheme(preferredTheme(), false);
  const embeddedData = parseJson(initialData?.textContent || "{}") || {};
  setClientName(embeddedData);
  data = normalizeInitialData(embeddedData);
  selectedLocation = decodeURIComponent(window.location.hash.replace(/^#/, "")) || data.activeLocation || data.locations[0]?.name || "";
  if (!getLocation(selectedLocation)) selectedLocation = data.locations[0]?.name || "";
  renderAll();
  loadRemoteDecks();
  refreshIcons();
})();
