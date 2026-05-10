from flask import Flask, render_template, request, jsonify, session, send_from_directory, redirect
import os
import uuid
import threading
import time
import cv2
from functools import wraps
from database import create_user, verify_user, get_user, save_config as fb_save, load_config as fb_load, delete_user_data

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['CLIPS_FOLDER'] = 'clips'
app.config['OUTPUTS_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

for folder in [app.config['UPLOAD_FOLDER'], app.config['CLIPS_FOLDER'], app.config['OUTPUTS_FOLDER']]:
    if not os.path.exists(folder):
        os.makedirs(folder)

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'El video es demasiado grande. Máximo 50MB.'}), 413

# Background task storage
_tasks = {}
_tasks_lock = threading.Lock()
_last_video_path = None
_last_video_lock = threading.Lock()

def _get_task(task_id):
    with _tasks_lock:
        return _tasks.get(task_id)

def _set_task(task_id, data):
    with _tasks_lock:
        _tasks[task_id] = data

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'No autenticado'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def user_path(subfolder):
    """Get user-scoped path, creating it if needed."""
    uid = str(session.get('user_id', ''))
    p = os.path.join(subfolder, uid)
    if not os.path.exists(p):
        os.makedirs(p)
    return p

# ========== PUBLIC ROUTES ==========

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'error': 'Usuario y contraseña requeridos'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Contraseña debe tener al menos 4 caracteres'}), 400
    user = create_user(username, password)
    if not user:
        return jsonify({'error': 'El usuario ya existe'}), 409
    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'success': True, 'user': user})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    user = verify_user(username, password)
    if not user:
        return jsonify({'error': 'Usuario o contraseña incorrectos'}), 401
    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'success': True, 'user': user})

@app.route('/api/logout')
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me')
def api_me():
    if 'user_id' not in session:
        return jsonify({'authenticated': False}), 200
    user = get_user(session['user_id'])
    if not user:
        session.clear()
        return jsonify({'authenticated': False}), 200
    return jsonify({'authenticated': True, 'user': user})

# ========== AUTHENTICATED ROUTES ==========

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/editor/<clip_id>')
@login_required
def editor(clip_id):
    clip_path = os.path.join('clips', str(session['user_id']), f'{clip_id}.mp4')
    if not os.path.exists(clip_path):
        return "Clip no encontrado", 404
    return render_template('editor.html',
                         clip_id=clip_id,
                         clip_path=f'/clips/{session["user_id"]}/{clip_id}.mp4',
                         user_id=str(session['user_id']))

@app.route('/preview/<clip_id>')
@login_required
def preview(clip_id):
    gif_rel = os.path.join('clips', str(session['user_id']), f'{clip_id}_preview.gif')
    gif_url = gif_rel.replace('\\', '/')
    return render_template('preview.html', clip_id=clip_id,
                          gif_path=gif_url if os.path.exists(gif_rel) else None)

# API: Upload de video
@app.route('/api/upload', methods=['POST'])
@login_required
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No se encontró video'}), 400
    video = request.files['video']
    if video.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400
    uid = str(session['user_id'])
    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], uid)
    os.makedirs(upload_dir, exist_ok=True)
    session_id = str(uuid.uuid4())
    filename = f'{session_id}_{video.filename}'
    filepath = os.path.join(upload_dir, filename)
    video.save(filepath)
    with _last_video_lock:
        global _last_video_path
        _last_video_path = filepath
    session['session_id'] = session_id
    session['video_path'] = filepath
    return jsonify({'session_id': session_id, 'filename': video.filename, 'video_path': filepath})

# API: Extraer clips virales (asíncrono)
@app.route('/api/extract-clips', methods=['POST'])
@login_required
def api_extract_clips():
    data = request.json
    video_path = data.get('video_path')
    max_clips = data.get('max_clips', 5)
    sensitivity = data.get('sensitivity', 0.3)
    if not video_path:
        video_path = session.get('video_path')
    if not video_path:
        with _last_video_lock:
            video_path = _last_video_path
    if not video_path or not os.path.exists(video_path):
        return jsonify({'error': 'Video no encontrado'}), 404

    user_id = session['user_id']
    task_id = str(uuid.uuid4())
    _set_task(task_id, {
        'status': 'running',
        'progress': 0,
        'message': 'Iniciando análisis...',
        'clips': None,
        'error': None,
        'video_path': video_path
    })

    def _run_extract(tid, vp, mc, sens, uid):
        try:
            _set_task(tid, {**_get_task(tid), 'progress': 5, 'message': 'Extrayendo audio del video...'})
            from processing.extract_clips import extract_viral_clips
            _set_task(tid, {**_get_task(tid), 'progress': 15, 'message': 'Analizando picos de actividad...'})
            clips = extract_viral_clips(vp, max_clips=mc, sensitivity=sens, user_id=uid)
            if clips:
                _set_task(tid, {**_get_task(tid), 'progress': 90, 'message': f'Generados {len(clips)} clips'})
            else:
                _set_task(tid, {**_get_task(tid), 'progress': 90, 'message': 'No se detectaron clips'})
            _set_task(tid, {**_get_task(tid), 'status': 'done', 'progress': 100, 'clips': clips})
        except Exception as e:
            import traceback
            traceback.print_exc()
            _set_task(tid, {**_get_task(tid), 'status': 'error', 'error': str(e)})

    thread = threading.Thread(target=_run_extract, args=(task_id, video_path, max_clips, sensitivity, user_id), daemon=True)
    thread.start()
    return jsonify({'task_id': task_id})

# API: Estado de extracción
@app.route('/api/extract-status/<task_id>')
def extract_status(task_id):
    task = _get_task(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    return jsonify({
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'clips': task.get('clips'),
        'error': task.get('error')
    })

# API: Obtener ruta del video
@app.route('/api/video-path')
@login_required
def get_video_path():
    vp = session.get('video_path')
    if not vp:
        with _last_video_lock:
            vp = _last_video_path
    return jsonify({'video_path': vp})

# API: Guardar config (segmentos)
@app.route('/api/save-config', methods=['POST'])
@login_required
def save_config():
    data = request.json
    clip_id = data.get('clip_id')
    segments = data.get('segments', [])
    if not clip_id:
        return jsonify({'error': 'Clip ID requerido'}), 400
    fb_save(clip_id, str(session['user_id']), segments)
    return jsonify({'success': True})

# API: Cargar config
@app.route('/api/load-config/<clip_id>')
@login_required
def load_config(clip_id):
    clips_dir = os.path.join(app.config['CLIPS_FOLDER'], str(session['user_id']))
    clip_path = os.path.join(clips_dir, f'{clip_id}.mp4')
    data = fb_load(clip_id, str(session['user_id']))
    if data:
        return jsonify(data)
    cap = cv2.VideoCapture(clip_path)
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS) if cap.get(cv2.CAP_PROP_FPS) else 10
    cap.release()
    return jsonify({'segments': [{
        'start': 0.0, 'end': duration,
        'layout_mode': 'single',
        'box_config': {},
        'output_config': {}
    }]})

# API: Generar preview GIF (asíncrono)
@app.route('/api/generate-preview', methods=['POST'])
@login_required
def api_generate_preview():
    data = request.json
    clip_id = data.get('clip_id')
    if not clip_id:
        return jsonify({'error': 'Clip ID requerido'}), 400

    user_id = str(session['user_id'])
    task_id = str(uuid.uuid4())
    _set_task(task_id, {
        'status': 'running', 'progress': 0,
        'message': 'Generando preview...', 'gif_path': None, 'error': None
    })

    def _run_preview(tid, cid, uid):
        try:
            _set_task(tid, {**_get_task(tid), 'progress': 30, 'message': 'Leyendo frames...'})
            from processing.generate_preview import create_preview_gif
            gif_path = create_preview_gif(cid, user_id=uid)
            if gif_path and os.path.exists(gif_path):
                _set_task(tid, {**_get_task(tid), 'status': 'done', 'progress': 100, 'gif_path': gif_path, 'message': 'Preview listo'})
            else:
                _set_task(tid, {**_get_task(tid), 'status': 'error', 'error': 'No se pudo generar el GIF'})
        except Exception as e:
            _set_task(tid, {**_get_task(tid), 'status': 'error', 'error': str(e)})

    thread = threading.Thread(target=_run_preview, args=(task_id, clip_id, user_id), daemon=True)
    thread.start()
    return jsonify({'task_id': task_id})

# API: Render final (asíncrono)
@app.route('/api/render-clip', methods=['POST'])
@login_required
def api_render_clip():
    data = request.json
    clip_id = data.get('clip_id')
    if not clip_id:
        return jsonify({'error': 'Clip ID requerido'}), 400

    user_id = str(session['user_id'])
    task_id = str(uuid.uuid4())
    _set_task(task_id, {
        'status': 'running', 'progress': 0,
        'message': 'Renderizando...', 'output_path': None, 'error': None
    })

    def _run_render(tid, cid, uid):
        try:
            from processing.render_clip import render_clip_with_boxes
            _set_task(tid, {**_get_task(tid), 'progress': 30, 'message': 'Procesando frames...'})
            output_path = render_clip_with_boxes(cid, user_id=uid)
            if output_path and os.path.exists(output_path):
                _set_task(tid, {**_get_task(tid), 'status': 'done', 'progress': 100, 'output_path': output_path, 'message': 'Render listo'})
            else:
                _set_task(tid, {**_get_task(tid), 'status': 'error', 'error': 'No se pudo renderizar'})
        except Exception as e:
            _set_task(tid, {**_get_task(tid), 'status': 'error', 'error': str(e)})

    thread = threading.Thread(target=_run_render, args=(task_id, clip_id, user_id), daemon=True)
    thread.start()
    return jsonify({'task_id': task_id})

# API: Status genérico para tareas
@app.route('/api/task-status/<task_id>')
def task_status(task_id):
    task = _get_task(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(task)

# API: Listar clips del usuario
@app.route('/api/list-clips')
@login_required
def list_clips():
    clips_dir = os.path.join(app.config['CLIPS_FOLDER'], str(session['user_id']))
    clips = []
    if os.path.exists(clips_dir):
        for filename in os.listdir(clips_dir):
            if filename.endswith('.mp4') and not filename.startswith('frame_') and '_preview' not in filename:
                clip_id = filename.replace('.mp4', '')
                clips.append({'id': clip_id, 'filename': filename})
    return jsonify({'clips': clips})

# API: Listar videos del usuario
@app.route('/api/list-videos')
@login_required
def list_videos():
    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(session['user_id']))
    videos = []
    if os.path.exists(upload_dir):
        for filename in os.listdir(upload_dir):
            if filename.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
                videos.append({'filename': filename, 'path': os.path.join(upload_dir, filename)})
    return jsonify({'videos': videos})

# API: YouTube OAuth
@app.route('/api/youtube/auth')
@login_required
def youtube_auth():
    from google_auth_oauthlib.flow import InstalledAppFlow
    import json as _json, tempfile, os
    env_json = os.environ.get('GOOGLE_CLIENT_SECRETS')
    if env_json:
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tmp.write(env_json)
        tmp.close()
        flow = InstalledAppFlow.from_client_secrets_file(
            tmp.name,
            scopes=['https://www.googleapis.com/auth/youtube.upload']
        )
        os.unlink(tmp.name)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['https://www.googleapis.com/auth/youtube.upload']
        )
    auth_url, _ = flow.authorization_url(prompt='consent')
    return jsonify({'auth_url': auth_url})

# API: Upload a YouTube
@app.route('/api/upload-youtube', methods=['POST'])
@login_required
def api_upload_youtube():
    data = request.json
    video_path = data.get('video_path')
    title = data.get('title', 'Short generado automáticamente')
    description = data.get('description', '#Shorts #viral')
    if not video_path or not os.path.exists(video_path):
        return jsonify({'error': 'Video no encontrado'}), 404
    try:
        from processing.upload_to_youtube import upload_short
        video_id = upload_short(video_path, title, description)
        if video_id:
            return jsonify({'success': True, 'video_id': video_id, 'url': f'https://youtu.be/{video_id}'})
        return jsonify({'error': 'Falló la subida'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API: Eliminar usuario (datos y cuenta)
@app.route('/api/delete-account', methods=['POST'])
@login_required
def delete_account():
    uid = str(session['user_id'])
    import shutil
    for folder in [app.config['UPLOAD_FOLDER'], app.config['CLIPS_FOLDER'], app.config['OUTPUTS_FOLDER']]:
        up = os.path.join(folder, uid)
        if os.path.exists(up):
            shutil.rmtree(up)
    delete_user_data(uid)
    session.clear()
    return jsonify({'success': True})

# Archivos estáticos
@app.route('/clips/<path:filename>')
def serve_clip(filename):
    return send_from_directory(app.config['CLIPS_FOLDER'], filename)

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    print("Iniciando Clips...")
    print("Abre http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
