// Phone Preview & Player Controller

const PlayerManager = {
  selectHook(clipId, hookText) {
    const card = document.getElementById(`clip-${clipId}`);
    if (!card) return;
    const titleEl = card.querySelector('.hook-active-display');
    if (titleEl) {
      titleEl.innerText = hookText;
    }
    const hookBtns = card.querySelectorAll('.hook-pill-opt');
    hookBtns.forEach(btn => {
      btn.classList.toggle('active', btn.innerText.trim() === hookText.trim());
    });
  },

  selectCover(clipId, frameFilename) {
    const card = document.getElementById(`clip-${clipId}`);
    if (!card) return;
    const thumbs = card.querySelectorAll('.cover-thumb-img');
    thumbs.forEach(t => {
      t.classList.toggle('selected-cover', t.getAttribute('data-frame') === frameFilename);
    });
  },

  playPause(videoId) {
    const video = document.getElementById(videoId);
    if (!video) return;
    if (video.paused) {
      video.play();
    } else {
      video.pause();
    }
  }
};

window.PlayerManager = PlayerManager;
