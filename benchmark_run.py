import time
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path.cwd()))
from backend import pipeline, gemini_engine, subtitle_engine
from backend.queue_manager import OUTPUTS_DIR

url = 'https://youtu.be/eHQWaFDZvn4'
print("=== STARTING 10-MINUTE VIDEO BENCHMARK ===")
t_start = time.time()

# 1. Audio Ingestion
t0 = time.time()
wav_path, vid_id = pipeline.download_audio_16k(url, OUTPUTS_DIR)
t_audio = time.time() - t0
print(f"[1/4] Audio Ingestion (16kHz mono WAV): {t_audio:.2f}s | Path: {wav_path.name}")

# 2. Whisper Transcription
t0 = time.time()
transcript = pipeline.transcribe_audio(wav_path, 'base', OUTPUTS_DIR, vid_id)
t_whisper = time.time() - t0
print(f"[2/4] Whisper Transcription: {t_whisper:.2f}s | Segments: {len(transcript)}")

# 3. Gemini Viral Selection & Social Metadata
t0 = time.time()
clip_candidates = gemini_engine.pick_clips_and_metadata(
    transcript_segments=transcript,
    num_clips=1,
    min_len=20,
    max_len=45,
    model_name='gemini-3.7-flash',
    language='hinglish'
)
t_gemini = time.time() - t0
cand = clip_candidates[0]
title = cand.get("title", "No Title")
print(f"[3/4] Gemini Intelligence: {t_gemini:.2f}s | Title: {title}")

# 4. Single-Pass Tagdi Edit Render
t0 = time.time()
clean_start, clean_end = pipeline.snap_to_sentence_boundary(transcript, float(cand['start']), float(cand['end']))
source_file = pipeline.download_section_video(url, clean_start, clean_end, OUTPUTS_DIR, vid_id)

clip_words = []
for s in transcript:
    if s['end'] >= clean_start and s['start'] <= clean_end:
        for w in s.get('words', []):
            w_word = w.get('word') or w.get('w', '')
            w_start = w.get('start') if 'start' in w else w.get('s', s['start'])
            w_end = w.get('end') if 'end' in w else w.get('e', s['end'])
            if w_end >= clean_start and w_start <= clean_end:
                clip_words.append({
                    'word': w_word,
                    'start': max(0.0, round(w_start - clean_start, 2)),
                    'end': max(0.1, round(w_end - clean_start, 2))
                })

ass_path = OUTPUTS_DIR / f"benchmark_{vid_id}.ass"
subtitle_engine.generate_hormozi_ass(clip_words, ass_path, style_key='hormozi')

out_clip = OUTPUTS_DIR / f"benchmark_{vid_id}_tagdi.mp4"
hook_text = cand.get('hook_line', 'ANNUAL FUNCTION DANCE SCAM! 💀')

pipeline.render_clip_single_pass(
    source_path=source_file,
    out_clip_path=out_clip,
    start_sec=clean_start,
    end_sec=clean_end,
    ass_path=ass_path,
    hook_text=hook_text,
    mode='cinematic_blur',
    is_preview=False,
    enable_sfx=True,
    watermark_text='@clipper'
)
t_render = time.time() - t0
filesize_mb = out_clip.stat().st_size / (1024 * 1024) if out_clip.exists() else 0
print(f"[4/4] Single-Pass Tagdi Render: {t_render:.2f}s | Output: {out_clip.name} ({filesize_mb:.1f} MB)")

t_total = time.time() - t_start
print(f"=== TOTAL BENCHMARK TIME: {t_total:.2f}s ===")
