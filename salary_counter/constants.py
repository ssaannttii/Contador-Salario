# salary_counter/constants.py

SETTINGS_FILE = "settings.json"
EXCHANGE_RATE_API = "https://api.exchangerate-api.com/v4/latest/"
MONTHLY_SUMMARY_FILE = "monthly_summary.csv"
SUPPORTED_CURRENCIES = ["USD", "EUR", "GBP"]
DEFAULT_SETTINGS = {
    "hourly_rate": 20.0,
    "tax_rate": 15.0,
    "is_autonomo": True,
    "base_currency": "USD",
    "start_date": "2025-01-01",
    "work_start_time": "09:00",
    "work_end_time": "17:00",
    "non_working_days": [],
    "selected_theme": "dark"
}
