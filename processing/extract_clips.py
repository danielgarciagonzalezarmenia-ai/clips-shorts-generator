import os
import uuid
import subprocess
import json
import tempfile
from datetime import datetime

# Find bundled ffmpeg from imageio-ffmpeg
_FFMPEG_PATH = None
try:
    import imageio_ffmpeg
    _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    _FFMPEG_PATH = 'ffmpeg'

def extract_viral_clips(video_path, max_clips=5, min_distance=3, sensitivity=0.3, user_id=None):
    clips = []
    ffmpeg = _FFMPEG_PATH
    clips_dir = f"clips/{user_id}" if user_id else "clips"

    try:
        import librosa
        import numpy as np

        # Get video duration first
        probe = subprocess.run(
            [ffmpeg, '-i', video_path],
            capture_output=True, text=True, timeout=30
        )
        import re
        duration_match = re.search(r'Duration: (\d+):(\d+):(\d+)\.(\d+)', probe.stderr)
        if duration_match:
            h, m, s, ms = map(int, duration_match.groups())
            video_duration = h * 3600 + m * 60 + s + ms / 100
        else:
            video_duration = 600  # assume 10 min

        # For very long videos (>30 min), only analyze first 30 min
        analyze_duration = min(video_duration, 1800)

        # Extract audio (only the portion we need to analyze)
        temp_audio = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_audio_path = temp_audio.name
        temp_audio.close()

        extract_cmd = [ffmpeg, '-y', '-i', video_path,
                       '-t', str(analyze_duration),
                       '-vn', '-acodec', 'pcm_s16le',
                       '-ar', '22050', '-ac', '1', temp_audio_path]
        subprocess.run(extract_cmd, capture_output=True, timeout=600)

        if not os.path.exists(temp_audio_path) or os.path.getsize(temp_audio_path) == 0:
            raise RuntimeError("Failed to extract audio from video")

        y, sr = librosa.load(temp_audio_path, sr=None)
        os.unlink(temp_audio_path)

        duration = len(y) / sr

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        times = librosa.times_like(onset_env, sr=sr)
        onset_env = onset_env / np.max(onset_env)

        peaks = librosa.util.peak_pick(
            onset_env, pre_max=3, post_max=3,
            pre_avg=3, post_avg=3,
            delta=sensitivity, wait=int(min_distance * sr / 512)
        )

        if len(peaks) == 0:
            peaks = librosa.util.peak_pick(
                onset_env, pre_max=3, post_max=3,
                pre_avg=3, post_avg=3,
                delta=max(0.05, sensitivity * 0.5), wait=int(min_distance * sr / 512)
            )

        if len(peaks) == 0:
            num_clips = min(max_clips, 5)
            for i in range(num_clips):
                mid = (i + 1) * duration / (num_clips + 1)
                clip_duration = min(30, duration * 0.5)
                start = max(0, mid - clip_duration / 2)
                end = min(duration, start + clip_duration)
                if end - start >= 10:
                    clips.append({
                        'id': f'clip_{i+1:02d}',
                        'start_time': float(start),
                        'end_time': float(end),
                        'duration': float(end - start),
                        'peak_time': float(mid),
                        'strength': 0.5
                    })
            return clips
        
        # Ordenar picos por intensidad
        peak_times = times[peaks]
        peak_strengths = onset_env[peaks]
        
        # Crear clip_data para cada pico
        clip_data_list = []
        for i, (t, s) in enumerate(zip(peak_times, peak_strengths)):
            clip_duration = 30
            start = max(0, t - 10)
            end = min(duration, start + clip_duration)
            
            if end - start < 10:
                continue
                
            clip_data_list.append({
                'id': f'clip_{i+1:02d}',
                'start_time': float(start),
                'end_time': float(end),
                'duration': float(end - start),
                'peak_time': float(t),
                'strength': float(s)
            })
        
        # Tomar los mejores max_clips
        clip_data_list.sort(key=lambda x: x['strength'], reverse=True)
        clip_data_list = clip_data_list[:max_clips]
        clip_data_list.sort(key=lambda x: x['start_time'])
        
        # Guardar clips como archivos de video
        os.makedirs(clips_dir, exist_ok=True)
        for i, clip in enumerate(clip_data_list):
            output_path = f"{clips_dir}/{clip['id']}.mp4"
            start = clip['start_time']
            dur = clip['duration']
            
            cmd = [
                ffmpeg, '-y', '-i', video_path,
                '-ss', str(start), '-t', str(dur),
                '-c:v', 'libx264', '-c:a', 'aac',
                '-preset', 'fast', '-crf', '23',
                output_path
            ]
            subprocess.run(cmd, capture_output=True, timeout=300)
            
            clip['file_path'] = output_path
        
        clips = clip_data_list
        return clips
        
    except Exception as e:
        print(f"Error extrayendo clips: {e}")
        import traceback
        traceback.print_exc()
        return clips

def create_timeline_frames(clip_path, num_frames=30):
    """
    Crea frames de preview para la línea de tiempo.
    """
    frames = []
    try:
        import cv2
        
        cap = cv2.VideoCapture(clip_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 1
        
        interval = total_frames // num_frames
        
        for i in range(num_frames):
            frame_pos = i * interval
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            
            if ret:
                # Guardar frame
                frame_path = f"clips/frame_{i:03d}.jpg"
                cv2.imwrite(frame_path, frame)
                frames.append({
                    'index': i,
                    'time': i * (duration / num_frames),
                    'path': frame_path
                })
        
        cap.release()
        
    except Exception as e:
        print(f"Error creando frames: {e}")
    
    return frames

if __name__ == "__main__":
    # Test
    clips = extract_viral_clips("test_video.mp4")
    print(f"Extraídos {len(clips)} clips")
    for c in clips:
        print(f"  {c['id']}: {c['start_time']:.1f}s - {c['end_time']:.1f}s")