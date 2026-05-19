(() => {
  "use strict";

  const initialData = document.getElementById("all-decks");
  const locationList = document.getElementById("location-list");
  const locationTitle = document.getElementById("location-title");
  const summary = document.getElementById("summary");
  const preview = document.getElementById("preview");
  const previewTitle = document.getElementById("preview-title");
  const slideGrid = document.getElementById("slide-grid");
  const auditStatus = document.getElementById("audit-status");
  const prevSlide = document.getElementById("prev-slide");
  const nextSlide = document.getElementById("next-slide");
  const themeToggle = document.getElementById("theme-toggle");
  const themeStorageKey = "promocaster-admin-theme";
  const legacyThemeStorageKeys = ["promocaster-inspector-theme", "promocaster-editor-theme"];
  const controlClient = document.body.dataset.client || "phgi";

  let data = { locations: [] };
  let selectedLocation = "";
  let selectedSlideIndex = 0;
  const videoBlobUrls = new Map();

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
    if (themeToggle) themeToggle.setAttribute("aria-label", `Switch to ${nextTheme === "dark" ? "light" : "dark"} mode`);
    if (persist) window.localStorage.setItem(themeStorageKey, nextTheme);
  }

  function parseJson(text) {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  function formatDuration(ms) {
    const seconds = Math.round((Number(ms) || 0) / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    if (minutes === 0) return `${remainder}s`;
    return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
  }

  function isExpired(expiresOn) {
    if (!expiresOn) return false;
    const expiresAt = new Date(`${expiresOn}T23:59:59`);
    return Number.isFinite(expiresAt.getTime()) && Date.now() > expiresAt.getTime();
  }

  function hasStarted(startsOn) {
    if (!startsOn) return true;
    const startsAt = new Date(`${startsOn}T00:00:00`);
    return !Number.isFinite(startsAt.getTime()) || Date.now() >= startsAt.getTime();
  }

  function scheduleLabels(slide) {
    const labels = [];
    if (slide.startsOn) labels.push(`${hasStarted(slide.startsOn) ? "started" : "starts"} ${slide.startsOn}`);
    if (slide.expiresOn) labels.push(`${isExpired(slide.expiresOn) ? "expired" : "expires"} ${slide.expiresOn}`);
    return labels;
  }

  function getLocation(name = selectedLocation) {
    return data.locations.find((location) => location.name === name) || data.locations[0] || null;
  }

  function setAuditStatus(message) {
    auditStatus.textContent = message;
  }

  function renderLocations() {
    locationList.replaceChildren();
    data.locations.forEach((location) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "location-button btn";
      button.dataset.location = location.name;
      button.classList.toggle("is-active", location.name === selectedLocation);

      const name = document.createElement("span");
      name.textContent = location.name;
      const count = document.createElement("span");
      count.textContent = String(location.slides.length);
      button.append(name, count);

      button.addEventListener("click", () => selectLocation(location.name));
      locationList.append(button);
    });
  }

  function renderSummary(location) {
    const slides = location?.slides || [];
    const totalMs = slides.reduce((sum, slide) => sum + (Number(slide.durationMs) || 0), 0);
    const videos = slides.filter((slide) => slide.type === "video").length;
    const images = slides.filter((slide) => slide.type === "image").length;
    const scheduled = slides.filter((slide) => !hasStarted(slide.startsOn)).length;
    const expired = slides.filter((slide) => isExpired(slide.expiresOn)).length;

    summary.replaceChildren(
      summaryItem("Slides", slides.length),
      summaryItem("Images", images),
      summaryItem("Videos", videos),
      summaryItem("Scheduled", scheduled),
      summaryItem("Expired", expired),
      summaryItem("Runtime", formatDuration(totalMs)),
    );
  }

  function summaryItem(label, value) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = String(value);
    wrapper.append(term, detail);
    return wrapper;
  }

  function mediaForSlide(slide, previewMode = false) {
    const media = document.createElement(slide.type === "video" ? "video" : "img");

    if (slide.type === "video") {
      media.muted = true;
      media.defaultMuted = true;
      media.volume = 0;
      media.playsInline = true;
      media.controls = previewMode;
      media.loop = previewMode;
      media.preload = previewMode ? "auto" : "metadata";
      media.setAttribute("muted", "");
      media.setAttribute("playsinline", "");
      if (previewMode) {
        media.autoplay = true;
        media.setAttribute("autoplay", "");
      }
      attachVideoSource(media, slide, previewMode);
    } else {
      media.src = slide.src;
      media.alt = slide.name;
      media.decoding = "async";
      media.loading = previewMode ? "eager" : "lazy";
    }

    return media;
  }

  async function attachVideoSource(video, slide, shouldPlay) {
    try {
      const src = await videoBlobUrl(slide);
      if (!video.isConnected) return;
      video.src = src;
      video.load();
      if (shouldPlay) {
        video.play().catch(() => {});
      }
    } catch {
      if (!video.isConnected) return;
      video.src = slide.src;
      video.load();
      if (shouldPlay) {
        video.play().catch(() => {});
      }
    }
  }

  async function videoBlobUrl(slide) {
    if (videoBlobUrls.has(slide.src)) {
      return videoBlobUrls.get(slide.src);
    }

    let response = await fetch(slide.src, { cache: "reload" });
    if (response.status === 304) {
      response = await fetch(`${slide.src}?video-cache-bust=${Date.now()}`, { cache: "no-store" });
    }

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    videoBlobUrls.set(slide.src, blobUrl);
    return blobUrl;
  }

  function renderPreview(location) {
    const slide = location?.slides[selectedSlideIndex];
    preview.replaceChildren();

    if (!slide) {
      previewTitle.textContent = "No slide selected";
      return;
    }

    previewTitle.textContent = `${selectedSlideIndex + 1}. ${slide.name}`;
    const media = mediaForSlide(slide, true);
    preview.append(media);
  }

  function renderSlides(location) {
    slideGrid.replaceChildren();
    if (!location || location.slides.length === 0) {
      setAuditStatus("No slides in this location");
      return;
    }

    location.slides.forEach((slide, index) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "slide-card";
      card.classList.toggle("is-selected", index === selectedSlideIndex);
      card.addEventListener("click", () => selectSlide(index));

      const thumb = document.createElement("div");
      thumb.className = "thumb";
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = slide.type;
      const media = mediaForSlide(slide);
      thumb.append(media, badge);

      const info = document.createElement("div");
      info.className = "slide-info";
      const name = document.createElement("div");
      name.className = "slide-name";
      name.title = slide.name;
      name.textContent = `${index + 1}. ${slide.name}`;
      const detail = document.createElement("div");
      detail.className = "slide-detail";
      const duration = document.createElement("span");
      duration.textContent = slide.type === "video" && !slide.maxDurationMs ? "auto" : formatDuration(slide.type === "video" ? slide.maxDurationMs : slide.durationMs);
      const state = document.createElement("span");
      state.className = "slide-status";
      state.textContent = "checking";
      detail.append(duration, state);
      info.append(name, detail);
      const schedule = scheduleLabels(slide);
      if (schedule.length > 0) {
        const scheduleNote = document.createElement("div");
        scheduleNote.className = "slide-schedule-note";
        scheduleNote.classList.toggle("is-inactive", !hasStarted(slide.startsOn) || isExpired(slide.expiresOn));
        scheduleNote.textContent = schedule.join(" / ");
        info.append(scheduleNote);
      }
      card.append(thumb, info);

      const markOk = (label = "file ok") => {
        state.textContent = label;
        state.classList.add("is-ok");
      };
      const markError = () => {
        state.textContent = "missing";
        state.classList.add("is-error");
        card.classList.add("has-error");
      };

      checkFile(slide.src).then((exists) => {
        if (exists) markOk();
        else markError();
      });

      slideGrid.append(card);
    });

    setAuditStatus(`${location.slides.length} slides queued for audit`);
  }

  function render() {
    const location = getLocation();
    if (!location) {
      locationTitle.textContent = "No locations";
      summary.replaceChildren();
      preview.replaceChildren();
      slideGrid.replaceChildren();
      setAuditStatus("No deck data found");
      return;
    }

    selectedLocation = location.name;
    selectedSlideIndex = Math.min(selectedSlideIndex, Math.max(location.slides.length - 1, 0));
    locationTitle.textContent = location.name;
    renderLocations();
    renderSummary(location);
    renderPreview(location);
    renderSlides(location);
  }

  function selectLocation(name) {
    selectedLocation = name;
    selectedSlideIndex = 0;
    window.location.hash = encodeURIComponent(name);
    render();
  }

  function selectSlide(index) {
    selectedSlideIndex = index;
    render();
  }

  function moveSlide(direction) {
    const location = getLocation();
    if (!location || location.slides.length === 0) return;
    selectedSlideIndex = (selectedSlideIndex + direction + location.slides.length) % location.slides.length;
    render();
  }

  function loadData(nextData) {
    if (!Array.isArray(nextData?.locations)) return;
    data = nextData;
    const hashLocation = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    selectedLocation = hashLocation || selectedLocation || data.activeLocation || data.locations[0]?.name || "";
    if (!getLocation(selectedLocation)) selectedLocation = data.locations[0]?.name || "";
    render();
  }

  async function checkFile(src) {
    try {
      const response = await fetch(src, { method: "HEAD", cache: "no-store" });
      return response.ok;
    } catch {
      try {
        const response = await fetch(src, { method: "GET", cache: "no-store" });
        return response.ok;
      } catch {
        return false;
      }
    }
  }

  document.body.addEventListener("htmx:afterRequest", (event) => {
    if (event.target?.id !== "inspector-data") return;
    const payload = parseJson(event.detail.xhr.responseText);
    if (payload) loadData(payload);
  });

  async function loadRemoteDecks() {
    setAuditStatus("Loading repo data");
    try {
      const response = await fetch(`/api/clients/${encodeURIComponent(controlClient)}/decks`, { cache: "no-store" });
      if (!response.ok) {
        setAuditStatus(response.status === 409 ? "Repo not synced" : `Load failed (${response.status})`);
        return;
      }
      loadData(await response.json());
    } catch {
      setAuditStatus("Load failed");
    }
  }

  themeToggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    setTheme(currentTheme === "dark" ? "light" : "dark");
  });

  prevSlide.addEventListener("click", () => moveSlide(-1));
  nextSlide.addEventListener("click", () => moveSlide(1));
  window.addEventListener("hashchange", () => {
    const hashLocation = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (hashLocation && hashLocation !== selectedLocation) selectLocation(hashLocation);
  });

  setTheme(preferredTheme(), false);
  loadData(parseJson(initialData?.textContent || "{}") || {});
  loadRemoteDecks();
})();
