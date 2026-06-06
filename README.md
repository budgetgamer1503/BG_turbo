# ⚡ BG Turbo Downloader & Repairer v1

**Developed by:** Budgetgamer1503

A premium, feature-rich Python utility built for gamers and power users. This suite provides a sleek, dark-mode desktop GUI (with an automatic CLI fallback) designed to maximize internet speeds, resume failed browser downloads, salvage corrupted archives, and manage download queues with smart throttling profiles.

---

## ✨ Key Features

### 🚀 1. Turbo Downloader & Queue Manager

* **32-Connection Thread Boost:** Accelerates downloads by splitting files into up to 32 concurrent segments.
* **Smart Queue Management:** Add multiple URLs, prioritize them, and let the app download them sequentially.
* **Bandwidth Profiles:**
* *Turbo Mode:* Maximum speed utilizing all available connections.
* *Background Mode:* Restricted to 4 connections and capped at 500 KB/s so you can game or stream without lag.
* *Custom Mode:* Set your own connection count and exact speed limits.


* **Auto-Extraction:** Toggle a checkbox to automatically unpack ZIP or RAR archives the moment they finish downloading.
* **Dynamic Progress Visualizer:** A real-time, color-coded grid block dashboard that shows exactly how each connection segment is performing.

### 📂 2. Browser Download Resumer

* **Multi-Browser Scanning:** Automatically detects and scans history databases for Chrome, Edge, Brave, Opera, Opera GX, and Vivaldi.
* **Safe Database Reading:** Safely backs up and reads browser history databases without locking errors, even handling active Write-Ahead Log (WAL) files.
* **Interrupted Download Recovery:** Automatically detects paused, failed, or interrupted browser downloads and takes over, finishing them via high-speed multi-threading.
* **Host Restrictions Detection:** Recognizes hosters that block multi-threading (like VikingFile) and automatically scales back to 1 connection to prevent data corruption.

### 🛠️ 3. Archive Repairer & Hash Verifier

* **ZIP Header Carving:** Scans corrupted `.zip` files byte-by-byte for local file header signatures (`PK\x03\x04`), rebuilding the central directory and skipping unreadable sections.
* **UnRAR Fallback:** Forces the extraction of salvageable files from broken `.rar` archives by passing the "Keep Broken Files" (`-kb`) parameter to WinRAR/UnRAR.
* **Integrity Verification:** Instantly calculate and compare MD5, SHA-1, and SHA-256 checksums to ensure your downloads match original repack hashes.

### 📖 4. Built-in Troubleshooter

* Includes a dedicated guide for debugging common Windows installation and repack errors, such as the notorious `ISDone.dll` and `Unarc.dll` issues.

---

## ⚙️ How It Works Under the Hood

### Multi-Threaded Segmented Downloads

When a download begins, the application sends HTTP Range requests to fetch different sections of the file simultaneously. Each chunk is saved as a temporary file (`temp_part_*`). Once all parts are fully retrieved, they are seamlessly merged into the final file.

### Safe SQLite WAL Reading

To safely pull active downloads from your browser without causing crashes, the app copies the active history database to a temporary location. This allows it to read data locked by Chromium's Write-Ahead Log (WAL) without interfering with your open browser.

### ZIP File Carving

Standard extraction tools reject ZIP archives if they notice even minor corruption. This tool bypasses those restrictions by scanning raw bytes for local header signatures, extracting the intact data streams, and compiling them into a brand-new, uncorrupted archive.

---

## 🛠️ Setup & Installation

### Prerequisites

* Windows OS
* Python 3.8 or higher
* **Zero Dependencies:** The application runs entirely on the Python Standard Library. No external packages required!

### Running the App

Simply double-click `v1.py` or launch it via PowerShell/Command Prompt:

```bash
python v1.py

```

*Note: If a graphical environment is not detected, the application will automatically fall back to a clean, interactive command-line interface (CLI).*

### 📦 Compiling to a Portable Executable (.exe)

If you want to turn the script into a standalone Windows application that you can run anywhere without installing Python, use PyInstaller:

1. Install PyInstaller:

```bash
pip install pyinstaller

```

2. Build the EXE:

```bash
pyinstaller --onefile --noconsole --name="BGTurboDownloader" v1.py

```

Once the process finishes, you will find your standalone executable in the newly created `dist/` folder.