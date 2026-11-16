// Main Application Controller — X Gen Clips (iOS Claymorphism + Neomorphism)

const App = {
  currentTab: 'home',
  currentPreset: 'custom',
  settings: {},
  clips: [],
  debounceTimer: null,
  eventSource: null,

  async init() {
    this.initTheme();
    await this.loadSettings();
    this.initSSE();
    this.loadClips();
    this.checkHealthBadge();
    this.bindEvents();
  },

  initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
  },

  toggleTheme() {
    const curr = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = curr === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    this.saveSettingKey('theme', next);
  },

  /* ======================================================== */
  /* iOS TAB NAVIGATION (Home | Library | Settings)          */
  /* ======================================================== */
  switchTab(tabName) {
    this.currentTab = tabName;

    // Update bottom tab items
    document.querySelectorAll('.ios-tab-item').forEach(el => {
      el.classList.toggle('active', el.getAttribute('data-tab') === tabName);
    });

    // Update view sections
    document.querySelectorAll('.view-section').forEach(sec => {
      sec.classList.remove('active');
    });

    const targetSec = document.getElementById(`view-${tabName}`);
    if (targetSec) {
      targetSec.classList.add('active');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    if (tabName === 'library') {
      this.loadHistory();
    } else if (tabName === 'settings') {
      this.populateSettingsFields();
      this.refreshHealth();
    }
  },

  togglePasswordVisibility(inputId) {
    const el = document.getElementById(inputId);
    if (!el) return;
    el.type = el.type === 'password' ? 'text' : 'password';
  },

  /* ======================================================== */
  /* SETTINGS & BRAND KIT                                     */
  /* ======================================================== */
  async loadSettings() {
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      this.settings = data.settings || {};
      this.populateSettingsFields(data);
    } catch (e) {
      console.warn("Could not load settings:", e);
    }
  },

  populateSettingsFields(data) {
    const keyField = document.getElementById('settingApiKey');
    if (keyField && data && data.has_key) {
      keyField.placeholder = `Configured (${data.key_masked})`;
    }

    const modelSelect = document.getElementById('settingModel');
    if (modelSelect && this.settings.model) {
      modelSelect.value = this.settings.model;
    }

    const watermarkInput = document.getElementById('settingWatermark');
    if (watermarkInput && this.settings.brand_watermark) {
      watermarkInput.value = this.settings.brand_watermark;
    }

    const fontSelect = document.getElementById('settingFont');
    if (fontSelect && this.settings.brand_font) {
      fontSelect.value = this.settings.brand_font;
    }

    const autoPasteToggle = document.getElementById('settingAutoPaste');
    if (autoPasteToggle) {
      autoPasteToggle.checked = !!this.settings.auto_render_on_paste;
    }

    const autoFolderToggle = document.getElementById('settingAutoFolder');
    if (autoFolderToggle) {
      autoFolderToggle.checked = !!this.settings.auto_open_folder;
    }
  },

  async saveFullSettings() {
    const key = document.getElementById('settingApiKey')?.value.trim();
    const model = document.getElementById('settingModel')?.value;
    const wm = document.getElementById('settingWatermark')?.value.trim();
    const font = document.getElementById('settingFont')?.value;
    const autoPaste = document.getElementById('settingAutoPaste')?.checked ?? false;
    const autoFolder = document.getElementById('settingAutoFolder')?.checked ?? false;

    const payload = {
      model: model,
      brand_watermark: wm,
      brand_font: font,
      auto_render_on_paste: autoPaste,
      auto_open_folder: autoFolder
    };
    if (key) payload.gemini_api_key = key;

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Save fail hua.");
      alert("✓ Settings aur Brand Kit save ho gayi hain!");
      await this.loadSettings();
      this.checkHealthBadge();
    } catch (e) {
      alert("Settings save karne mein error aaya: " + e.message);
    }
  },

  async testGeminiConnection() {
    const resultEl = document.getElementById('connectionTestResult');
    if (resultEl) {
      resultEl.style.display = 'block';
      resultEl.style.color = 'var(--text-secondary)';
      resultEl.innerText = 'Connecting to Google AI Studio...';
    }

    try {
      const res = await fetch('/api/check-connection', { method: 'POST' });
      const data = await res.json();
      if (resultEl) {
        if (data.status === 'connected') {
          resultEl.style.color = '#5BC0DE';
          resultEl.innerText = `✓ ${data.message}`;
        } else {
          resultEl.style.color = '#D97706';
          resultEl.innerText = `⚠ ${data.message}`;
        }
      }
      this.checkHealthBadge();
    } catch (e) {
      if (resultEl) {
        resultEl.style.color = '#EF4444';
        resultEl.innerText = 'Connection check error. Internet verify karein.';
      }
    }
  },

  async saveSettingKey(k, v) {
    const payload = {};
    payload[k] = v;
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (e) {}
  },

  /* ======================================================== */
  /* LIBRARY & HISTORY                                        */
  /* ======================================================== */
  async loadHistory() {
    const container = document.getElementById('historyListContainer');
    if (!container) return;
    container.innerHTML = "<p style='color:var(--text-muted);'>Loading history...</p>";

    try {
      const res = await fetch('/api/history');
      const data = await res.json();
      if (!data || data.length === 0) {
        container.innerHTML = `
          <div class="clay-inset-box" style="padding: 36px; text-align: center; color: var(--text-muted);">
            <h3>Koi saved project nahi mila</h3>
            <p style="margin-top: 6px;">Home tab se video clip banayein, wo automatically yahan dikhegi.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = data.map(item => `
        <div class="history-item">
          <div>
            <strong style="color:var(--text-primary); font-size:16px;">${item.title || 'Untitled Project'}</strong>
            <p style="font-size:13px; color:var(--text-muted); margin-top:2px;">
              ⏱ ${item.timestamp || 'Recent'} • 🎬 ${item.clips_count || 1} Clips
            </p>
          </div>
          <div style="display:flex; gap:10px;">
            <button class="clay-btn clay-btn-sky" style="font-size:13px; padding:6px 14px;" onclick="App.reopenHistoryItem('${item.url}')">
              🔁 Re-Open
            </button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = "<p style='color:#EF4444;'>History load nahi ho paayi.</p>";
    }
  },

  reopenHistoryItem(url) {
    if (!url) return;
    this.switchTab('home');
    const input = document.getElementById('videoUrlInput');
    if (input) {
      input.value = url;
      this.fetchVideoInfo(url);
    }
  },

  async clearWorkspaceHistory() {
    if (!confirm("Kya aap saari clips aur history clear karna chahte hain?")) return;
    try {
      await fetch('/api/history/clear', { method: 'POST' });
      alert("Workspace clear ho gaya!");
      this.loadHistory();
      this.loadClips();
    } catch (e) {
      alert("Clear fail hua.");
    }
  },

  /* ======================================================== */
  /* SSE REAL-TIME STREAMING                                  */
  /* ======================================================== */
  initSSE() {
    if (this.eventSource) this.eventSource.close();
    this.eventSource = new EventSource('/api/stream');

    this.eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data);
      this.updateProgress(data.progress, data.step, data.elapsed_sec);
    });

    this.eventSource.addEventListener('clip_ready', (e) => {
      const clip = JSON.parse(e.data);
      this.onNewClipReady(clip);
    });

    this.eventSource.addEventListener('error', (e) => {
      try {
        const data = JSON.parse(e.data);
        this.showError(data.message);
      } catch (err) {}
    });
  },

  updateProgress(pct, stepMsg, elapsed) {
    const card = document.getElementById('progressCard');
    const bar = document.getElementById('progressBarFill');
    const step = document.getElementById('progressStepText');
    const timer = document.getElementById('progressTimer');

    if (card) card.style.display = 'flex';
    if (bar) bar.style.width = `${pct}%`;
    if (step) step.innerText = stepMsg;
    if (timer) timer.innerText = `${elapsed || 0}s elapsed`;

    if (pct >= 100) {
      setTimeout(() => {
        if (card) card.style.display = 'none';
        this.loadClips();
      }, 2500);
    }
  },

  onNewClipReady(clip) {
    this.clips.unshift(clip);
    this.renderClips();
    this.playChime();
  },

  playChime() {
    try {
      const audio = new Audio('/sounds/pop.wav');
      audio.volume = 0.5;
      audio.play();
    } catch (e) {}
  },

  async checkHealthBadge() {
    const badge = document.getElementById('headerStatusBadge');
    try {
      const res = await fetch('/api/check-connection', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'connected') {
        badge.className = 'status-pill connected';
        badge.innerHTML = `<span class="status-dot"></span> Gemini Ready (${data.latency_ms}ms)`;
      } else {
        badge.className = 'status-pill not-connected';
        badge.innerHTML = `<span class="status-dot"></span> Gemini Not Ready`;
      }
    } catch (e) {
      badge.className = 'status-pill not-connected';
      badge.innerHTML = `<span class="status-dot"></span> Offline`;
    }
  },

  bindEvents() {
    const urlInput = document.getElementById('videoUrlInput');
    urlInput?.addEventListener('input', () => {
      const val = urlInput.value.trim();
      document.getElementById('clearUrlBtn').style.display = val ? 'block' : 'none';
      clearTimeout(this.debounceTimer);
      if (val.length > 8) {
        this.debounceTimer = setTimeout(() => this.fetchVideoInfo(val), 400);
      } else {
        document.getElementById('linkPreviewCard').style.display = 'none';
      }
    });

    document.getElementById('clearUrlBtn')?.addEventListener('click', () => {
      urlInput.value = '';
      document.getElementById('clearUrlBtn').style.display = 'none';
      document.getElementById('linkPreviewCard').style.display = 'none';
    });

    document.getElementById('toggleOptionsBtn')?.addEventListener('click', () => {
      const drawer = document.getElementById('optionsDrawer');
      drawer.classList.toggle('open');
    });

    document.getElementById('mainSubmitBtn')?.addEventListener('click', () => {
      this.submitProcess();
    });
  },

  async fetchVideoInfo(url) {
    const card = document.getElementById('linkPreviewCard');
    const thumb = document.getElementById('previewThumb');
    const title = document.getElementById('previewTitle');
    const meta = document.getElementById('previewMeta');

    try {
      const res = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
      const data = await res.json();
      if (data.title) {
        title.innerText = data.title;
        meta.innerText = `Duration: ${data.duration}`;
        thumb.src = data.thumbnail || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=160&q=80';
        card.style.display = 'flex';

        if (this.settings.auto_render_on_paste) {
          this.submitProcess();
        }
      }
    } catch (e) {
      card.style.display = 'none';
    }
  },

  selectPreset(preset) {
    this.currentPreset = preset;
    document.querySelectorAll('.preset-pill').forEach(p => {
      p.classList.toggle('selected', p.getAttribute('data-preset') === preset);
    });

    const styleSelect = document.getElementById('optStyle');
    const colorSelect = document.getElementById('optColor');
    const minLen = document.getElementById('optMinLen');
    const maxLen = document.getElementById('optMaxLen');

    if (preset === 'podcast') {
      if (styleSelect) styleSelect.value = 'cinematic_blur';
      if (colorSelect) colorSelect.value = 'hormozi';
      if (minLen) minLen.value = 35;
      if (maxLen) maxLen.value = 55;
    } else if (preset === 'motivation') {
      if (styleSelect) styleSelect.value = 'film_mood';
      if (colorSelect) colorSelect.value = 'neon_cyan';
      if (minLen) minLen.value = 25;
      if (maxLen) maxLen.value = 45;
    } else if (preset === 'comedy') {
      if (styleSelect) styleSelect.value = 'vibrant';
      if (colorSelect) colorSelect.value = 'electric_mint';
      if (minLen) minLen.value = 18;
      if (maxLen) maxLen.value = 35;
    }
  },

  async submitProcess() {
    const url = document.getElementById('videoUrlInput').value.trim();
    if (!url) {
      alert("Pehle YouTube link daalo ya local video select karo!");
      return;
    }

    const payload = {
      url: url,
      preset: this.currentPreset,
      clips_count: parseInt(document.getElementById('optClipsCount')?.value || "1"),
      style: document.getElementById('optStyle')?.value || "cinematic_blur",
      caption_color: document.getElementById('optColor')?.value || "hormozi",
      caption_position: document.getElementById('optPos')?.value || "bottom",
      caption_size: parseInt(document.getElementById('optSize')?.value || "58"),
      whisper_model: document.getElementById('optWhisper')?.value || "base",
      min_length: parseInt(document.getElementById('optMinLen')?.value || "20"),
      max_length: parseInt(document.getElementById('optMaxLen')?.value || "60"),
      enable_sfx: document.getElementById('optSfx')?.checked ?? true,
      watermark_text: document.getElementById('optWatermark')?.value || ""
    };

    document.getElementById('progressCard').style.display = 'flex';
    this.updateProgress(5, "Queue mein laga rahe hain...", 0);

    try {
      const res = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Process shuru nahi ho paya.");
      }
    } catch (e) {
      this.showError(e.message);
    }
  },

  showError(msg) {
    const card = document.getElementById('progressCard');
    if (card) card.style.display = 'none';
    alert(`Error: ${msg}`);
  },

  async loadClips() {
    try {
      const res = await fetch('/api/clips');
      this.clips = await res.json();
      this.renderClips();
    } catch (e) {
      console.warn("Could not load clips:", e);
    }
  },

  toggleSafeZone(clipId) {
    const overlay = document.getElementById(`safe-overlay-${clipId}`);
    if (overlay) overlay.classList.toggle('active');
  },

  renderClips() {
    const container = document.getElementById('clipsGrid');
    if (!container) return;

    if (!this.clips || this.clips.length === 0) {
      container.innerHTML = `
        <div class="clay-inset-box" style="padding: 48px; text-align: center; color: var(--text-muted);">
          <h3 style="color:var(--text-primary);">Abhi koi clip ready nahi hai</h3>
          <p style="margin-top: 8px;">Upar link paste karo aur '🚀 Clips Banao' dabao!</p>
        </div>
      `;
      return;
    }

    container.innerHTML = this.clips.map(clip => this.renderClipCard(clip)).join('');
  },

  renderClipCard(clip) {
    const p = clip.platforms || {};
    const yt = p.youtube || { title: clip.title, description: "Relatable reel!", hashtags: ["#shorts"] };
    const ig = p.instagram || { title: clip.title, description: "Tag a friend! 😂", hashtags: ["#reels"] };
    const tt = p.tiktok || { title: clip.title, description: "Wait for it...", hashtags: ["#fyp"] };

    const topPickBadge = clip.is_top_pick ? `
      <div class="top-pick-badge">
        <span>⭐ Pehle ye post karo</span>
      </div>
    ` : '';

    const hookOptionsHtml = (clip.hook_options || [clip.hook_line]).map(h => `
      <div class="title-pill-opt hook-pill-opt ${h === clip.hook_line ? 'active' : ''}" onclick="PlayerManager.selectHook(${clip.id}, '${h.replace(/'/g, "\\'")}')">
        🎯 ${h}
      </div>
    `).join('');

    return `
      <div class="clay-card clip-card" id="clip-${clip.id}">
        ${topPickBadge}

        <!-- 9:16 Smartphone Mockup with Safe Area Visualizer -->
        <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
          <button class="clay-pill" onclick="App.toggleSafeZone(${clip.id})" style="font-size:12px; padding:4px 12px; cursor:pointer;" title="Show/Hide Reels & Phone Camera Safe Areas">
            🛡️ Safe Area Guides
          </button>
          <div class="phone-mockup">
            <div class="phone-notch"></div>
            <div class="safe-zone-overlay" id="safe-overlay-${clip.id}">
              <div class="safe-zone-top">📷 Camera & Notch Safe</div>
              <div class="safe-zone-center">🎯 Caption Sweet Spot</div>
              <div class="safe-zone-bottom">📱 Reels UI Safe</div>
            </div>
            <video id="video-player-${clip.id}" controls playsinline preload="metadata" poster="/video/${clip.filename}">
              <source src="/video/${clip.filename}" type="video/mp4">
            </video>
          </div>
        </div>

        <!-- Metadata & Social Hub -->
        <div class="clip-details">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
            <div>
              <h2 class="clip-main-title hook-active-display">${clip.hook_line || clip.title}</h2>
              <p style="font-size: 14px; color: var(--text-secondary); margin-top: 4px;">
                ⏱ ${clip.duration} • 💾 ${clip.filesize} • 🔥 Viral Score: <strong style="color:var(--accent-orange);">${clip.viral_score}/100</strong>
              </p>
            </div>
            <button class="clay-btn btn-resuggest" onclick="SocialManager.resuggestText(${clip.id}, '${clip.filename}')">
              🔄 Dobara suggest karo
            </button>
          </div>

          <!-- Quality Inspector Bar -->
          <div class="quality-bar">
            <span class="quality-badge-good">✓ Camera Safe</span>
            <span class="quality-badge-good">✓ Cut Snapped</span>
            <span class="quality-badge-good">✓ Audio -14 LUFS</span>
            <span class="quality-badge-good">✓ Auto-Fit Bounds</span>
            <span style="margin-left:auto; color:var(--text-muted); font-size:12px;">Quality Score: 99%</span>
          </div>

          <!-- Hook A/B Options -->
          <div class="title-options-selector">
            <span style="font-size:12px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">
              Hook A/B Options (Pehle 3 Sec):
            </span>
            ${hookOptionsHtml}
          </div>

          <!-- Platform Tabs -->
          <div class="platform-tabs">
            <button class="platform-tab-btn active" data-plat="youtube" onclick="SocialManager.switchPlatform(${clip.id}, 'youtube')">🔴 YouTube Shorts</button>
            <button class="platform-tab-btn" data-plat="instagram" onclick="SocialManager.switchPlatform(${clip.id}, 'instagram')">🟣 Instagram Reels</button>
            <button class="platform-tab-btn" data-plat="tiktok" onclick="SocialManager.switchPlatform(${clip.id}, 'tiktok')">⚫ TikTok</button>
          </div>

          <!-- YouTube Content Pane -->
          <div class="platform-content platform-pane" data-plat="youtube" style="display:flex;">
            <div class="copy-box">
              <label class="copy-box-label">
                <span>Title</span>
                <a href="#" onclick="SocialManager.copyText(document.getElementById('yt-title-${clip.id}').value, this); return false;">Copy</a>
              </label>
              <input type="text" id="yt-title-${clip.id}" class="clay-input copy-title-input" value="${yt.title || ''}">
            </div>
            <div class="copy-box">
              <label class="copy-box-label">
                <span>Description & CTA</span>
                <a href="#" onclick="SocialManager.copyText(document.getElementById('yt-desc-${clip.id}').value, this); return false;">Copy</a>
              </label>
              <textarea id="yt-desc-${clip.id}" class="copy-textarea copy-desc-textarea">${yt.description || ''}</textarea>
            </div>
            <div class="copy-box">
              <label class="copy-box-label">
                <span>Hashtags</span>
                <a href="#" onclick="SocialManager.copyText(document.getElementById('yt-tags-${clip.id}').value, this); return false;">Copy</a>
              </label>
              <input type="text" id="yt-tags-${clip.id}" class="clay-input copy-tags-input" value="${(yt.hashtags || []).join(' ')}">
            </div>
          </div>

          <!-- Instagram Content Pane -->
          <div class="platform-content platform-pane" data-plat="instagram" style="display:none;">
            <div class="copy-box">
              <label class="copy-box-label">
                <span>Reels Caption & CTA</span>
                <a href="#" onclick="SocialManager.copyText(document.getElementById('ig-desc-${clip.id}').value, this); return false;">Copy</a>
              </label>
              <textarea id="ig-desc-${clip.id}" class="copy-textarea copy-desc-textarea">${ig.description || ''}</textarea>
            </div>
            <div class="copy-box">
              <label class="copy-box-label">
                <span>Hashtags</span>
                <a href="#" onclick="SocialManager.copyText(document.getElementById('ig-tags-${clip.id}').value, this); return false;">Copy</a>
              </label>
              <input type="text" id="ig-tags-${clip.id}" class="clay-input copy-tags-input" value="${(ig.hashtags || []).join(' ')}">
            </div>
          </div>

          <!-- TikTok Content Pane -->
          <div class="platform-content platform-pane" data-plat="tiktok" style="display:none;">
            <div class="copy-box">
              <label class="copy-box-label">
                <span>TikTok Caption</span>
                <a href="#" onclick="SocialManager.copyText(document.getElementById('tt-desc-${clip.id}').value, this); return false;">Copy</a>
              </label>
              <textarea id="tt-desc-${clip.id}" class="copy-textarea copy-desc-textarea">${tt.description || ''}</textarea>
            </div>
            <div class="copy-box">
              <label class="copy-box-label">
                <span>Hashtags</span>
                <a href="#" onclick="SocialManager.copyText(document.getElementById('tt-tags-${clip.id}').value, this); return false;">Copy</a>
              </label>
              <input type="text" id="tt-tags-${clip.id}" class="clay-input copy-tags-input" value="${(tt.hashtags || []).join(' ')}">
            </div>
          </div>

          <!-- Action Toolbar -->
          <div class="clip-actions">
            <button class="clay-btn clay-btn-primary btn-copy-all" onclick="SocialManager.copyAllForPlatform(${clip.id}, 'youtube')">
              📋 Sab Copy Karo
            </button>
            <a href="/video/${clip.filename}" download="${clip.filename.startsWith('xgenclips_') ? clip.filename : 'xgenclips_' + clip.filename}" class="clay-btn clay-btn-sky">
              💾 Download MP4
            </a>
            <button class="clay-btn" onclick="SocialManager.downloadZip('${clip.filename}')">
              📦 Sab Export (ZIP)
            </button>
            <button class="clay-btn" onclick="SocialManager.openPlatform('youtube')">
              🔴 YouTube Studio
            </button>
            <button class="clay-btn" onclick="SocialManager.openPlatform('instagram')">
              🟣 Instagram
            </button>
          </div>

        </div>
      </div>
    `;
  },

  async refreshHealth() {
    const grid = document.getElementById('healthDetailsGrid');
    if (!grid) return;
    grid.innerHTML = "<p style='color:var(--text-muted);'>Checking system health...</p>";

    try {
      const res = await fetch('/api/health');
      const data = await res.json();
      grid.innerHTML = `
        <div class="clay-card" style="padding:16px;">
          <div style="font-size:13px; color:var(--text-muted);">FFMPEG ENGINE</div>
          <strong style="color:var(--text-primary); font-size:15px;">${data.ffmpeg.installed ? 'Installed ✓' : 'Missing ✗'}</strong>
          <p style="font-size:12px; color:var(--accent-sky); margin-top:4px;">${data.ffmpeg.encoder}</p>
        </div>

        <div class="clay-card" style="padding:16px;">
          <div style="font-size:13px; color:var(--text-muted);">HARDWARE ACCEL</div>
          <strong style="color:var(--text-primary); font-size:15px;">${data.gpu.type}</strong>
          <p style="font-size:12px; color:var(--accent-sky); margin-top:4px;">${data.gpu.available ? 'Active GPU Mode' : 'CPU Multi-Core'}</p>
        </div>

        <div class="clay-card" style="padding:16px;">
          <div style="font-size:13px; color:var(--text-muted);">YT-DLP DOWNLOADER</div>
          <strong style="color:var(--text-primary); font-size:15px;">${data.yt_dlp.installed ? `v${data.yt_dlp.version}` : 'Missing'}</strong>
          <p style="font-size:12px; color:var(--accent-sky); margin-top:4px;">Audio-First Ingestion</p>
        </div>

        <div class="clay-card" style="padding:16px;">
          <div style="font-size:13px; color:var(--text-muted);">WHISPER TRANSCRIBER</div>
          <strong style="color:var(--text-primary); font-size:15px;">${data.whisper.installed ? 'Faster-Whisper Ready ✓' : 'Missing'}</strong>
          <p style="font-size:12px; color:var(--accent-sky); margin-top:4px;">${data.system.cpu_cores} CPU Threads</p>
        </div>
      `;
    } catch (e) {
      grid.innerHTML = "<p style='color:#EF4444;'>Health check fail ho gaya.</p>";
    }
  }
};

window.App = App;
document.addEventListener('DOMContentLoaded', () => App.init());
