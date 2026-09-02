import os
import glob
import yt_dlp
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

def get_base_ydl_opts(use_proxy=True):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'remote_components': ['ejs:github'],
        # Cycle mobile client emulators to bypass datacenter IP blocks
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
        }
    }

    # Optional: Set a PROXY_URL environment variable in Render (e.g., http://user:pass@proxy.com:port)
    proxy_url = os.environ.get('PROXY_URL')
    if use_proxy and proxy_url:
        opts['proxy'] = proxy_url

    # Check for locally uploaded cookies
    cookie_path = os.path.join(os.getcwd(), 'cookies.txt')
    if os.path.exists(cookie_path):
        opts['cookiefile'] = cookie_path

    # Auto-detect Deno runtime if available
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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract video metadata directly without storing files locally
            info = ydl.extract_info(url, download=False)
            formats_raw = info.get('formats', [])
            
            playable_formats = []

            for f in formats_raw:
                format_id = str(f.get('format_id', ''))
                ext = str(f.get('ext', '')).lower()
                vcodec = f.get('vcodec', 'none')
                acodec = f.get('acodec', 'none')
                direct_url = f.get('url')

                # Filter out preview storyboards, mhtml entries, and empty stream links
                if format_id.startswith('sb') or ext == 'mhtml' or not direct_url:
                    continue

                res = f.get('resolution') or (f"{f.get('height')}p" if f.get('height') else "Audio")
                fps = f.get('fps')
                fps_str = f" @ {int(fps)}fps" if fps else ""

                if vcodec != 'none' and acodec != 'none':
                    tag = "Video + Audio (Direct Stream)"
                elif vcodec != 'none':
                    tag = "Video Only"
                else:
                    tag = "Audio Only"

                label = f"{res}{fps_str} ({ext.upper()}) - {tag}"
                
                playable_formats.append({
                    'format_id': format_id,
                    'label': label,
                    'download_url': direct_url
                })

            if not playable_formats:
                return jsonify({
                    'error': "No playable streams returned.\n\n"
                             "[Action Required] Run 'python sync.py' locally to refresh cookies on Render."
                }), 400

            return jsonify({
                'title': info.get('title', 'YouTube Video'),
                'formats': playable_formats
            })

    except Exception as e:
        err_msg = str(e)
        if "The page needs to be reloaded" in err_msg or "Requested format is not available" in err_msg:
            err_msg += "\n\n[Action Required] Render's IP address is flagged by YouTube. Run sync.py from your local machine to upload fresh browser cookies to Render."
        return jsonify({'error': err_msg}), 400

@app.route('/update-cookies', methods=['POST'])
def update_cookies():
    try:
        data = request.get_json(silent=True) or {}
        cookie_text = data.get('cookies') or request.data.decode('utf-8')

        if not cookie_text or not cookie_text.strip():
            return jsonify({'error': 'No cookie content provided'}), 400

        cookie_text = cookie_text.strip()

        # Enforce valid Netscape header expected by yt-dlp
        header = "# Netscape HTTP Cookie File\n"
        if not cookie_text.startswith("# Netscape") and not cookie_text.startswith("# HTTP Cookie File"):
            cookie_text = header + cookie_text

        cookie_path = os.path.join(os.getcwd(), 'cookies.txt')
        with open(cookie_path, 'w', encoding='utf-8') as f:
            f.write(cookie_text + "\n")

        return jsonify({'status': 'success', 'message': 'Cookies updated successfully in valid Netscape format'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
