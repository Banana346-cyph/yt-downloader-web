kimport os
import sys
import glob
import threading
from flask import Flask, render_template, request, jsonify

# Prepend Deno paths to system PATH so yt-dlp auto-detects the JavaScript runtime
deno_dirs = [
    os.path.join(os.getcwd(), 'deno', 'bin'),
    os.path.expanduser('~/.deno/bin'),
    '/opt/render/.deno/bin'
]
for d in deno_dirs:
    if os.path.exists(d) and d not in os.environ.get('PATH', ''):
        os.environ['PATH'] = f"{d}:{os.environ.get('PATH', '')}"

import static_ffmpeg
static_ffmpeg.add_paths()

import yt_dlp

app = Flask(__name__)

DOWNLOAD_FOLDER = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

progress_data = {
    'status': 'idle',
    'progress': 0,
    'speed': '0 KB/s',
    'eta': '0s',
    'filename': '',
    'error': None
}

def find_cookie_file():
    root_cookies = os.path.join(os.getcwd(), 'cookies.txt')
    if os.path.exists(root_cookies):
        return root_cookies
    
    txt_files = glob.glob(os.path.join(os.getcwd(), '*.txt'))
    if txt_files:
        return txt_files[0]
    
    return None

def progress_hook(d):
    global progress_data
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        pct = (downloaded / total * 100) if total > 0 else 0
        
        progress_data['status'] = 'downloading'
        progress_data['progress'] = round(pct, 1)
        progress_data['speed'] = d.get('_speed_str', 'N/A').strip()
        progress_data['eta'] = d.get('_eta_str', 'N/A').strip()
        progress_data['filename'] = os.path.basename(d.get('filename', ''))
    elif d['status'] == 'finished':
        progress_data['status'] = 'finished'
        progress_data['progress'] = 100.0

def run_download(url):
    global progress_data
    progress_data['status'] = 'starting'
    progress_data['progress'] = 0
    progress_data['error'] = None

    cookie_file = find_cookie_file()
    if cookie_file:
        print(f"Using cookies from: {cookie_file}")

    ydl_opts = {
        # Catch-all format selector: accepts best video+audio, best single file, or any available stream
        'format': 'bv*+ba/b/best',
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'progress_hooks': [progress_hook],
        'quiet': True,
        'no_warnings': False,
        'remote_components': ['ejs:github'],
    }

    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    deno_exe = None
    for candidate in [
        os.path.join(os.getcwd(), 'deno', 'bin', 'deno'),
        os.path.expanduser('~/.deno/bin/deno'),
        '/opt/render/.deno/bin/deno'
    ]:
        if os.path.isfile(candidate):
            deno_exe = candidate
            break

    if deno_exe:
        ydl_opts['js_runtimes'] = {'deno': {'path': deno_exe}}

    try:
        print(f"Starting download for: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        progress_data['status'] = 'error'
        progress_data['error'] = str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json(silent=True) or {}
    url = data.get('url') or request.form.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    thread = threading.Thread(target=run_download, args=(url,))
    thread.start()
    return jsonify({'status': 'started'})

@app.route('/progress')
def progress():
    return jsonify(progress_data)

@app.route('/update-cookies', methods=['POST'])
def update_cookies():
    try:
        data = request.get_json(silent=True) or {}
        cookie_text = data.get('cookies') or request.data.decode('utf-8')
        
        if not cookie_text:
            return jsonify({'error': 'No cookie content provided'}), 400

        cookie_path = os.path.join(os.getcwd(), 'cookies.txt')
        with open(cookie_path, 'w', encoding='utf-8') as f:
            f.write(cookie_text)

        return jsonify({'status': 'success', 'message': 'Cookies updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
