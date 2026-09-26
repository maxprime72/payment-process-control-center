import os
import sys
import time
import socket
import logging
import threading
import webbrowser
import urllib.request
import urllib.error
import json
import tkinter as tk
from tkinter import messagebox

# Determine application and bundle directories
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.abspath(os.path.dirname(__file__))
    BUNDLE_DIR = APP_DIR

# Ensure backend folder is in sys.path
backend_path = os.path.join(BUNDLE_DIR, "backend")
if os.path.isdir(backend_path) and backend_path not in sys.path:
    sys.path.insert(0, backend_path)
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)

# Set up logs directory and file logging
LOGS_DIR = os.path.join(APP_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "payble.log")
STARTUP_ERROR_LOG = os.path.join(LOGS_DIR, "startup_error.log")

def write_startup_error(details: str):
    """Writes full technical error to logs/startup_error.log."""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(STARTUP_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n[{timestamp}] PAYBLE STARTUP FAILURE\n{'=' * 60}\n{details}\n\n")
    except Exception:
        pass

DATA_DIR = os.path.join(APP_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Custom stdout/stderr redirector to capture console output in log file
class LogWriter:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, message):
        if message:
            self.buffer += message
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                line = line.strip()
                if line:
                    self.logger.log(self.level, line)

    def flush(self):
        if self.buffer.strip():
            self.logger.log(self.level, self.buffer.strip())
            self.buffer = ""

    def isatty(self):
        return False

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("PaybleLauncher")

# Redirect sys.stdout and sys.stderr to logger
sys.stdout = LogWriter(logger, logging.INFO)
sys.stderr = LogWriter(logger, logging.ERROR)

PORT_FILE = os.path.join(APP_DIR, ".running_port")

def check_existing_instance() -> bool:
    """Checks if Payble is already running. If so, opens the browser and returns True."""
    if not os.path.exists(PORT_FILE):
        return False
    try:
        with open(PORT_FILE, "r") as f:
            port_str = f.read().strip()
        port = int(port_str)
        url = f"http://127.0.0.1:{port}/api/health"
        req = urllib.request.Request(url, headers={"User-Agent": "PaybleLauncher"})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                if data.get("status") == "ok":
                    logger.info(f"Existing Payble instance detected on port {port}. Opening browser.")
                    webbrowser.open(f"http://127.0.0.1:{port}/")
                    return True
    except Exception as e:
        logger.warning(f"Stale .running_port found or connection failed: {e}")
    
    # Remove stale port file
    try:
        if os.path.exists(PORT_FILE):
            os.remove(PORT_FILE)
    except Exception:
        pass
    return False

def find_available_port(host: str = "127.0.0.1", preferred_port: int = 8000) -> int:
    """Finds an available local port, trying preferred_port first."""
    # First check if preferred_port is actively listening or in use
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((host, preferred_port)) == 0:
                logger.info(f"Preferred port {preferred_port} is already in use, selecting dynamic port.")
            else:
                # Test exclusive bind (without SO_REUSEADDR to avoid Windows port sharing)
                s.bind((host, preferred_port))
                return preferred_port
    except OSError:
        logger.info(f"Preferred port {preferred_port} could not be bound, selecting dynamic port.")

    # Find free dynamic port assigned by OS
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]

def wait_for_backend(port: int, timeout: float = 15.0) -> bool:
    """Polls health check until backend is responsive or timeout expires."""
    url = f"http://127.0.0.1:{port}/api/health"
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PaybleLauncher"})
            with urllib.request.urlopen(req, timeout=0.8) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False

class PaybleControlWindow:
    """Sleek native control center window for the Payble application."""
    def __init__(self, port: int, server, uvicorn_thread):
        self.port = port
        self.server = server
        self.uvicorn_thread = uvicorn_thread
        self.app_url = f"http://127.0.0.1:{port}/"

        self.root = tk.Tk()
        self.root.title("Payble - Payment Process Control Center")
        self.root.geometry("480x280")
        self.root.resizable(False, False)

        # Center window on screen
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"+{x}+{y}")

        # Dark Slate Palette
        bg_main = "#0f172a"      # Slate 900
        bg_card = "#1e293b"      # Slate 800
        accent_blue = "#38bdf8"  # Sky 400
        accent_green = "#22c55e" # Green 500
        text_primary = "#f8fafc" # Slate 50
        text_muted = "#94a3b8"   # Slate 400
        btn_hover = "#0284c7"    # Sky 600

        self.root.configure(bg=bg_main)

        # Top Banner
        header_frame = tk.Frame(self.root, bg=bg_card, padx=20, pady=12)
        header_frame.pack(fill="x", side="top")

        title_label = tk.Label(
            header_frame,
            text="PAYBLE",
            font=("Segoe UI", 16, "bold"),
            fg=text_primary,
            bg=bg_card
        )
        title_label.pack(side="left")

        badge_label = tk.Label(
            header_frame,
            text=" PORTABLE EDITION ",
            font=("Segoe UI", 8, "bold"),
            fg=accent_blue,
            bg="#0f172a",
            padx=6,
            pady=2
        )
        badge_label.pack(side="left", padx=10)

        # Body Container
        body_frame = tk.Frame(self.root, bg=bg_main, padx=24, pady=16)
        body_frame.pack(fill="both", expand=True)

        # Status Line
        status_frame = tk.Frame(body_frame, bg=bg_main)
        status_frame.pack(fill="x", pady=(0, 14))

        status_dot = tk.Label(
            status_frame,
            text="●",
            font=("Segoe UI", 14),
            fg=accent_green,
            bg=bg_main
        )
        status_dot.pack(side="left", padx=(0, 6))

        status_text = tk.Label(
            status_frame,
            text=f"Server Active on {self.app_url}",
            font=("Segoe UI", 10, "bold"),
            fg=text_primary,
            bg=bg_main
        )
        status_text.pack(side="left")

        desc_label = tk.Label(
            body_frame,
            text="The Payble backend and frontend are running locally.\nClosing this window will safely shut down the application.",
            font=("Segoe UI", 9),
            fg=text_muted,
            bg=bg_main,
            justify="left"
        )
        desc_label.pack(fill="x", pady=(0, 16))

        # Button Row 1: Open in Browser
        btn_browser = tk.Button(
            body_frame,
            text="🌐  Open in Browser",
            font=("Segoe UI", 10, "bold"),
            bg=accent_blue,
            fg="#0f172a",
            activebackground=btn_hover,
            activeforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=6,
            command=self.open_browser
        )
        btn_browser.pack(fill="x", pady=(0, 8))

        # Button Row 2: Utilities (Data folder, Logs, Exit)
        row2_frame = tk.Frame(body_frame, bg=bg_main)
        row2_frame.pack(fill="x")

        btn_data = tk.Button(
            row2_frame,
            text="📁 Data Folder",
            font=("Segoe UI", 9),
            bg=bg_card,
            fg=text_primary,
            activebackground="#334155",
            activeforeground=text_primary,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=4,
            command=self.open_data_folder
        )
        btn_data.pack(side="left", expand=True, fill="x", padx=(0, 4))

        btn_logs = tk.Button(
            row2_frame,
            text="📄 View Logs",
            font=("Segoe UI", 9),
            bg=bg_card,
            fg=text_primary,
            activebackground="#334155",
            activeforeground=text_primary,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=4,
            command=self.open_logs_folder
        )
        btn_logs.pack(side="left", expand=True, fill="x", padx=(4, 4))

        btn_exit = tk.Button(
            row2_frame,
            text="🛑 Stop & Exit",
            font=("Segoe UI", 9, "bold"),
            bg="#ef4444",
            fg="#ffffff",
            activebackground="#dc2626",
            activeforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=4,
            command=self.on_closing
        )
        btn_exit.pack(side="left", expand=True, fill="x", padx=(4, 0))

        # Intercept window close button
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def open_browser(self):
        webbrowser.open(self.app_url)

    def open_data_folder(self):
        try:
            os.startfile(DATA_DIR)
        except Exception as e:
            logger.error(f"Failed to open data folder: {e}")

    def open_logs_folder(self):
        try:
            os.startfile(LOGS_DIR)
        except Exception as e:
            logger.error(f"Failed to open logs folder: {e}")

    def on_closing(self):
        logger.info("Shutdown requested by user. Terminating server...")
        try:
            # Signal Uvicorn to exit
            if self.server:
                self.server.should_exit = True
            
            # Execute database checkpoint
            try:
                from services.db_service import checkpoint_database
                checkpoint_database()
            except Exception as e:
                logger.warning(f"Error during shutdown checkpoint: {e}")

            # Clean up port file
            if os.path.exists(PORT_FILE):
                os.remove(PORT_FILE)
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            self.root.destroy()
            sys.exit(0)

    def run(self):
        self.root.mainloop()

def main():
    logger.info("=" * 60)
    logger.info("Payble Portable Launcher starting...")
    logger.info(f"Application Directory: {APP_DIR}")
    logger.info(f"Bundle Directory: {BUNDLE_DIR}")

    # Check if instance is already running
    if check_existing_instance():
        logger.info("Exiting: instance already active.")
        sys.exit(0)

    # Pick available port
    port = find_available_port(host="127.0.0.1", preferred_port=8000)
    logger.info(f"Selected port: {port}")

    # Start FastAPI / Uvicorn server in a separate daemon thread
    import uvicorn
    from main import app

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
        log_config=None,
        use_colors=False,
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    uvicorn_thread = threading.Thread(target=server.run, daemon=True)
    uvicorn_thread.start()

    logger.info("Waiting for backend server to become responsive...")
    if not wait_for_backend(port, timeout=15.0):
        technical_details = (
            f"Backend server failed to respond on 127.0.0.1:{port} within 15.0 seconds.\n"
            f"Executable: {sys.executable}\n"
            f"Application Directory: {APP_DIR}\n"
            f"Bundle Directory: {BUNDLE_DIR}\n"
            f"Port: {port}\n"
            f"Check logs/payble.log for full backend output."
        )
        logger.error(technical_details)
        write_startup_error(technical_details)
        clean_msg = (
            f"Payble could not complete startup.\n\n"
            f"A technical error report has been written to:\n"
            f"logs\\startup_error.log\n\n"
            f"Please check logs\\startup_error.log and logs\\payble.log for details."
        )
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Payble Startup Error", clean_msg)
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

    logger.info("Backend is live and healthy!")

    # Write running port
    try:
        with open(PORT_FILE, "w") as f:
            f.write(str(port))
    except Exception as e:
        logger.warning(f"Could not write port file: {e}")

    # Automatically open in user's default browser
    app_url = f"http://127.0.0.1:{port}/"
    logger.info(f"Opening browser to {app_url}")
    webbrowser.open(app_url)

    # Launch GUI Control Center window
    try:
        control_window = PaybleControlWindow(port, server, uvicorn_thread)
        control_window.run()
    except Exception as e:
        logger.error(f"Error in GUI loop: {e}")
        # If GUI fails (headless environment or display issues), keep main thread alive
        try:
            while uvicorn_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
            sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception(f"Unhandled critical launcher error: {e}")
        write_startup_error(f"Unhandled critical exception in launcher main:\n{e}\n\nTraceback:\n{tb}")
        clean_msg = (
            f"Payble encountered an unexpected startup problem.\n\n"
            f"The full technical error has been written to:\n"
            f"logs\\startup_error.log"
        )
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Payble Startup Error", clean_msg)
            root.destroy()
        except Exception:
            pass
        sys.exit(1)
