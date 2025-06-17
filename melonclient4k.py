#!/usr/bin/env python3
"""
Melon Client 1.0x – Custom Minecraft Launcher
================================================

Setup Instructions (Python Environment)
---------------------------------------
1. **Install Python 3.8 or newer**
   Visit <https://www.python.org/downloads/> or use your OS package manager.
   Verify with:
   ```bash
   python --version
   ```

2. **Create an isolated virtual environment (optional but recommended)**
   ```bash
   python -m venv .venv          # create venv in current folder
   # Activate it:
   #   Windows PowerShell:
   .venv\Scripts\Activate.ps1
   #   Windows cmd.exe:
   .venv\Scripts\activate.bat
   #   macOS/Linux:
   source .venv/bin/activate
   ```
   *(Deactivate later with `deactivate`.)*

3. **Install runtime dependencies**
   ```bash
   pip install minecraft-launcher-lib
   ```
   *Tkinter is bundled with the official CPython installers for Windows/macOS.  
   On many Linux distros you may need to add it:*  
   ```bash
   sudo apt install python3-tk     # Debian/Ubuntu
   # or
   sudo dnf install python3-tkinter # Fedora
   ```

4. **Ensure Java 8+ is on your PATH** (required by Minecraft itself)
   ```bash
   java -version
   ```

5. **Run the launcher**
   ```bash
   python melon_launcher.py
   ```

6. **Files created at runtime**
   - `melon_client.log` – rotating log of launcher activity & errors.  
   - `melonclient_config.json` – persists user preferences between sessions.

Notes & Next Steps
~~~~~~~~~~~~~~~~~~
- The Microsoft‑account login button is a placeholder; implementing OAuth flow
  will require additional libraries (e.g. `msal`) and registering an Azure app.
- The launcher will attempt to auto‑install missing Minecraft versions via
  `minecraft-launcher-lib`; a working internet connection and Mojang servers
  availability are therefore required on first launch.
- Offline ("cracked") mode generates a deterministic UUID from the supplied
  username, mirroring the official game's behaviour.
- Feel free to tweak styling constants (`bg_color`, `accent_color` etc.) or add
  more mod‑loader options (e.g. Quilt) – the code is intentionally modular.

--------------------------------------------------
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
import os
import json
import uuid
import subprocess
import platform
import re
import hashlib


class MelonLauncher:
    """Main application class – builds the UI, handles events & launches MC."""

    def __init__(self):
        # --------------------------------------------------
        # Logging
        # --------------------------------------------------
        logging.basicConfig(
            filename="melon_client.log",
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        logging.info("Melon Launcher starting up.")

        # --------------------------------------------------
        # Root window
        # --------------------------------------------------
        self.root = tk.Tk()
        self.root.title("Melon Client 1.0x")
        self.root.geometry("400x300")

        # Dark‑theme palette
        self.bg_color = "#2e2e2e"
        self.fg_color = "#ffffff"
        self.accent_color = "#5fbf00"
        self.root.configure(bg=self.bg_color)

        # --------------------------------------------------
        # ttk style tweaks for dark mode
        # --------------------------------------------------
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            # Some systems may miss the theme – silently ignore.
            pass

        style.configure("TLabel", background=self.bg_color, foreground=self.fg_color)
        style.configure("TButton", background=self.bg_color, foreground=self.fg_color)
        style.map("TButton", background=[("active", self.accent_color)])
        style.configure("TEntry", fieldbackground=self.bg_color, foreground=self.fg_color)
        style.configure(
            "TCombobox",
            fieldbackground=self.bg_color,
            background=self.bg_color,
            foreground=self.fg_color,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.bg_color)],
            foreground=[("readonly", self.fg_color)],
        )
        style.configure("Horizontal.TScale", background=self.bg_color)

        # --------------------------------------------------
        # State variables (Tk‑observable)
        # --------------------------------------------------
        self.username_var: tk.StringVar = tk.StringVar()
        self.login_type_var: tk.StringVar = tk.StringVar(value="offline")
        self.ram_var: tk.IntVar = tk.IntVar()

        # Allow slider to expose full system memory up to ram_max GB.
        self.ram_max = self._detect_max_ram() or 16

        # --------------------------------------------------
        # Load persisted configuration (if present)
        # --------------------------------------------------
        self.config: dict[str, object] = {}
        self._load_config()
        if "offline_username" in self.config:
            self.username_var.set(self.config["offline_username"])
        if "login_type" in self.config:
            self.login_type_var.set(self.config["login_type"])
        # Default to 4 GB or half available, whichever is smaller.
        self.ram_var.set(self.config.get("ram", min(4, self.ram_max)))

        # --------------------------------------------------
        # Build UI widgets
        # --------------------------------------------------
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        logging.info("UI initialised.")

    # ---------------------------------------------------------------------
    # ----- UI helpers -----------------------------------------------------
    # ---------------------------------------------------------------------
    def _build_ui(self):
        # Title banner
        tk.Label(
            self.root,
            text="Melon Client 1.0x",
            fg=self.fg_color,
            bg=self.bg_color,
            font=("Arial", 16, "bold"),
        ).pack(pady=10)

        # ------------ Login mode radio buttons ---------------------------
        login_frame = tk.Frame(self.root, bg=self.bg_color)
        login_frame.pack(pady=5)
        tk.Radiobutton(
            login_frame,
            text="Offline",
            variable=self.login_type_var,
            value="offline",
            command=self._update_login_ui,
            fg=self.fg_color,
            bg=self.bg_color,
            selectcolor=self.bg_color,
            activeforeground=self.accent_color,
        ).pack(side="left", padx=5)
        tk.Radiobutton(
            login_frame,
            text="Microsoft",
            variable=self.login_type_var,
            value="microsoft",
            command=self._update_login_ui,
            fg=self.fg_color,
            bg=self.bg_color,
            selectcolor=self.bg_color,
            activeforeground=self.accent_color,
        ).pack(side="left", padx=5)

        # Username entry (for offline mode)
        self.username_label = tk.Label(
            self.root, text="Username:", bg=self.bg_color, fg=self.fg_color
        )
        self.username_entry = tk.Entry(
            self.root,
            textvariable=self.username_var,
            bg="#454545",
            fg=self.fg_color,
            insertbackground=self.fg_color,
        )

        # Microsoft login button
        self.ms_button = tk.Button(
            self.root,
            text="Login with Microsoft",
            command=self._login_with_ms,
            bg="#454545",
            fg=self.fg_color,
            activebackground=self.accent_color,
        )

        # Game type combobox
        tk.Label(self.root, text="Game Type:", bg=self.bg_color, fg=self.fg_color).pack(
            pady=5
        )
        self.version_options = ("Vanilla", "Forge", "Fabric")
        self.version_var: tk.StringVar = tk.StringVar(value=self.version_options[0])
        ttk.Combobox(
            self.root,
            textvariable=self.version_var,
            values=self.version_options,
            state="readonly",
        ).pack(pady=5)

        # RAM slider
        self.ram_label = tk.Label(
            self.root,
            text=f"RAM Allocation (GB): {self.ram_var.get()}",
            bg=self.bg_color,
            fg=self.fg_color,
        )
        self.ram_label.pack(pady=5)
        ttk.Scale(
            self.root,
            from_=1,
            to=self.ram_max,
            orient="horizontal",
            variable=self.ram_var,
            command=self._on_ram_slider_change,
        ).pack(pady=5, fill="x", padx=20)

        # Launch button
        tk.Button(
            self.root,
            text="Launch",
            command=self._launch,
            bg=self.accent_color,
            fg="black",
            activebackground="#7fe34a",
        ).pack(pady=10)

        # Initial visibility pass
        self._update_login_ui()

    # ------------------------------------------------------------------
    # ----- Helper funcs -------------------------------------------------
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_username(name: str) -> bool:
        """Return True if *name* matches Minecraft offline rules."""
        return bool(name and 3 <= len(name) <= 16 and re.fullmatch(r"[A-Za-z0-9_]+", name))

    def _detect_max_ram(self) -> int | None:
        """Detect total system RAM in GB (best‑effort, cross‑platform)."""
        try:
            system = platform.system()
            if system == "Windows":
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_uint64),
                        ("ullAvailPhys", ctypes.c_uint64),
                        ("ullTotalPageFile", ctypes.c_uint64),
                        ("ullAvailPageFile", ctypes.c_uint64),
                        ("ullTotalVirtual", ctypes.c_uint64),
                        ("ullAvailVirtual", ctypes.c_uint64),
                        ("ullAvailExtendedVirtual", ctypes.c_uint64),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                return max(1, stat.ullTotalPhys // 1024 ** 3)
            elif system == "Linux":
                with open("/proc/meminfo") as fp:
                    for line in fp:
                        if line.startswith("MemTotal:"):
                            total_kb = int(line.split()[1])
                            return max(1, (total_kb * 1024) // 1024 ** 3)
            elif system == "Darwin":  # macOS
                res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
                if res.returncode == 0:
                    return max(1, int(res.stdout.strip()) // 1024 ** 3)
        except Exception as exc:
            logging.warning("RAM detection failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # ----- UI event callbacks ------------------------------------------
    # ------------------------------------------------------------------
    def _update_login_ui(self):
        """Toggle visibility of username entry vs. MS button."""
        if self.login_type_var.get() == "offline":
            self.username_label.pack(pady=5)
            self.username_entry.pack(pady=5)
            self.ms_button.pack_forget()
        else:
            self.username_label.pack_forget()
            self.username_entry.pack_forget()
            self.ms_button.pack(pady=5)

    def _on_ram_slider_change(self, value: str):
        self.ram_label.config(text=f"RAM Allocation (GB): {int(float(value))}")

    # ------------------------------------------------------------------
    # ----- Login & launch logic ----------------------------------------
    # ------------------------------------------------------------------
    def _login_with_ms(self):
        """Stub for future Microsoft OAuth flow."""
        logging.info("Microsoft login initiated (placeholder).")
        messagebox.showinfo("Microsoft Login", "Microsoft login is not implemented in this version.")
        self.ms_profile = {"name": "Player", "id": str(uuid.uuid4())}
        self.ms_token = "placeholder_token"
        logging.info("Microsoft login placeholder complete (user: %s).", self.ms_profile["name"])

    def _launch(self):
        """Validate settings and spawn Minecraft via minecraft-launcher-lib."""
        logging.info("Launch initiated by user.")
        login_type = self.login_type_var.get()
        username = self.username_var.get().strip()
        game_type = self.version_var.get()
        ram_gb = self.ram_var.get()
        logging.info("Settings – mode=%s, user=%s, type=%s, RAM=%sG", login_type, username, game_type, ram_gb)

        # ---- Validate username if offline -----------------------------
        if login_type == "offline" and not self._validate_username(username):
            logging.warning("Invalid offline username: %s", username)
            messagebox.showerror(
                "Invalid Username",
                "Username must be 3–16 characters long and contain only letters, numbers, and underscores.",
            )
            return

        # ---- Ensure Microsoft login happened --------------------------
        if login_type == "microsoft" and not hasattr(self, "ms_profile"):
            logging.warning("Microsoft login missing before launch.")
            messagebox.showerror("Not Logged In", "Please log in with Microsoft before launching.")
            return

        # ---- Persist config ------------------------------------------
        if login_type == "offline":
            self.config["offline_username"] = username
        self.config["login_type"] = login_type
        self.config["ram"] = ram_gb
        self._save_config()

        # ---- Import launcher lib -------------------------------------
        try:
            import minecraft_launcher_lib  # noqa: PD401
        except ImportError:
            logging.error("minecraft_launcher_lib missing; aborting launch.")
            messagebox.showwarning("Launch Unavailable", "Install 'minecraft-launcher-lib' to enable launching.")
            return

        mc_dir = minecraft_launcher_lib.utils.get_minecraft_directory()

        # ---- Pick appropriate MC version -----------------------------
        try:
            installed = minecraft_launcher_lib.utils.get_installed_versions(mc_dir)
            if game_type == "Vanilla":
                version_id = minecraft_launcher_lib.utils.get_latest_version()["release"]
            elif game_type == "Forge":
                version_id = next((v["id"] for v in installed if "forge" in v.get("id", "").lower()), None)
            elif game_type == "Fabric":
                version_id = next((v["id"] for v in installed if "fabric" in v.get("id", "").lower()), None)
            if not version_id:
                version_id = minecraft_launcher_lib.utils.get_latest_version()["release"]
                game_type = "Vanilla"
            logging.info("Using version_id=%s (%s)", version_id, game_type)
        except Exception as exc:
            logging.error("Version selection failed: %s", exc)
            messagebox.showerror("Launch Error", f"Could not determine game version: {exc}")
            return

        # ---- Ensure version assets exist -----------------------------
        try:
            minecraft_launcher_lib.install.install_minecraft_version(version_id, mc_dir)
        except Exception as exc:
            logging.error("Installation of %s failed: %s", version_id, exc)
            messagebox.showerror("Installation Error", f"Failed to install Minecraft {version_id}: {exc}")
            return

        # ---- Session data -------------------------------------------
        if login_type == "offline":
            # Generate deterministic UUID (per Mojang offline scheme)
            digest = hashlib.md5(f"OfflinePlayer:{username}".encode()).digest()
            digest = bytearray(digest)
            digest[6] = (digest[6] & 0x0F) | 0x30  # Version 3 UUID
            digest[8] = (digest[8] & 0x3F) | 0x80  # Variant 10
            session = {"name": username, "id": str(uuid.UUID(bytes=bytes(digest))), "token": ""}
        else:
            session = {
                "name": self.ms_profile["name"],
                "id": self.ms_profile["id"],
                "token": self.ms_token,
            }
        logging.info("Session for launch: %s", session)

        # ---- Build JVM/MC command -----------------------------------
        options = {
            "username": session["name"],
            "uuid": session["id"],
            "token": session["token"],
            "jvmArguments": [f"-Xmx{ram_gb}G", f"-Xms{max(1, ram_gb // 2)}G"],
        }
        try:
            cmd = minecraft_launcher_lib.command.get_minecraft_command(version_id, mc_dir, options)
            logging.info("Executing command: %s", " ".join(cmd[:8]) + " ...")
            subprocess.Popen(cmd)
            messagebox.showinfo("Launching", f"Launching Minecraft ({game_type}) …")
            logging.info("Minecraft launched.")
        except Exception as exc:
            logging.error("Launch error: %s", exc)
            messagebox.showerror("Launch Failed", f"An error occurred while launching: {exc}")

    # ------------------------------------------------------------------
    # ----- Config persistence -----------------------------------------
    # ------------------------------------------------------------------
    def _load_config(self):
        try:
            with open("melonclient_config.json", "r", encoding="utf-8") as fp:
                self.config = json.load(fp)
            logging.info("Configuration loaded from file.")
        except FileNotFoundError:
            logging.info("No configuration file; starting with defaults.")
            self.config = {}
        except Exception as exc:
            logging.error("Failed to load config: %s", exc)
            self.config = {}

    def _save_config(self):
        try:
            with open("melonclient_config.json", "w", encoding="utf-8") as fp:
                json.dump(self.config, fp, indent=2)
            logging.info("Configuration saved.")
        except Exception as exc:
            logging.error("Failed to save config: %s", exc)

    # ------------------------------------------------------------------
    # ----- App shutdown ----------------------------------------------
    # ------------------------------------------------------------------
    def _on_close(self):
        self._save_config()
        logging.info("Exiting Melon Launcher.")
        self.root.destroy()


# ----------------------------------------------------------------------
# Entry point -----------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = MelonLauncher()
    app.root.mainloop()
