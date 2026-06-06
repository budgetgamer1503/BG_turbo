import os
import sys
import time
import zlib
import shutil
import sqlite3
import tempfile
import zipfile
import threading
import subprocess
import socket
import http.client
import hashlib
import urllib.request
import urllib.error
from datetime import datetime
from urllib.parse import urlparse, unquote

# Try to import Tkinter modules for GUI
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

# ==============================================================================
# CONFIGURATION & COLOR SCHEME (Bespoke Gamer Dashboard Theme)
# ==============================================================================
SIDEBAR_BG = "#070a13"    # Ultra Dark Navy
BG_COLOR = "#0c101f"      # Deep Navy
CARD_COLOR = "#151b2d"    # Dark Slate
ACCENT_COLOR = "#6366f1"  # Electric Indigo
ACCENT_HOVER = "#4f46e5"  # Dark Indigo
TEXT_COLOR = "#f8fafc"    # Ice White
TEXT_MUTED = "#64748b"    # Slate Muted Gray
SUCCESS_COLOR = "#10b981" # Emerald Green
SUCCESS_HOVER = "#059669" # Dark Emerald
ERROR_COLOR = "#f43f5e"   # Crimson Red
ERROR_HOVER = "#e11d48"   # Dark Crimson
WARNING_COLOR = "#fbbf24" # Golden Warning Yellow

# List of common file hosters that restrict parallel downloads for free accounts
LIMITED_HOSTERS = [
    'vikingfile.com', 'rapidgator.net', 'keep2share.cc', 'mediafire.com',
    'mega.nz', 'uploadhaven.com', 'turbobit.net', 'filefactory.com',
    'uploaded.net', 'uploaded.to', 'nitroflare.com', 'gofile.io',
    '1fichier.com', 'uptobox.com', 'sendspace.com', 'zippyshare.com',
    'mega.co.nz', 'gamedrive.org', 'er-gamedrive.org'
]

# ==============================================================================
# UTILITY HELPER FUNCTIONS
# ==============================================================================
def format_size(bytes_size):
    """Formats bytes size into human-readable format."""
    if bytes_size is None or bytes_size < 0:
        return "Unknown size"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def format_time(seconds):
    """Formats seconds into human-readable duration (MM:SS or HH:MM:SS)."""
    if seconds is None or seconds == float('inf') or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def format_chrome_time(webkit_time):
    """Converts Chrome WebKit timestamp to readable string."""
    try:
        if webkit_time == 0 or webkit_time is None:
            return "Unknown"
        sec = (webkit_time / 1000000) - 11644473600
        return datetime.fromtimestamp(sec).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return "Unknown"

def open_file_in_explorer(file_path):
    """Opens Windows Explorer and highlights the file."""
    try:
        norm_path = os.path.normpath(file_path)
        subprocess.run(['explorer', '/select,', norm_path], check=False)
    except Exception:
        pass

def bind_hover_effect(widget, hover_bg, normal_bg):
    """Adds hover color changes to buttons."""
    widget.bind("<Enter>", lambda e: widget.configure(bg=hover_bg))
    widget.bind("<Leave>", lambda e: widget.configure(bg=normal_bg))

def check_hoster_limits(url):
    """Checks if the URL host matches a known throttled file hoster."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not host:
            # Try parsing path if netloc is empty (e.g. relative strings)
            host = parsed.path.split('/')[0].lower()
            
        for hoster in LIMITED_HOSTERS:
            if hoster in host:
                return True, hoster
    except Exception:
        pass
    return False, ""

# ==============================================================================
# DOWNLOAD MOTOR
# ==============================================================================
def check_range_support(url, timeout=10):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Range': 'bytes=0-0'
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 206
    except Exception:
        return False

def download_segment_thread(url, part_path, start, end, results, index, stop_event, max_retries=100, timeout=15, state_obj=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    retry_count = 0
    backoff = 2
    
    while not stop_event.is_set():
        try:
            downloaded = 0
            if os.path.exists(part_path):
                downloaded = os.path.getsize(part_path)
                
            current_start = start + downloaded
            if current_start > end:
                results[index] = True
                return
                
            active_headers = headers.copy()
            active_headers['Range'] = f'bytes={current_start}-{end}'
            
            req = urllib.request.Request(url, headers=active_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status != 206:
                    raise ValueError("Server did not respond with 206 Partial Content")
                    
                with open(part_path, 'ab' if downloaded > 0 else 'wb') as f:
                    chunk_size = 32768
                    last_chunk_time = time.time()
                    while not stop_event.is_set():
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        
                        # Speed throttling logic
                        if state_obj and getattr(state_obj, 'speed_limit', None):
                            limit = state_obj.speed_limit
                            active_conn = getattr(state_obj, 'active_connections', 1) or 1
                            speed_limit_per_thread = limit / active_conn
                            elapsed = time.time() - last_chunk_time
                            expected_time = len(chunk) / speed_limit_per_thread
                            if elapsed < expected_time:
                                time.sleep(expected_time - elapsed)
                            last_chunk_time = time.time()
                        
            if not stop_event.is_set():
                results[index] = True
                return
                
        except Exception:
            if stop_event.is_set():
                results[index] = False
                return
                
            retry_count += 1
            if retry_count > max_retries:
                results[index] = False
                return
                
            time.sleep(backoff)
            backoff = min(backoff * 2, 10)
            
    results[index] = False

class DownloadProgressState:
    def __init__(self):
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed = 0
        self.status = "Initializing..."
        self.active_connections = 0
        self.is_completed = False
        self.is_failed = False
        self.is_paused = False
        self.error_message = ""
        self.speed_limit = None
        self.segments = []


def download_core(url, temp_path, target_path, total_size=None, num_connections=32, max_retries=100, timeout=15, state_obj=None):
    if state_obj is None:
        state_obj = DownloadProgressState()
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # Auto check hoster limitations
    is_limited, hoster_name = check_hoster_limits(url)
    if is_limited:
        state_obj.status = f"Limiting connections due to {hoster_name} guidelines..."
        num_connections = 1
        
    state_obj.status = "Checking server capability..."
    accepts_ranges = check_range_support(url, timeout=timeout)
    
    if total_size is None or total_size <= 0:
        try:
            req = urllib.request.Request(url, headers=headers, method='HEAD')
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content_length = response.headers.get('Content-Length')
                if content_length:
                    total_size = int(content_length)
        except Exception:
            pass
            
    state_obj.total_bytes = total_size or 0

    if accepts_ranges and total_size and total_size > 0 and num_connections > 1:
        state_obj.status = "Segmenting file (Boost Mode)..."
        actual_connections = min(num_connections, max(1, total_size // (1024 * 1024)))
        state_obj.active_connections = actual_connections
        
        segment_size = total_size // actual_connections
        segments = []
        for i in range(actual_connections):
            start = i * segment_size
            end = (i + 1) * segment_size - 1 if i < actual_connections - 1 else total_size - 1
            segments.append((start, end))
            
        state_obj.segments = segments
            
        if temp_path and os.path.exists(temp_path) and not os.path.exists(f"{target_path}.part0"):
            try:
                shutil.move(temp_path, f"{target_path}.part0")
                part0_size = os.path.getsize(f"{target_path}.part0")
                segment0_end = segments[0][1]
                if part0_size > segment0_end + 1:
                    with open(f"{target_path}.part0", "r+b") as f:
                        f.truncate(segment0_end + 1)
            except Exception:
                pass
                
        threads = []
        results = [None] * actual_connections
        stop_event = threading.Event()
        
        for i in range(actual_connections):
            part_path = f"{target_path}.part{i}"
            start, end = segments[i]
            t = threading.Thread(
                target=download_segment_thread,
                args=(url, part_path, start, end, results, i, stop_event, max_retries, timeout, state_obj),
                daemon=True
            )
            threads.append(t)
            t.start()
            
        start_time = time.time()
        last_bytes = 0
        last_time = start_time
        state_obj.status = "Downloading (Turbo Mode)..."
        
        try:
            while any(t.is_alive() for t in threads):
                if state_obj.is_paused:
                    stop_event.set()
                    break
                    
                downloaded = 0
                active_count = 0
                for i in range(actual_connections):
                    part_path = f"{target_path}.part{i}"
                    if os.path.exists(part_path):
                        downloaded += os.path.getsize(part_path)
                    if threads[i].is_alive():
                        active_count += 1
                        
                state_obj.downloaded_bytes = downloaded
                state_obj.active_connections = active_count
                
                now = time.time()
                elapsed = now - last_time
                if elapsed >= 0.5:
                    state_obj.speed = (downloaded - last_bytes) / elapsed
                    last_bytes = downloaded
                    last_time = now
                    
                time.sleep(0.1)
                
            stop_event.set()
            for t in threads:
                t.join(timeout=1.0)
                
            if state_obj.is_paused:
                state_obj.status = "Paused"
                return
                
            downloaded = 0
            for i in range(actual_connections):
                part_path = f"{target_path}.part{i}"
                if os.path.exists(part_path):
                    downloaded += os.path.getsize(part_path)
                    
            if downloaded >= total_size and all(results):
                state_obj.downloaded_bytes = total_size
                state_obj.status = "Merging segments..."
                
                try:
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    with open(target_path, 'wb') as outfile:
                        for i in range(actual_connections):
                            part_path = f"{target_path}.part{i}"
                            with open(part_path, 'rb') as infile:
                                shutil.copyfileobj(infile, outfile)
                            os.remove(part_path)
                    
                    state_obj.status = "Completed"
                    state_obj.is_completed = True
                    return target_path
                except Exception as e:
                    state_obj.status = "Merge failed"
                    state_obj.is_failed = True
                    state_obj.error_message = f"Merge failed: {e}"
                    return None
            else:
                state_obj.status = "Failed / Incomplete"
                state_obj.is_failed = True
                state_obj.error_message = "Some segments could not be downloaded."
                return None
                
        except Exception as e:
            stop_event.set()
            state_obj.status = "Unexpected failure"
            state_obj.is_failed = True
            state_obj.error_message = str(e)
            return None
    else:
        # Standard Single-Threaded Fallback (1 Connection)
        state_obj.status = "Downloading (Single Connection)..."
        state_obj.active_connections = 1
        
        downloaded_bytes = 0
        if os.path.exists(temp_path):
            downloaded_bytes = os.path.getsize(temp_path)
            if total_size and downloaded_bytes >= total_size:
                try:
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    os.rename(temp_path, target_path)
                    state_obj.status = "Completed"
                    state_obj.is_completed = True
                    return target_path
                except Exception as e:
                    state_obj.status = "Error completing file"
                    state_obj.is_failed = True
                    state_obj.error_message = str(e)
                    return temp_path
                    
        retry_count = 0
        backoff = 2
        start_time = time.time()
        last_bytes = downloaded_bytes
        last_time = start_time
        
        while True:
            if state_obj.is_paused:
                state_obj.status = "Paused"
                return None
                
            try:
                active_headers = headers.copy()
                if downloaded_bytes > 0:
                    active_headers['Range'] = f'bytes={downloaded_bytes}-'
                    
                req = urllib.request.Request(url, headers=active_headers)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    if total_size is None or total_size <= 0:
                        content_length = response.headers.get('Content-Length')
                        if content_length:
                            remaining = int(content_length)
                            if response.status == 206:
                                total_size = remaining + downloaded_bytes
                            else:
                                total_size = remaining
                            state_obj.total_bytes = total_size
                    
                    file_mode = 'ab' if response.status == 206 else 'wb'
                    if response.status != 206 and downloaded_bytes > 0:
                        downloaded_bytes = 0
                        
                    retry_count = 0
                    backoff = 2
                    
                    with open(temp_path, file_mode) as f:
                        chunk_size = 32768
                        last_chunk_time = time.time()
                        while True:
                            if state_obj.is_paused:
                                break
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            state_obj.downloaded_bytes = downloaded_bytes
                            
                            # Speed throttling logic
                            if state_obj and getattr(state_obj, 'speed_limit', None):
                                limit = state_obj.speed_limit
                                elapsed = time.time() - last_chunk_time
                                expected_time = len(chunk) / limit
                                if elapsed < expected_time:
                                    time.sleep(expected_time - elapsed)
                                last_chunk_time = time.time()
                            
                            now = time.time()
                            elapsed = now - last_time
                            if elapsed >= 0.5:
                                state_obj.speed = (downloaded_bytes - last_bytes) / elapsed
                                last_bytes = downloaded_bytes
                                last_time = now
                                
                    if state_obj.is_paused:
                        break
                        
                if state_obj.is_paused:
                    state_obj.status = "Paused"
                    return None
                    
                try:
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    os.rename(temp_path, target_path)
                    state_obj.status = "Completed"
                    state_obj.is_completed = True
                    return target_path
                except Exception as e:
                    state_obj.status = "Move failed"
                    state_obj.is_failed = True
                    state_obj.error_message = str(e)
                    return temp_path
                    
            except (urllib.error.URLError, socket.timeout, socket.error, ConnectionError, http.client.IncompleteRead) as e:
                retry_count += 1
                if retry_count > max_retries:
                    state_obj.status = "Connection failed"
                    state_obj.is_failed = True
                    state_obj.error_message = f"Connection error: {e}"
                    return None
                    
                state_obj.status = "Connection dropped, retrying..."
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                last_bytes = downloaded_bytes
                last_time = time.time()
                
            except Exception as e:
                state_obj.status = "Unexpected error"
                state_obj.is_failed = True
                state_obj.error_message = str(e)
                return None

# ==============================================================================
# CHROME SQLITE DATABASE QUERY ENGINE (WAL-Safe via Backup API)
# ==============================================================================
def find_chrome_history_files():
    paths_to_check = {
        'Google Chrome': os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data'),
        'Microsoft Edge': os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\User Data'),
        'Brave Browser': os.path.expandvars(r'%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data'),
        'Opera Stable': os.path.expandvars(r'%APPDATA%\Opera Software\Opera Stable'),
        'Opera GX': os.path.expandvars(r'%APPDATA%\Opera Software\Opera GX Stable'),
        'Vivaldi': os.path.expandvars(r'%LOCALAPPDATA%\Vivaldi\User Data')
    }
    
    history_paths = []
    for browser_name, base_dir in paths_to_check.items():
        if not os.path.isdir(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            if 'History' in files:
                p = os.path.join(root, 'History')
                parts = p.split(os.sep)
                if any(part in ['Default'] or part.startswith('Profile ') for part in parts) or 'Opera' in browser_name:
                    history_paths.append((browser_name, p))
    return history_paths

def get_recent_downloads(history_paths, limit=15):
    downloads = []
    seen_ids = set()
    
    for browser_name, path in history_paths:
        temp_dir = tempfile.gettempdir()
        temp_db_path = os.path.join(temp_dir, f"browser_history_temp_{os.path.basename(os.path.dirname(path))}_{browser_name.replace(' ', '_')}.db")
        
        for suffix in ['', '-wal', '-shm']:
            p = temp_db_path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
                
        try:
            source_conn = sqlite3.connect(f"file:{path}?mode=ro&nolock=1", uri=True)
            dest_conn = sqlite3.connect(temp_db_path)
            try:
                source_conn.backup(dest_conn)
            finally:
                source_conn.close()
                
            cursor = dest_conn.cursor()
            query = """
            SELECT d.id, d.current_path, d.target_path, d.state, d.total_bytes, d.received_bytes, u.url, d.start_time
            FROM downloads d
            JOIN downloads_url_chains u ON d.id = u.id
            WHERE u.chain_index = (SELECT MAX(chain_index) FROM downloads_url_chains WHERE id = d.id)
            ORDER BY d.start_time DESC
            LIMIT ?
            """
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            
            for r in rows:
                dl_id, current_path, target_path, state, total_bytes, received_bytes, url, start_time = r
                unique_key = (target_path, url)
                if unique_key not in seen_ids:
                    seen_ids.add(unique_key)
                    downloads.append({
                        'browser': browser_name,
                        'id': dl_id,
                        'current_path': current_path,
                        'target_path': target_path,
                        'state': state,
                        'total_bytes': total_bytes,
                        'received_bytes': received_bytes,
                        'url': url,
                        'start_time': start_time
                    })
            dest_conn.close()
        except Exception:
            pass
        finally:
            for suffix in ['', '-wal', '-shm']:
                p = temp_db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                        
    downloads.sort(key=lambda x: x['start_time'], reverse=True)
    return downloads[:limit]

def get_state_string(state_code):
    """Translates Chrome download state integer to status string."""
    if state_code == 0:
        return "In Progress / Paused"
    elif state_code == 1:
        return "Completed"
    elif state_code == 2:
        return "Cancelled"
    elif state_code == 3:
        return "Interrupted / Failed"
    return "Unknown"

# ==============================================================================
# ARCHIVE REPAIRER MODULE (ZIP Carving & UnRAR Fallback Extraction)
# ==============================================================================
def carve_zip_file(corrupted_path, output_path, log_callback):
    log_callback("Opening corrupted ZIP file...")
    try:
        with open(corrupted_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        log_callback(f"ERROR: Cannot read file: {e}")
        return False, f"Cannot read file: {e}"

    log_callback(f"File loaded: {len(data)} bytes. Scanning for local file headers...")
    
    local_headers = []
    offset = 0
    total_found = 0
    
    while True:
        pos = data.find(b'PK\x03\x04', offset)
        if pos == -1:
            break
            
        try:
            if pos + 30 > len(data):
                break
                
            comp_method = int.from_bytes(data[pos+8:pos+10], 'little')
            comp_size = int.from_bytes(data[pos+18:pos+22], 'little')
            uncomp_size = int.from_bytes(data[pos+22:pos+26], 'little')
            name_len = int.from_bytes(data[pos+26:pos+28], 'little')
            extra_len = int.from_bytes(data[pos+28:pos+30], 'little')
            
            if pos + 30 + name_len + comp_size > len(data):
                log_callback(f"⚠️ Truncated file header found at byte {pos}. Skipping...")
                offset = pos + 4
                continue
                
            name = data[pos+30:pos+30+name_len].decode('utf-8', errors='ignore')
            total_found += 1
            
            local_headers.append({
                'pos': pos,
                'comp_method': comp_method,
                'comp_size': comp_size,
                'uncomp_size': uncomp_size,
                'name_len': name_len,
                'extra_len': extra_len,
                'name': name
            })
            
            log_callback(f"🔍 Found entry: {name} ({format_size(uncomp_size)})")
            offset = pos + 30 + name_len + extra_len + comp_size
        except Exception as e:
            log_callback(f"⚠️ Header parsing error at byte {pos}: {e}")
            offset = pos + 4
            
    log_callback(f"\nScan complete. Found {total_found} file headers.")
    
    if not local_headers:
        return False, "No valid ZIP entries could be carved from the file."
        
    log_callback("\nRebuilding ZIP structure and extracting intact files...")
    success_count = 0
    fail_count = 0
    
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as clean_zip:
            for entry in local_headers:
                try:
                    start_data = entry['pos'] + 30 + entry['name_len'] + entry['extra_len']
                    end_data = start_data + entry['comp_size']
                    raw_data = data[start_data:end_data]
                    
                    if entry['comp_method'] == 8:
                        decompressed = zlib.decompress(raw_data, -15)
                        clean_zip.writestr(entry['name'], decompressed)
                        success_count += 1
                        log_callback(f"✔️ Salvaged and compressed: {entry['name']}")
                    elif entry['comp_method'] == 0:
                        clean_zip.writestr(entry['name'], raw_data)
                        success_count += 1
                        log_callback(f"✔️ Salvaged (Stored): {entry['name']}")
                    else:
                        fail_count += 1
                        log_callback(f"❌ Unsupported compression method for: {entry['name']}")
                except Exception as e:
                    fail_count += 1
                    log_callback(f"❌ Failed to salvage {entry['name']}: {e}")
    except Exception as e:
        log_callback(f"ERROR: Rebuild failed: {e}")
        return False, f"Rebuild failed: {e}"
        
    summary = f"Successfully recovered {success_count} files (Failed/Corrupted: {fail_count})."
    log_callback(f"\n🎉 {summary}")
    return True, summary

def extract_rar_keep_broken(corrupted_path, output_dir, log_callback):
    """Extracts files from a corrupted RAR archive using the -kb switch."""
    log_callback("Checking for WinRAR/UnRAR utilities...")
    winrar_paths = [
        r"C:\Program Files\WinRAR\WinRAR.exe",
        r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe"
    ]
    winrar_exe = None
    for p in winrar_paths:
        if os.path.exists(p):
            winrar_exe = p
            break
            
    if not winrar_exe:
        return False, "WinRAR/UnRAR executable not found."
        
    try:
        os.makedirs(output_dir, exist_ok=True)
        cmd = [winrar_exe, "x", "-kb", "-y", corrupted_path, output_dir]
        log_callback(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        extracted_files = []
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                extracted_files.append(os.path.join(root, file))
                
        if extracted_files:
            log_callback(f"Successfully extracted {len(extracted_files)} files (broken files were salvaged!).")
            return True, output_dir
        else:
            return False, "Could not extract any files. The archive may be completely corrupt."
    except Exception as e:
        return False, str(e)

def repair_rar_file(corrupted_path, log_callback):
    """Tries standard WinRAR repair, falling back to force extraction if missing recovery records."""
    log_callback("Searching for WinRAR on your system...")
    
    winrar_paths = [
        r"C:\Program Files\WinRAR\WinRAR.exe",
        r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
        os.path.expandvars(r"%ProgramFiles%\WinRAR\WinRAR.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\WinRAR\WinRAR.exe")
    ]
    
    winrar_exe = None
    for p in winrar_paths:
        if os.path.exists(p):
            winrar_exe = p
            break
            
    if not winrar_exe:
        log_callback("❌ ERROR: WinRAR is not installed in standard directories.")
        return False, "WinRAR not found."
        
    log_callback(f"WinRAR found: {winrar_exe}")
    log_callback("Attempting standard archive repair...")
    
    dir_name = os.path.dirname(corrupted_path)
    base_name = os.path.basename(corrupted_path)
    
    try:
        cmd = [winrar_exe, "r", corrupted_path]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        rebuilt_path = os.path.join(dir_name, "rebuilt." + base_name)
        if os.path.exists(rebuilt_path):
            log_callback(f"🎉 Success! Repaired archive created at:\n{rebuilt_path}")
            return True, rebuilt_path
        else:
            log_callback("\n[!] Standard WinRAR repair produced no output (missing recovery record).")
            log_callback("⚠️ Switching to 'Force Extraction' mode (-kb)...")
            
            folder_name = base_name.replace(".rar", "") + "_salvaged"
            output_dir = os.path.join(dir_name, folder_name)
            
            success, result_dir = extract_rar_keep_broken(corrupted_path, output_dir, log_callback)
            if success:
                return True, ("extracted", result_dir)
            else:
                return False, "Extraction failed. No files could be salvaged."
    except Exception as e:
        log_callback(f"❌ WinRAR execution failed: {e}")
        return False, str(e)

# ==============================================================================
# UNIFIED DESKTOP INTERFACE (Modern Vertical Navigation Sidebar)
# ==============================================================================
class BudgetGamerTurboSuiteV1:
    def __init__(self, root):
        self.root = root
        self.root.title("BG Turbo Downloader & Repairer v1")
        self.root.geometry("1000x680")
        self.root.minsize(900, 580)
        self.root.configure(bg=BG_COLOR)
        
        self.history_paths = find_chrome_history_files()
        self.active_state = None
        self.download_thread = None
        
        # Queue attributes
        self.queue = []
        self.queue_running = False
        self.active_queue_state = None
        self.queue_thread = None
        
        # Style Definitions
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure(".", background=BG_COLOR, foreground=TEXT_COLOR)
        self.style.configure("TFrame", background=BG_COLOR)
        self.style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground=TEXT_COLOR)
        self.style.configure("Sub.TLabel", font=("Segoe UI", 9), foreground=TEXT_MUTED)
        
        # Treeview styling
        self.style.configure("Treeview",
                             background=CARD_COLOR,
                             foreground=TEXT_COLOR,
                             fieldbackground=CARD_COLOR,
                             rowheight=35,
                             font=("Segoe UI", 10))
        self.style.map("Treeview", background=[('selected', ACCENT_COLOR)])
        self.style.configure("Treeview.Heading", background=CARD_COLOR, foreground=TEXT_COLOR, font=("Segoe UI", 10, "bold"), borderwidth=0)
        
        self.build_layout()
        
    def build_layout(self):
        # 1. SIDEBAR NAVIGATION PANEL (Left side)
        self.sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=220)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False) # Keep width fixed
        
        # Sidebar Logo
        logo_lbl = tk.Label(self.sidebar, text="⚡ BG TURBO v1", font=("Segoe UI", 16, "bold"), fg=TEXT_COLOR, bg=SIDEBAR_BG, pady=10)
        logo_lbl.pack(fill=tk.X, pady=(25, 0))
        
        author_lbl = tk.Label(self.sidebar, text="by Budgetgamer1503", font=("Segoe UI", 8, "bold"), fg=ACCENT_COLOR, bg=SIDEBAR_BG)
        author_lbl.pack(fill=tk.X, pady=(0, 25))
        
        # Sidebar Navigation Buttons
        self.nav_buttons = {}
        tabs = [
            ("chrome", "📂 Browser Resumer"),
            ("custom", "🚀 Custom Downloader"),
            ("repair", "🛠️ Archive Repairer"),
            ("guide", "📖 User Guide")
        ]
        
        for tab_id, tab_name in tabs:
            btn = tk.Button(
                self.sidebar,
                text=f"  {tab_name}",
                font=("Segoe UI", 10, "bold"),
                fg=TEXT_MUTED,
                bg=SIDEBAR_BG,
                activebackground=CARD_COLOR,
                activeforeground=TEXT_COLOR,
                bd=0,
                anchor=tk.W,
                padx=20,
                pady=12,
                cursor="hand2",
                command=lambda tid=tab_id: self.switch_tab(tid)
            )
            btn.pack(fill=tk.X, pady=2)
            self.nav_buttons[tab_id] = btn
            bind_hover_effect(btn, CARD_COLOR, SIDEBAR_BG)
            
        # 2. MAIN CONTENT FRAME (Right side)
        self.content_area = tk.Frame(self.root, bg=BG_COLOR)
        self.content_area.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Initialize Tab Frames
        self.frames = {
            "chrome": tk.Frame(self.content_area, bg=BG_COLOR),
            "custom": tk.Frame(self.content_area, bg=BG_COLOR),
            "repair": tk.Frame(self.content_area, bg=BG_COLOR),
            "guide": tk.Frame(self.content_area, bg=BG_COLOR)
        }
        
        self.build_chrome_tab()
        self.build_custom_tab()
        self.build_repair_tab()
        self.build_guide_tab()
        
        # Default Active Tab
        self.switch_tab("chrome")

    def switch_tab(self, tab_id):
        # Hide all frames
        for f in self.frames.values():
            f.pack_forget()
            
        # Reset navigation button highlights
        for tid, btn in self.nav_buttons.items():
            btn.configure(fg=TEXT_MUTED, bg=SIDEBAR_BG)
            # Rebind standard hover
            bind_hover_effect(btn, CARD_COLOR, SIDEBAR_BG)
            
        # Show selected frame
        self.frames[tab_id].pack(fill=tk.BOTH, expand=True, padx=30, pady=30)
        
        # Highlight active navigation button
        active_btn = self.nav_buttons[tab_id]
        active_btn.configure(fg=TEXT_COLOR, bg=ACCENT_COLOR)
        # Disable hover changes while active
        active_btn.unbind("<Enter>")
        active_btn.unbind("<Leave>")
        
        # Refresh Chrome Resumer list if selected
        if tab_id == "chrome":
            self.refresh_chrome_downloads()

    # ==========================================================================
    # TAB 1: BROWSER DOWNLOADS RESUMER
    # ==========================================================================
    def build_chrome_tab(self):
        frame = self.frames["chrome"]
        
        lbl_title = ttk.Label(frame, text="Browser Download History Resumer", style="Header.TLabel")
        lbl_title.pack(anchor=tk.W, pady=(0, 5))
        
        lbl_desc = ttk.Label(frame, text="Select an interrupted download from Chrome, Edge, Brave, Opera, or Vivaldi to Turbo-Resume it.", style="Sub.TLabel")
        lbl_desc.pack(anchor=tk.W, pady=(0, 20))
        
        # Scrollable Treeview Container
        tree_frame = tk.Frame(frame, bg=BG_COLOR)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        self.tree = ttk.Treeview(tree_frame, columns=("browser", "filename", "size", "status", "date"), show="headings")
        self.tree.heading("browser", text="Browser", anchor=tk.W)
        self.tree.heading("filename", text="File Name", anchor=tk.W)
        self.tree.heading("size", text="File Size", anchor=tk.W)
        self.tree.heading("status", text="Status", anchor=tk.W)
        self.tree.heading("date", text="Date Started", anchor=tk.W)
        
        self.tree.column("browser", width=120, stretch=False)
        self.tree.column("filename", width=250, stretch=True)
        self.tree.column("size", width=110, stretch=False)
        self.tree.column("status", width=120, stretch=False)
        self.tree.column("date", width=130, stretch=False)
        
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.bind("<Double-1>", lambda e: self.start_chrome_resume())
        
        # Controls Frame
        ctrl_frame = tk.Frame(frame, bg=BG_COLOR, pady=20)
        ctrl_frame.pack(fill=tk.X)
        
        # Thread count / Speed Boost setting
        thread_lbl = ttk.Label(ctrl_frame, text="Speed Boost (Parallel Connections):", font=("Segoe UI", 10, "bold"))
        thread_lbl.pack(side=tk.LEFT, padx=(0, 10))
        
        self.chrome_threads_val = tk.IntVar(value=32)
        self.chrome_threads_spin = ttk.Spinbox(ctrl_frame, from_=1, to=64, width=5, textvariable=self.chrome_threads_val, font=("Segoe UI", 10, "bold"))
        self.chrome_threads_spin.pack(side=tk.LEFT, padx=(0, 20))
        
        # Action Buttons
        self.btn_refresh = tk.Button(ctrl_frame, text="🔄 Refresh List", bg=CARD_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold"), borderwidth=0, padx=15, pady=8, cursor="hand2", command=self.refresh_chrome_downloads)
        self.btn_refresh.pack(side=tk.RIGHT, padx=5)
        bind_hover_effect(self.btn_refresh, "#27314d", CARD_COLOR)
        
        self.btn_resume = tk.Button(ctrl_frame, text="🚀 Turbo Resume Selected", bg=ACCENT_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold"), borderwidth=0, padx=20, pady=8, cursor="hand2", command=self.start_chrome_resume)
        self.btn_resume.pack(side=tk.RIGHT, padx=5)
        bind_hover_effect(self.btn_resume, ACCENT_HOVER, ACCENT_COLOR)
 
    def refresh_chrome_downloads(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.history_paths:
            return
            
        self.chrome_downloads = get_recent_downloads(self.history_paths, limit=20)
        for idx, dl in enumerate(self.chrome_downloads):
            browser = dl.get('browser', 'Chrome')
            filename = os.path.basename(dl['target_path']) or "Unknown File"
            total_size_str = format_size(dl['total_bytes']) if dl['total_bytes'] > 0 else "Unknown size"
            status = get_state_string(dl['state'])
            date_str = format_chrome_time(dl['start_time'])
            self.tree.insert("", tk.END, iid=str(idx), values=(browser, filename, total_size_str, status, date_str))

    def start_chrome_resume(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Selection Required", "Please select a failed Chrome download from the list.")
            return
            
        idx = int(selected[0])
        dl = self.chrome_downloads[idx]
        url = dl['url']
        target_path = dl['target_path']
        current_path = dl['current_path']
        total_size = dl['total_bytes']
        
        # Check if URL matches a limited hoster
        is_limited, hoster = check_hoster_limits(url)
        threads = self.chrome_threads_val.get()
        
        if is_limited and threads > 1:
            ans = messagebox.askyesno(
                "Host Throttling Detected",
                f"We detected that this download is hosted by {hoster}.\n\n"
                f"This file hoster restricts free downloads to exactly 1 connection per IP. "
                f"Downloading with {threads} connections will result in a corrupted file.\n\n"
                f"Would you like to automatically switch to 1 connection to prevent corruption?"
            )
            if ans:
                self.chrome_threads_val.set(1)
                threads = 1
                
        temp_file = current_path if current_path and os.path.exists(current_path) else target_path + ".crdownload"
        self.launch_download_panel(url, temp_file, target_path, total_size, threads)

    # ==========================================================================
    # TAB 2: CUSTOM URL DOWNLOADER (with hoster auto-detection)
    # ==========================================================================
    def build_custom_tab(self):
        frame = self.frames["custom"]
        
        lbl_title = ttk.Label(frame, text="Turbo Downloader & Queue Manager", style="Header.TLabel")
        lbl_title.pack(anchor=tk.W, pady=(0, 2))
        
        lbl_desc = ttk.Label(frame, text="Boost downloads using multi-threaded segments or add them to the sequential Queue.", style="Sub.TLabel")
        lbl_desc.pack(anchor=tk.W, pady=(0, 10))
        
        # 1. INPUT PANEL (Top card)
        card = tk.Frame(frame, bg=CARD_COLOR, bd=0, padx=20, pady=15)
        card.pack(fill=tk.X, pady=(0, 15))
        
        # Row 0: URL
        lbl_url = ttk.Label(card, text="Download URL:", font=("Segoe UI", 10, "bold"), background=CARD_COLOR)
        lbl_url.grid(row=0, column=0, sticky=tk.W, pady=2)
        
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self.on_url_modified)
        self.entry_url = tk.Entry(card, bg="#0b0f19", fg=TEXT_COLOR, insertbackground=TEXT_COLOR, font=("Segoe UI", 10), bd=1, relief="solid", textvariable=self.url_var)
        self.entry_url.grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=2, ipady=4)
        
        # Row 1: Warning (Label under URL)
        self.lbl_warning = tk.Label(card, text="", font=("Segoe UI", 8, "bold"), fg=WARNING_COLOR, bg=CARD_COLOR, anchor=tk.W)
        self.lbl_warning.grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=(0, 5))
        
        # Row 2: Save Destination
        lbl_save = ttk.Label(card, text="Save Path:", font=("Segoe UI", 10, "bold"), background=CARD_COLOR)
        lbl_save.grid(row=2, column=0, sticky=tk.W, pady=2)
        
        self.entry_save = tk.Entry(card, bg="#0b0f19", fg=TEXT_COLOR, insertbackground=TEXT_COLOR, font=("Segoe UI", 10), bd=1, relief="solid")
        self.entry_save.grid(row=2, column=1, sticky=tk.EW, pady=2, ipady=4)
        
        btn_browse = tk.Button(card, text="Browse...", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=12, cursor="hand2", command=self.browse_save_location)
        btn_browse.grid(row=2, column=2, sticky=tk.E, padx=(8, 0), pady=2, ipady=3)
        bind_hover_effect(btn_browse, "#1e293b", BG_COLOR)
        
        # Row 3: Profiles and Options
        self.options_frame = tk.Frame(card, bg=CARD_COLOR)
        self.options_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(10, 0))
        
        lbl_profile = ttk.Label(self.options_frame, text="Speed Profile:", font=("Segoe UI", 9, "bold"), background=CARD_COLOR)
        lbl_profile.pack(side=tk.LEFT, padx=(0, 8))
        
        self.profile_var = tk.StringVar(value="Turbo Mode")
        self.profile_combo = ttk.Combobox(self.options_frame, textvariable=self.profile_var, values=["Turbo Mode", "Background Mode", "Custom Limits"], width=18, state="readonly")
        self.profile_combo.pack(side=tk.LEFT, padx=(0, 15))
        self.profile_combo.bind("<<ComboboxSelected>>", self.on_profile_changed)
        
        # Connections and Throttling entries (packed dynamically in Custom Limits)
        self.lbl_cust_threads = ttk.Label(self.options_frame, text="Threads:", font=("Segoe UI", 9, "bold"), background=CARD_COLOR)
        self.custom_threads_val = tk.IntVar(value=32)
        self.custom_threads_spin = ttk.Spinbox(self.options_frame, from_=1, to=64, width=4, textvariable=self.custom_threads_val, font=("Segoe UI", 9, "bold"))
        
        self.lbl_cust_speed = ttk.Label(self.options_frame, text="Limit (KB/s):", font=("Segoe UI", 9, "bold"), background=CARD_COLOR)
        self.custom_speed_var = tk.StringVar(value="0")
        self.entry_custom_speed = tk.Entry(self.options_frame, bg="#0b0f19", fg=TEXT_COLOR, insertbackground=TEXT_COLOR, font=("Segoe UI", 9), bd=1, relief="solid", width=8, textvariable=self.custom_speed_var)
        
        # Auto extract checkbox
        self.auto_extract_var = tk.BooleanVar(value=True)
        self.chk_auto_extract = tk.Checkbutton(self.options_frame, text="Auto-Extract Archive", variable=self.auto_extract_var, bg=CARD_COLOR, fg=TEXT_COLOR, selectcolor=BG_COLOR, activebackground=CARD_COLOR, activeforeground=TEXT_COLOR, font=("Segoe UI", 9))
        self.chk_auto_extract.pack(side=tk.RIGHT, padx=5)
        
        # Row 4: Buttons
        btn_frame = tk.Frame(card, bg=CARD_COLOR)
        btn_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(12, 0))
        
        self.btn_add_queue = tk.Button(btn_frame, text="➕ Add to Queue", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=18, pady=7, cursor="hand2", command=self.add_to_queue)
        self.btn_add_queue.pack(side=tk.LEFT, padx=2)
        bind_hover_effect(self.btn_add_queue, "#1e293b", BG_COLOR)
        
        self.btn_custom_start = tk.Button(btn_frame, text="🚀 Download Now", bg=ACCENT_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=20, pady=7, cursor="hand2", command=self.start_custom_download)
        self.btn_custom_start.pack(side=tk.RIGHT, padx=2)
        bind_hover_effect(self.btn_custom_start, ACCENT_HOVER, ACCENT_COLOR)
        
        # Card Grid configuration
        card.grid_columnconfigure(0, weight=0)
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(2, weight=0)
        
        # 2. QUEUE PANEL (Bottom card)
        queue_card = tk.Frame(frame, bg=CARD_COLOR, bd=0, padx=20, pady=15)
        queue_card.pack(fill=tk.BOTH, expand=True)
        
        lbl_q_title = ttk.Label(queue_card, text="Download Queue:", font=("Segoe UI", 11, "bold"), background=CARD_COLOR)
        lbl_q_title.pack(anchor=tk.W, pady=(0, 8))
        
        # Treeview Scrollbar Frame
        tree_frame = tk.Frame(queue_card, bg=CARD_COLOR)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        q_columns = ("index", "filename", "size", "profile", "status", "speed", "progress")
        self.queue_tree = ttk.Treeview(tree_frame, columns=q_columns, show="headings", height=8)
        
        self.queue_tree.heading("index", text="#")
        self.queue_tree.heading("filename", text="Filename")
        self.queue_tree.heading("size", text="Size")
        self.queue_tree.heading("profile", text="Profile")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("speed", text="Speed")
        self.queue_tree.heading("progress", text="Progress")
        
        self.queue_tree.column("index", width=30, minwidth=30, anchor=tk.CENTER)
        self.queue_tree.column("filename", width=200, minwidth=150, anchor=tk.W)
        self.queue_tree.column("size", width=80, minwidth=80, anchor=tk.CENTER)
        self.queue_tree.column("profile", width=100, minwidth=80, anchor=tk.CENTER)
        self.queue_tree.column("status", width=90, minwidth=80, anchor=tk.CENTER)
        self.queue_tree.column("speed", width=80, minwidth=80, anchor=tk.CENTER)
        self.queue_tree.column("progress", width=180, minwidth=120, anchor=tk.W)
        
        q_vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=q_vsb.set)
        
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        q_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Queue controls
        q_ctrls = tk.Frame(queue_card, bg=CARD_COLOR, pady=10)
        q_ctrls.pack(fill=tk.X)
        
        self.btn_start_q = tk.Button(q_ctrls, text="▶️ Start Queue", bg=SUCCESS_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=15, pady=6, cursor="hand2", command=self.start_queue_processing)
        self.btn_start_q.pack(side=tk.LEFT, padx=3)
        bind_hover_effect(self.btn_start_q, SUCCESS_HOVER, SUCCESS_COLOR)
        
        self.btn_pause_q = tk.Button(q_ctrls, text="⏸️ Pause Queue", bg=ERROR_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=15, pady=6, cursor="hand2", command=self.stop_queue_processing)
        self.btn_pause_q.pack(side=tk.LEFT, padx=3)
        bind_hover_effect(self.btn_pause_q, ERROR_HOVER, ERROR_COLOR)
        
        self.btn_remove_q = tk.Button(q_ctrls, text="❌ Remove Selected", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=15, pady=6, cursor="hand2", command=self.remove_from_queue)
        self.btn_remove_q.pack(side=tk.RIGHT, padx=3)
        bind_hover_effect(self.btn_remove_q, "#1e293b", BG_COLOR)
        
        self.btn_clear_q = tk.Button(q_ctrls, text="🧹 Clear Queue", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=15, pady=6, cursor="hand2", command=self.clear_queue)
        self.btn_clear_q.pack(side=tk.RIGHT, padx=3)
        bind_hover_effect(self.btn_clear_q, "#1e293b", BG_COLOR)

    def on_profile_changed(self, event=None):
        prof = self.profile_var.get()
        if prof == "Custom Limits":
            self.lbl_cust_threads.pack(side=tk.LEFT, padx=(10, 2))
            self.custom_threads_spin.pack(side=tk.LEFT, padx=(0, 10))
            self.lbl_cust_speed.pack(side=tk.LEFT, padx=(10, 2))
            self.entry_custom_speed.pack(side=tk.LEFT, padx=(0, 10))
        else:
            self.lbl_cust_threads.pack_forget()
            self.custom_threads_spin.pack_forget()
            self.lbl_cust_speed.pack_forget()
            self.entry_custom_speed.pack_forget()

    def on_url_modified(self, *args):
        url = self.url_var.get().strip()
        is_limited, hoster = check_hoster_limits(url)
        
        if is_limited:
            self.lbl_warning.configure(text=f"⚠️ Throttling Warning: {hoster} detected! Connections restricted to 1 to prevent file corruption.")
            self.custom_threads_val.set(1)
        else:
            self.lbl_warning.configure(text="")
            if self.custom_threads_val.get() == 1:
                self.custom_threads_val.set(32)

    def browse_save_location(self):
        url = self.entry_url.get().strip()
        filename = ""
        if url:
            filename = os.path.basename(urlparse(url).path)
            filename = unquote(filename)
            
        file_path = filedialog.asksaveasfilename(
            initialfile=filename,
            title="Choose Save Location",
            defaultextension="*.*",
            filetypes=[("All Files", "*.*")]
        )
        if file_path:
            self.entry_save.delete(0, tk.END)
            self.entry_save.insert(0, os.path.normpath(file_path))

    def start_custom_download(self):
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a valid URL.")
            return
            
        target_path = self.entry_save.get().strip()
        if not target_path:
            filename = os.path.basename(urlparse(url).path) or "downloaded_file"
            filename = unquote(filename)
            downloads_dir = os.path.expanduser(r'~\Downloads')
            target_path = os.path.join(downloads_dir, filename)
            
        temp_file = target_path + ".crdownload"
        
        prof = self.profile_var.get()
        if prof == "Turbo Mode":
            threads = 32
            speed_limit = None
        elif prof == "Background Mode":
            threads = 4
            speed_limit = 500 * 1024
        else:
            threads = self.custom_threads_val.get()
            try:
                limit_kb = int(self.custom_speed_var.get().strip() or 0)
                speed_limit = limit_kb * 1024 if limit_kb > 0 else None
            except ValueError:
                speed_limit = None
        
        is_limited, hoster = check_hoster_limits(url)
        if is_limited and threads > 1:
            ans = messagebox.askyesno(
                "Verify Connection Throttling",
                f"You are attempting to download from {hoster} using {threads} parallel connections.\n\n"
                f"Free accounts on this site will block multi-connection requests, leading to installer corruption.\n\n"
                f"Force connection throttle to 1?"
            )
            if ans:
                threads = 1
                
        self.launch_download_panel(url, temp_file, target_path, None, threads, speed_limit, self.auto_extract_var.get())

    def add_to_queue(self):
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a valid URL.")
            return
            
        target_path = self.entry_save.get().strip()
        if not target_path:
            filename = os.path.basename(urlparse(url).path) or "downloaded_file"
            filename = unquote(filename)
            downloads_dir = os.path.expanduser(r'~\Downloads')
            target_path = os.path.join(downloads_dir, filename)
            
        prof = self.profile_var.get()
        if prof == "Turbo Mode":
            threads = 32
            speed_limit = None
            speed_limit_str = "Turbo"
        elif prof == "Background Mode":
            threads = 4
            speed_limit = 500 * 1024
            speed_limit_str = "Bg (500KB/s)"
        else:
            threads = self.custom_threads_val.get()
            try:
                limit_kb = int(self.custom_speed_var.get().strip() or 0)
                speed_limit = limit_kb * 1024 if limit_kb > 0 else None
                speed_limit_str = f"Custom ({limit_kb}KB/s)" if limit_kb > 0 else "Unlimited"
            except ValueError:
                speed_limit = None
                speed_limit_str = "Unlimited"
                
        is_limited, hoster = check_hoster_limits(url)
        if is_limited and threads > 1:
            threads = 1
            speed_limit_str = "Limited (1 Conn)"
            
        item = {
            'url': url,
            'target_path': target_path,
            'connections': threads,
            'speed_limit': speed_limit,
            'profile_name': speed_limit_str,
            'auto_extract': self.auto_extract_var.get(),
            'status': 'Pending',
            'downloaded': 0,
            'total': 0,
            'speed': 0,
            'progress_str': '0%',
            'speed_str': '-- B/s'
        }
        
        self.queue.append(item)
        self.refresh_queue_table()
        
        self.entry_url.delete(0, tk.END)
        self.entry_save.delete(0, tk.END)
        self.lbl_warning.configure(text="")
        
    def refresh_queue_table(self):
        for row in self.queue_tree.get_children():
            self.queue_tree.delete(row)
            
        for idx, item in enumerate(self.queue):
            filename = os.path.basename(item['target_path'])
            size_str = format_size(item['total']) if item['total'] > 0 else "Unknown"
            self.queue_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    idx + 1,
                    filename,
                    size_str,
                    item['profile_name'],
                    item['status'],
                    item['speed_str'],
                    item['progress_str']
                )
            )
            
    def remove_from_queue(self):
        selected = self.queue_tree.selection()
        if not selected:
            messagebox.showwarning("Selection Required", "Please select a queue item to remove.")
            return
            
        idx = int(selected[0])
        if self.queue_running and self.queue[idx]['status'] == 'Downloading':
            messagebox.showerror("Error", "Cannot remove an active download. Pause the queue first.")
            return
            
        self.queue.pop(idx)
        self.refresh_queue_table()
        
    def clear_queue(self):
        if self.queue_running:
            messagebox.showerror("Error", "Cannot clear queue while it is running. Pause the queue first.")
            return
            
        self.queue = []
        self.refresh_queue_table()
        
    def start_queue_processing(self):
        if self.queue_running:
            return
        if not self.queue:
            messagebox.showinfo("Queue Empty", "Please add items to the queue first.")
            return
        self.queue_running = True
        self.btn_start_q.configure(state=tk.DISABLED)
        
        self.queue_thread = threading.Thread(target=self.process_queue_loop, daemon=True)
        self.queue_thread.start()
        
    def stop_queue_processing(self):
        if not self.queue_running:
            return
        self.queue_running = False
        self.btn_start_q.configure(state=tk.NORMAL)
        if self.active_queue_state:
            self.active_queue_state.is_paused = True
            
    def process_queue_loop(self):
        while self.queue_running:
            active_item = None
            active_index = -1
            for idx, item in enumerate(self.queue):
                if item['status'] in ('Pending', 'Paused', 'Failed'):
                    active_item = item
                    active_index = idx
                    break
                    
            if not active_item:
                self.queue_running = False
                self.root.after(0, lambda: [
                    self.btn_start_q.configure(state=tk.NORMAL),
                    messagebox.showinfo("Queue Processed", "All queue items have been processed!")
                ])
                break
                
            active_item['status'] = 'Downloading'
            self.root.after(0, self.refresh_queue_table)
            
            url = active_item['url']
            target_path = active_item['target_path']
            temp_file = target_path + ".crdownload"
            connections = active_item['connections']
            speed_limit = active_item['speed_limit']
            auto_extract = active_item['auto_extract']
            
            state_obj = DownloadProgressState()
            state_obj.speed_limit = speed_limit
            self.active_queue_state = state_obj
            
            d_thread = threading.Thread(
                target=download_core,
                args=(url, temp_file, target_path, None, connections, 100, 15, state_obj),
                daemon=True
            )
            d_thread.start()
            
            while d_thread.is_alive():
                if not self.queue_running:
                    state_obj.is_paused = True
                    active_item['status'] = 'Paused'
                    break
                    
                downloaded = state_obj.downloaded_bytes
                total = state_obj.total_bytes
                speed = state_obj.speed
                
                active_item['downloaded'] = downloaded
                active_item['total'] = total
                active_item['speed'] = speed
                
                if total > 0:
                    pct = (downloaded / total) * 100
                    active_item['progress_str'] = f"{pct:.1f}% ({format_size(downloaded)}/{format_size(total)})"
                else:
                    active_item['progress_str'] = f"{format_size(downloaded)}"
                    
                active_item['speed_str'] = f"{format_size(speed)}/s" if speed > 0 else "-- B/s"
                active_item['status'] = f"Downloading"
                
                self.root.after(0, self.refresh_queue_table)
                time.sleep(0.5)
                
            if not self.queue_running:
                active_item['status'] = 'Paused'
                self.root.after(0, self.refresh_queue_table)
                break
                
            if state_obj.is_completed:
                active_item['status'] = 'Completed'
                active_item['progress_str'] = "100% (Success)"
                active_item['speed_str'] = "0 B/s"
                self.root.after(0, self.refresh_queue_table)
                
                if auto_extract:
                    active_item['status'] = 'Extracting...'
                    self.root.after(0, self.refresh_queue_table)
                    self.run_auto_extraction_for_item(target_path, active_index)
            else:
                active_item['status'] = 'Failed'
                active_item['progress_str'] = f"Failed"
                active_item['speed_str'] = "0 B/s"
                self.root.after(0, self.refresh_queue_table)
                
            time.sleep(1.0)
            
    def run_auto_extraction_for_item(self, file_path, index):
        def do_extract():
            ext = os.path.splitext(file_path)[1].lower()
            out_dir = os.path.splitext(file_path)[0]
            try:
                os.makedirs(out_dir, exist_ok=True)
                if ext == '.zip':
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(out_dir)
                    self.queue[index]['status'] = 'Extracted'
                elif ext == '.rar':
                    extract_rar_keep_broken(file_path, out_dir, self.log)
                    self.queue[index]['status'] = 'Extracted'
                else:
                    self.queue[index]['status'] = 'Completed'
            except Exception as e:
                self.queue[index]['status'] = 'Extr. Failed'
                self.log(f"Auto extraction failed for {os.path.basename(file_path)}: {e}")
            self.root.after(0, self.refresh_queue_table)
            
        threading.Thread(target=do_extract, daemon=True).start()

    # ==========================================================================
    # TAB 3: ARCHIVE REPAIRER MODULE
    # ==========================================================================
    def build_repair_tab(self):
        frame = self.frames["repair"]
        
        lbl_title = ttk.Label(frame, text="Archive Repair & Hash Integrity Suite", style="Header.TLabel")
        lbl_title.pack(anchor=tk.W, pady=(0, 2))
        
        lbl_desc = ttk.Label(frame, text="Repair damaged ZIP indexes, force-extract RAR files, and verify repack checksums.", style="Sub.TLabel")
        lbl_desc.pack(anchor=tk.W, pady=(0, 15))
        
        card = tk.Frame(frame, bg=CARD_COLOR, bd=0, padx=20, pady=15)
        card.pack(fill=tk.BOTH, expand=True)
        
        # Split into Left and Right Panes
        left_pane = tk.Frame(card, bg=CARD_COLOR)
        left_pane.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 15))
        
        right_pane = tk.Frame(card, bg=CARD_COLOR)
        right_pane.grid(row=0, column=1, sticky=tk.NSEW, padx=(15, 0))
        
        card.grid_columnconfigure(0, weight=1, uniform="group1")
        card.grid_columnconfigure(1, weight=1, uniform="group1")
        card.grid_rowconfigure(0, weight=1)
        
        # ==================== LEFT COLUMN: ARCHIVE REPAIRER ====================
        lbl_repair_title = ttk.Label(left_pane, text="🛠️ Archive Repair & Salvage", font=("Segoe UI", 12, "bold"), background=CARD_COLOR)
        lbl_repair_title.pack(anchor=tk.W, pady=(0, 10))
        
        lbl_file = ttk.Label(left_pane, text="Select Corrupted ZIP or RAR File:", font=("Segoe UI", 9, "bold"), background=CARD_COLOR)
        lbl_file.pack(anchor=tk.W, pady=(0, 4))
        
        select_frame = tk.Frame(left_pane, bg=CARD_COLOR)
        select_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.entry_repair_path = tk.Entry(select_frame, bg="#0b0f19", fg=TEXT_COLOR, insertbackground=TEXT_COLOR, font=("Segoe UI", 10), bd=1, relief="solid")
        self.entry_repair_path.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        
        btn_browse_repair = tk.Button(select_frame, text="Browse...", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=12, cursor="hand2", command=self.browse_repair_file)
        btn_browse_repair.pack(side=tk.RIGHT, padx=(8, 0), ipady=3)
        bind_hover_effect(btn_browse_repair, "#1e293b", BG_COLOR)
        
        self.btn_repair = tk.Button(left_pane, text="🔧 Run Repair Diagnostics", bg=ACCENT_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold"), borderwidth=0, padx=25, pady=8, cursor="hand2", command=self.start_repair)
        self.btn_repair.pack(fill=tk.X, pady=(0, 12))
        bind_hover_effect(self.btn_repair, ACCENT_HOVER, ACCENT_COLOR)
        
        lbl_logs = ttk.Label(left_pane, text="Process Console Log:", font=("Segoe UI", 9, "bold"), background=CARD_COLOR)
        lbl_logs.pack(anchor=tk.W, pady=(0, 4))
        
        log_frame = tk.Frame(left_pane, bg=BG_COLOR)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, bg="#070a13", fg=TEXT_COLOR, font=("Consolas", 9), bd=0, padx=10, pady=10)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        # ==================== RIGHT COLUMN: HASH INTEGRITY VERIFIER ====================
        lbl_hash_title = ttk.Label(right_pane, text="🔢 File Integrity Hash Verifier", font=("Segoe UI", 12, "bold"), background=CARD_COLOR)
        lbl_hash_title.pack(anchor=tk.W, pady=(0, 10))
        
        lbl_hash_file = ttk.Label(right_pane, text="Select File to Hash Check:", font=("Segoe UI", 9, "bold"), background=CARD_COLOR)
        lbl_hash_file.pack(anchor=tk.W, pady=(0, 4))
        
        select_hash_frame = tk.Frame(right_pane, bg=CARD_COLOR)
        select_hash_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.entry_hash_path = tk.Entry(select_hash_frame, bg="#0b0f19", fg=TEXT_COLOR, insertbackground=TEXT_COLOR, font=("Segoe UI", 10), bd=1, relief="solid")
        self.entry_hash_path.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        
        btn_browse_hash = tk.Button(select_hash_frame, text="Browse...", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=12, cursor="hand2", command=self.browse_hash_file)
        btn_browse_hash.pack(side=tk.RIGHT, padx=(8, 0), ipady=3)
        bind_hover_effect(btn_browse_hash, "#1e293b", BG_COLOR)
        
        hash_calc_frame = tk.Frame(right_pane, bg=CARD_COLOR)
        hash_calc_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.btn_calc_hash = tk.Button(hash_calc_frame, text="🔢 Calculate Hashes", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold"), borderwidth=0, padx=15, pady=6, cursor="hand2", command=self.calculate_file_hashes)
        self.btn_calc_hash.pack(side=tk.LEFT)
        bind_hover_effect(self.btn_calc_hash, "#1e293b", BG_COLOR)
        
        self.lbl_hash_status = tk.Label(hash_calc_frame, text="Status: Idle", font=("Segoe UI", 9, "italic"), fg=TEXT_MUTED, bg=CARD_COLOR)
        self.lbl_hash_status.pack(side=tk.LEFT, padx=15)
        
        # Results outputs
        results_card = tk.Frame(right_pane, bg="#0b0f19", bd=1, relief="solid", padx=12, pady=10)
        results_card.pack(fill=tk.BOTH, expand=True)
        
        # MD5
        lbl_md5 = tk.Label(results_card, text="MD5:", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg="#0b0f19")
        lbl_md5.pack(anchor=tk.W)
        self.entry_md5 = tk.Entry(results_card, bg="#0c101f", fg=TEXT_COLOR, font=("Consolas", 9), bd=0, state="readonly")
        self.entry_md5.pack(fill=tk.X, pady=(0, 6), ipady=2)
        
        # SHA-1
        lbl_sha1 = tk.Label(results_card, text="SHA-1:", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg="#0b0f19")
        lbl_sha1.pack(anchor=tk.W)
        self.entry_sha1 = tk.Entry(results_card, bg="#0c101f", fg=TEXT_COLOR, font=("Consolas", 9), bd=0, state="readonly")
        self.entry_sha1.pack(fill=tk.X, pady=(0, 6), ipady=2)
        
        # SHA-256
        lbl_sha256 = tk.Label(results_card, text="SHA-256:", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg="#0b0f19")
        lbl_sha256.pack(anchor=tk.W)
        self.entry_sha256 = tk.Entry(results_card, bg="#0c101f", fg=TEXT_COLOR, font=("Consolas", 9), bd=0, state="readonly")
        self.entry_sha256.pack(fill=tk.X, pady=(0, 12), ipady=2)
        
        # Match/Comparison
        lbl_match = tk.Label(results_card, text="Paste Checksum to Compare:", font=("Segoe UI", 9, "bold"), fg=TEXT_COLOR, bg="#0b0f19")
        lbl_match.pack(anchor=tk.W)
        
        self.match_hash_var = tk.StringVar()
        self.match_hash_var.trace_add("write", self.verify_hash_match)
        self.entry_match_hash = tk.Entry(results_card, bg="#070a13", fg=TEXT_COLOR, insertbackground=TEXT_COLOR, font=("Consolas", 10), bd=1, relief="solid", textvariable=self.match_hash_var)
        self.entry_match_hash.pack(fill=tk.X, pady=(0, 5), ipady=3)
        
        self.lbl_match_result = tk.Label(results_card, text="Waiting for calculation...", font=("Segoe UI", 9, "bold"), fg=TEXT_MUTED, bg="#0b0f19")
        self.lbl_match_result.pack(anchor=tk.W)

    def browse_repair_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Corrupted Archive",
            filetypes=[("Archive Files (*.zip, *.rar)", "*.zip;*.rar"), ("All Files", "*.*")]
        )
        if file_path:
            self.entry_repair_path.delete(0, tk.END)
            self.entry_repair_path.insert(0, os.path.normpath(file_path))
            self.log_text.delete("1.0", tk.END)

    def browse_hash_file(self):
        file_path = filedialog.askopenfilename(
            title="Select File to Hash",
            filetypes=[("All Files", "*.*")]
        )
        if file_path:
            self.entry_hash_path.delete(0, tk.END)
            self.entry_hash_path.insert(0, os.path.normpath(file_path))
            self.entry_md5.configure(state=tk.NORMAL)
            self.entry_md5.delete(0, tk.END)
            self.entry_md5.configure(state="readonly")
            self.entry_sha1.configure(state=tk.NORMAL)
            self.entry_sha1.delete(0, tk.END)
            self.entry_sha1.configure(state="readonly")
            self.entry_sha256.configure(state=tk.NORMAL)
            self.entry_sha256.delete(0, tk.END)
            self.entry_sha256.configure(state="readonly")
            self.lbl_hash_status.configure(text="Status: Idle", fg=TEXT_MUTED)
            self.lbl_match_result.configure(text="Waiting for calculation...", fg=TEXT_MUTED)

    def calculate_file_hashes(self):
        file_path = self.entry_hash_path.get().strip()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid file to calculate hashes.")
            return
            
        def calc():
            self.root.after(0, lambda: [
                self.lbl_hash_status.configure(text="Status: Calculating...", fg=ACCENT_COLOR),
                self.btn_calc_hash.configure(state=tk.DISABLED)
            ])
            
            md5_hash = hashlib.md5()
            sha1_hash = hashlib.sha1()
            sha256_hash = hashlib.sha256()
            
            try:
                total_size = os.path.getsize(file_path)
                read_bytes = 0
                with open(file_path, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        md5_hash.update(chunk)
                        sha1_hash.update(chunk)
                        sha256_hash.update(chunk)
                        
                        read_bytes += len(chunk)
                        pct = (read_bytes / total_size) * 100
                        self.root.after(0, lambda p=pct: self.lbl_hash_status.configure(text=f"Status: Hashing... {p:.1f}%"))
                        
                md5_val = md5_hash.hexdigest()
                sha1_val = sha1_hash.hexdigest()
                sha256_val = sha256_hash.hexdigest()
                
                self.root.after(0, lambda: self.display_computed_hashes(md5_val, sha1_val, sha256_val))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Hashing Error", f"Failed to compute hashes: {e}"))
            finally:
                self.root.after(0, lambda: [
                    self.btn_calc_hash.configure(state=tk.NORMAL),
                    self.lbl_hash_status.configure(text="Status: Completed", fg=SUCCESS_COLOR)
                ])
                
        threading.Thread(target=calc, daemon=True).start()
        
    def display_computed_hashes(self, md5_val, sha1_val, sha256_val):
        self.entry_md5.configure(state=tk.NORMAL)
        self.entry_md5.delete(0, tk.END)
        self.entry_md5.insert(0, md5_val)
        self.entry_md5.configure(state="readonly")
        
        self.entry_sha1.configure(state=tk.NORMAL)
        self.entry_sha1.delete(0, tk.END)
        self.entry_sha1.insert(0, sha1_val)
        self.entry_sha1.configure(state="readonly")
        
        self.entry_sha256.configure(state=tk.NORMAL)
        self.entry_sha256.delete(0, tk.END)
        self.entry_sha256.insert(0, sha256_val)
        self.entry_sha256.configure(state="readonly")
        
        self.verify_hash_match()
        
    def verify_hash_match(self, *args):
        input_hash = self.match_hash_var.get().strip().lower()
        if not input_hash:
            self.lbl_match_result.configure(text="Waiting for comparison hash...", fg=TEXT_MUTED)
            return
            
        md5_val = self.entry_md5.get().strip().lower()
        sha1_val = self.entry_sha1.get().strip().lower()
        sha256_val = self.entry_sha256.get().strip().lower()
        
        if input_hash in (md5_val, sha1_val, sha256_val):
            self.lbl_match_result.configure(text="✅ MATCH DETECTED!", fg=SUCCESS_COLOR)
        else:
            self.lbl_match_result.configure(text="❌ NO MATCH!", fg=ERROR_COLOR)


    def start_repair(self):
        file_path = self.entry_repair_path.get().strip()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid archive file.")
            return
            
        self.log_text.delete("1.0", tk.END)
        self.btn_repair.configure(state=tk.DISABLED, text="Analyzing...")
        
        t = threading.Thread(target=self.run_repair_thread, args=(file_path,), daemon=True)
        t.start()
        
    def run_repair_thread(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == '.zip':
            dir_name = os.path.dirname(file_path)
            base_name = os.path.basename(file_path)
            output_path = os.path.join(dir_name, "rebuilt." + base_name)
            
            success, msg = carve_zip_file(file_path, output_path, self.log)
            if success:
                messagebox.showinfo("Success", f"ZIP repair complete!\n\nRepaired file saved as:\n{output_path}")
            else:
                messagebox.showerror("Failed", f"ZIP repair failed:\n{msg}")
                
        elif ext == '.rar':
            success, result = repair_rar_file(file_path, self.log)
            if success:
                if isinstance(result, tuple) and result[0] == "extracted":
                    extracted_dir = result[1]
                    try:
                        subprocess.run(['explorer', os.path.normpath(extracted_dir)], check=False)
                    except Exception:
                        pass
                    messagebox.showinfo("Success", f"RAR file was too corrupted to repair, but files were successfully force-extracted!\n\nFolder opened:\n{extracted_dir}")
                else:
                    messagebox.showinfo("Success", f"RAR repair complete!\n\nRepaired file saved as:\n{result}")
            else:
                messagebox.showerror("Failed", f"RAR repair failed:\nCould not repair or extract the archive. Ensure WinRAR is installed.")
        else:
            self.log("❌ ERROR: Only ZIP and RAR files are supported.")
            messagebox.showerror("Unsupported File", "Please select a .zip or .rar file")
            
        self.btn_repair.configure(state=tk.NORMAL, text="🔧 Run Repair Diagnostics")

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    # ==========================================================================
    # TAB 4: TROUBLESHOOTING GUIDE
    # ==========================================================================
    def build_guide_tab(self):
        frame = self.frames["guide"]
        
        lbl_title = ttk.Label(frame, text="User Guide & Troubleshooting Manual", style="Header.TLabel")
        lbl_title.pack(anchor=tk.W, pady=(0, 5))
        
        lbl_desc = ttk.Label(frame, text="Essential documentation authored by Budgetgamer1503 to ensure clean installs.", style="Sub.TLabel")
        lbl_desc.pack(anchor=tk.W, pady=(0, 20))
        
        card = tk.Frame(frame, bg=CARD_COLOR, padx=25, pady=25)
        card.pack(fill=tk.BOTH, expand=True)
        
        text_widget = tk.Text(card, bg=CARD_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 10), bd=0, wrap=tk.WORD)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        vsb = ttk.Scrollbar(card, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        guide_content = """BUDGETGAMER TURBO TOOLKIT GUIDE (V1)
================================================================================

1. THE SPEED BOOST ENGINE (CONNECTIONS AND LIMITS)
--------------------------------------------------------------------------------
* HOW IT WORKS:
  The downloader splits a file into multiple parts (up to 64) and downloads them
  concurrently, saturating your internet bandwidth for maximum speed.
  
* THE SERVER LIMIT EXPLANATION (VERY IMPORTANT):
  - Public/Direct Links (e.g. GitHub, Google Drive, direct download URLs):
    You can set connections to 32 or 64. It will download at maximum speed.
  - Free File Hosters (e.g. VikingFile, Rapidgator, Keep2Share, etc.):
    Free hosters limit free downloads to exactly 1 connection per IP.
    ⚠️ If you set the connection count to 32 or 64 on a free link, the server will block 
    your connections and send HTML error pages instead of file data. This results in a 
    corrupted download!
    💡 The toolkit automatically scans pasted URLs. If a limited hoster is detected, 
       it will auto-switch your connections to 1 with a warning.

2. ARCHIVE REPAIRER MODULE
--------------------------------------------------------------------------------
* ZIP RECOVERY:
  If a ZIP file becomes corrupted (e.g. because of network interruptions or failed 
  segmented downloads), this tool runs a forensic raw-bytes scan. It locates local 
  file headers (PK0304), decompresses all intact data, and rebuilds a healthy ZIP file.
  
* RAR RECOVERY & FORCE EXTRACTION:
  - If a RAR file is corrupted, the tool runs a standard WinRAR block repair.
  - If the RAR does not contain recovery records, standard repair fails.
    In this case, the tool automatically switches to 'Force Extraction' mode.
    It executes the UnRAR engine using the '-kb' (Keep Broken Files) flag.
    This force-extracts all salvageable contents to a folder without deleting files
    on CRC failures. (Note: WinRAR must be installed on your system).

3. FIXING GAME INSTALLATION ERRORS (ISDone.dll / Unarc.dll)
--------------------------------------------------------------------------------
If you install a game and encounter 'Unarc.dll returned error code: -1 (decompression fails)', 
it means a data package inside the installer is damaged or your system is crashing.

To fix this:
1. Limit RAM: Check the box "Limit installer to 2GB RAM" on the installer's first screen. 
   This prevents memory exhaustion.
2. Exclude Antivirus: Temporarily turn off Windows Defender / Real-time Protection. 
   Defender often blocks unarc.dll operations.
3. Boost Virtual Memory (Pagefile): Set your Windows virtual memory Pagefile to at 
   least 16GB (Initial: 8000MB, Maximum: 16000MB) on your C: drive.
4. Run as Administrator: Right-click setup.exe and select 'Run as administrator'.
================================================================================
Developed by Budgetgamer1503
"""
        text_widget.insert(tk.END, guide_content)
        text_widget.configure(state=tk.DISABLED)

    # ==========================================================================
    # POP-UP ACTIVE PROGRESS DIALOG WINDOW
    # ==========================================================================
    def launch_download_panel(self, url, temp_path, target_path, total_size, threads_count, speed_limit=None, auto_extract=False):
        self.active_state = DownloadProgressState()
        self.active_state.speed_limit = speed_limit
        self.active_state.auto_extract = auto_extract
        
        self.progress_win = tk.Toplevel(self.root)
        self.progress_win.title("Turbo Download Status")
        self.progress_win.geometry("600x440")
        self.progress_win.resizable(False, False)
        self.progress_win.configure(bg=CARD_COLOR)
        self.progress_win.transient(self.root)
        self.progress_win.grab_set()
        
        filename = os.path.basename(target_path)
        lbl_file = tk.Label(self.progress_win, text=filename, font=("Segoe UI", 12, "bold"), fg=TEXT_COLOR, bg=CARD_COLOR, wraplength=550, justify=tk.LEFT)
        lbl_file.pack(fill=tk.X, padx=20, pady=(20, 10), anchor=tk.W)
        
        lbl_folder = tk.Label(self.progress_win, text=f"Saving to: {os.path.dirname(target_path)}", font=("Segoe UI", 9), fg=TEXT_MUTED, bg=CARD_COLOR, anchor=tk.W)
        lbl_folder.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        self.progress_bar = ttk.Progressbar(self.progress_win, style="Custom.Horizontal.TProgressbar", orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill=tk.X, padx=20, pady=10)
        self.style.configure("Custom.Horizontal.TProgressbar", troughcolor='#0b0f19', background=ACCENT_COLOR, thickness=18)
        
        stats_frame = tk.Frame(self.progress_win, bg=CARD_COLOR)
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.lbl_percent = tk.Label(stats_frame, text="0.0%", font=("Segoe UI", 18, "bold"), fg=TEXT_COLOR, bg=CARD_COLOR)
        self.lbl_percent.grid(row=0, column=0, sticky=tk.W, pady=2)
        
        self.lbl_sizes = tk.Label(stats_frame, text="0 MB / 0 MB (0 MB left)", font=("Segoe UI", 10), fg=TEXT_MUTED, bg=CARD_COLOR)
        self.lbl_sizes.grid(row=1, column=0, sticky=tk.W, pady=2)
        
        self.lbl_speed = tk.Label(stats_frame, text="Speed: -- KB/s", font=("Segoe UI", 10, "bold"), fg=TEXT_COLOR, bg=CARD_COLOR)
        self.lbl_speed.grid(row=0, column=1, sticky=tk.E, pady=2)
        
        self.lbl_eta = tk.Label(stats_frame, text="ETA: --:--", font=("Segoe UI", 10), fg=TEXT_MUTED, bg=CARD_COLOR)
        self.lbl_eta.grid(row=1, column=1, sticky=tk.E, pady=2)
        
        self.lbl_threads = tk.Label(stats_frame, text="Connections: 0 active", font=("Segoe UI", 9), fg=TEXT_MUTED, bg=CARD_COLOR)
        self.lbl_threads.grid(row=2, column=0, sticky=tk.W, pady=(10, 0))
        
        self.lbl_status = tk.Label(stats_frame, text="Status: Starting...", font=("Segoe UI", 9, "italic"), fg=ACCENT_COLOR, bg=CARD_COLOR)
        self.lbl_status.grid(row=2, column=1, sticky=tk.E, pady=(10, 0))
        
        stats_frame.grid_columnconfigure(0, weight=1)
        stats_frame.grid_columnconfigure(1, weight=1)
        
        # Chunk Blocks Visualizer Canvas
        self.chunk_canvas = tk.Canvas(self.progress_win, bg="#070a13", height=60, highlightthickness=0)
        self.chunk_canvas.pack(fill=tk.X, padx=20, pady=(10, 0))
        
        btn_frame = tk.Frame(self.progress_win, bg=CARD_COLOR, pady=15)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.btn_pause = tk.Button(btn_frame, text="⏸️ Pause Download", bg=ERROR_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold"), borderwidth=0, padx=20, pady=8, cursor="hand2", command=self.toggle_pause)
        self.btn_pause.pack(side=tk.LEFT, padx=20)
        bind_hover_effect(self.btn_pause, ERROR_HOVER, ERROR_COLOR)
        
        self.btn_action = tk.Button(btn_frame, text="Cancel", bg=BG_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold"), borderwidth=0, padx=20, pady=8, cursor="hand2", command=self.close_progress_win)
        self.btn_action.pack(side=tk.RIGHT, padx=20)
        bind_hover_effect(self.btn_action, "#161d30", BG_COLOR)
        
        self.download_thread = threading.Thread(
            target=download_core,
            args=(url, temp_path, target_path, total_size, threads_count, 100, 15, self.active_state),
            daemon=True
        )
        self.download_thread.start()
        self.update_progress_loop(target_path)

    def toggle_pause(self):
        if not self.active_state:
            return
        if not self.active_state.is_paused:
            self.active_state.is_paused = True
            self.btn_pause.configure(text="▶️ Resume Download", bg=SUCCESS_COLOR)
            bind_hover_effect(self.btn_pause, SUCCESS_HOVER, SUCCESS_COLOR)
            self.lbl_status.configure(text="Status: Pausing...", fg=ERROR_COLOR)
        else:
            self.active_state.is_paused = False
            self.btn_pause.configure(text="⏸️ Pause Download", bg=ERROR_COLOR)
            bind_hover_effect(self.btn_pause, ERROR_HOVER, ERROR_COLOR)
            self.lbl_status.configure(text="Status: Resuming...", fg=ACCENT_COLOR)

    def close_progress_win(self):
        if self.active_state and not (self.active_state.is_completed or self.active_state.is_failed):
            self.active_state.is_paused = True
        self.progress_win.grab_release()
        self.progress_win.destroy()

    def update_progress_loop(self, file_path):
        if not self.progress_win.winfo_exists():
            return
            
        state = self.active_state
        downloaded = state.downloaded_bytes
        total = state.total_bytes
        speed = state.speed
        status = state.status
        active_conns = state.active_connections
        
        if total > 0:
            pct = (downloaded / total) * 100
            self.lbl_percent.configure(text=f"{pct:.1f}%")
            self.progress_bar['value'] = pct
            left_bytes = total - downloaded
            self.lbl_sizes.configure(text=f"{format_size(downloaded)} / {format_size(total)} ({format_size(left_bytes)} left)")
            eta = left_bytes / speed if speed > 0 else float('inf')
            self.lbl_eta.configure(text=f"ETA: {format_time(eta)}")
        else:
            self.lbl_percent.configure(text="-- %")
            self.progress_bar.configure(mode="indeterminate")
            self.progress_bar.step(2)
            self.lbl_sizes.configure(text=f"{format_size(downloaded)} (Total size unknown)")
            self.lbl_eta.configure(text="ETA: --:--")
            
        self.lbl_speed.configure(text=f"Speed: {format_size(speed)}/s" if speed > 0 else "Speed: -- B/s")
        self.lbl_threads.configure(text=f"Connections: {active_conns} active")
        self.lbl_status.configure(text=f"Status: {status}")
        
        # Redraw chunk blocks
        self.chunk_canvas.delete("all")
        width = self.chunk_canvas.winfo_width() or 560
        height = self.chunk_canvas.winfo_height() or 60
        
        if hasattr(state, 'segments') and state.segments:
            num_blocks = len(state.segments)
            cols = 16 if num_blocks > 16 else num_blocks
            rows = (num_blocks + cols - 1) // cols
            
            block_w = (width - (cols + 1) * 2) / cols
            block_h = (height - (rows + 1) * 2) / rows
            
            for idx, (start, end) in enumerate(state.segments):
                part_path = f"{file_path}.part{idx}"
                chunk_downloaded = 0
                if os.path.exists(part_path):
                    chunk_downloaded = os.path.getsize(part_path)
                total_chunk_bytes = end - start + 1
                
                pct = chunk_downloaded / total_chunk_bytes if total_chunk_bytes > 0 else 0
                
                if pct >= 0.999:
                    color = SUCCESS_COLOR
                elif pct > 0.0:
                    color = "#f59e0b"
                else:
                    color = "#334155"
                    
                r = idx // cols
                c = idx % cols
                x1 = 2 + c * (block_w + 2)
                y1 = 2 + r * (block_h + 2)
                x2 = x1 + block_w
                y2 = y1 + block_h
                
                self.chunk_canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="")
                
        if state.is_completed:
            self.lbl_status.configure(text="Status: Completed successfully!", fg=SUCCESS_COLOR)
            self.btn_pause.pack_forget()
            self.btn_action.configure(text="📂 Open File Folder", bg=SUCCESS_COLOR)
            bind_hover_effect(self.btn_action, SUCCESS_HOVER, SUCCESS_COLOR)
            self.btn_action.configure(command=lambda: [open_file_in_explorer(file_path), self.close_progress_win()])
            
            if getattr(state, 'auto_extract', False):
                self.lbl_status.configure(text="Status: Auto-extracting...", fg=ACCENT_COLOR)
                def extract_bg():
                    ext = os.path.splitext(file_path)[1].lower()
                    out_dir = os.path.splitext(file_path)[0]
                    try:
                        os.makedirs(out_dir, exist_ok=True)
                        if ext == '.zip':
                            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                                zip_ref.extractall(out_dir)
                            self.root.after(0, lambda: messagebox.showinfo("Auto-Extract Complete", f"Successfully extracted archive to:\n{out_dir}"))
                        elif ext == '.rar':
                            extract_rar_keep_broken(file_path, out_dir, self.log)
                            self.root.after(0, lambda: messagebox.showinfo("Auto-Extract Complete", f"Force extracted salvageable RAR contents to:\n{out_dir}"))
                    except Exception as e:
                        self.root.after(0, lambda: messagebox.showerror("Auto-Extraction Failed", f"Failed to extract {os.path.basename(file_path)}:\n{e}"))
                threading.Thread(target=extract_bg, daemon=True).start()
            else:
                messagebox.showinfo("Success", f"Download completed successfully!\nSaved to: {file_path}")
            return
            
        if state.is_failed:
            self.lbl_status.configure(text=f"Status: Failed - {state.error_message}", fg=ERROR_COLOR)
            self.btn_pause.pack_forget()
            self.btn_action.configure(text="Close", bg=CARD_COLOR)
            bind_hover_effect(self.btn_action, "#334155", CARD_COLOR)
            self.btn_action.configure(command=self.close_progress_win)
            messagebox.showerror("Download Failed", f"The download failed:\n{state.error_message}")
            return
            
        self.root.after(100, lambda: self.update_progress_loop(file_path))

# ==============================================================================
# COMMAND LINE FALLBACK ENGINE (Headless Mode)
# ==============================================================================
def draw_cli_progress_bar(downloaded, total, speed, start_time):
    term_width = 80
    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        pass
    
    downloaded_str = format_size(downloaded)
    speed_str = f"{format_size(speed)}/s" if speed > 0 else "-- B/s"
    
    if total and total > 0:
        pct = (downloaded / total) * 100
        left_bytes = total - downloaded
        eta = left_bytes / speed if speed > 0 else float('inf')
        eta_str = f"ETA: {format_time(eta)}"
        total_str = format_size(total)
        left_str = f"Left: {format_size(left_bytes)}"
        
        info_str = f" {pct:5.1f}% | {downloaded_str}/{total_str} ({left_str}) | {speed_str} | {eta_str}"
        bar_width = term_width - len(info_str) - 3
        
        if bar_width > 5:
            filled_len = int(bar_width * downloaded // total)
            bar = '█' * filled_len + '░' * (bar_width - filled_len)
            sys.stdout.write(f"\r[{bar}]{info_str}")
        else:
            sys.stdout.write(f"\r{pct:.1f}% | {downloaded_str}/{total_str} | {speed_str} | {eta_str}")
    else:
        elapsed = time.time() - start_time
        info_str = f" Downloaded: {downloaded_str} | Speed: {speed_str} | Time: {format_time(elapsed)}"
        sys.stdout.write(f"\r{info_str}")
        
    sys.stdout.flush()

def run_cli_monitor_mode(history_paths):
    print("\n" + "="*80)
    print("                    STARTING BROWSER DOWNLOAD MONITOR MODE")
    print("  Will check for failed downloads every 5 seconds.")
    print("  Uses exactly 10 connections for background stability.")
    print("  To stop monitoring, press Ctrl+C.")
    print("="*80)
    
    handled_downloads = set()
    try:
        while True:
            recent = get_recent_downloads(history_paths, limit=10)
            for dl in recent:
                dl_id = dl['id']
                state = dl['state']
                target_path = dl['target_path']
                current_path = dl['current_path']
                url = dl['url']
                total_size = dl['total_bytes']
                
                if state == 3 and dl_id not in handled_downloads:
                    filename = os.path.basename(target_path)
                    browser_name = dl.get('browser', 'Browser')
                    print(f"\n[!] Detected failed {browser_name} download: {filename}")
                    
                    is_limited, hoster = check_hoster_limits(url)
                    bg_connections = 10
                    if is_limited:
                        print(f"    ⚠️ Limited hoster detected ({hoster}). Throttling to 1 connection.")
                        bg_connections = 1
                        
                    temp_file = current_path if current_path else target_path + ".crdownload"
                    print(f"    Resuming failed download to: {target_path} (connections: {bg_connections})")
                    
                    handled_downloads.add(dl_id)
                    state_obj = DownloadProgressState()
                    
                    d_thread = threading.Thread(
                        target=download_core,
                        args=(url, temp_file, target_path, total_size, bg_connections, 100, 15, state_obj),
                        daemon=True
                    )
                    d_thread.start()
                    
                    start_time = time.time()
                    while d_thread.is_alive():
                        draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
                        time.sleep(0.2)
                        
                    draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
                    if state_obj.is_completed:
                        print("\nDownload finished and merged successfully!")
                    else:
                        print(f"\nDownload aborted: {state_obj.error_message}")
                    break
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nExiting Monitor Mode.")

def main_cli():
    print("="*60)
    print("      BG TURBO DOWNLOADER & REPAIRER v1 (CLI)")
    print("      Author: Budgetgamer1503")
    print("="*60)
    
    history_paths = find_chrome_history_files()
    if not history_paths:
        print("Could not locate Chrome History file.")
        url = input("\nEnter download URL: ").strip()
        if url:
            out = input("Enter output path (press Enter to auto-name): ").strip()
            if not out:
                out = os.path.basename(urlparse(url).path) or "downloaded_file"
            
            is_limited, hoster = check_hoster_limits(url)
            connections = 32
            if is_limited:
                print(f"⚠️ Warning: Detected throttled hoster ({hoster}).")
                ans = input("Force 1 connection to prevent corruption? (Y/n): ").strip().lower()
                if ans != 'n':
                    connections = 1
                    
            temp_out = out + ".crdownload"
            state_obj = DownloadProgressState()
            d_thread = threading.Thread(target=download_core, args=(url, temp_out, out, None, connections, 100, 15, state_obj), daemon=True)
            d_thread.start()
            start_time = time.time()
            while d_thread.is_alive():
                draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
                time.sleep(0.2)
            draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
        return

    while True:
        print("\nScanning browser download history...")
        recent = get_recent_downloads(history_paths, limit=10)
        
        print("\nRecent Browser Downloads:")
        print("-" * 80)
        for idx, dl in enumerate(recent):
            filename = os.path.basename(dl['target_path']) or "Unknown File"
            status = get_state_string(dl['state'])
            total_size_str = format_size(dl['total_bytes']) if dl['total_bytes'] > 0 else "Unknown size"
            rec_size_str = format_size(dl['received_bytes'])
            browser_name = dl.get('browser', 'Browser')
            
            print(f"[{idx + 1}] {filename} ({browser_name})")
            print(f"    Status: {status} ({rec_size_str} of {total_size_str})")
            print(f"    URL: {dl['url'][:100]}..." if len(dl['url']) > 100 else f"    URL: {dl['url']}")
            print()
        print("-" * 80)
        
        print("Menu options:")
        print("  [1-10]  Select a browser download to resume/retry (uses all internet - 32 connections!)")
        print("  [M]     Start MONITOR MODE (auto-resume in background - 10 connections)")
        print("  [U]     Download a custom URL with all internet (32 connections)")
        print("  [R]     Refresh download history list")
        print("  [Q]     Quit")
        
        choice = input("\nEnter choice: ").strip().upper()
        
        if choice == 'Q':
            print("Goodbye!")
            break
        elif choice == 'R':
            continue
        elif choice == 'M':
            run_cli_monitor_mode(history_paths)
        elif choice == 'U':
            url = input("\nEnter URL: ").strip()
            if url:
                out = input("Enter target filename/path (press Enter to auto-name): ").strip()
                if not out:
                    out = os.path.basename(urlparse(url).path) or "downloaded_file"
                
                is_limited, hoster = check_hoster_limits(url)
                connections = 32
                if is_limited:
                    print(f"⚠️ Warning: Detected throttled hoster ({hoster}).")
                    ans = input("Force 1 connection to prevent corruption? (Y/n): ").strip().lower()
                    if ans != 'n':
                        connections = 1
                        
                temp_out = out + ".crdownload"
                state_obj = DownloadProgressState()
                d_thread = threading.Thread(target=download_core, args=(url, temp_out, out, None, connections, 100, 15, state_obj), daemon=True)
                d_thread.start()
                start_time = time.time()
                while d_thread.is_alive():
                    draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
                    time.sleep(0.2)
                draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
                print()
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(recent):
                    dl = recent[idx]
                    target_path = dl['target_path']
                    current_path = dl['current_path']
                    url = dl['url']
                    total_size = dl['total_bytes']
                    
                    is_limited, hoster = check_hoster_limits(url)
                    connections = 32
                    if is_limited:
                        print(f"⚠️ Warning: Detected throttled hoster ({hoster}).")
                        ans = input("Force 1 connection to prevent corruption? (Y/n): ").strip().lower()
                        if ans != 'n':
                            connections = 1
                            
                    temp_file = current_path if current_path and os.path.exists(current_path) else target_path + ".crdownload"
                    print(f"\nResuming download for: {os.path.basename(target_path)}")
                    
                    state_obj = DownloadProgressState()
                    d_thread = threading.Thread(target=download_core, args=(url, temp_file, target_path, total_size, connections, 100, 15, state_obj), daemon=True)
                    d_thread.start()
                    start_time = time.time()
                    while d_thread.is_alive():
                        draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
                        time.sleep(0.2)
                    draw_cli_progress_bar(state_obj.downloaded_bytes, state_obj.total_bytes, state_obj.speed, start_time)
                    print()
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Invalid input.")

# ==============================================================================
# MAIN INITIALIZER
# ==============================================================================
def main():
    if GUI_AVAILABLE:
        try:
            root = tk.Tk()
            app = BudgetGamerTurboSuiteV1(root)
            root.mainloop()
            return
        except Exception as e:
            print(f"GUI Initialization failed: {e}. Falling back to CLI mode.")
            
    main_cli()

if __name__ == "__main__":
    main()
