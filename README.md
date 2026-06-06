# ⚡ BG Turbo Downloader & Repairer v1

A premium, feature-rich, standalone Python utility designed for gamers and power users. This suite offers a professional dark-mode desktop GUI (and CLI fallback) to supercharge internet downloads, resume failed browser downloads, repair corrupted archives, and manage download queues with full speed throttling profiles.

**Author & Coder:** Budgetgamer1503

---

## ✨ Features

### 🚀 1. Turbo Custom Downloader & Queue Manager
- **32-Connection Thread Boost**: Accelerates downloads by splitting files into up to 64 concurrent segments.
- **Download Queue**: Add multiple URLs, prioritize them, and download them sequentially.
- **Bandwidth Throttling Profiles**:
  - **Turbo Mode**: Maximum download speed utilizing 32+ connections.
  - **Background Mode**: Lower priority, 4 connections, speed-limited to 500 KB/s (uses only ~10% bandwidth).
  - **Custom Mode**: Define your own connection count and custom speed limits (in KB/s).
- **Auto-Extraction**: Checkbox to automatically extract ZIP or RAR archives once they download successfully.
- **Dynamic Chunk Grid Visualizer**: Visualizes download progress across connection segments as a real-time color-coded grid block dashboard.

### 📂 2. Browser Downloads Resumer
- **Multi-Browser Scanning**: Automatically finds and queries history databases for **Google Chrome**, **Microsoft Edge**, **Brave Browser**, **Opera Stable**, **Opera GX**, and **Vivaldi**.
- **Safe SQLite Reading**: Merges WAL-logged changes and parses browser history databases without locking errors.
- **Smart Detection**: Detects paused, failed, or interrupted downloads and resumes them immediately using high-speed multi-threaded connections.
- **Automatic Throttling**: Checks for restricted hosters (like *VikingFile*) and automatically throttles down to `1` connection to prevent data corruption.

### 🛠️ 3. Archive Repairer & Hash Verifier
- **Local Header Carving**: Repairs corrupted `.zip` archives by scanning and carving local file headers (`PK\x03\x04`), rebuilding central directories, and bypassing corrupted sections.
- **UnRAR Fallback**: Forces extraction of salvageable files from corrupted `.rar` archives using WinRAR/UnRAR's Keep Broken Files (`-kb`) fallback parameters.
- **Integrity Hash Verifier**: Instantly compute and compare **MD5**, **SHA-1**, and **SHA-256** checksums of files to verify they match original repack hashes.

### 📖 4. Troubleshooter Guide
- Detailed instructions for debugging common Windows setup errors (e.g., `ISDone.dll` / `Unarc.dll` errors).

---

## 🛠️ Requirements & Installation

The application runs entirely on the **Python Standard Library**—no external packages are required!

### Prerequisites
- Windows OS
- Python 3.8 or higher

### Running the App
Double-click `v1.py` or run the following command in PowerShell/CMD:
```powershell
python v1.py
```
*If a display is not available, the application automatically falls back to a clean, interactive command-line interface (CLI) mode.*

---

## 📦 Compiling to Standalone Executable (.exe)

You can compile the script into a single, portable executable file using PyInstaller:

1. Install PyInstaller:
   ```powershell
   pip install -r requirements.txt
   ```
2. Build the EXE:
   ```powershell
   pyinstaller --onefile --noconsole --name="BGTurboDownloader" v1.py
   ```
The compiled executable will be placed in the `dist/` directory.

---

## ⚙️ How It Works Under the Hood

### 1. Multi-Threaded Segmented Downloads
When downloading a file, the downloader issues HTTP `Range` requests to fetch sections of the file concurrently. Individual segments are saved as temporary files (`temp_part_*`) and combined sequentially into the final file upon completion.

### 2. SQLite WAL Reader for Chrome History
To safely read active Chrome downloads, the resumer performs a temporary backup of Chrome's history database. This handles Chrome's Write-Ahead Log (WAL) mode cleanly and avoids database lock (`database is locked`) issues.

### 3. ZIP File Carving
If a `.zip` archive gets corrupted during download, standard extractors will reject it. The repairer scans byte-by-byte for local file header signatures (`PK\x03\x04`), extracts the compressed streams, and constructs a new, clean zip file containing only the salvageable files.
