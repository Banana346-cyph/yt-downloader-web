import os
import glob
import shutil
import tempfile
import threading
import traceback
from flask import Flask, render_template, request, jsonify, send_file, abort
import static_ffmpeg
import yt_dlp

# Set path to the project-installed Deno executable inside Render container
deno_path = os.path.join(os.getcwd(), 'deno', 'bin', 'deno')
deno_dir = os.path.dirname(deno_path)

if os.path.exists(deno_dir):
    os.environ['PATH'] = deno_dir + os.pathsep + os.environ.get('PATH', '')

# Register FFmpeg in PATH
static_ffmpeg.add_paths()

app = Flask(__name__)

# Security secret for updating cookies. Set COOKIE_UPDATE_SECRET in Render Environment Variables.
UPDATE_SECRET = os.environ.get('COOKIE_UPDATE_SECRET', 'youtube-downloader-346')

# Ensure download directory exists
DOWNLOAD_FOLDER = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

download_status = {}

def progress_hook(d):
    """Update progress percentage during download."""
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        percentage = (downloaded / total * 100) if total > 0 else 0

        download_status['percent'] = round(percentage, 1)
        download_status['status'] = 'downloading'
        download_status['filename'] = d.get('filename', '')
    elif d['status'] == 'finished':
        download_status['percent'] = 100

def run_download(url):
    """Executes yt-dlp in a background thread using standard web client processing."""
    global download_status
    download_status = {'status': 'downloading', 'percent': 0}

    # Priority: 1) Dynamically synced root cookies.txt, 2) Render secret file
    active_cookie_file = None
    root_cookie_path = os.path.join(os.getcwd(), 'cookies.txt')
    secret_cookie_path = '/etc/secrets/cookies.txt'

    if os.path.exists(root_cookie_path):
        active_cookie_file = root_cookie_path
    elif os.path.exists(secret_cookie_path):
        try:
            temp_cookie = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
            temp_cookie.close()
            shutil.copy(secret_cookie_path, temp_cookie.name)
            active_cookie_file = temp_cookie.name
            print(f"Copied secret cookies to writable path: {active_cookie_file}")
        except Exception as e:
            print(f"Error copying secret cookies: {e}")

    ydl_opts = {
        # Standard computer/web format selection merged via FFmpeg into MP4
        'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',

        # Speed Optimizations
        'concurrent_fragment_downloads': 8,
        'http_chunk_size': 10485760,  # 10MB chunk size
        'buffersize': 1024 * 64,       # 64KB buffer

        'progress_hooks': [progress_hook],
        'nocheckcertificate': True,
        'remote_components': ['ejs:github'],
        'js_runtimes': {
            'deno': {'path': deno_path if os.path.exists(deno_path) else 'deno'}
        }
    }

    if active_cookie_file and os.path.exists(active_cookie_file):
        print(f"Using cookies from: {active_cookie_file}")
        ydl_opts['cookiefile'] = active_cookie_file
    else:
        print("WARNING: No cookies found. Download may fail with bot detection.")

    try:
        print(f"Starting download for: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the downloaded file on disk
        files = glob.glob(os.path.join(DOWNLOAD_FOLDER, '*'))
        if files:
            latest_file = max(files, key=os.path.getctime)
            download_status['filepath'] = latest_file
            download_status['percent'] = 100
            download_status['status'] = 'completed'
            print(f"Successfully downloaded: {latest_file}")
        else:
            raise Exception("No downloaded file was found in directory.")

    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        traceback.print_exc()
        download_status['status'] = 'error'
        download_status['error'] = str(e)
    
    # Cleanup temporary secret cookie copy if used
    if active_cookie_file and active_cookie_file.startswith(tempfile.gettempdir()):
        try:
            os.remove(active_cookie_file)
        except:
            pass

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get('url') or request.form.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    thread = threading.Thread(target=run_download, args=(url,))
    thread.start()
    return jsonify({'message': 'Download started'})

@app.route('/progress')
def get_progress():
    return jsonify(download_status)

@app.route('/get-file')
def get_file():
    filepath = download_status.get('filepath')
    if filepath and os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

@app.route('/update-cookies', methods=['POST'])
def update_cookies():
    """Secure endpoint to dynamically receive fresh cookies."""
    auth_key = request.headers.get('X-Update-Secret')
    if auth_key != UPDATE_SECRET:
        abort(401, description="Unauthorized")

    cookie_data = request.data.decode('utf-8')
    if not cookie_data:
        return jsonify({'error': 'No cookie data provided'}), 400

    cookie_path = os.path.join(os.getcwd(), 'cookies.txt')
    try:
        with open(cookie_path, 'w', encoding='utf-8') as f:
            f.write(cookie_data)
        print("Successfully updated root cookies.txt via /update-cookies endpoint")
        return jsonify({'message': 'Cookies updated successfully!'})
    except Exception as e:
        print(f"Error writing cookies.txt: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
