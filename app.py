import os
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

def get_base_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'remote_components': ['ejs:github'],
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'ios', 'android', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
    }
    
    cookie_file = find_cookie_file()
    if cookie_file:
        opts['cookiefile'] = cookie_file

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
        opts['js_runtimes'] = {'deno': {'path': deno_exe}}

    return opts

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

def run_download(url, format_id=None):
    global progress_data
    progress_data['status'] = 'starting'
    progress_data['progress'] = 0
    progress_data['error'] = None

    ydl_opts = get_base_ydl_opts()

    # Use explicit format or broad fallback chain
    if format_id and format_id != 'auto':
        ydl_format = f"{format_id}+bestaudio/best"
    else:
        ydl_format = 'bv*+ba/b/best'

    ydl_opts.update({
        'format': ydl_format,
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'progress_hooks': [progress_hook],
    })

    try:
        print(f"Starting download for {url} with format selection: {ydl_format}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        progress_data['status'] = 'error'
        progress_data['error'] = str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-formats', methods=['POST'])
def get_formats():
    data = request.get_json(silent=True) or {}
    url = data.get('url') or request.form.get('url')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    ydl_opts = get_base_ydl_opts()
    # Bypass format requirements during extraction to return all raw streams
    ydl_opts['format'] = 'all'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats_raw = info.get('formats', [])
            
            formats = [{'format_id': 'auto', 'label': 'Best Quality (Auto Merge)'}]

            for f in formats_raw:
                format_id = f.get('format_id')
                ext = f.get('ext', '')
                res = f.get('resolution') or (f"{f.get('height')}p" if f.get('height') else "Audio")
                vcodec = f.get('vcodec', 'none')
                acodec = f.get('acodec', 'none')
                fps = f.get('fps')
                fps_str = f" @ {int(fps)}fps" if fps else ""

                if vcodec != 'none' and acodec != 'none':
                    tag = "Video + Audio"
                elif vcodec != 'none':
                    tag = "Video Only"
                else:
                    tag = "Audio Only"

                label = f"{res}{fps_str} ({ext.upper()}) - {tag} [ID: {format_id}]"
                formats.append({'format_id': format_id, 'label': label})

            return jsonify({
                'title': info.get('title', 'YouTube Video'),
                'formats': formats
            })
    except Exception as e:
        err_msg = str(e)
        if "The page needs to be reloaded" in err_msg:
            err_msg += "\n\n[Action Required] Render's IP address is flagged by YouTube. Run sync.py from your local machine to upload fresh browser cookies to Render."
        return jsonify({'error': err_msg}), 400

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json(silent=True) or {}
    url = data.get('url') or request.form.get('url')
    format_id = data.get('format_id') or request.form.get('format_id')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    thread = threading.Thread(target=run_download, args=(url, format_id))
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
