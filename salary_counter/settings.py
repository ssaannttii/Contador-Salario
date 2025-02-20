# salary_counter/settings.py

import json
import os
from .constants import SETTINGS_FILE, DEFAULT_SETTINGS

class SettingsManager:
    def __init__(self):
        self.settings = DEFAULT_SETTINGS.copy()
        self.load_settings()

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
                    loaded_settings = json.load(file)
                self.settings.update(loaded_settings)
                print("Settings loaded successfully.")
            except Exception as e:
                print(f"Error loading settings: {e}")
        else:
            self.save_settings()

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
                json.dump(self.settings, file, indent=4)
            print("Settings saved successfully.")
        except Exception as e:
            print(f"Error saving settings: {e}")

    def update_setting(self, key, value):
        self.settings[key] = value
        self.save_settings()

    def get_setting(self, key):
        return self.settings.get(key, DEFAULT_SETTINGS.get(key))
