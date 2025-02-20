# salary_counter/utils.py

import os
import json
from datetime import datetime, timedelta, date
import calendar
import requests
import threading
from .constants import EXCHANGE_RATE_API, MONTHLY_SUMMARY_FILE

def generate_monthly_summary(year: int, month: int, settings: dict, non_working_days: set) -> dict:
    try:
        hourly_rate = float(settings.get("hourly_rate", 20.0))
    except ValueError:
        hourly_rate = 20.0

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    total_seconds = 0
    current = first_day
    while current <= last_day:
        date_str = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and date_str not in non_working_days:
            try:
                work_start = datetime.strptime(settings.get("work_start_time", "09:00"), "%H:%M").time()
                work_end = datetime.strptime(settings.get("work_end_time", "17:00"), "%H:%M").time()
            except ValueError:
                work_start = datetime.strptime("09:00", "%H:%M").time()
                work_end = datetime.strptime("17:00", "%H:%M").time()

            start_dt = datetime.combine(current, work_start)
            end_dt = datetime.combine(current, work_end)
            seconds = max(0, (end_dt - start_dt).total_seconds())
            total_seconds += seconds
        current += timedelta(days=1)

    total_hours = round(total_seconds / 3600.0, 2)
    total_earnings = round(total_hours * hourly_rate, 2)
    return {
        "year": year,
        "month": month,
        "total_hours": total_hours,
        "total_earnings": total_earnings
    }

def save_monthly_summary(summary: dict, net_eur: float, filename: str = MONTHLY_SUMMARY_FILE):
    file_exists = os.path.exists(filename)
    try:
        with open(filename, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write("Año,Mes,Horas Totales,Ganancia Bruta (Base),Ganancia Neta (EUR)\n")
            f.write("{year},{month},{total_hours},{total_earnings},{net_earnings}\n".format(
                net_earnings=net_eur, **summary))
        print("Monthly summary saved.")
    except Exception as e:
        print(f"Error saving monthly summary: {e}")

def fetch_exchange_rate(base_currency: str, callback, error_callback):
    def worker():
        try:
            url = EXCHANGE_RATE_API + base_currency
            response = requests.get(url, timeout=10)
            print(f"API Response: {response.text}")  # Debugging
            if response.status_code == 200:
                data = response.json()
                rate = data.get("rates", {}).get("EUR")
                if rate:
                    callback(round(rate, 4))
                else:
                    error_callback("EUR rate not found in response.")
            else:
                error_callback(f"API response status code: {response.status_code}")
        except Exception as e:
            error_callback(str(e))
    threading.Thread(target=worker, daemon=True).start()
