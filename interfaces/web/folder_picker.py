"""Native folder dialog in its own main thread (Linux)."""
from __future__ import annotations


def main():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes('-topmost', True)
        folder = filedialog.askdirectory(parent=root, title='Папка для сохранения документов', mustexist=True)
        print(folder or '', flush=True)
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
