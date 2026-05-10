import os
import json
import subprocess
import cv2
import numpy as np
import imageio_ffmpeg


def _merge_audio(clip_path, video_path):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    temp_path = video_path + '.tmp.mp4'
    os.rename(video_path, temp_path)
    try:
        subprocess.run([
            ffmpeg, '-i', temp_path, '-i', clip_path,
            '-c:v', 'copy', '-c:a', 'aac',
            '-map', '0:v:0', '-map', '1:a:0',
            '-shortest', '-y', video_path
        ], check=True, capture_output=True)
    except Exception:
        os.rename(temp_path, video_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _get_segment(t, segments):
    for seg in segments:
        if seg['start'] <= t < seg['end']:
            return seg
    return segments[-1] if segments else None


def render_clip_with_boxes(clip_id, user_id=None):
    base = f"clips/{user_id}" if user_id else "clips"
    out_base = f"outputs/{user_id}" if user_id else "outputs"
    clip_path = f"{base}/{clip_id}.mp4"
    config_path = f"{base}/{clip_id}_config.json"
    output_path = f"{out_base}/{clip_id}_rendered.mp4"

    if not os.path.exists(clip_path):
        raise FileNotFoundError(f"Clip no encontrado: {clip_path}")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config no encontrado: {config_path}")

    with open(config_path, 'r') as f:
        config = json.load(f)

    segments = config.get('segments', [])
    if not segments:
        raise ValueError("No hay segmentos en la configuracion")

    os.makedirs(out_base, exist_ok=True)

    cap = cv2.VideoCapture(clip_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_w, out_h = 1080, 1920
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))

    for frame_idx in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break

        t = frame_idx / fps
        seg = _get_segment(t, segments)
        if seg is None:
            continue

        positions = build_initial_positions(seg.get('box_config', {}), seg.get('layout_mode', 'single'))
        out_positions = build_default_output_positions(seg.get('output_config', {}), seg.get('layout_mode', 'single'))

        output_frame = create_layout_frame(frame, positions, out_positions, out_w, out_h, src_w, src_h)
        out.write(output_frame)

    cap.release()
    out.release()

    _merge_audio(clip_path, output_path)
    return output_path


def render_single_clip(clip_path, output_path, config, user_id=None):
    base = f"clips/{user_id}" if user_id else "clips"
    out_base = f"outputs/{user_id}" if user_id else "outputs"
    segments = config.get('segments', [])
    if not segments:
        raise ValueError("No hay segmentos en la configuracion")

    cap = cv2.VideoCapture(clip_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_w, out_h = 1080, 1920
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))

    for frame_idx in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break
        t = frame_idx / fps
        seg = _get_segment(t, segments)
        if seg is None:
            continue
        positions = build_initial_positions(seg.get('box_config', {}), seg.get('layout_mode', 'single'))
        out_positions = build_default_output_positions(seg.get('output_config', {}), seg.get('layout_mode', 'single'))
        output_frame = create_layout_frame(frame, positions, out_positions, out_w, out_h, src_w, src_h)
        out.write(output_frame)

    cap.release()
    out.release()
    _merge_audio(clip_path, output_path)
    return output_path


def build_default_output_positions(output_config, layout_mode):
    if layout_mode == 'single':
        return {'box1': {
            'x': output_config.get('x', 0),
            'y': output_config.get('y', 0),
            'width': output_config.get('width', 1080),
            'height': output_config.get('height', 1920)
        }}
    elif layout_mode == 'dual':
        return {
            'box1': {
                'x': output_config.get('box1_x', 0),
                'y': output_config.get('box1_y', 0),
                'width': output_config.get('box1_width', 540),
                'height': output_config.get('box1_height', 1920)
            },
            'box2': {
                'x': output_config.get('box2_x', 540),
                'y': output_config.get('box2_y', 0),
                'width': output_config.get('box2_width', 540),
                'height': output_config.get('box2_height', 1920)
            }
        }
    elif layout_mode == 'gaming':
        return {
            'face': {
                'x': output_config.get('face_x', 0),
                'y': output_config.get('face_y', 0),
                'width': output_config.get('face_width', 1080),
                'height': output_config.get('face_height', 672)
            },
            'gameplay': {
                'x': output_config.get('game_x', 0),
                'y': output_config.get('game_y', 672),
                'width': output_config.get('game_width', 1080),
                'height': output_config.get('game_height', 1248)
            }
        }
    return {}


def build_initial_positions(box_config, layout_mode):
    if layout_mode == 'single':
        return {'box1': dict(box_config)}
    elif layout_mode == 'dual':
        def strip(d, p):
            pl = len(p)
            return {k[pl:]: v for k, v in d.items() if k.startswith(p)}
        return {'box1': strip(box_config, 'box1_'),
                'box2': strip(box_config, 'box2_')}
    elif layout_mode == 'gaming':
        def strip(d, p):
            pl = len(p)
            return {k[pl:]: v for k, v in d.items() if k.startswith(p)}
        return {'face': strip(box_config, 'face_'),
                'gameplay': strip(box_config, 'game_')}
    return {}


def create_layout_frame(frame, positions, out_positions, out_w, out_h, src_w, src_h):
    output = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    for key in positions:
        s = positions[key]
        sx = max(0, s.get('x', 0))
        sy = max(0, s.get('y', 0))
        sw = max(10, min(s.get('width', src_w), src_w - sx))
        sh = max(10, min(s.get('height', src_h), src_h - sy))
        crop = frame[sy:sy+sh, sx:sx+sw]
        if crop.size == 0:
            continue

        o = out_positions.get(key, {'x': 0, 'y': 0, 'width': out_w, 'height': out_h})
        ox = max(0, o.get('x', 0))
        oy = max(0, o.get('y', 0))
        ow = max(1, min(o.get('width', out_w), out_w - ox))
        oh = max(1, min(o.get('height', out_h), out_h - oy))

        resized = cv2.resize(crop, (ow, oh))
        output[oy:oy+oh, ox:ox+ow] = resized

    return output
