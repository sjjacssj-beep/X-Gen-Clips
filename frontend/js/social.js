// Social Metadata Hub & Copy Manager

const SocialManager = {
  switchPlatform(clipId, platform) {
    const card = document.getElementById(`clip-${clipId}`);
    if (!card) return;
    const tabBtns = card.querySelectorAll('.platform-tab-btn');
    tabBtns.forEach(b => b.classList.toggle('active', b.getAttribute('data-plat') === platform));

    const contentPanes = card.querySelectorAll('.platform-pane');
    contentPanes.forEach(p => p.style.display = (p.getAttribute('data-plat') === platform ? 'flex' : 'none'));
  },

  async copyText(text, btnElement) {
    try {
      await navigator.clipboard.writeText(text);
      const originalText = btnElement.innerText;
      btnElement.innerText = "✓ Copied!";
      btnElement.style.color = "#10B981";
      setTimeout(() => {
        btnElement.innerText = originalText;
        btnElement.style.color = "";
      }, 1800);
    } catch (e) {
      alert("Copy failed. Please copy manually.");
    }
  },

  async copyAllForPlatform(clipId, platform) {
    const card = document.getElementById(`clip-${clipId}`);
    if (!card) return;
    const pane = card.querySelector(`.platform-pane[data-plat="${platform}"]`);
    if (!pane) return;

    const title = pane.querySelector('.copy-title-input')?.value || "";
    const desc = pane.querySelector('.copy-desc-textarea')?.value || "";
    const tags = pane.querySelector('.copy-tags-input')?.value || "";

    const fullText = `${title}\n\n${desc}\n\n${tags}`.trim();
    const btn = card.querySelector('.btn-copy-all');
    await this.copyText(fullText, btn);
  },

  async resuggestText(clipId, filename) {
    const card = document.getElementById(`clip-${clipId}`);
    const btn = card?.querySelector('.btn-resuggest');
    if (btn) btn.innerText = "⏳ Soch raha hai...";

    try {
      const res = await fetch('/api/resuggest-text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clip_id: clipId, filename: filename, language: 'hinglish' })
      });
      if (!res.ok) throw new Error("Resuggest fail ho gaya.");
      const freshData = await res.json();
      
      // Refresh clips to render new metadata
      if (window.App) {
        window.App.loadClips();
      }
    } catch (e) {
      alert(e.message);
    } finally {
      if (btn) btn.innerText = "🔄 Dobara suggest karo";
    }
  },

  downloadZip(filename) {
    window.location.href = `/api/export-zip?filename=${encodeURIComponent(filename)}`;
  },

  openPlatform(target) {
    if (target === 'youtube') window.open('https://studio.youtube.com', '_blank');
    if (target === 'instagram') window.open('https://www.instagram.com', '_blank');
    if (target === 'tiktok') window.open('https://www.tiktok.com/upload', '_blank');
  },

  selectTitleVariant(clipId, titleText, pillElement) {
    const titleInput = document.getElementById(`yt-title-${clipId}`);
    if (titleInput) {
      titleInput.value = titleText;
      this.syncLivePreview(clipId);
    }
    const card = document.getElementById(`clip-${clipId}`);
    if (card) {
      card.querySelectorAll('.title-variant-pill').forEach(p => p.classList.remove('active'));
      if (pillElement) pillElement.classList.add('active');
    }
  },

  selectDescVariant(clipId, descText, pillElement) {
    const descInput = document.getElementById(`yt-desc-${clipId}`);
    if (descInput) {
      descInput.value = descText;
      this.syncLivePreview(clipId);
    }
    const card = document.getElementById(`clip-${clipId}`);
    if (card) {
      card.querySelectorAll('.desc-variant-pill').forEach(p => p.classList.remove('active'));
      if (pillElement) pillElement.classList.add('active');
    }
  },

  syncLivePreview(clipId) {
    const titleVal = document.getElementById(`yt-title-${clipId}`)?.value || "";
    const descVal = document.getElementById(`yt-desc-${clipId}`)?.value || "";
    
    const previewTitle = document.getElementById(`yt-preview-title-${clipId}`);
    const previewDesc = document.getElementById(`yt-preview-desc-${clipId}`);
    
    if (previewTitle) previewTitle.innerText = titleVal;
    if (previewDesc) {
      const firstLine = descVal.split('\n')[0] || "";
      previewDesc.innerText = firstLine;
    }
  },

  async cycleTitleEmoji(clipId, mood = 'shock_action') {
    const input = document.getElementById(`yt-title-${clipId}`);
    if (!input || !input.value.trim()) return;
    try {
      const res = await fetch('/api/metadata/cycle-emoji', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: input.value, mood: mood })
      });
      if (res.ok) {
        const data = await res.json();
        input.value = data.text;
        this.syncLivePreview(clipId);
      }
    } catch (e) {
      console.warn("Cycle emoji failed:", e);
    }
  },

  async toggleTitleEmoji(clipId, btnElement, mood = 'shock_action') {
    const input = document.getElementById(`yt-title-${clipId}`);
    if (!input || !input.value.trim()) return;
    const hasEmoji = /[\u{1F300}-\u{1FAFF}]/u.test(input.value);
    const remove = hasEmoji;

    try {
      const res = await fetch('/api/metadata/toggle-emoji', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: input.value, remove: remove, mood: mood })
      });
      if (res.ok) {
        const data = await res.json();
        input.value = data.text;
        if (btnElement) {
          btnElement.innerText = remove ? "✨ Emoji Lagao" : "🚫 Bina Emoji";
          btnElement.title = remove ? "Emoji wapas lagao" : "Emojis hata kar clean text banao";
        }
        this.syncLivePreview(clipId);
      }
    } catch (e) {
      console.warn("Toggle emoji failed:", e);
    }
  },

  async cycleDescEmoji(clipId, mood = 'shock_action') {
    const input = document.getElementById(`yt-desc-${clipId}`);
    if (!input || !input.value.trim()) return;
    try {
      const res = await fetch('/api/metadata/cycle-emoji', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: input.value, mood: mood })
      });
      if (res.ok) {
        const data = await res.json();
        input.value = data.text;
        this.syncLivePreview(clipId);
      }
    } catch (e) {
      console.warn("Cycle desc emoji failed:", e);
    }
  },

  async toggleDescEmoji(clipId, btnElement, mood = 'shock_action') {
    const input = document.getElementById(`yt-desc-${clipId}`);
    if (!input || !input.value.trim()) return;
    const hasEmoji = /[\u{1F300}-\u{1FAFF}]/u.test(input.value);
    const remove = hasEmoji;

    try {
      const res = await fetch('/api/metadata/toggle-emoji', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: input.value, remove: remove, mood: mood })
      });
      if (res.ok) {
        const data = await res.json();
        input.value = data.text;
        if (btnElement) {
          btnElement.innerText = remove ? "✨ Emoji Lagao" : "🚫 Bina Emoji";
        }
        this.syncLivePreview(clipId);
      }
    } catch (e) {
      console.warn("Toggle desc emoji failed:", e);
    }
  }
    if (target === 'tiktok') window.open('https://www.tiktok.com/upload', '_blank');
  }
};

window.SocialManager = SocialManager;
