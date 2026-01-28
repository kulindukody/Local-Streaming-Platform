import os
from flask import Flask, render_template, send_file, abort, request, Response
import cv2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
THUMB_DIR = os.path.join(BASE_DIR, "static", "thumbnails")

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

@app.route("/folder/<path:folder>")
def folder_view(folder):
    full_path = os.path.join(VIDEO_DIR, folder)
    if not os.path.exists(full_path):
        abort(404)

    items = []
    for item in os.listdir(full_path):
        item_path = os.path.join(full_path, item)
        if os.path.isdir(item_path):
            items.append({"type": "folder", "name": item})
        elif item.lower().endswith(".mp4"):
            safe_name = f"{folder}_{item}"
            safe_name = safe_name.replace("/", "_").replace(" ", "_")

            thumb_file = safe_name + ".jpg"
            thumb_path = os.path.join(THUMB_DIR, thumb_file)

            generate_thumbnail(item_path, thumb_path)

            items.append({
                "type": "video",
                "name": item,
                "thumb": thumb_file
            })


    return render_template("folder.html", folder=folder, items=items)

@app.route("/watch/<path:video_path>")
def watch(video_path):
    folder, video_name = os.path.split(video_path)
    return render_template(
        "player.html",
        video_name=video_name,
        folder=folder,
        video_path=f"/stream/{video_path}"
    )


@app.route("/stream/<path:video_path>")
def stream(video_path):
    video = os.path.join(VIDEO_DIR, video_path)
    if not os.path.exists(video):
        abort(404)

    range_header = request.headers.get('Range', None)
    if not range_header:
        return send_file(video, mimetype="video/mp4")

    size = os.path.getsize(video)
    byte1, byte2 = 0, None

    m = range_header.replace('bytes=', '').split('-')
    byte1 = int(m[0])
    if len(m) > 1 and m[1]:
        byte2 = int(m[1])

    length = size - byte1 if byte2 is None else byte2 - byte1 + 1

    with open(video, 'rb') as f:
        f.seek(byte1)
        data = f.read(length)

    rv = Response(data, 206, mimetype='video/mp4', direct_passthrough=True)
    rv.headers.add('Content-Range', f'bytes {byte1}-{byte1 + length - 1}/{size}')
    return rv

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
