import os
import json
import cv2
import numpy as np
import imageio


def create_preview_gif(clip_id, duration=5, fps=10, user_id=None):
    base = f"clips/{user_id}" if user_id else "clips"
    clip_path = f"{base}/{clip_id}.mp4"
    config_path = f"{base}/{clip_id}_config.json"
    gif_path = f"{base}/{clip_id}_preview.gif"

    if not os.path.exists(clip_path):
        raise FileNotFoundError(f"Clip no encontrado: {clip_path}")

    segments = []
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            segments = json.load(f).get('segments', [])

    try:
        cap = cv2.VideoCapture(clip_path)
        source_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        source_duration = total_frames / source_fps if source_fps > 0 else 0

        if source_duration <= 0:
            cap.release()
            return None

        num_frames = min(int(duration * fps), total_frames)
        step = max(1, total_frames // num_frames)

        frames = []
        for i in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                break

            if frame.shape[1] > 720:
                scale = 720 / frame.shape[1]
                new_w = int(frame.shape[1] * scale)
                new_h = int(frame.shape[0] * scale)
                frame = cv2.resize(frame, (new_w, new_h))

            t = i / source_fps
            seg = _get_segment(t, segments)
            if seg:
                frame = draw_boxes_on_frame(frame, seg.get('box_config', {}), seg.get('layout_mode', 'single'))

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(frame_rgb)

        cap.release()

        if frames:
            imageio.mimsave(gif_path, frames, fps=fps, loop=0)
            return gif_path

        return None

    except Exception as e:
        print(f"Error creando GIF: {e}")
        import traceback
        traceback.print_exc()
        return None


def _get_segment(t, segments):
    for seg in segments:
        if seg['start'] <= t < seg['end']:
            return seg
    return segments[-1] if segments else None


def draw_boxes_on_frame(frame, box_config, layout_mode):
    h, w = frame.shape[:2]
    positions = _build_positions(box_config, layout_mode, w, h)

    for box_id, pos in positions.items():
        x = pos.get('x', 0)
        y = pos.get('y', 0)
        box_w = pos.get('width', w // 4)
        box_h = pos.get('height', h // 4)

        color = (0, 255, 0) if box_id == 'face' else (255, 0, 0)
        cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), color, 3)

        label = 'Cara' if box_id == 'face' else ('Persona 2' if box_id == 'box2' else 'Juego')
        cv2.putText(frame, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    return frame


def _build_positions(box_config, layout_mode, src_w, src_h):
    if layout_mode == 'single':
        return {'box1': {
            'x': box_config.get('x', src_w // 4),
            'y': box_config.get('y', src_h // 4),
            'width': box_config.get('width', src_w // 2),
            'height': box_config.get('height', src_h // 2)
        }}
    elif layout_mode == 'dual':
        return {
            'box1': {
                'x': box_config.get('box1_x', 0),
                'y': box_config.get('box1_y', 0),
                'width': box_config.get('box1_width', src_w // 2),
                'height': box_config.get('box1_height', src_h)
            },
            'box2': {
                'x': box_config.get('box2_x', src_w // 2),
                'y': box_config.get('box2_y', 0),
                'width': box_config.get('box2_width', src_w // 2),
                'height': box_config.get('box2_height', src_h)
            }
        }
    elif layout_mode == 'gaming':
        return {
            'face': {
                'x': box_config.get('face_x', src_w // 4),
                'y': box_config.get('face_y', 0),
                'width': box_config.get('face_width', src_w // 2),
                'height': box_config.get('face_height', src_h // 3)
            },
            'gameplay': {
                'x': box_config.get('game_x', 0),
                'y': box_config.get('game_y', src_h // 3),
                'width': box_config.get('game_width', src_w),
                'height': box_config.get('game_height', src_h * 2 // 3)
            }
        }
    return {}
