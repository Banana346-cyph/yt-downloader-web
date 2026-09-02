import os
import requests

# --- CONFIGURATION ---
# Replace with your actual Render application URL
RENDER_APP_URL = "https://youtube-video-downloader-f42m.onrender.com/update-cookies"

# Replace with the exact secret key you set in app.py
SECRET_KEY = "youtube-downloader-346"

# Updated path based on your Chromebook search results
COOKIE_FILE = "/mnt/shared/MyFiles/Downloads/cookies.txt"

def send_cookies():
    if not os.path.exists(COOKIE_FILE):
        print(f"Error: Could not find '{COOKIE_FILE}'.")
        return

    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            cookie_data = f.read()

        headers = {'X-Update-Secret': SECRET_KEY}
        print("Sending cookies to Render...")
        response = requests.post(RENDER_APP_URL, data=cookie_data, headers=headers)
        
        if response.status_code == 200:
            print("SUCCESS! Fresh cookies pushed to your Render server.")
        else:
            print(f"Error ({response.status_code}): {response.text}")
    except Exception as e:
        print(f"Failed to send cookies: {e}")

if __name__ == '__main__':
    send_cookies()
