/**
 * app.js — Frontend Controller for Stoic Shorts AI Deployment Studio
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const statusPill = document.getElementById("statusPill");
  const statusText = document.getElementById("statusText");
  const launchBtn = document.getElementById("launchBtn");
  const quickRunBtn = document.getElementById("quickRunBtn");
  const themeSelect = document.getElementById("themeSelect");
  const noDownloadToggle = document.getElementById("noDownloadToggle");
  const noCaptionsToggle = document.getElementById("noCaptionsToggle");
  const consoleOutput = document.getElementById("consoleOutput");
  const clearConsoleBtn = document.getElementById("clearConsoleBtn");
  const currentStepTag = document.getElementById("currentStepTag");
  
  // Telemetry Elements
  const tokensValue = document.getElementById("tokensValue");
  const downloadValue = document.getElementById("downloadValue");
  const apiCallsValue = document.getElementById("apiCallsValue");
  const runtimeValue = document.getElementById("runtimeValue");

  // Video Elements
  const videoGalleryGrid = document.getElementById("videoGalleryGrid");
  const emptyVideoState = document.getElementById("emptyVideoState");
  const featuredPlayerWrapper = document.getElementById("featuredPlayerWrapper");
  const mainVideoPlayer = document.getElementById("mainVideoPlayer");
  const featuredVideoTitle = document.getElementById("featuredVideoTitle");
  const downloadVideoBtn = document.getElementById("downloadVideoBtn");
  const refreshVideosBtn = document.getElementById("refreshVideosBtn");

  // Quote Elements
  const quoteCountBadge = document.getElementById("quoteCountBadge");
  const themePills = document.getElementById("themePills");
  const quotesList = document.getElementById("quotesList");

  let pollInterval = null;
  let lastLoggedCount = 0;
  let allQuotesData = [];
  let currentThemeFilter = "all";

  // Step definitions order
  const stepOrder = [
    "quote_picker",
    "script_generator",
    "tts_generator",
    "caption_generator",
    "broll_matcher",
    "video_renderer"
  ];

  // Initialize Data
  fetchStatus();
  fetchTelemetry();
  fetchQuotes();
  fetchVideos();

  // Event Listeners
  launchBtn.addEventListener("click", triggerPipelineRun);
  quickRunBtn.addEventListener("click", triggerPipelineRun);
  clearConsoleBtn.addEventListener("click", () => {
    consoleOutput.innerHTML = '<div class="log-line info">[System] Console cleared.</div>';
    lastLoggedCount = 0;
  });
  refreshVideosBtn.addEventListener("click", fetchVideos);

  // API Call: Trigger Run
  async function triggerPipelineRun() {
    const payload = {
      theme: themeSelect.value || null,
      no_download: noDownloadToggle.checked,
      no_captions: noCaptionsToggle.checked
    };

    try {
      launchBtn.disabled = true;
      quickRunBtn.disabled = true;
      appendConsoleLine("[Client] Sending pipeline execution request...", "info");

      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to trigger run");
      }

      appendConsoleLine(`[Client] ${data.message}`, "success");
      startPolling();

    } catch (err) {
      appendConsoleLine(`[Error] ${err.message}`, "error");
      launchBtn.disabled = false;
      quickRunBtn.disabled = false;
    }
  }

  // Polling Pipeline Status
  function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    lastLoggedCount = 0;
    pollInterval = setInterval(fetchStatus, 1000);
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    launchBtn.disabled = false;
    quickRunBtn.disabled = false;
  }

  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();

      updateStatusUI(data);

      if (data.status === "running") {
        if (!pollInterval) startPolling();
      } else {
        if (pollInterval && (data.status === "completed" || data.status === "failed")) {
          stopPolling();
          fetchTelemetry();
          fetchVideos();
          fetchQuotes();
        }
      }
    } catch (err) {
      console.error("Status fetch error:", err);
    }
  }

  function updateStatusUI(data) {
    const status = data.status || "idle";

    // Update Status Pill
    statusPill.className = `status-indicator ${status}`;
    statusText.textContent = `MODEL ${status.toUpperCase()}`;

    // Update Active Step Tag
    if (status === "running") {
      currentStepTag.textContent = `Active: ${data.current_step || "Initializing"}`;
      currentStepTag.className = "step-active-tag active";
    } else if (status === "completed") {
      currentStepTag.textContent = "Completed 🎉";
      currentStepTag.className = "step-active-tag completed";
    } else if (status === "failed") {
      currentStepTag.textContent = "Failed ❌";
      currentStepTag.className = "step-active-tag failed";
    } else {
      currentStepTag.textContent = "Ready";
      currentStepTag.className = "step-active-tag";
    }

    // Update Stepper Cards
    const currentStepIndex = stepOrder.indexOf(data.current_step);

    document.querySelectorAll(".step-card").forEach((card) => {
      const stepName = card.getAttribute("data-step");
      const stepIdx = stepOrder.indexOf(stepName);
      const badge = card.querySelector(".step-badge");

      if (status === "running") {
        if (stepName === data.current_step) {
          card.className = "step-card active";
          badge.textContent = "Running...";
        } else if (stepIdx < currentStepIndex && currentStepIndex !== -1) {
          card.className = "step-card completed";
          badge.textContent = "Done";
        } else {
          card.className = "step-card";
          badge.textContent = "Pending";
        }
      } else if (status === "completed") {
        card.className = "step-card completed";
        badge.textContent = "Done";
      } else if (status === "failed") {
        if (stepName === data.current_step) {
          card.className = "step-card failed";
          badge.textContent = "Failed";
        }
      } else {
        card.className = "step-card";
        badge.textContent = "Pending";
      }
    });

    // Update Logs Terminal
    if (data.logs && data.logs.length > lastLoggedCount) {
      const newLogs = data.logs.slice(lastLoggedCount);
      newLogs.forEach(line => {
        let type = "info";
        if (line.includes("ERROR") || line.includes("FAILED") || line.includes("Exception")) type = "error";
        else if (line.includes("WARN")) type = "warn";
        else if (line.includes("COMPLETE") || line.includes("written") || line.includes("successfully")) type = "success";

        appendConsoleLine(line, type);
      });
      lastLoggedCount = data.logs.length;
    }

    // Calculate Runtime
    if (data.start_time) {
      const end = data.end_time || (Date.now() / 1000);
      const elapsed = Math.round(end - data.start_time);
      runtimeValue.textContent = `${elapsed}s`;
    }
  }

  function appendConsoleLine(text, type = "info") {
    const line = document.createElement("div");
    line.className = `log-line ${type}`;
    line.textContent = text;
    consoleOutput.appendChild(line);
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
  }

  // Telemetry Data Fetch
  async function fetchTelemetry() {
    try {
      const res = await fetch("/api/telemetry");
      if (!res.ok) return;
      const data = await res.json();

      tokensValue.textContent = (data.total_tokens || 0).toLocaleString();
      downloadValue.textContent = `${data.total_download_mb || 0} MB`;
      apiCallsValue.textContent = data.api_calls_count || 0;
    } catch (err) {
      console.error("Telemetry fetch error:", err);
    }
  }

  // Video Showcase Fetch
  async function fetchVideos() {
    try {
      const res = await fetch("/api/videos");
      if (!res.ok) return;
      const videos = await res.json();

      videoGalleryGrid.innerHTML = "";

      if (!videos || videos.length === 0) {
        emptyVideoState.classList.remove("hidden");
        featuredPlayerWrapper.classList.add("hidden");
        return;
      }

      emptyVideoState.classList.add("hidden");
      featuredPlayerWrapper.classList.remove("hidden");

      // Auto-load latest video into featured player
      setMainVideo(videos[0]);

      // Populate Gallery
      videos.forEach(v => {
        const thumbCard = document.createElement("div");
        thumbCard.className = "video-thumb-card";
        thumbCard.innerHTML = `
          <div class="video-thumb-name">🎬 ${v.filename}</div>
          <div class="video-thumb-size">${v.size_mb} MB • ${v.created_at.split(" ")[1]}</div>
        `;
        thumbCard.addEventListener("click", () => setMainVideo(v));
        videoGalleryGrid.appendChild(thumbCard);
      });
    } catch (err) {
      console.error("Videos fetch error:", err);
    }
  }

  function setMainVideo(video) {
    mainVideoPlayer.src = video.url;
    featuredVideoTitle.textContent = video.filename;
    downloadVideoBtn.href = video.url;
  }

  // Quotes Database Fetch
  async function fetchQuotes() {
    try {
      const res = await fetch("/api/quotes");
      if (!res.ok) return;
      const data = await res.json();

      allQuotesData = data.quotes || [];
      quoteCountBadge.textContent = `${allQuotesData.length} Quotes`;

      renderThemePills(data.themes || []);
      renderQuotesList(allQuotesData);
    } catch (err) {
      console.error("Quotes fetch error:", err);
    }
  }

  function renderThemePills(themes) {
    themePills.innerHTML = "";
    
    const allPill = document.createElement("div");
    allPill.className = `pill ${currentThemeFilter === "all" ? "active" : ""}`;
    allPill.textContent = "All Themes";
    allPill.addEventListener("click", () => filterQuotes("all"));
    themePills.appendChild(allPill);

    themes.forEach(t => {
      const pill = document.createElement("div");
      pill.className = `pill ${currentThemeFilter === t ? "active" : ""}`;
      pill.textContent = t.charAt(0).toUpperCase() + t.slice(1);
      pill.addEventListener("click", () => filterQuotes(t));
      themePills.appendChild(pill);
    });
  }

  function filterQuotes(theme) {
    currentThemeFilter = theme;
    document.querySelectorAll(".pill").forEach(p => {
      p.classList.toggle("active", p.textContent.toLowerCase() === theme || (theme === "all" && p.textContent === "All Themes"));
    });

    const filtered = theme === "all" ? allQuotesData : allQuotesData.filter(q => q.theme === theme);
    renderQuotesList(filtered);
  }

  function renderQuotesList(quotes) {
    quotesList.innerHTML = "";
    if (quotes.length === 0) {
      quotesList.innerHTML = '<div class="quote-item-card">No quotes found for this theme.</div>';
      return;
    }

    quotes.slice(0, 15).forEach(q => {
      const card = document.createElement("div");
      card.className = "quote-item-card";
      card.innerHTML = `
        <div class="quote-text">"${q.quote}"</div>
        <div class="quote-author-source">
          <span>— ${q.author} (${q.source})</span>
          <span class="badge">${q.theme}</span>
        </div>
      `;
      quotesList.appendChild(card);
    });
  }
});
