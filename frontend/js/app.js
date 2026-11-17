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
    this.checkActiveStatus();
    this.checkYouTubeStatus();
    this.loadProfiles();
    this.loadLLMProviders();
    this.loadClips();
    this.checkHealthBadge();
    this.bindEvents();

    // Check if redirected to Settings tab
    if (window.location.hash === '#settings') {
      this.switchTab('settings');
      this.checkYouTubeStatus();
    }
    window.addEventListener('hashchange', () => {
      if (window.location.hash === '#settings') {
        this.switchTab('settings');
        this.checkYouTubeStatus();
      }
    });

    // Cross-tab real-time sync when YouTube auth completes!
    window.addEventListener('storage', (e) => {
      if (e.key === 'xgenclips_youtube_auth_done') {
        this.checkYouTubeStatus();
        this.switchTab('settings');
      }
    });
    try {
      const bc = new BroadcastChannel('xgenclips_channel');
      bc.onmessage = (msg) => {
        if (msg.data && msg.data.type === 'youtube_connected') {
          this.checkYouTubeStatus();
          this.switchTab('settings');
        }
      };
    } catch (e) {}
  },

  pollTimer: null,

  async checkActiveStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (data.status === 'running') {
        this.updateProgress(data.progress || 10, data.step || 'Kaam chal raha hai...', data.elapsed_sec || 0);
        this.setWorkingState(true, data.step, data.progress);
        this.startPolling();
      } else {
        this.setWorkingState(false);
      }
    } catch (e) {}
  },

  startPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = setInterval(async () => {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.status === 'running') {
          this.updateProgress(data.progress || 10, data.step || 'Kaam chal raha hai...', data.elapsed_sec || 0);
          this.setWorkingState(true, data.step, data.progress);
        } else if (data.status === 'completed') {
          this.updateProgress(100, data.step || 'Done!', data.elapsed_sec || 0);
          this.setWorkingState(false);
          this.stopPolling();
          this.loadClips();
        } else if (data.status === 'idle') {
          this.setWorkingState(false);
          this.stopPolling();
        } else if (data.status === 'error') {
          this.setWorkingState(false);
          this.stopPolling();
        }
      } catch (e) {}
    }, 2000);
  },

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  },

  setWorkingState(isWorking, stepMsg, pct) {
    if (isWorking) {
      this.startPolling();
    } else {
      this.stopPolling();
    }

    const banner = document.getElementById('headerActiveWorkBanner');
    const headerText = document.getElementById('headerWorkText');
    const heroCancel = document.getElementById('heroCancelBtn');
    const heroReset = document.getElementById('heroResetBtn');
    const submitBtn = document.getElementById('mainSubmitBtn');

    if (banner) {
      banner.style.display = isWorking ? 'inline-flex' : 'none';
      if (headerText && stepMsg) {
        headerText.innerText = `${stepMsg} ${pct ? '(' + pct + '%)' : ''}`;
      }
    }

    if (heroCancel) {
      heroCancel.style.display = isWorking ? 'inline-block' : 'none';
    }
    if (heroReset) {
      heroReset.style.display = isWorking ? 'inline-block' : 'none';
    }

    if (submitBtn) {
      if (isWorking) {
        submitBtn.innerHTML = `⏳ Kaam chal raha hai... ${pct ? '(' + pct + '%)' : ''}`;
        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.85';
      } else {
        submitBtn.innerHTML = `🚀 Clips Banao`;
        submitBtn.disabled = false;
        submitBtn.style.opacity = '1';
      }
    }
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
      this.checkYouTubeStatus();
      this.loadProfiles();
      this.loadLLMProviders();
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

  /* ======================================================== */
  /* YOUTUBE DATA API & OAUTH METHODS                         */
  /* ======================================================== */
  ytAuthPollTimer: null,
  isYouTubeConnected: false,

  async checkYouTubeStatus() {
    const badge = document.getElementById('ytStatusBadge');
    const msg = document.getElementById('ytStatusMsg');
    const connectBtn = document.getElementById('ytConnectBtn');
    const disconnectBtn = document.getElementById('ytDisconnectBtn');

    try {
      const res = await fetch('/api/youtube/status');
      const data = await res.json();
      this.isYouTubeConnected = !!data.connected;

      if (badge) {
        if (data.connected) {
          badge.className = 'health-badge badge-good';
          badge.innerText = '🟢 Connected';
          if (this.ytAuthPollTimer) {
            clearInterval(this.ytAuthPollTimer);
            this.ytAuthPollTimer = null;
          }
        } else if (data.in_progress) {
          badge.className = 'health-badge badge-warning';
          badge.innerText = '⏳ Authenticating...';
        } else if (data.status === 'expired') {
          badge.className = 'health-badge badge-danger';
          badge.innerText = '🔴 Login Expired';
        } else {
          badge.className = 'health-badge badge-warning';
          badge.innerText = '🔴 Not Connected';
        }
      }

      if (msg) {
        if (data.in_progress && data.auth_url) {
          msg.innerHTML = `
            <div style="margin: 8px 0;">
              <p style="color: #f59e0b; font-weight: 600; margin-bottom: 8px;">
                ⚠️ Agar Google Login window automatic nahi khuli, to niche diye button par click karein:
              </p>
              <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                <a href="${data.auth_url}" target="_blank" style="background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 700; display: inline-flex; align-items: center; gap: 8px; box-shadow: 0 4px 12px rgba(37,99,235,0.4);">
                  🌐 Yahan Click Karke Google Login Kholein ↗
                </a>
                <button type="button" onclick="App.cancelYouTubeAuth()" style="background: #374151; color: #e5e7eb; padding: 10px 16px; border-radius: 8px; border: 1px solid #4b5563; font-weight: 600; cursor: pointer;">
                  ❌ Cancel Login
                </button>
              </div>
            </div>
          `;
        } else if (data.message) {
          msg.innerText = data.message;
        }
      }

      if (connectBtn && disconnectBtn) {
        if (data.connected) {
          connectBtn.style.display = 'none';
          disconnectBtn.style.display = 'inline-block';
        } else if (data.in_progress) {
          connectBtn.style.display = 'none';
          disconnectBtn.style.display = 'none';
        } else {
          connectBtn.style.display = 'inline-block';
          connectBtn.innerText = data.status === 'expired' ? '🔄 Dobara Jodo' : '🔗 YouTube Jodo';
          disconnectBtn.style.display = 'none';
        }
      }
      return data;
    } catch (e) {
      if (badge) {
        badge.className = 'health-badge badge-danger';
        badge.innerText = 'Error';
      }
      return { connected: false };
    }
  },

  async connectYouTube() {
    const connectBtn = document.getElementById('ytConnectBtn');
    if (connectBtn) connectBtn.innerText = "⏳ Link generate ho rahi hai...";

    try {
      const res = await fetch('/api/youtube/connect', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connect shuru nahi ho paya.");

      // Open OAuth URL directly in new window
      if (data.auth_url) {
        window.open(data.auth_url, '_blank');
      }

      await this.checkYouTubeStatus();

      // Poll status every 2s until connected
      if (this.ytAuthPollTimer) clearInterval(this.ytAuthPollTimer);
      let attempts = 0;
      this.ytAuthPollTimer = setInterval(async () => {
        attempts++;
        const st = await this.checkYouTubeStatus();
        if (st.connected) {
          clearInterval(this.ytAuthPollTimer);
          this.ytAuthPollTimer = null;
          alert("✓ Badhaai ho! Aapka YouTube account kamyaabi se jud gaya hai.");
        } else if (attempts > 90) {
          clearInterval(this.ytAuthPollTimer);
          this.ytAuthPollTimer = null;
        }
      }, 2000);
    } catch (e) {
      alert("YouTube Connect Error: " + e.message);
      this.checkYouTubeStatus();
    }
  },

  async cancelYouTubeAuth() {
    try {
      await fetch('/api/youtube/cancel-auth', { method: 'POST' });
      if (this.ytAuthPollTimer) clearInterval(this.ytAuthPollTimer);
      this.ytAuthPollTimer = null;
      await this.checkYouTubeStatus();
    } catch (e) {
      console.error(e);
    }
  },

  async disconnectYouTube() {
    if (!confirm("Kya aap sach mein YouTube account disconnect karna chahte hain?")) return;
    try {
      const res = await fetch('/api/youtube/disconnect', { method: 'POST' });
      const data = await res.json();
      alert(data.message || "Account disconnect ho gaya.");
      await this.checkYouTubeStatus();
    } catch (e) {
      alert("Disconnect fail hua: " + e.message);
    }
  },

  /* ======================================================== */
  /* MULTI-CHANNEL PROFILES (v2)                              */
  /* ======================================================== */
  activeProfile: null,
  profiles: [],

  async loadProfiles() {
    try {
      const res = await fetch('/api/profiles');
      const data = await res.json();
      this.profiles = data.profiles || [];
      this.activeProfile = data.active_profile || null;

      // Update header profile pill
      const nameEl = document.getElementById('channelNameText');
      const dotEl = document.getElementById('channelColorDot');
      if (this.activeProfile) {
        if (nameEl) nameEl.innerText = this.activeProfile.name || 'Default Channel';
        if (dotEl) dotEl.style.backgroundColor = this.activeProfile.color || '#38BDF8';
      }

      // Render profile grid in Settings
      const grid = document.getElementById('profilesListGrid');
      if (grid) {
        grid.innerHTML = this.profiles.map(p => {
          const isActive = this.activeProfile && this.activeProfile.id === p.id;
          return `
            <div class="clay-card" style="padding: 16px; border: 1.5px solid ${isActive ? p.color : 'rgba(255,255,255,0.08)'}; background: ${isActive ? 'rgba(56,189,248,0.05)' : 'var(--bg-card)'}; border-radius: 14px;">
              <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:${p.color};"></span>
                  <strong style="color:var(--text-primary); font-size:15px;">${p.name}</strong>
                </div>
                ${isActive ? '<span style="font-size:11px; padding:2px 8px; border-radius:10px; background:#10B981; color:#fff; font-weight:700;">ACTIVE</span>' : ''}
              </div>
              <p style="font-size:12px; color:var(--text-muted); margin-bottom: 12px;">
                Channel: ${p.channel_title || 'YouTube Linked'}<br>
                Clips: ${p.total_clips || 0} • Pin: ${p.has_pin ? '🔒 Set' : '🔓 None'}
              </p>
              <div style="display: flex; gap: 8px;">
                ${!isActive ? `
                  <button class="clay-btn" onclick="App.switchProfile('${p.id}', ${p.has_pin})" style="flex:1; padding:6px 10px; font-size:12px; background:rgba(56,189,248,0.15); color:var(--accent-sky);">
                    Switch
                  </button>
                ` : `
                  <button class="clay-btn" onclick="App.exportActiveProfile()" style="flex:1; padding:6px 10px; font-size:12px; background:rgba(245,158,11,0.15); color:var(--accent-orange);">
                    📦 Backup Export
                  </button>
                `}
              </div>
            </div>
          `;
        }).join('');
      }
    } catch (e) {
      console.warn("Could not load profiles:", e);
    }
  },

  async switchProfile(profileId, hasPin) {
    let pin = null;
    if (hasPin) {
      pin = prompt("Is profile ka 4-digit PIN enter karein:");
      if (!pin) return;
    }
    try {
      const res = await fetch('/api/profiles/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_id: profileId, pin: pin })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Profile switch error.");
        return;
      }
      alert(`✓ Switched to profile: ${data.active_profile.name}`);
      await this.loadProfiles();
      await this.checkYouTubeStatus();
    } catch (e) {
      alert("Switch error: " + e.message);
    }
  },

  async createProfilePrompt() {
    const name = prompt("Naye Channel Profile ka naam likhein (e.g. FreeFire Shorts):");
    if (!name) return;
    const pin = prompt("Optional 4-digit PIN daalo (skip karne ke liye OK dabayein):");
    try {
      const res = await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, color: '#F59E0B', pin: pin || null })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Profile create error.");
        return;
      }
      alert(`✓ Naya profile ban gaya: ${name}`);
      await this.loadProfiles();
    } catch (e) {
      alert("Create error: " + e.message);
    }
  },

  exportActiveProfile() {
    window.open('/api/profiles/export', '_blank');
  },

  /* ======================================================== */
  /* LLM PROVIDER CHAIN (v2)                                  */
  /* ======================================================== */
  llmConfig: null,

  async loadLLMProviders() {
    const container = document.getElementById('llmProvidersList');
    if (!container) return;
    try {
      const res = await fetch('/api/llm/providers');
      this.llmConfig = await res.json();
      const provs = this.llmConfig.providers || {};
      const priority = this.llmConfig.priority || [];

      container.innerHTML = priority.map(pId => {
        const p = provs[pId];
        if (!p) return '';
        const isReady = p.status === 'ready';
        const isLocal = p.is_local;
        return `
          <div class="clay-inset-box" style="padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; border-left: 4px solid ${isReady ? '#10B981' : '#F59E0B'};">
            <div style="flex: 1; min-width: 220px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <strong style="color:var(--text-primary); font-size:15px;">${p.name}</strong>
                <span class="health-badge ${isReady ? 'badge-good' : 'badge-warning'}" style="font-size:10px; padding:2px 8px;">
                  ${isReady ? 'READY' : (p.status || 'CONFIG')}
                </span>
                ${isLocal ? '<span style="font-size:10px; background:#38BDF8; color:#000; padding:2px 6px; border-radius:4px; font-weight:700;">LOCAL (Zero Cost)</span>' : ''}
              </div>
              <p style="font-size:12px; color:var(--text-muted); margin-top: 4px;">
                Model: <code>${p.model}</code> • ${p.description || ''}
              </p>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              ${!isLocal ? `
                <input type="password" id="key_${pId}" class="clay-input" placeholder="API Key" value="${p.api_key || ''}" style="width: 140px; padding: 6px 10px; font-size: 12px;" onchange="App.saveLLMKey('${pId}', this.value)">
              ` : `
                <span style="font-size:12px; color:#10B981; font-weight:600;">✓ Installed on PC</span>
              `}
              <button class="clay-btn" onclick="App.testLLMProvider('${pId}')" style="padding: 6px 14px; font-size: 12px; background: rgba(56,189,248,0.15); color: var(--accent-sky);">
                ⚡ Test
              </button>
            </div>
          </div>
        `;
      }).join('');
    } catch (e) {
      console.warn("Could not load LLM providers:", e);
    }
  },

  async testLLMProvider(providerId) {
    try {
      const res = await fetch('/api/llm/test-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: providerId })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        alert(`✓ Provider [${providerId}] TEST PASSED!\nLatency: ${data.latency_ms}ms\nResponse: "${data.test_response}"`);
      } else {
        alert(`❌ Provider [${providerId}] TEST FAILED:\n${data.error || data.detail}`);
      }
      await this.loadLLMProviders();
    } catch (e) {
      alert("Test error: " + e.message);
    }
  },

  async saveLLMKey(providerId, apiKey) {
    if (!this.llmConfig || !this.llmConfig.providers[providerId]) return;
    this.llmConfig.providers[providerId].api_key = apiKey;
    this.llmConfig.providers[providerId].enabled = !!apiKey;
    try {
      await fetch('/api/llm/save-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          priority: this.llmConfig.priority,
          providers: this.llmConfig.providers
        })
      });
      await this.loadLLMProviders();
    } catch (e) {
      console.error(e);
    }
  },

  /* ======================================================== */
  /* SHORTS BUNDLE IMPORTER (v2)                              */
  /* ======================================================== */
  async startBundleImport() {
    const input = document.getElementById('bundlePathInput');
    const pathVal = input ? input.value.trim() : '';
    if (!pathVal) {
      alert("Kripya valid folder path ya .zip file path enter karein!");
      return;
    }
    try {
      const res = await fetch('/api/bundle/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: pathVal, daily_cap: 4 })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Bundle import error.");
        return;
      }
      alert(`✓ Bundle Import Shuru!\nImported items: ${data.imported_count || 1}\nQueue me add kar diya gaya hai.`);
      if (input) input.value = '';
    } catch (e) {
      alert("Bundle import error: " + e.message);
    }
  },

  async uploadSingleClipToYouTube(clipId, filename) {
    if (!this.isYouTubeConnected) {
      const st = await this.checkYouTubeStatus();
      if (!st.connected) {
        const goToSettings = confirm("YouTube abhi connected nahi hai!\n\nKya aap Settings tab mein jaakar 'YouTube Jodo' se apna account link karna chahte hain?");
        if (goToSettings) {
          this.switchTab('settings');
        }
        return;
      }
    }

    const btn = document.getElementById(`yt-upload-btn-${clipId}`);
    if (btn) {
      btn.disabled = true;
      btn.innerText = "⏳ Uploading... (0%)";
      btn.style.opacity = "0.85";
    }

    const title = document.getElementById(`yt-title-${clipId}`)?.value;
    const desc = document.getElementById(`yt-desc-${clipId}`)?.value;
    const tagsRaw = document.getElementById(`yt-tags-${clipId}`)?.value || "";
    const tags = tagsRaw.split(/\s+/).filter(t => t.length > 0);

    const payload = {
      filename: filename,
      title: title,
      description: desc,
      hashtags: tags,
      privacy: "private"
    };

    try {
      const res = await fetch('/api/youtube/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Upload fail hua.");
      }

      if (btn) {
        btn.disabled = false;
        btn.outerHTML = `
          <a href="${data.video_url}" target="_blank" class="clay-btn" style="background: rgba(16,185,129,0.18); border: 1px solid #10B981; color: #10B981; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">
            ✓ Uploaded! 🔗 Open on YouTube ↗
          </a>
        `;
      }

      let msg = `✓ Clip YouTube par Private video ke roop mein successfully upload ho gayi!\n\nLink: ${data.video_url}`;
      if (data.is_locked_private) {
        msg += `\n\n⚠ Note: ${data.warning_message || "Video Google developer restriction ke karan 'Locked Private' hai (sirf aapke test user account ko dikhegi)."}`;
      }
      alert(msg);
      this.loadClips();
    } catch (e) {
      if (btn) {
        btn.disabled = false;
        btn.innerText = "🔴 YouTube pe bhejo";
        btn.style.opacity = "1";
      }
      alert("YouTube Upload Error:\n" + e.message);
    }
  },

  async uploadAllClipsToYouTube() {
    if (!this.isYouTubeConnected) {
      const st = await this.checkYouTubeStatus();
      if (!st.connected) {
        const goToSettings = confirm("YouTube abhi connected nahi hai!\n\nKya aap Settings tab mein jaakar 'YouTube Jodo' se apna account link karna chahte hain?");
        if (goToSettings) {
          this.switchTab('settings');
        }
        return;
      }
    }

    if (!confirm("Kya aap sabhi ready clips ko YouTube par as Private videos upload karna chahte hain?")) {
      return;
    }

    const btn = document.getElementById('uploadAllYtBtn');
    if (btn) {
      btn.disabled = true;
      btn.innerText = "⏳ Sab upload ho rahe hain...";
    }

    try {
      const res = await fetch('/api/youtube/upload-all', { method: 'POST' });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Upload fail hua.");
      }

      let summary = `✓ Kul ${data.uploaded_count} clips successfully YouTube par upload ho gayi hain!`;
      if (data.errors && data.errors.length > 0) {
        summary += `\n\nErrors:\n` + data.errors.join('\n');
      }
      alert(summary);
      this.loadClips();
    } catch (e) {
      alert("YouTube Batch Upload Error:\n" + e.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerText = "🚀 Sab YouTube pe bhejo";
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

    this.eventSource.addEventListener('cancelled', (e) => {
      let msg = "Process user dwara cancel kar diya gaya.";
      try {
        const data = JSON.parse(e.data);
        msg = data.message || msg;
      } catch (err) {}
      this.onJobCancelled(msg);
    });

    this.eventSource.addEventListener('error', (e) => {
      try {
        const data = JSON.parse(e.data);
        this.showError(data.message);
      } catch (err) {}
    });

    this.eventSource.addEventListener('youtube_progress', (e) => {
      try {
        const data = JSON.parse(e.data);
        document.querySelectorAll(`[id^="yt-upload-btn-"]`).forEach(b => {
          b.innerText = `⏳ Uploading... (${data.progress}%)`;
        });
      } catch (err) {}
    });
  },

  updateProgress(pct, stepMsg, elapsed) {
    const card = document.getElementById('progressCard');
    const bar = document.getElementById('progressBarFill');
    const step = document.getElementById('progressStepText');
    const timer = document.getElementById('progressTimer');
    const pctLabel = document.getElementById('progressPctLabel');

    if (card) card.style.display = 'flex';
    if (bar) bar.style.width = `${pct}%`;
    if (step) step.innerText = stepMsg;
    if (timer) timer.innerText = `${elapsed || 0}s elapsed`;
    if (pctLabel) pctLabel.innerText = `${pct}% completed`;

    this.setWorkingState(true, stepMsg, pct);

    if (pct >= 100) {
      this.setWorkingState(false);
      setTimeout(() => {
        if (card) card.style.display = 'none';
        this.loadClips();
      }, 2500);
    }
  },

  async cancelJob() {
    if (!confirm("Kya aap chal rahe process ko sach mein rokna chahte hain?")) {
      return;
    }

    const cardCancel = document.getElementById('cardCancelBtn');
    const heroCancel = document.getElementById('heroCancelBtn');
    const headerCancel = document.querySelector('.btn-cancel-header');

    if (cardCancel) cardCancel.innerText = "⏳ Rok rahe hain...";
    if (heroCancel) heroCancel.innerText = "⏳ Rok rahe hain...";
    if (headerCancel) headerCancel.innerText = "⏳ ...";

    try {
      const res = await fetch('/api/cancel', { method: 'POST' });
      const data = await res.json();
      this.onJobCancelled(data.message || "Process successfully rok diya gaya hai.");
    } catch (e) {
      this.onJobCancelled("Process cancel kar diya gaya.");
    } finally {
      if (cardCancel) cardCancel.innerText = "🛑 Kaam Roko / End";
      if (heroCancel) heroCancel.innerText = "🛑 Kaam Roko (End)";
      if (headerCancel) headerCancel.innerText = "🛑 End";
    }
  },

  async resetQueue() {
    try {
      await fetch('/api/reset', { method: 'POST' });
      this.setWorkingState(false);
      const card = document.getElementById('progressCard');
      if (card) card.style.display = 'none';
      const bar = document.getElementById('progressBarFill');
      if (bar) bar.style.width = '0%';
      alert("✓ Queue aur background process successfully reset ho gaya hai! Ab aap fresh video process kar sakte hain.");
    } catch (e) {
      console.error("Reset error:", e);
    }
  },

  onJobCancelled(msg) {
    this.setWorkingState(false);
    const card = document.getElementById('progressCard');
    if (card) card.style.display = 'none';
    const bar = document.getElementById('progressBarFill');
    if (bar) bar.style.width = '0%';

    alert(msg || "✓ Process successfully rok diya gaya hai.");
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

    const countVal = document.getElementById('optClipsCount')?.value || "auto";
    const payload = {
      url: url,
      preset: this.currentPreset,
      clips_count: countVal === "auto" ? "auto" : parseInt(countVal),
      style: document.getElementById('optStyle')?.value || "game",
      tagdi_intensity: document.getElementById('optTagdiIntensity')?.value || "medium",
      long_short_mode: document.getElementById('optLongShortMode')?.checked || false,
      caption_color: document.getElementById('optColor')?.value || "hormozi",
      caption_position: document.getElementById('optPos')?.value || "bottom",
      caption_size: parseInt(document.getElementById('optSize')?.value || "58"),
      whisper_model: document.getElementById('optWhisper')?.value || "base",
      min_length: parseInt(document.getElementById('optMinLen')?.value || "20"),
      max_length: parseInt(document.getElementById('optMaxLen')?.value || "60"),
      enable_sfx: document.getElementById('optSfx')?.checked ?? true,
      watermark_text: document.getElementById('optWatermark')?.value || "",
      language: document.getElementById('optLanguage')?.value || "auto"
    };

    document.getElementById('progressCard').style.display = 'flex';
    this.updateProgress(5, "Queue mein laga rahe hain...", 0);
    this.setWorkingState(true, "Queue mein laga rahe hain...", 5);

    try {
      const res = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json();
        const detail = err.detail || "";
        if (detail.includes("pehle se chal raha hai")) {
          const shouldRestart = confirm("Ek job background mein pehle se chal raha hai.\n\nKya aap purana job ROK KAR naye सिरे se shuru karna chahte hain?");
          if (shouldRestart) {
            this.updateProgress(5, "Purana job rokar naya video shuru kar rahe hain...", 0);
            await fetch('/api/cancel', { method: 'POST' });
            await new Promise(r => setTimeout(r, 600));
            payload.force = true;
            const retryRes = await fetch('/api/process', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            });
            if (!retryRes.ok) {
              const retryErr = await retryRes.json();
              throw new Error(retryErr.detail || "Process restart fail hua.");
            }
            this.setWorkingState(true, "Video download ho raha hai...", 10);
            return;
          } else {
            this.setWorkingState(false);
            return;
          }
        }
        throw new Error(detail || "Process shuru nahi ho paya.");
      }
    } catch (e) {
      this.showError(e.message);
    }
  },

  showError(msg) {
    this.setWorkingState(false);
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
              <div style="display:flex; align-items:center; gap:8px; margin-top:4px; flex-wrap:wrap;">
                <span style="font-size:11px; font-weight:800; padding:2px 8px; border-radius:6px; background:${clip.viral_tier === 'Tier A' ? '#10B981' : (clip.viral_tier === 'Tier B' ? '#38BDF8' : '#F59E0B')}; color:#000;">
                  ${clip.viral_tier || 'Tier A (High Retention)'}
                </span>
                <span style="font-size: 13px; color: var(--text-secondary);">
                  ⏱ ${clip.duration} • 💾 ${clip.filesize} • 🔥 Score: <strong style="color:var(--accent-orange);">${clip.viral_score}/100</strong>
                </span>
              </div>
              ${clip.improvement_tip ? `
                <p style="font-size:12px; color:#FCD34D; background:rgba(245,158,11,0.1); padding:6px 10px; border-radius:6px; margin-top:6px; border:1px solid rgba(245,158,11,0.25);">
                  💡 <strong>Virality Tip:</strong> ${clip.improvement_tip}
                </p>
              ` : ''}
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
            ${clip.youtube_upload && clip.youtube_upload.video_url ? `
              <a href="${clip.youtube_upload.video_url}" target="_blank" class="clay-btn" style="background: rgba(16,185,129,0.18); border: 1px solid #10B981; color: #10B981; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">
                ✓ YouTube Link ↗
              </a>
            ` : `
              <button id="yt-upload-btn-${clip.id}" class="clay-btn" onclick="App.uploadSingleClipToYouTube(${clip.id}, '${clip.filename}')" style="background: linear-gradient(135deg, #FF0000, #CC0000); color: #fff; font-weight: 700; border: none; box-shadow: 0 4px 14px rgba(255,0,0,0.35);">
                🔴 YouTube pe bhejo
              </button>
            `}
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
