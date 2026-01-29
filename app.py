import os
from flask import Flask, render_template, send_file, abort, request, Response
import cv2
from urllib.parse import quote, unquote
import mimetypes



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
THUMB_DIR = os.path.join(BASE_DIR, "static", "thumbnails")
BASE_CONTENT_DIR = VIDEO_DIR

app = Flask(__name__)

os.makedirs(THUMB_DIR, exist_ok=True)

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
    # Decode URL-encoded path
    video_path = unquote(video_path)

    # Split folder and file name
    folder, video_name = os.path.split(video_path)

    # Encode video_path for streaming link
    encoded_video_path = quote(video_path)

    return render_template(
        "player.html",
        video_name=video_name,
        folder=folder,
        video_path=f"/stream/{encoded_video_path}"
    )



@app.route("/stream/<path:video_path>")
def stream(video_path):
    # Decode URL-encoded path
    video_path = unquote(video_path)

    video = os.path.join(VIDEO_DIR, video_path)
    if not os.path.exists(video):
        abort(404)

    range_header = request.headers.get('Range', None)
    if not range_header:
        return send_file(video, mimetype="video/mp4")

    size = os.path.getsize(video)
    byte1, byte2 = 0, None

    # Parse Range header
    try:
        m = range_header.replace('bytes=', '').split('-')
        byte1 = int(m[0])
        if len(m) > 1 and m[1]:
            byte2 = int(m[1])
    except ValueError:
        byte1 = 0
        byte2 = None

    length = size - byte1 if byte2 is None else byte2 - byte1 + 1

    with open(video, 'rb') as f:
        f.seek(byte1)
        data = f.read(length)

    rv = Response(data, 206, mimetype='video/mp4', direct_passthrough=True)
    rv.headers.add('Content-Range', f'bytes {byte1}-{byte1 + length - 1}/{size}')
    rv.headers.add('Accept-Ranges', 'bytes')
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
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
