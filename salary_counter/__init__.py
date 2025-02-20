import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import Calendar
from datetime import datetime, timedelta, date
import calendar
import json
import os
import requests
import threading

# Sun Valley theme for modern look
# pip install sv-ttk
import sv_ttk

SETTINGS_FILE = "settings.json"
EXCHANGE_RATE_API = "https://api.exchangerate-api.com/v4/latest/"

class PatchedCalendar(Calendar):
    def __init__(self, *args, **kwargs):
        self._properties = {"style": None}
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        if key == "style":
            self._properties["style"] = value
            return
        self._properties[key] = value

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

def save_monthly_summary(summary: dict, net_eur: float, filename: str = "monthly_summary.csv"):
    file_exists = os.path.exists(filename)
    with open(filename, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write("Año,Mes,Horas Totales,Ganancia Bruta (Base),Ganancia Neta (EUR)\n")
        f.write("{year},{month},{total_hours},{total_earnings},{net_earnings}\n".format(
            net_earnings=net_eur, **summary))

class SalaryCounterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Contador de Salario - Sun Valley UI")

        # Initially set a theme; we can toggle later
        sv_ttk.set_theme("dark")

        self.root.geometry("1000x800")

        # Setup a menubar for extra UI flair
        self.create_menubar()

        # Default settings
        self.settings = {
            "hourly_rate": 20.0,
            "tax_rate": 15.0,
            "is_autonomo": True,
            "base_currency": "USD",
            "start_date": "2025-01-01",
            "work_start_time": "09:00",
            "work_end_time": "17:00",
            "non_working_days": []
        }

        # Data variables
        self.hourly_rate = tk.DoubleVar(value=20.0)
        self.tax_rate = tk.DoubleVar(value=15.0)
        self.is_autonomo = tk.BooleanVar(value=True)
        self.base_currency = tk.StringVar(value="USD")
        self.start_date = tk.StringVar(value="2025-01-01")
        self.work_start_time = tk.StringVar(value="09:00")
        self.work_end_time = tk.StringVar(value="17:00")

        self.exchange_rate = tk.DoubleVar(value=1.0)
        self.total_earned = tk.StringVar(value="0.00")
        self.total_converted = tk.StringVar(value="0.00")
        self.net_earned = tk.StringVar(value="0.00")

        self.non_working_days = set()
        self.non_working_events = {}

        self.last_summary_generated = None
        self.last_exchange_update = None

        # Create Notebook with tabs for better UX
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, pady=10, padx=10)

        # We'll create three tabs: Dashboard, Calendar, and Settings
        self.dashboard_frame = ttk.Frame(self.notebook, padding=10)
        self.calendar_frame = ttk.Frame(self.notebook, padding=10)
        self.settings_frame = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.dashboard_frame, text="Dashboard")
        self.notebook.add(self.calendar_frame, text="Calendario")
        self.notebook.add(self.settings_frame, text="Configuración")

        # Build UI in each tab
        self.setup_dashboard_tab()
        self.setup_calendar_tab()
        self.setup_settings_tab()

        self.load_settings()
        self.load_non_working_days()

        # Start the initial exchange rate fetch
        self.update_exchange_rate()

        # Real-time updates every second
        self.update_earnings()

        # Refresh exchange rate every hour
        self.root.after(3600000, self.update_exchange_rate)

    def create_menubar(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

    # ---------------------------
    # TAB 1: Dashboard
    # ---------------------------
    def setup_dashboard_tab(self):
        # Earnings Dashboard
        earnings_frame = ttk.LabelFrame(self.dashboard_frame, text="Earnings Dashboard", padding=10)
        earnings_frame.pack(fill="x", pady=10)

        self.gross_label = ttk.Label(
            earnings_frame, text="Ganancia Bruta (USD):", font=("Arial", 14)
        )
        self.gross_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        ttk.Label(
            earnings_frame,
            textvariable=self.total_earned,
            font=("Arial", 28, "bold"),
            foreground="#28a745"
        ).grid(row=0, column=1, sticky="e", padx=5, pady=5)

        ttk.Label(
            earnings_frame,
            text="Convertido a EUR (Bruto):",
            font=("Arial", 14)
        ).grid(row=1, column=0, sticky="w", padx=5, pady=5)

        ttk.Label(
            earnings_frame,
            textvariable=self.total_converted,
            font=("Arial", 28, "bold"),
            foreground="#6f42c1"
        ).grid(row=1, column=1, sticky="e", padx=5, pady=5)

        ttk.Label(
            earnings_frame,
            text="Ganancia Neta (EUR):",
            font=("Arial", 14)
        ).grid(row=2, column=0, sticky="w", padx=5, pady=5)

        ttk.Label(
            earnings_frame,
            textvariable=self.net_earned,
            font=("Arial", 28, "bold"),
            foreground="#007bff"
        ).grid(row=2, column=1, sticky="e", padx=5, pady=5)

        # Exchange Rate Frame
        ex_frame = ttk.LabelFrame(self.dashboard_frame, text="Tasa de Cambio", padding=10)
        ex_frame.pack(fill="x", pady=10)

        self.ex_rate_label = ttk.Label(ex_frame, text="Tasa de Cambio (USD → EUR): 1.0000", font=("Arial", 12))
        self.ex_rate_label.pack(side="left", padx=5)

        self.last_update_label = ttk.Label(ex_frame, text="Última actualización: --:--", font=("Arial", 10))
        self.last_update_label.pack(side="right", padx=5)

        # Theme toggle button for quick switching
        theme_toggle_btn = ttk.Button(
            self.dashboard_frame,
            text="Toggle Dark/Light",
            command=self.toggle_theme_mode
        )
        theme_toggle_btn.pack(pady=10)

    # ---------------------------
    # TAB 2: Calendar
    # ---------------------------
    def setup_calendar_tab(self):
        # Calendar Navigation
        nav_frame = ttk.Frame(self.calendar_frame)
        nav_frame.pack(side="top", fill="x", pady=5)

        self.prev_button = ttk.Button(nav_frame, text="◄", command=self.prev_month)
        self.prev_button.pack(side="left", padx=5)

        self.header_label = ttk.Label(nav_frame, text="", font=("Arial", 14, "bold"), anchor="center")
        self.header_label.pack(side="left", expand=True)

        self.next_button = ttk.Button(nav_frame, text="►", command=self.next_month)
        self.next_button.pack(side="right", padx=5)

        # Calendar widget
        self.calendar = PatchedCalendar(
            self.calendar_frame,
            selectmode='day',
            date_pattern="yyyy-mm-dd",
            locale="es_ES",
            firstweekday="monday",
            showweeknumbers=True,
            headerbackground="lightblue",
            headerforeground="black",
            headerfont=("Arial", 12, "bold")
        )
        self.calendar.pack(pady=5, fill="x")
        self.calendar.tag_config("nonworking", background="red", foreground="white")

        self.update_calendar_header()

        # Action Frame (mark unmark non-working days)
        self.action_frame = ttk.Frame(self.calendar_frame, padding=5)
        self.action_frame.pack(fill="x", pady=5)

        # Bind the selection event
        self.calendar.bind("<<CalendarSelected>>", self.on_date_selected)

    # ---------------------------
    # TAB 3: Settings
    # ---------------------------
    def setup_settings_tab(self):
        form = ttk.Frame(self.settings_frame)
        form.pack(fill="x", padx=10, pady=10)

        # Hourly Rate
        ttk.Label(form, text="Tarifa por Hora:", font=("Arial", 12)) \
            .grid(row=0, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.hourly_rate, font=("Arial", 12), width=10) \
            .grid(row=0, column=1, sticky="e", pady=5, padx=5)

        # Is Autonomo & Tax
        auton_chk = ttk.Checkbutton(form, text="Soy Autónomo", variable=self.is_autonomo, command=self.update_tax_state)
        auton_chk.grid(row=1, column=0, sticky="w", pady=5, padx=5)

        ttk.Label(form, text="Impuesto (%):", font=("Arial", 12)) \
            .grid(row=2, column=0, sticky="w", pady=5, padx=5)
        self.tax_entry = ttk.Entry(form, textvariable=self.tax_rate, font=("Arial", 12), width=10)
        self.tax_entry.grid(row=2, column=1, sticky="e", pady=5, padx=5)

        # Base Currency
        ttk.Label(form, text="Moneda Base:", font=("Arial", 12)) \
            .grid(row=3, column=0, sticky="w", pady=5, padx=5)
        currency_cb = ttk.Combobox(form, textvariable=self.base_currency, values=["USD", "EUR", "GBP"],
                                   state="readonly", font=("Arial", 12), width=5)
        currency_cb.grid(row=3, column=1, sticky="e", pady=5, padx=5)
        currency_cb.bind("<<ComboboxSelected>>", self.on_base_currency_changed)

        # Start date & times
        ttk.Label(form, text="Fecha de Inicio (YYYY-MM-DD):", font=("Arial", 12)) \
            .grid(row=4, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.start_date, font=("Arial", 12), width=12) \
            .grid(row=4, column=1, sticky="e", pady=5, padx=5)

        ttk.Label(form, text="Hora de Inicio (HH:MM):", font=("Arial", 12)) \
            .grid(row=5, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.work_start_time, font=("Arial", 12), width=5) \
            .grid(row=5, column=1, sticky="e", pady=5, padx=5)

        ttk.Label(form, text="Hora de Fin (HH:MM):", font=("Arial", 12)) \
            .grid(row=6, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.work_end_time, font=("Arial", 12), width=5) \
            .grid(row=6, column=1, sticky="e", pady=5, padx=5)

        # Save Button
        ttk.Button(self.settings_frame, text="Guardar Configuración", command=self.save_settings)\
            .pack(pady=10)

    # ---------------------------
    # Real-time Logic
    # ---------------------------
    def update_earnings(self):
        """Called every second to update the salary in near real-time."""
        try:
            self.apply_ui_to_settings()

            start_date = datetime.strptime(self.start_date.get(), "%Y-%m-%d")
            work_start = datetime.strptime(self.work_start_time.get(), "%H:%M").time()
            work_end = datetime.strptime(self.work_end_time.get(), "%H:%M").time()

            hourly = float(self.hourly_rate.get())
            now = datetime.now()

            if now.date() < start_date.date():
                gross_base = 0.0
            else:
                total_seconds = 0
                current_date = start_date
                while current_date.date() <= now.date():
                    date_str = current_date.strftime("%Y-%m-%d")
                    if current_date.weekday() < 5 and date_str not in self.non_working_days:
                        start_dt = datetime.combine(current_date.date(), work_start)
                        end_dt = datetime.combine(current_date.date(), work_end)

                        if current_date.date() == now.date():
                            if now.time() < work_start:
                                end_dt = start_dt
                            elif work_start <= now.time() <= work_end:
                                end_dt = datetime.combine(current_date.date(), now.time())

                        seconds = max(0, (end_dt - start_dt).total_seconds())
                        total_seconds += seconds

                    current_date += timedelta(days=1)

                total_hours = total_seconds / 3600.0
                gross_base = round(total_hours * hourly, 2)

            converted_gross = round(gross_base * self.exchange_rate.get(), 2)
            tax = float(self.tax_rate.get())
            net_eur = round(converted_gross * (1 - tax / 100.0), 2)

            self.gross_label.config(
                text=f"Ganancia Bruta ({self.base_currency.get()}):"
            )
            self.total_earned.set(f"{gross_base:.2f} {self.base_currency.get()}")
            self.total_converted.set(f"{converted_gross:.2f} EUR")
            self.net_earned.set(f"{net_eur:.2f} EUR")

        except ValueError as e:
            print("Error en el cálculo:", e)

        self.check_and_generate_monthly_summary()

        # Re-schedule in 1 second
        self.root.after(1000, self.update_earnings)

    # ---------------------------
    # Exchange Rate
    # ---------------------------
    def update_exchange_rate(self):
        """Fetch exchange rate in a separate thread."""
        def worker():
            base = self.base_currency.get() or "USD"
            try:
                url = EXCHANGE_RATE_API + base
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    rate = data.get("rates", {}).get("EUR")
                    if rate:
                        self.exchange_rate.set(round(rate, 4))
                        self.last_exchange_update = datetime.now()
                        self.root.after(0, lambda: self.update_exchange_rate_ui(base, rate))
                    else:
                        self.root.after(0, lambda: self.ex_rate_label.config(
                            text="Error: No se encontró tasa para EUR"))
                else:
                    self.root.after(0, lambda: self.ex_rate_label.config(
                        text=f"Error al consultar la tasa. Estado: {response.status_code}"))
            except Exception as e:
                self.root.after(0, lambda: self.ex_rate_label.config(
                    text=f"Error al consultar tasa: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def update_exchange_rate_ui(self, base, rate):
        self.ex_rate_label.config(text=f"Tasa de Cambio ({base} → EUR): 1 = {rate:.4f} EUR")
        if self.last_exchange_update:
            self.last_update_label.config(
                text="Última actualización: " + self.last_exchange_update.strftime("%H:%M:%S")
            )
        self.update_earnings()

    # ---------------------------
    # Monthly Summaries
    # ---------------------------
    def check_and_generate_monthly_summary(self):
        today = date.today()
        if today.day == 1:
            prev_month = today.month - 1 if today.month > 1 else 12
            prev_year = today.year if today.month > 1 else today.year - 1
            key = f"{prev_year}-{prev_month:02d}"

            if self.last_summary_generated != key:
                summary = generate_monthly_summary(prev_year, prev_month, self.settings, self.non_working_days)
                converted_gross = round(summary["total_earnings"] * self.exchange_rate.get(), 2)
                net_eur = round(converted_gross * (1 - self.tax_rate.get() / 100.0), 2)
                save_monthly_summary(summary, net_eur)

                messagebox.showinfo(
                    "Resumen Mensual",
                    f"Resumen de {calendar.month_name[prev_month]} {prev_year}:\n"
                    f"Horas Totales: {summary['total_hours']} hrs\n"
                    f"G. Bruta ({self.base_currency.get()}): {summary['total_earnings']}\n"
                    f"G. Neta (EUR): {net_eur}"
                )
                self.last_summary_generated = key

    # ---------------------------
    # Calendar Navigation
    # ---------------------------
    def update_calendar_header(self):
        try:
            current_date = self.calendar._date
        except AttributeError:
            try:
                current_date = datetime.strptime(self.calendar.get_date(), "%Y-%m-%d").date()
            except ValueError:
                current_date = date.today()

        self.header_label.config(
            text=f"{calendar.month_name[current_date.month]} {current_date.year}"
        )

    def prev_month(self):
        try:
            self.calendar._prev_month()
            new_date = date(self.calendar._date.year, self.calendar._date.month, 1)
            self.calendar.selection_set(new_date)
        except Exception as e:
            print("Error en prev_month:", e)
        self.update_calendar_header()

    def next_month(self):
        try:
            self.calendar._next_month()
            new_date = date(self.calendar._date.year, self.calendar._date.month, 1)
            self.calendar.selection_set(new_date)
        except Exception as e:
            print("Error en next_month:", e)
        self.update_calendar_header()

    # ---------------------------
    # Non-Working Days
    # ---------------------------
    def on_date_selected(self, event):
        for widget in self.action_frame.winfo_children():
            widget.destroy()

        selected_date_str = self.calendar.get_date()
        if selected_date_str:
            if selected_date_str in self.non_working_days:
                btn = ttk.Button(self.action_frame,
                                 text="Remover Día No Laborable",
                                 command=self.remove_non_working_day)
                btn.pack(side="left", padx=5, pady=5)
            else:
                btn = ttk.Button(self.action_frame,
                                 text="Marcar Día No Laborable",
                                 command=self.mark_non_working_day)
                btn.pack(side="left", padx=5, pady=5)

        self.update_calendar_header()

    def mark_non_working_day(self):
        selected_date_str = self.calendar.get_date()
        if selected_date_str not in self.non_working_days:
            self.non_working_days.add(selected_date_str)
            date_obj = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
            event_id = self.calendar.calevent_create(date_obj, "No Laborable", "nonworking")
            self.non_working_events[selected_date_str] = event_id
            self.save_settings()
            messagebox.showinfo("Éxito", f"{selected_date_str} marcado como día no laborable.")
        else:
            messagebox.showinfo("Información", f"{selected_date_str} ya está marcado como no laborable.")
        self.update_earnings()

    def remove_non_working_day(self):
        selected_date_str = self.calendar.get_date()
        if selected_date_str in self.non_working_days:
            self.non_working_days.remove(selected_date_str)
            event_id = self.non_working_events.get(selected_date_str)
            if event_id:
                self.calendar.calevent_remove(event_id)
                del self.non_working_events[selected_date_str]
            self.save_settings()
            messagebox.showinfo("Éxito", f"{selected_date_str} eliminado de los días no laborables.")
        else:
            messagebox.showerror("Error", f"{selected_date_str} no está marcado como día no laborable.")
        self.update_earnings()

    # ---------------------------
    # Settings
    # ---------------------------
    def save_settings(self):
        self.apply_ui_to_settings()
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
                json.dump(self.settings, file, indent=4)
            print("Configuración guardada.")
        except Exception as e:
            print("Error al guardar configuración:", e)

        self.update_tax_state()
        # We'll do a fresh exchange rate fetch if base currency changed
        self.update_exchange_rate()
        self.update_earnings()

    def apply_ui_to_settings(self):
        self.settings["hourly_rate"] = float(self.hourly_rate.get())
        self.settings["tax_rate"] = float(self.tax_rate.get())
        self.settings["is_autonomo"] = bool(self.is_autonomo.get())
        self.settings["base_currency"] = self.base_currency.get()
        self.settings["start_date"] = self.start_date.get()
        self.settings["work_start_time"] = self.work_start_time.get()
        self.settings["work_end_time"] = self.work_end_time.get()
        self.settings["non_working_days"] = list(self.non_working_days)

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
                    self.settings = json.load(file)
                self.hourly_rate.set(self.settings.get("hourly_rate", 20.0))
                self.tax_rate.set(self.settings.get("tax_rate", 15.0))
                self.is_autonomo.set(self.settings.get("is_autonomo", True))
                self.base_currency.set(self.settings.get("base_currency", "USD"))
                self.start_date.set(self.settings.get("start_date", "2025-01-01"))
                self.work_start_time.set(self.settings.get("work_start_time", "09:00"))
                self.work_end_time.set(self.settings.get("work_end_time", "17:00"))
                self.non_working_days = set(self.settings.get("non_working_days", []))

                print("Configuración cargada.")
                self.update_tax_state()
            except Exception as e:
                print("Error cargando configuración:", e)
        else:
            self.save_settings()

    def load_non_working_days(self):
        for date_str in self.non_working_days:
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                event_id = self.calendar.calevent_create(date_obj, "No Laborable", "nonworking")
                self.non_working_events[date_str] = event_id
            except ValueError as e:
                print(f"Error creando evento para {date_str}: {e}")

    def update_tax_state(self):
        """Enable or disable the tax entry based on autonomo status."""
        if self.is_autonomo.get():
            self.tax_rate.set(15.0)
            self.tax_entry.state(["disabled"])
        else:
            self.tax_entry.state(["!disabled"])

    # ---------------------------
    # Theme Toggle
    # ---------------------------
    def toggle_theme_mode(self):
        """A quick way to flip between dark and light with sv_ttk."""
        current_theme = sv_ttk.get_theme()
        if current_theme == "dark":
            sv_ttk.set_theme("light")
        else:
            sv_ttk.set_theme("dark")

        # In some cases, you might need to re-draw or re-pack to see changes instantly
        self.root.update_idletasks()

    # ---------------------------
    # Base Currency
    # ---------------------------
    def on_base_currency_changed(self, event=None):
        self.update_exchange_rate()
        self.update_earnings()


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = SalaryCounterApp(root)
    root.mainloop()
