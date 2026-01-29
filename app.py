import os
from flask import Flask, render_template, send_file, abort, request, Response
import cv2
from urllib.parse import quote, unquote
import mimetypes
import json
from datetime import datetime

mimetypes.add_type('video/mp4', '.mp4')
mimetypes.add_type('video/x-matroska', '.mkv')
mimetypes.add_type('video/mp2t', '.ts')
mimetypes.add_type('video/webm', '.webm')
mimetypes.add_type('video/avi', '.avi')


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
THUMB_DIR = os.path.join(BASE_DIR, "static", "thumbnails")
BASE_CONTENT_DIR = VIDEO_DIR

app = Flask(__name__)

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

@app.route("/")
def index():
    folders = [f for f in os.listdir(VIDEO_DIR) if os.path.isdir(os.path.join(VIDEO_DIR, f))]
    return render_template("index.html", folders=folders)

from urllib.parse import unquote

@app.route("/folder/<path:folder>")
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
