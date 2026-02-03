import os
from flask import Flask, render_template, send_file, abort, request, Response, redirect, url_for, flash
import cv2
from urllib.parse import quote, unquote
import mimetypes
import json
from datetime import datetime
import logging
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

# Configure Logging
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
)

mimetypes.add_type('video/mp4', '.mp4')
mimetypes.add_type('video/x-matroska', '.mkv')
mimetypes.add_type('video/mp2t', '.ts')
mimetypes.add_type('video/webm', '.webm')
mimetypes.add_type('video/avi', '.avi')
mimetypes.add_type('video/quicktime', '.mov')


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
THUMB_DIR = os.path.join(BASE_DIR, "static", "thumbnails")
BASE_CONTENT_DIR = VIDEO_DIR

app = Flask(__name__)
app.secret_key = 'super-secret-key' # In a real app, use a proper secret key

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Simple user model for local use
class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# Hardcoded user for local streaming (can be expanded later)
USERS = {
    "admin": generate_password_hash("admin123")
}

os.makedirs(THUMB_DIR, exist_ok=True)

ANALYTICS_FILE = os.path.join(BASE_DIR, "analytics.json")

def load_analytics():
    if not os.path.exists(ANALYTICS_FILE):
        return {}
    with open(ANALYTICS_FILE, "r") as f:
        return json.load(f)

def save_analytics(data):
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def generate_thumbnail(video_path, thumb_path):
    if os.path.exists(thumb_path):
        return
    cap = cv2.VideoCapture(video_path)
    success, frame = cap.read()
    if success:
        cv2.imwrite(thumb_path, frame)
    cap.release()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USERS and check_password_hash(USERS[username], password):
            user = User(username)
            login_user(user)
            logging.info(f"User {username} logged in")
            return redirect(url_for("index"))
        flash("Invalid username or password")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logging.info(f"User {current_user.id} logged out")
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    folders = [f for f in os.listdir(VIDEO_DIR) if os.path.isdir(os.path.join(VIDEO_DIR, f))]
    
    # Fetch "Continue Watching" from analytics
    data = load_analytics()
    # Sort by 'last' timestamp and take top 4
    history = []
    for path, entry in data.items():
        if entry.get("last"):
            history.append({
                "path": path,
                "name": os.path.basename(path),
                "folder": os.path.dirname(path),
                "last": entry["last"],
                "views": entry["views"]
            })
    history = sorted(history, key=lambda x: x["last"], reverse=True)[:4]
    
    return render_template("index.html", folders=folders, history=history)

from urllib.parse import unquote

@app.route("/folder/<path:folder>")
@login_required
def folder_view(folder):
    # Decode URL-encoded folder names (handles #, spaces, etc.)
    folder = unquote(folder)

    full_path = os.path.join(VIDEO_DIR, folder)
    if not os.path.exists(full_path):
        abort(404)

    items = []
    for item in os.listdir(full_path):
        item_path = os.path.join(full_path, item)
        if os.path.isdir(item_path):
            # Subfolder
            items.append({"type": "folder", "name": item})
        else:
            # Determine file type
            ext = item.lower().split('.')[-1]
            if ext in ["mp4", "mov", "avi", "mkv","ts"]:
                file_type = "video"
                # Safe thumbnail name
                safe_name = f"{folder}_{item}".replace("/", "_").replace(" ", "_").replace("#", "_")
                thumb_file = safe_name + ".jpg"
                thumb_path = os.path.join(THUMB_DIR, thumb_file)
                generate_thumbnail(item_path, thumb_path)
                items.append({"type": file_type, "name": item, "thumb": thumb_file})
            elif ext in ["jpg", "jpeg", "png", "gif"]:
                file_type = "image"
                items.append({"type": file_type, "name": item, "thumb": item})
            elif ext in ["pdf", "html", "txt","zip"]:
                file_type = "document"
                items.append({"type": file_type, "name": item})
            else:
                # Ignore other unknown file types
                continue

    return render_template("folder.html", folder=folder, items=items)



from urllib.parse import quote, unquote

@app.route("/watch/<path:video_path>")
@login_required
def watch(video_path):
    folder, video_name = os.path.split(video_path)

    data = load_analytics()
    entry = data.get(video_path, {
        "views": 0,
        "last": None,
        "watch_seconds": 0
    })

    entry["views"] += 1
    entry["last"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    data[video_path] = entry
    save_analytics(data)

    return render_template(
        "player.html",
        video_name=video_name,
        folder=folder,
        video_path=f"/stream/{video_path}"
    )

@app.route("/analytics/progress", methods=["POST"])
@login_required
def analytics_progress():
    payload = request.json
    video = payload["video"]
    seconds = int(payload["seconds"])

    data = load_analytics()
    if video in data:
        data[video]["watch_seconds"] += seconds
        save_analytics(data)

    return {"ok": True}



@app.route("/stream/<path:video_path>")
@login_required
def stream(video_path):
    video_path = unquote(video_path)
    video = os.path.join(VIDEO_DIR, video_path)

    if not os.path.exists(video):
        abort(404)

    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(video)
    mime_type = mime_type or "application/octet-stream"

    range_header = request.headers.get('Range', None)

    # No Range header → normal send
    if not range_header:
        return send_file(
            video,
            mimetype=mime_type,
            conditional=True
        )

    size = os.path.getsize(video)
    byte1, byte2 = 0, None

    # Parse Range header
    try:
        range_value = range_header.replace('bytes=', '')
        m = range_value.split('-')
        byte1 = int(m[0])
        if len(m) > 1 and m[1]:
            byte2 = int(m[1])
    except Exception:
        byte1 = 0
        byte2 = None

    if byte2 is None or byte2 >= size:
        byte2 = size - 1

    length = byte2 - byte1 + 1

    with open(video, 'rb') as f:
        f.seek(byte1)
        data = f.read(length)

    rv = Response(
        data,
        206,
        mimetype=mime_type,
        direct_passthrough=True
    )

    rv.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{size}')
    rv.headers.add('Accept-Ranges', 'bytes')
    rv.headers.add('Content-Length', str(length))

    return rv

@app.route("/open/<path:relative_path>")
@login_required
def open_file(relative_path):
    full_path = os.path.normpath(
        os.path.join(BASE_CONTENT_DIR, relative_path)
    )

    # Prevent path traversal
    if not full_path.startswith(os.path.abspath(BASE_CONTENT_DIR)):
        abort(403)

    if not os.path.isfile(full_path):
        print("[OPEN 404]", full_path)  # DEBUG LINE
        abort(404)

    mime, _ = mimetypes.guess_type(full_path)

    return send_file(
        full_path,
        mimetype=mime,
        as_attachment=False
    )

@app.route("/analytics")
@login_required
def analytics():
    data = load_analytics()

    total_views = sum(v["views"] for v in data.values())
    total_watch_minutes = sum(v["watch_seconds"] for v in data.values()) // 60

    total_videos = 0
    total_folders = 0

    for root, dirs, files in os.walk(VIDEO_DIR):
        total_folders += len(dirs)
        total_videos += len([f for f in files if f.endswith(".mp4")])

    top_videos = sorted(
        [{"name": k, **v} for k, v in data.items()],
        key=lambda x: x["views"],
        reverse=True
    )[:10]

    return render_template(
        "analytics.html",
        total_views=total_views,
        total_watch_minutes=total_watch_minutes,
        total_videos=total_videos,
        total_folders=total_folders,
        top_videos=top_videos
    )

# File Management Routes
@app.route("/actions/rename", methods=["POST"])
@login_required
def rename_file():
    data = request.json
    relative_old_path = unquote(data["old_path"])
    old_path = os.path.join(VIDEO_DIR, relative_old_path)
    new_name = data["new_name"]
    directory = os.path.dirname(old_path)
    new_path = os.path.join(directory, new_name)

    if not os.path.normpath(new_path).startswith(os.path.normpath(VIDEO_DIR)):
        return {"ok": False, "error": "Access denied"}, 403

    try:
        os.rename(old_path, new_path)
        logging.info(f"File renamed from {old_path} to {new_path} by {current_user.id}")
        return {"ok": True}
    except Exception as e:
        logging.error(f"Error renaming file: {e}")
        return {"ok": False, "error": str(e)}, 500

@app.route("/actions/delete", methods=["POST"])
@login_required
def delete_file():
    data = request.json
    relative_path = unquote(data["path"])
    file_path = os.path.normpath(os.path.join(VIDEO_DIR, relative_path))

    if not file_path.startswith(os.path.normpath(VIDEO_DIR)):
        return {"ok": False, "error": "Access denied"}, 403

    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
            logging.info(f"File deleted: {file_path} by {current_user.id}")
        elif os.path.isdir(file_path):
            import shutil
            shutil.rmtree(file_path)
            logging.info(f"Directory deleted: {file_path} by {current_user.id}")
        return {"ok": True}
    except Exception as e:
        logging.error(f"Error deleting file/dir: {e}")
        return {"ok": False, "error": str(e)}, 500

@app.route("/logs")
@login_required
def view_logs():
    if not os.path.exists("app.log"):
        return render_template("logs.html", logs=["No logs found."])
    with open("app.log", "r") as f:
        lines = f.readlines()[-100:]
    return render_template("logs.html", logs=lines)

@app.route("/api/logs")
@login_required
def get_logs_json():
    if not os.path.exists("app.log"):
        return {"logs": []}
    with open("app.log", "r") as f:
        lines = f.readlines()[-100:]
    return {"logs": lines}

@app.route("/api/search")
@login_required
def search():
    query = request.args.get("q", "").lower()
    results = []
    for root, dirs, files in os.walk(VIDEO_DIR):
        for name in dirs + files:
            if query in name.lower():
                rel_path = os.path.relpath(os.path.join(root, name), VIDEO_DIR)
                # Check for video extensions
                ext = name.split(".")[-1].lower() if "." in name else ""
                is_video = ext in ["mp4", "mkv", "webm", "avi", "ts", "mov"]
                is_dir = os.path.isdir(os.path.join(root, name))
                
                if is_video or is_dir:
                    results.append({
                        "name": name,
                        "path": rel_path.replace("\\", "/"),
                        "type": "video" if is_video else "folder"
                    })
    return {"results": results[:10]}

@app.route("/download/<path:file_path>")
@login_required
def download_file(file_path):
    file_path = unquote(file_path)
    full_path = os.path.normpath(os.path.join(VIDEO_DIR, file_path))
    
    if not full_path.startswith(os.path.normpath(VIDEO_DIR)) or not os.path.isfile(full_path):
        abort(403)
        
    logging.info(f"File downloaded: {full_path} by {current_user.id}")
    return send_file(full_path, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
