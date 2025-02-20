# salary_counter/main.py

import tkinter as tk
from .settings import SettingsManager
from .gui import SalaryCounterApp

def main():
    root = tk.Tk()
    settings_manager = SettingsManager()
    app = SalaryCounterApp(root, settings_manager)
    root.mainloop()

if __name__ == "__main__":
    main()
