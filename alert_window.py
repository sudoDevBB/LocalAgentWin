"""Show a centered, topmost room alert on the Windows server display."""

import ctypes
import sys
import tkinter as tk


def wake_display():
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
    # F15 has no normal typing effect, but counts as input to dismiss an active
    # screen saver. It does not unlock a locked Windows session.
    user32.keybd_event(0x7E, 0, 0, 0)
    user32.keybd_event(0x7E, 0, 0x0002, 0)


def main():
    room = sys.argv[1] if len(sys.argv) > 1 else "Unknown room"
    recipient = sys.argv[2] if len(sys.argv) > 2 else ""
    wake_display()

    window = tk.Tk()
    window.title("Soundroom · Room bell")
    window.configure(bg="#18232a")
    window.attributes("-topmost", True)
    width, height = 760, 330
    x = max(0, (window.winfo_screenwidth() - width) // 2)
    y = max(0, (window.winfo_screenheight() - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.resizable(False, False)

    tk.Label(window, text="SOUND ALERT", bg="#18232a", fg="#e5c45e",
             font=("Segoe UI", 13, "bold")).pack(pady=(38, 12))
    tk.Label(window, text=f"{recipient or 'Please attend'}: Room\n{room}", bg="#18232a", fg="#fffaf0",
             font=("Segoe UI", 30, "bold"), justify="center", wraplength=680).pack(expand=True)
    tk.Button(window, text="Acknowledge", command=window.destroy, width=18, height=2,
              bg="#d8b548", fg="#18232a", activebackground="#e5c45e",
              font=("Segoe UI", 12, "bold"), relief="flat").pack(pady=(0, 28))
    window.after(100, lambda: (window.lift(), window.focus_force(), window.attributes("-topmost", True)))
    window.after(60000, window.destroy)
    try:
        window.mainloop()
    finally:
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == "__main__":
    main()
