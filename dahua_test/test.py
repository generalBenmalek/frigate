import threading
import tkinter as tk

from tkinter import (
    ttk,
    messagebox,
)

from datetime import (
    datetime,
    timedelta,
)

import requests

from dahua_adapter import (
    DahuaAccessController,
)


# ============================================================
# COLORS
# ============================================================

BG = "#111827"
PANEL = "#1f2937"
TEXT = "#f9fafb"
MUTED = "#9ca3af"
GREEN = "#22c55e"
RED = "#ef4444"
BLUE = "#3b82f6"


# ============================================================
# APPLICATION
# ============================================================

class AccessControllerUI:

    def __init__(
        self,
        root,
    ):

        self.root = root

        self.root.title(
            "Dahua Access Controller"
        )

        self.root.geometry(
            "1100x700"
        )

        self.root.configure(
            bg=BG
        )

        self.ac = None

        self.live_thread = None

        self.live_running = False

        self.build_ui()

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):

        # ----------------------------------------------------
        # CONNECTION PANEL
        # ----------------------------------------------------

        connection = tk.Frame(
            self.root,
            bg=PANEL,
            padx=15,
            pady=15,
        )

        connection.pack(
            fill="x"
        )

        tk.Label(
            connection,
            text="Dahua Access Controller",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 18, "bold"),
        ).grid(
            row=0,
            column=0,
            columnspan=8,
            sticky="w",
            pady=(0, 12),
        )

        self.ip_entry = self.field(
            connection,
            "IP:",
            "127.0.0.1",
            1,
            0,
        )

        self.port_entry = self.field(
            connection,
            "Port:",
            "8080",
            1,
            2,
        )

        self.user_entry = self.field(
            connection,
            "Username:",
            "admin",
            1,
            4,
        )

        self.password_entry = self.field(
            connection,
            "Password:",
            "",
            1,
            6,
        )

        self.connect_button = tk.Button(
            connection,
            text="Connect",
            command=self.connect,
            bg=BLUE,
            fg="white",
            relief="flat",
            padx=15,
            pady=5,
        )

        self.connect_button.grid(
            row=2,
            column=0,
            columnspan=2,
            pady=12,
            sticky="w",
        )

        self.status_label = tk.Label(
            connection,
            text="● DISCONNECTED",
            bg=PANEL,
            fg=RED,
            font=("Segoe UI", 11, "bold"),
        )

        self.status_label.grid(
            row=2,
            column=2,
            columnspan=3,
            sticky="w",
        )

        # ----------------------------------------------------
        # DEVICE INFO
        # ----------------------------------------------------

        info = tk.LabelFrame(
            self.root,
            text="Controller Information",
            bg=PANEL,
            fg=TEXT,
            padx=10,
            pady=10,
        )

        info.pack(
            fill="x",
            padx=10,
            pady=10,
        )

        self.info_text = tk.Label(
            info,
            text="Not connected",
            bg=PANEL,
            fg=TEXT,
            justify="left",
            font=("Consolas", 10),
        )

        self.info_text.pack(
            anchor="w"
        )

        # ----------------------------------------------------
        # MAIN AREA
        # ----------------------------------------------------

        main = tk.Frame(
            self.root,
            bg=BG,
        )

        main.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=5,
        )

        # ----------------------------------------------------
        # EVENTS
        # ----------------------------------------------------

        events_frame = tk.LabelFrame(
            main,
            text="Live Events",
            bg=PANEL,
            fg=TEXT,
        )

        events_frame.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(0, 5),
        )

        self.events = tk.Text(
            events_frame,
            bg="#0b1120",
            fg=TEXT,
            insertbackground=TEXT,
            font=("Consolas", 10),
        )

        self.events.pack(
            fill="both",
            expand=True,
            padx=5,
            pady=5,
        )

        # ----------------------------------------------------
        # SIMULATOR PANEL
        # ----------------------------------------------------

        sim = tk.LabelFrame(
            main,
            text="Simulator Controls",
            bg=PANEL,
            fg=TEXT,
            padx=10,
            pady=10,
        )

        sim.pack(
            side="right",
            fill="y",
            padx=(5, 0),
        )

        tk.Label(
            sim,
            text="User ID",
            bg=PANEL,
            fg=TEXT,
        ).pack(
            anchor="w"
        )

        self.sim_user = tk.Entry(
            sim,
            width=25,
        )

        self.sim_user.insert(
            0,
            "Mohamed",
        )

        self.sim_user.pack(
            pady=(0, 10)
        )

        tk.Label(
            sim,
            text="Card Number",
            bg=PANEL,
            fg=TEXT,
        ).pack(
            anchor="w"
        )

        self.sim_card = tk.Entry(
            sim,
            width=25,
        )

        self.sim_card.insert(
            0,
            "12345",
        )

        self.sim_card.pack(
            pady=(0, 10)
        )

        tk.Label(
            sim,
            text="Door",
            bg=PANEL,
            fg=TEXT,
        ).pack(
            anchor="w"
        )

        self.sim_door = tk.Entry(
            sim,
            width=25,
        )

        self.sim_door.insert(
            0,
            "0",
        )

        self.sim_door.pack(
            pady=(0, 15)
        )

        self.sim_button(
            sim,
            "🟢 Access Granted",
            "grant",
        )

        self.sim_button(
            sim,
            "🔴 Access Denied",
            "deny",
        )

        self.sim_button(
            sim,
            "🚪 Door Opened",
            "open",
        )

        self.sim_button(
            sim,
            "🚪 Door Closed",
            "close",
        )

        ttk.Separator(
            sim,
            orient="horizontal",
        ).pack(
            fill="x",
            pady=15,
        )

        tk.Button(
            sim,
            text="🔴 Set OFFLINE",
            command=self.sim_offline,
            bg=RED,
            fg="white",
            relief="flat",
            width=22,
        ).pack(
            pady=3
        )

        tk.Button(
            sim,
            text="🟢 Set ONLINE",
            command=self.sim_online,
            bg=GREEN,
            fg="white",
            relief="flat",
            width=22,
        ).pack(
            pady=3
        )

        tk.Button(
            sim,
            text="📜 Load History",
            command=self.load_history,
            bg="#374151",
            fg="white",
            relief="flat",
            width=22,
        ).pack(
            pady=15
        )

    # ========================================================
    # FIELD
    # ========================================================

    def field(
        self,
        parent,
        label,
        default,
        row,
        column,
    ):

        tk.Label(
            parent,
            text=label,
            bg=PANEL,
            fg=MUTED,
        ).grid(
            row=row,
            column=column,
            padx=5,
        )

        entry = tk.Entry(
            parent,
            width=18,
        )

        entry.insert(
            0,
            default,
        )

        entry.grid(
            row=row,
            column=column + 1,
            padx=5,
        )

        return entry

    # ========================================================
    # BUTTON
    # ========================================================

    def sim_button(
        self,
        parent,
        text,
        event_type,
    ):

        tk.Button(
            parent,
            text=text,
            command=lambda:
                self.sim_event(event_type),
            bg="#374151",
            fg="white",
            relief="flat",
            width=22,
        ).pack(
            pady=3
        )

    # ========================================================
    # CONNECT
    # ========================================================

    def connect(self):

        try:

            ip = self.ip_entry.get()

            port = int(
                self.port_entry.get()
            )

            username = (
                self.user_entry.get()
            )

            password = (
                self.password_entry.get()
            )

            self.ac = (
                DahuaAccessController(
                    ip=ip,
                    username=username,
                    password=password,
                    port=port,
                    use_auth=False,
                )
            )

            if not self.ac.is_online():

                raise ConnectionError(
                    "Controller is offline."
                )

            info = (
                self.ac.get_system_info()
            )

            self.show_info(
                info
            )

            self.status_label.config(
                text="● ONLINE",
                fg=GREEN,
            )

            self.start_live_events()

        except Exception as e:

            self.status_label.config(
                text="● OFFLINE",
                fg=RED,
            )

            messagebox.showerror(
                "Connection failed",
                str(e),
            )

    # ========================================================
    # DEVICE INFO
    # ========================================================

    def show_info(
        self,
        info,
    ):

        text = (
            f"Device Type : "
            f"{info.get('deviceType', '-')}\n"
            f"Name        : "
            f"{info.get('deviceName', '-')}\n"
            f"Serial      : "
            f"{info.get('serialNumber', '-')}\n"
            f"Channels    : "
            f"{info.get('channelNumber', '-')}\n"
            f"Firmware    : "
            f"{info.get('firmwareVersion', '-')}"
        )

        self.info_text.config(
            text=text
        )

    # ========================================================
    # LIVE EVENTS
    # ========================================================

    def start_live_events(self):

        if self.live_running:
            return

        self.live_running = True

        self.live_thread = threading.Thread(
            target=self.live_worker,
            daemon=True,
        )

        self.live_thread.start()

    def live_worker(self):

        while self.live_running:

            try:

                self.ac.listen_events(
                    self.on_event
                )

            except Exception:

                self.root.after(
                    0,
                    self.set_offline
                )

                time.sleep(2)

    # ========================================================
    # EVENT CALLBACK
    # ========================================================

    def on_event(
        self,
        event,
    ):

        self.root.after(
            0,
            lambda:
                self.display_event(
                    event
                )
        )

    def display_event(
        self,
        event,
    ):

        self.events.insert(
            "end",
            "\n"
            + "=" * 60
            + "\n"
            + str(event)
            + "\n",
        )

        self.events.see(
            "end"
        )

    # ========================================================
    # OFFLINE / ONLINE
    # ========================================================

    def set_offline(self):

        self.status_label.config(
            text="● OFFLINE",
            fg=RED,
        )

    def sim_offline(self):

        try:

            requests.get(
                "http://127.0.0.1:8080/sim/offline",
                timeout=2,
            )

            self.set_offline()

        except Exception as e:

            messagebox.showerror(
                "Error",
                str(e),
            )

    def sim_online(self):

        try:

            requests.get(
                "http://127.0.0.1:8080/sim/online",
                timeout=2,
            )

            self.status_label.config(
                text="● ONLINE",
                fg=GREEN,
            )

        except Exception as e:

            messagebox.showerror(
                "Error",
                str(e),
            )

    # ========================================================
    # SIMULATE EVENT
    # ========================================================

    def sim_event(
        self,
        event_type,
    ):

        try:

            params = {
                "type":
                    event_type,

                "user":
                    self.sim_user.get(),

                "card":
                    self.sim_card.get(),

                "door":
                    self.sim_door.get(),
            }

            requests.get(
                "http://127.0.0.1:8080/sim/event",
                params=params,
                timeout=2,
            )

        except Exception as e:

            messagebox.showerror(
                "Simulator error",
                str(e),
            )

    # ========================================================
    # HISTORY
    # ========================================================

    def load_history(self):

        try:

            records = (
                self.ac.get_access_records(
                    datetime.now()
                    - timedelta(days=1),
                    datetime.now(),
                )
            )

            self.events.insert(
                "end",
                "\n\n"
                + "=" * 60
                + "\n"
                + "HISTORICAL EVENTS\n"
                + "=" * 60
                + "\n",
            )

            for record in records:

                self.events.insert(
                    "end",
                    str(record)
                    + "\n",
                )

            self.events.see(
                "end"
            )

        except Exception as e:

            messagebox.showerror(
                "History error",
                str(e),
            )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    import time

    root = tk.Tk()

    app = AccessControllerUI(
        root
    )

    root.mainloop()