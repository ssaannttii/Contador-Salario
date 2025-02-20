# salary_counter/gui.py

import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import Calendar
from datetime import datetime, timedelta, date
import calendar
import os
import csv
import sv_ttk

from .settings import SettingsManager
from .utils import generate_monthly_summary, save_monthly_summary, fetch_exchange_rate
from .constants import SUPPORTED_CURRENCIES, MONTHLY_SUMMARY_FILE

class PatchedCalendar(Calendar):
    def __init__(self, *args, **kwargs):
        self._properties = {"style": None}
        super().__init__(*args, **kwargs)
    def __setitem__(self, key, value):
        if key == "style":
            self._properties["style"] = value
            return
        self._properties[key] = value

class SalaryCounterApp:
    def __init__(self, root: tk.Tk, settings_manager: SettingsManager):
        self.root = root
        self.settings_manager = settings_manager
        self.settings = self.settings_manager.settings

        self.root.title("Contador de Salario - Sun Valley UI")
        sv_ttk.set_theme(self.settings.get("selected_theme", "dark"))
        self.root.geometry("1000x800")

        # Variables de datos
        self.hourly_rate = tk.DoubleVar(value=self.settings.get("hourly_rate", 20.0))
        self.tax_rate = tk.DoubleVar(value=self.settings.get("tax_rate", 15.0))
        self.is_autonomo = tk.BooleanVar(value=self.settings.get("is_autonomo", True))
        self.base_currency = tk.StringVar(value=self.settings.get("base_currency", "USD"))
        self.start_date = tk.StringVar(value=self.settings.get("start_date", "2025-01-01"))
        self.work_start_time = tk.StringVar(value=self.settings.get("work_start_time", "09:00"))
        self.work_end_time = tk.StringVar(value=self.settings.get("work_end_time", "17:00"))

        self.exchange_rate = tk.DoubleVar(value=1.0)
        # Las ganancias que se muestran en la zona principal se calculan en euros.
        self.total_earned = tk.StringVar(value="€0.00")
        self.net_earned = tk.StringVar(value="€0.00")

        self.non_working_days = set(self.settings.get("non_working_days", []))
        self.non_working_events = {}

        self.last_summary_generated = None  # Control interno para el resumen del mes anterior
        self.last_exchange_update = None

        # Notebook y pestañas
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, pady=10, padx=10)

        self.dashboard_frame = ttk.Frame(self.notebook, padding=10)
        self.calendar_frame = ttk.Frame(self.notebook, padding=10)
        self.settings_frame = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.dashboard_frame, text="Dashboard")
        self.notebook.add(self.calendar_frame, text="Calendario")
        self.notebook.add(self.settings_frame, text="Configuración")

        # Construir la interfaz en cada pestaña
        self.setup_dashboard_tab()
        self.setup_calendar_tab()
        self.setup_settings_tab()

        self.create_menubar()
        self.load_non_working_days()

        # Actualiza tasa de cambio y ganancias en tiempo real
        self.update_exchange_rate()
        self.update_earnings()
        self.root.after(3600000, self.update_exchange_rate)

        # Cargar el historial mensual (más la línea del mes actual) al iniciar
        self.update_monthly_summary_view()

    def create_menubar(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

    # ---------------------------
    # Pestaña Dashboard (Historial debajo de Ganancias)
    # ---------------------------
    def setup_dashboard_tab(self):
        # Zona superior: Ganancias y Tasa de Cambio
        top_frame = ttk.Frame(self.dashboard_frame)
        top_frame.pack(fill="x", padx=10, pady=10)

        earnings_frame = ttk.LabelFrame(top_frame, text="Dashboard de Ganancias", padding=10)
        earnings_frame.pack(fill="x", pady=5)

        # Se muestran las ganancias (convertidas a euros) en la zona principal
        self.gross_label = ttk.Label(earnings_frame, text="Ganancia Bruta (EUR):", font=("Arial", 14))
        self.gross_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Label(
            earnings_frame,
            textvariable=self.total_earned,
            font=("Arial", 28, "bold"),
            foreground="#28a745"
        ).grid(row=0, column=1, sticky="e", padx=5, pady=5)

        net_frame = ttk.Frame(earnings_frame)
        net_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        net_label = ttk.Label(net_frame, text="Ganancia Neta (EUR):", font=("Arial", 14))
        net_label.pack(side="left", padx=5)
        ttk.Label(
            net_frame,
            textvariable=self.net_earned,
            font=("Arial", 28, "bold"),
            foreground="#007bff"
        ).pack(side="right", padx=5)

        ex_frame = ttk.LabelFrame(top_frame, text="Tasa de Cambio", padding=10)
        ex_frame.pack(fill="x", pady=5)
        self.ex_rate_label = ttk.Label(ex_frame, text="Tasa de Cambio (USD → EUR): 1.0000", font=("Arial", 12))
        self.ex_rate_label.pack(side="left", padx=5)
        self.last_update_label = ttk.Label(ex_frame, text="Última actualización: --:--", font=("Arial", 10))
        self.last_update_label.pack(side="right", padx=5)

        theme_toggle_btn = ttk.Button(top_frame, text="Toggle Dark/Light", command=self.toggle_theme_mode)
        theme_toggle_btn.pack(pady=10)

        # Sección de historial mensual (colocada debajo de la zona principal)
        monthly_frame = ttk.LabelFrame(self.dashboard_frame, text="Historial Mensual", padding=10)
        monthly_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Columnas originales:
        # "Año", "Mes", "Horas Totales", "Ganancia Bruta (Base)" y "Ganancia Neta (EUR)"
        self.monthly_tree = ttk.Treeview(
            monthly_frame,
            columns=("Año", "Mes", "Horas Totales", "Ganancia Bruta (Base)", "Ganancia Neta (EUR)"),
            show="headings"
        )
        self.monthly_tree.heading("Año", text="Año")
        self.monthly_tree.heading("Mes", text="Mes")
        self.monthly_tree.heading("Horas Totales", text="Horas Totales")
        self.monthly_tree.heading("Ganancia Bruta (Base)", text="Ganancia Bruta (Base)")
        self.monthly_tree.heading("Ganancia Neta (EUR)", text="Ganancia Neta (EUR)")
        self.monthly_tree.pack(fill="both", expand=True)

    # ---------------------------
    # Método para generar resumen del mes actual
    # ---------------------------
    def generate_current_month_summary(self) -> dict:
        current_date = date.today()
        first_day = date(current_date.year, current_date.month, 1)
        total_seconds = 0
        iter_date = first_day
        while iter_date <= current_date:
            date_str = iter_date.strftime("%Y-%m-%d")
            if iter_date.weekday() < 5 and date_str not in self.non_working_days:
                try:
                    work_start = datetime.strptime(self.settings.get("work_start_time", "09:00"), "%H:%M").time()
                    work_end = datetime.strptime(self.settings.get("work_end_time", "17:00"), "%H:%M").time()
                except ValueError:
                    work_start = datetime.strptime("09:00", "%H:%M").time()
                    work_end = datetime.strptime("17:00", "%H:%M").time()
                start_dt = datetime.combine(iter_date, work_start)
                end_dt = datetime.combine(iter_date, work_end)
                seconds = max(0, (end_dt - start_dt).total_seconds())
                total_seconds += seconds
            iter_date += timedelta(days=1)
        total_hours = round(total_seconds / 3600.0, 2)
        try:
            hourly_rate = float(self.settings.get("hourly_rate", 20.0))
        except ValueError:
            hourly_rate = 20.0
        total_earnings = round(total_hours * hourly_rate, 2)
        return {
            "year": current_date.year,
            "month": current_date.month,
            "total_hours": total_hours,
            "total_earnings": total_earnings
        }

    # ---------------------------
    # Pestaña Calendario
    # ---------------------------
    def setup_calendar_tab(self):
        nav_frame = ttk.Frame(self.calendar_frame)
        nav_frame.pack(side="top", fill="x", pady=5)
        self.prev_button = ttk.Button(nav_frame, text="◄", command=self.prev_month)
        self.prev_button.pack(side="left", padx=5)
        self.header_label = ttk.Label(nav_frame, text="", font=("Arial", 14, "bold"), anchor="center")
        self.header_label.pack(side="left", expand=True)
        self.next_button = ttk.Button(nav_frame, text="►", command=self.next_month)
        self.next_button.pack(side="right", padx=5)
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
        self.action_frame = ttk.Frame(self.calendar_frame, padding=5)
        self.action_frame.pack(fill="x", pady=5)
        self.calendar.bind("<<CalendarSelected>>", self.on_date_selected)

    # ---------------------------
    # Pestaña Configuración
    # ---------------------------
    def setup_settings_tab(self):
        form = ttk.Frame(self.settings_frame)
        form.pack(fill="x", padx=10, pady=10)
        ttk.Label(form, text="Tarifa por Hora:", font=("Arial", 12)).grid(row=0, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.hourly_rate, font=("Arial", 12), width=10)\
            .grid(row=0, column=1, sticky="e", pady=5, padx=5)
        auton_chk = ttk.Checkbutton(form, text="Soy Autónomo", variable=self.is_autonomo, command=self.update_tax_state)
        auton_chk.grid(row=1, column=0, sticky="w", pady=5, padx=5)
        ttk.Label(form, text="Impuesto (%):", font=("Arial", 12)).grid(row=2, column=0, sticky="w", pady=5, padx=5)
        self.tax_entry = ttk.Entry(form, textvariable=self.tax_rate, font=("Arial", 12), width=10)
        self.tax_entry.grid(row=2, column=1, sticky="e", pady=5, padx=5)
        ttk.Label(form, text="Moneda Base:", font=("Arial", 12)).grid(row=3, column=0, sticky="w", pady=5, padx=5)
        currency_cb = ttk.Combobox(form, textvariable=self.base_currency, values=SUPPORTED_CURRENCIES,
                                     state="readonly", font=("Arial", 12), width=5)
        currency_cb.grid(row=3, column=1, sticky="e", pady=5, padx=5)
        currency_cb.bind("<<ComboboxSelected>>", self.on_base_currency_changed)
        ttk.Label(form, text="Fecha de Inicio (YYYY-MM-DD):", font=("Arial", 12))\
            .grid(row=4, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.start_date, font=("Arial", 12), width=12)\
            .grid(row=4, column=1, sticky="e", pady=5, padx=5)
        ttk.Label(form, text="Hora de Inicio (HH:MM):", font=("Arial", 12))\
            .grid(row=5, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.work_start_time, font=("Arial", 12), width=5)\
            .grid(row=5, column=1, sticky="e", pady=5, padx=5)
        ttk.Label(form, text="Hora de Fin (HH:MM):", font=("Arial", 12))\
            .grid(row=6, column=0, sticky="w", pady=5, padx=5)
        ttk.Entry(form, textvariable=self.work_end_time, font=("Arial", 12), width=5)\
            .grid(row=6, column=1, sticky="e", pady=5, padx=5)
        ttk.Label(form, text="Tema Seleccionado:", font=("Arial", 12))\
            .grid(row=7, column=0, sticky="w", pady=5, padx=5)
        theme_cb = ttk.Combobox(form, values=["dark", "light"], state="readonly", font=("Arial", 12), width=10)
        theme_cb.set(self.settings.get("selected_theme", "dark"))
        theme_cb.grid(row=7, column=1, sticky="e", pady=5, padx=5)
        theme_cb.bind("<<ComboboxSelected>>", self.on_theme_changed)
        ttk.Button(self.settings_frame, text="Guardar Configuración", command=self.save_settings)\
            .pack(pady=10)

    # ---------------------------
    # Lógica en Tiempo Real
    # ---------------------------
    def update_earnings(self):
        try:
            self.apply_ui_to_settings()
            start_date_dt = datetime.strptime(self.start_date.get(), "%Y-%m-%d")
            work_start = datetime.strptime(self.work_start_time.get(), "%H:%M").time()
            work_end = datetime.strptime(self.work_end_time.get(), "%H:%M").time()
            hourly = float(self.hourly_rate.get())
            now = datetime.now()
            if now.date() < start_date_dt.date():
                gross_base = 0.0
            else:
                total_seconds = 0
                current_date = start_date_dt
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
            # Convertir la ganancia bruta a euros usando la tasa de cambio
            converted_gross = round(gross_base * self.exchange_rate.get(), 2)
            tax = float(self.tax_rate.get())
            net_eur = round(converted_gross * (1 - tax / 100.0), 2)
            # Actualizar las etiquetas (se muestran en euros con el símbolo "€")
            self.gross_label.config(text="Ganancia Bruta (EUR):")
            self.total_earned.set(f"€{converted_gross:.2f}")
            self.net_earned.set(f"€{net_eur:.2f}")
        except ValueError as e:
            print("Error en el cálculo:", e)
        self.check_and_generate_monthly_summary()
        self.root.after(1000, self.update_earnings)

    # ---------------------------
    # Tasa de Cambio
    # ---------------------------
    def update_exchange_rate(self):
        base = self.base_currency.get() or "USD"
        fetch_exchange_rate(
            base,
            callback=lambda rate: self.root.after(0, lambda: self.on_exchange_rate_success(base, rate)),
            error_callback=lambda error: self.root.after(0, lambda: self.on_exchange_rate_failure(error))
        )
    def on_exchange_rate_success(self, base, rate):
        self.exchange_rate.set(rate)
        self.last_exchange_update = datetime.now()
        self.ex_rate_label.config(text=f"Tasa de Cambio ({base} → EUR): 1 = {rate:.4f} EUR")
        if self.last_exchange_update:
            self.last_update_label.config(text="Última actualización: " + self.last_exchange_update.strftime("%H:%M:%S"))
        self.update_earnings()
    def on_exchange_rate_failure(self, error_message):
        self.ex_rate_label.config(text=f"Error al consultar tasa: {error_message}")
        print(f"Exchange rate fetch error: {error_message}")

    # ---------------------------
    # Resúmenes Mensuales (Evita duplicados y añade línea del mes actual)
    # ---------------------------
    def check_and_generate_monthly_summary(self):
        """
        Se comprueba si el resumen del mes anterior ya existe en el CSV.
        Si no, se genera y se agrega; de lo contrario, no se vuelve a agregar.
        """
        today = date.today()
        previous_month = today.month - 1 if today.month > 1 else 12
        previous_year = today.year if today.month > 1 else today.year - 1
        key = f"{previous_year}-{previous_month:02d}"

        # Verificar si ya existe el resumen en el CSV
        summary_exists = False
        if os.path.exists(MONTHLY_SUMMARY_FILE):
            with open(MONTHLY_SUMMARY_FILE, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["Año"] == str(previous_year) and row["Mes"] == str(previous_month):
                        summary_exists = True
                        break
        if summary_exists:
            self.last_summary_generated = key
            return

        summary = generate_monthly_summary(previous_year, previous_month, self.settings, self.non_working_days)
        converted_gross = round(summary["total_earnings"] * self.exchange_rate.get(), 2)
        net_eur = round(converted_gross * (1 - self.tax_rate.get() / 100.0), 2)
        save_monthly_summary(summary, net_eur)
        messagebox.showinfo(
            "Resumen Mensual",
            f"Resumen de {calendar.month_name[previous_month]} {previous_year}:\n"
            f"Horas Totales: {summary['total_hours']} hrs\n"
            f"G. Bruta (Base): {summary['total_earnings']}\n"
            f"G. Neta (EUR): {net_eur}"
        )
        self.last_summary_generated = key
        self.update_monthly_summary_view()

    def update_monthly_summary_view(self):
        if not os.path.exists(MONTHLY_SUMMARY_FILE):
            return
        for item in self.monthly_tree.get_children():
            self.monthly_tree.delete(item)
        with open(MONTHLY_SUMMARY_FILE, "r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                self.monthly_tree.insert("", "end", values=(
                    row["Año"],
                    row["Mes"],
                    row["Horas Totales"],
                    row["Ganancia Bruta (Base)"],
                    row["Ganancia Neta (EUR)"]
                ))
        # Calcular y añadir una línea extra con lo ganado en el mes actual (en tiempo real)
        current_summary = self.generate_current_month_summary()
        converted_gross_current = round(current_summary["total_earnings"] * self.exchange_rate.get(), 2)
        net_eur_current = round(converted_gross_current * (1 - self.tax_rate.get() / 100.0), 2)
        self.monthly_tree.insert("", 0, values=(
            current_summary["year"],
            f"{current_summary['month']} (Actual)",
            current_summary["total_hours"],
            current_summary["total_earnings"],
            net_eur_current
        ))

    # ---------------------------
    # Navegación en el Calendario
    # ---------------------------
    def update_calendar_header(self):
        try:
            current_date = self.calendar.selection_get()
        except Exception:
            try:
                current_date = datetime.strptime(self.calendar.get_date(), "%Y-%m-%d").date()
            except ValueError:
                current_date = date.today()
        self.header_label.config(text=f"{calendar.month_name[current_date.month]} {current_date.year}")
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
    # Días No Laborables
    # ---------------------------
    def on_date_selected(self, event):
        for widget in self.action_frame.winfo_children():
            widget.destroy()
        selected_date_str = self.calendar.get_date()
        if selected_date_str:
            if selected_date_str in self.non_working_days:
                btn = ttk.Button(self.action_frame, text="Remover Día No Laborable", command=self.remove_non_working_day)
                btn.pack(side="left", padx=5, pady=5)
            else:
                btn = ttk.Button(self.action_frame, text="Marcar Día No Laborable", command=self.mark_non_working_day)
                btn.pack(side="left", padx=5, pady=5)
        self.update_calendar_header()
    def mark_non_working_day(self):
        selected_date_str = self.calendar.get_date()
        if selected_date_str not in self.non_working_days:
            self.non_working_days.add(selected_date_str)
            try:
                date_obj = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
                event_id = self.calendar.calevent_create(date_obj, "No Laborable", "nonworking")
                self.non_working_events[selected_date_str] = event_id
                self.settings_manager.update_setting("non_working_days", list(self.non_working_days))
                messagebox.showinfo("Éxito", f"{selected_date_str} marcado como día no laborable.")
            except ValueError as e:
                print(f"Error creando evento para {selected_date_str}: {e}")
            self.update_earnings()
        else:
            messagebox.showinfo("Información", f"{selected_date_str} ya está marcado como no laborable.")
    def remove_non_working_day(self):
        selected_date_str = self.calendar.get_date()
        if selected_date_str in self.non_working_days:
            self.non_working_days.remove(selected_date_str)
            event_id = self.non_working_events.get(selected_date_str)
            if event_id:
                self.calendar.calevent_remove(event_id)
                del self.non_working_events[selected_date_str]
            self.settings_manager.update_setting("non_working_days", list(self.non_working_days))
            messagebox.showinfo("Éxito", f"{selected_date_str} eliminado de los días no laborables.")
            self.update_earnings()
        else:
            messagebox.showerror("Error", f"{selected_date_str} no está marcado como día no laborable.")

    # ---------------------------
    # Configuración
    # ---------------------------
    def save_settings(self):
        self.apply_ui_to_settings()
        self.settings_manager.save_settings()
        self.update_tax_state()
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
    def on_base_currency_changed(self, event=None):
        self.update_exchange_rate()
        self.update_earnings()
    def update_tax_state(self):
        if self.is_autonomo.get():
            self.tax_rate.set(15.0)
            self.tax_entry.state(["disabled"])
        else:
            self.tax_entry.state(["!disabled"])
    def toggle_theme_mode(self):
        current_theme = sv_ttk.get_theme()
        new_theme = "light" if current_theme == "dark" else "dark"
        sv_ttk.set_theme(new_theme)
        self.settings["selected_theme"] = new_theme
        self.settings_manager.update_setting("selected_theme", new_theme)
        self.root.update_idletasks()
    def on_theme_changed(self, event=None):
        selected_theme = event.widget.get()
        sv_ttk.set_theme(selected_theme)
        self.settings["selected_theme"] = selected_theme
        self.settings_manager.update_setting("selected_theme", selected_theme)
        self.root.update_idletasks()
    def load_non_working_days(self):
        for date_str in self.non_working_days:
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                event_id = self.calendar.calevent_create(date_obj, "No Laborable", "nonworking")
                self.non_working_events[date_str] = event_id
            except ValueError as e:
                print(f"Error creando evento para {date_str}: {e}")

# Bloque principal
def main():
    root = tk.Tk()
    settings_manager = SettingsManager()
    app = SalaryCounterApp(root, settings_manager)
    root.mainloop()

if __name__ == "__main__":
    main()
