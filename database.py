import os
import firebase_admin
from firebase_admin import credentials, firestore, auth
from google.cloud.firestore import FieldFilter
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

_initialized = False
_db = None

def _init():
    global _initialized, _db
    if _initialized:
        return
    env_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    if env_json:
        import json as _json, tempfile
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tmp.write(env_json)
        tmp.close()
        cred = credentials.Certificate(tmp.name)
        firebase_admin.initialize_app(cred)
        os.unlink(tmp.name)
    else:
        cred_path = os.path.join(os.path.dirname(__file__), 'firebase_credentials.json')
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
    _db = firestore.client()
    _initialized = True

def _get_collection(name):
    _init()
    return _db.collection(name)

# === USERS ===

def create_user(username, password):
    users = _get_collection('users')
    existing = users.where(filter=FieldFilter('username', '==', username)).limit(1).get()
    if len(list(existing)) > 0:
        return None
    try:
        auth.create_user(email=f'{username}@clips.app', password=password, uid=username)
    except Exception:
        pass
    doc = users.document(username)
    doc.set({
        'username': username,
        'password_hash': generate_password_hash(password),
        'created_at': datetime.now().isoformat()
    })
    return {'id': username, 'username': username}

def verify_user(username, password):
    users = _get_collection('users')
    docs = users.where(filter=FieldFilter('username', '==', username)).limit(1).get()
    for doc in docs:
        data = doc.to_dict()
        if check_password_hash(data['password_hash'], password):
            return {'id': doc.id, 'username': data['username']}
    return None

def get_user(user_id):
    users = _get_collection('users')
    doc = users.document(user_id).get()
    if doc.exists:
        data = doc.to_dict()
        return {'id': doc.id, 'username': data.get('username', user_id), 'created_at': data.get('created_at')}
    return None

# === CONFIGS (segmentos) ===

def save_config(clip_id, user_id, segments):
    configs = _get_collection('configs')
    doc_id = f'{user_id}_{clip_id}'
    configs.document(doc_id).set({
        'clip_id': clip_id,
        'user_id': user_id,
        'segments': segments,
        'updated_at': datetime.now().isoformat()
    })
    return True

def load_config(clip_id, user_id):
    configs = _get_collection('configs')
    doc_id = f'{user_id}_{clip_id}'
    doc = configs.document(doc_id).get()
    if doc.exists:
        return doc.to_dict()
    return None

def delete_user_data(user_id):
    batch = _db.batch()
    configs = _get_collection('configs')
    docs = configs.where(filter=FieldFilter('user_id', '==', user_id)).get()
    for doc in docs:
        batch.delete(doc.reference)
    batch.commit()
    users = _get_collection('users')
    users.document(user_id).delete()
    try:
        auth.delete_user(user_id)
    except Exception:
        pass
