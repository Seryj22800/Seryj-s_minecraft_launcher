import minecraft_launcher_lib
import subprocess
import os
import sys
import shutil
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import threading
import ctypes
import platform
import logging
import uuid
import time
import requests
import urllib.error
from PIL import Image, ImageTk
import sv_ttk

# Настройка подробного логирования
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

# Включаем поддержку высокого DPI для Windows
try:
    if platform.system() == "Windows":
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        logging.debug("DPI awareness успешно активирован.")
except Exception as e:
    logging.debug(f"Не удалось установить DPI awareness: {e}")

def open_folder_crossplatform(path):
    """Кроссплатформенное открытие папки"""
    logging.info(f"Попытка открыть папку: {path}")
    if platform.system() == "Windows":
        os.startfile(path)
    elif platform.system() == "Darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])

class ConfigManager:
    """Управление глобальными настройками лаунчера"""
    def __init__(self, launcher_dir):
        self.config_file = os.path.join(launcher_dir, "launcher_settings.json")
        self.data = {
            "java_path": "",
            "java_args": "-Dfml.ignoreInvalidMinecraftCertificates=true",
            "max_ram": 2048,
            "version_names": {},
            "usernames": ["Steve"],
            "last_version": None
        }
        self.load()

    def load(self):
        logging.info("Чтение конфигурации лаунчера...")
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    self.data.update(loaded_data)
                logging.info("Конфигурация успешно загружена.")
            except Exception as e:
                logging.error(f"Ошибка загрузки конфига: {e}")
        else:
            logging.info("Файл конфигурации не найден, используются настройки по умолчанию.")

    def save(self):
        """Атомарное сохранение настроек для предотвращения их потери при сбое"""
        logging.info("Сохранение конфигурации лаунчера...")
        temp_file = self.config_file + ".tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4)
            # Атомарная замена (переименование файла поверх старого)
            os.replace(temp_file, self.config_file)
            logging.info("Конфигурация успешно сохранена.")
        except Exception as e:
            logging.error(f"Ошибка сохранения конфига: {e}")
            if os.path.exists(temp_file):
                try: os.remove(temp_file) 
                except: pass

class MinecraftCore:
    """Работа с ядром Minecraft (установка, запуск, изоляция папок)"""
    def __init__(self, launcher_dir, config_manager):
        self.config = config_manager
        self.launcher_dir = launcher_dir
        self.mc_dir = os.path.join(self.launcher_dir, ".minecraft")
        self.process = None
        self.is_running = False
        
        logging.info(f"Инициализация ядра Minecraft. Рабочая папка: {self.mc_dir}")
        self.create_directories()

    def create_directories(self):
        dirs = ["versions", "libraries", "assets", "logs", "screenshots", "crash-reports", "resourcepacks", "saves"]
        try:
            os.makedirs(self.mc_dir, exist_ok=True)
            for d in dirs:
                path = os.path.join(self.mc_dir, d)
                if not os.path.exists(path):
                    os.makedirs(path, exist_ok=True)
                    logging.info(f"Создана директория: {path}")
        except Exception as e:
            logging.error(f"Ошибка создания папок: {e}")

    def _validate_version_id(self, version_id):
        """Защита от уязвимости Path Traversal"""
        if not version_id or ".." in version_id or "/" in version_id or "\\" in version_id:
            raise ValueError(f"Недопустимое имя версии: {version_id}")

    def get_installed_versions(self):
        try:
            installed = minecraft_launcher_lib.utils.get_installed_versions(self.mc_dir)
            versions = [v['id'] for v in installed]
            logging.info(f"Найдено установленных версий: {len(versions)}")
            return versions
        except Exception as e:
            logging.error(f"Ошибка получения списка версий: {e}")
            return []

    def ensure_version_dirs(self, version_id):
        self._validate_version_id(version_id)
        logging.info(f"Подготовка изолированных папок для версии {version_id}")
        v_dir = os.path.join(self.mc_dir, "versions", version_id)
        dirs_to_create = ["mods", "resourcepacks", "shaderpacks", "saves"]
        os.makedirs(v_dir, exist_ok=True)
        for d in dirs_to_create:
            os.makedirs(os.path.join(v_dir, d), exist_ok=True)

    def install_version(self, version, mod_type, callback_dict):
        self._validate_version_id(version)
        logging.info(f"Начало установки версии {version} (Тип: {mod_type})")
        
        minecraft_launcher_lib.install.install_minecraft_version(version, self.mc_dir, callback=callback_dict)
        
        if mod_type == "Fabric":
            logging.info(f"Установка Fabric для версии {version}")
            minecraft_launcher_lib.fabric.install_fabric(version, self.mc_dir, callback=callback_dict)
        elif mod_type == "Forge":
            logging.info(f"Поиск версии Forge для {version}...")
            forge_version = minecraft_launcher_lib.forge.find_forge_version(version)
            
            if forge_version is None:
                logging.error(f"Forge для версии {version} не найден в базе.")
                raise Exception(f"Forge не найден для версии {version}")
                
            logging.info(f"Найден Forge: {forge_version}. Начинаю установку...")
            minecraft_launcher_lib.forge.install_forge_version(forge_version, self.mc_dir, callback=callback_dict)
                
        if mod_type in ["Fabric", "Forge"]:
            installed = self.get_installed_versions()
            mod_prefix = "fabric-loader-" if mod_type == "Fabric" else "forge-"
            for v in installed:
                if v.startswith(mod_prefix) and version in v:
                    logging.info(f"{mod_type} успешно установлен: {v}")
                    self.ensure_version_dirs(v)
                    return v
                
        logging.info(f"Установка завершена: {version}")
        return version

    def launch(self, version, username):
        self._validate_version_id(version)
        
        if self.is_running:
            raise RuntimeError("Minecraft уже запущен")

        session_uuid = str(uuid.uuid4())
        max_ram = self.config.data["max_ram"]
        java_args = [f"-Xmx{max_ram}M", "-Xms512M"]
        
        custom_args = self.config.data.get("java_args", "").strip()
        if custom_args:
            java_args.extend(custom_args.split())

        is_modded = "fabric" in version.lower() or "forge" in version.lower()
        
        v_dir = os.path.join(self.mc_dir, "versions", version)
        game_dir = v_dir if is_modded else self.mc_dir

        logs_dir = os.path.join(game_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        options = {
            "username": username,
            "uuid": session_uuid,
            "token": "",
            "gameDirectory": game_dir,
            "jvmArguments": java_args
        }
        
        java_path = self.config.data.get("java_path", "").strip()
        if java_path and os.path.exists(java_path):
            options["executablePath"] = java_path
        
        cmd = minecraft_launcher_lib.command.get_minecraft_command(version, self.mc_dir, options)

        try:
            java_idx = next(i for i, p in enumerate(cmd) if 'java' in p.lower() or 'javaw' in p.lower())
            mem_end = java_idx + 1
            while mem_end < len(cmd) and cmd[mem_end].startswith('-X'):
                mem_end += 1
            cmd = cmd[:mem_end] + [f"-Dminecraft.logs={logs_dir}"] + cmd[mem_end:]
        except StopIteration:
            pass

        self.process = subprocess.Popen(
            cmd,
            cwd=game_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )
        self.is_running = True
        return self.process

    def terminate(self):
        """Принудительное завершение дочернего процесса при закрытии лаунчера"""
        if self.is_running and self.process:
            logging.info("Завершение процесса Minecraft...")
            try:
                self.process.terminate()
            except Exception as e:
                logging.error(f"Ошибка при закрытии процесса: {e}")
            self.is_running = False
            
    def clear_cache(self):
        """Удаление временных файлов для исправления ошибок"""
        for folder in ['libraries', 'assets', 'logs']:
            path = os.path.join(self.mc_dir, folder)
            if os.path.exists(path):
                try:
                    shutil.rmtree(path)
                    os.makedirs(path)
                except Exception as e:
                    logging.error(f"Ошибка очистки {folder}: {e}")
        messagebox.showinfo("Готово", "Кеш и библиотеки очищены!")


class MinecraftLauncherGUI:
    """Графический интерфейс Seryj's minecraft Launcher"""
    def __init__(self, root):
        self.root = root
        self.root.title("Seryj's minecraft Launcher")
        self.root.geometry("1150x800")
        self.root.minsize(1050, 700)
        self.installed_versions_cache = []
        self.versions_listbox = None 
        self.screenshots = []
        self.current_photo = None
        self.current_pil_image = None

        self.colors = {
            'bg': '#2b2b2b', 'bg_light': '#3c3f41', 'bg_lighter': '#4e5254',
            'fg': '#ffffff', 'fg_secondary': '#888888',
            'accent': '#007acc', 'accent_hover': '#1c97ea',
        }
        self.root.configure(bg=self.colors['bg'])
        
        self.launcher_dir = str(Path(__file__).parent.absolute())
        self.config_manager = ConfigManager(self.launcher_dir)
        self.core = MinecraftCore(self.launcher_dir, self.config_manager)
        
        self.selected_version = self.config_manager.data.get("last_version")
        self.username = tk.StringVar(value=self.config_manager.data["usernames"][0])
        
        self.setup_styles()
        self.create_widgets()
        
        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)
        
        self.refresh_versions()
        self.refresh_screenshots()
        self.center_window(self.root)
        
        if self.selected_version in self.installed_versions_cache:
            idx = self.installed_versions_cache.index(self.selected_version)
            self.versions_listbox.selection_set(idx)
            self.on_version_select(None)

    def on_tab_changed(self, event):
        selected_tab = self.notebook.tab(self.notebook.select(), "text")
        if "Главная" in selected_tab:
            self.refresh_versions()
        elif "Скриншоты" in selected_tab:
            self.refresh_screenshots()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        style.configure('TNotebook', background=self.colors['bg'], borderwidth=0)
        style.configure('TNotebook.Tab', background=self.colors['bg_light'], 
                        foreground=self.colors['fg'], padding=[20, 10], 
                        font=("Segoe UI", 10), borderwidth=0)
        style.map('TNotebook.Tab', 
                  background=[('selected', self.colors['accent'])], 
                  foreground=[('selected', self.colors['fg'])])

    def center_window(self, window, width=None, height=None):
        window.update_idletasks()
        w = width or window.winfo_width()
        h = height or window.winfo_height()
        x = (window.winfo_screenwidth() - w) // 2
        y = (window.winfo_screenheight() - h) // 2
        window.geometry(f"+{x}+{y}")

    def _create_centered_dialog(self, title, width, height):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry(f"{width}x{height}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=self.colors['bg'])
        self.center_window(dialog, width, height)
        frame = tk.Frame(dialog, bg=self.colors['bg_light'], bd=2, relief=tk.SOLID)
        frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        return dialog, frame

    def create_widgets(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 0))
        
        self.main_frame = tk.Frame(self.notebook, bg=self.colors['bg'])
        self.screenshots_frame = tk.Frame(self.notebook, bg=self.colors['bg'])
        self.settings_frame = tk.Frame(self.notebook, bg=self.colors['bg'])
        
        self.notebook.add(self.main_frame, text="Главная")
        self.notebook.add(self.screenshots_frame, text="Скриншоты")
        self.notebook.add(self.settings_frame, text="Настройки")
        
        self.create_main_tab()
        self.create_screenshots_tab()
        self.create_settings_tab()
        self.create_bottom_bar()

    def create_main_tab(self):
        left_frame = tk.Frame(self.main_frame, bg=self.colors['bg'])
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=10)
        
        tk.Label(left_frame, text="Установленные версии:", font=("Segoe UI", 12, "bold"), 
                 bg=self.colors['bg'], fg=self.colors['fg']).pack(anchor=tk.W, pady=(0, 5))
        
        list_frame = tk.Frame(left_frame, bg=self.colors['bg_lighter'], bd=2, relief=tk.SOLID)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame, bg=self.colors['bg_light'], troughcolor=self.colors['bg'])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.versions_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                          bg=self.colors['bg_light'], fg=self.colors['fg'],
                                          selectbackground=self.colors['accent'], bd=0, 
                                          highlightthickness=0, font=("Consolas", 11))
        self.versions_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.config(command=self.versions_listbox.yview)
        self.versions_listbox.bind('<<ListboxSelect>>', self.on_version_select)
        
        right_frame = tk.Frame(self.main_frame, bg=self.colors['bg'], width=380)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, pady=10)
        right_frame.pack_propagate(False)
        
        info_card = tk.Frame(right_frame, bg=self.colors['bg_light'], bd=2, relief=tk.SOLID)
        info_card.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(info_card, text="Информация о версии", font=("Segoe UI", 12, "bold"), 
                 bg=self.colors['bg_light'], fg=self.colors['fg']).pack(anchor=tk.W, padx=15, pady=(10, 5))
        self.info_label = tk.Label(info_card, text="Версия не выбрана", bg=self.colors['bg_light'], 
                                   fg=self.colors['fg_secondary'], justify=tk.LEFT, font=("Segoe UI", 10))
        self.info_label.pack(anchor=tk.W, padx=15, pady=(0, 10))
        
        buttons_frame = tk.Frame(right_frame, bg=self.colors['bg'])
        buttons_frame.pack(fill=tk.X)
        
        btns = [
            ("Запустить", self.launch_version, self.colors['accent'], self.colors['accent_hover'], "bold"),
            ("Установить версию", self.install_version_dialog, self.colors['bg_light'], self.colors['bg_lighter'], "normal"),
            ("Открыть папку игры", self.open_mc_folder, self.colors['bg_light'], self.colors['bg_lighter'], "normal"),
            ("Переименовать", self.rename_version_dialog, self.colors['bg_light'], self.colors['bg_lighter'], "normal"),
            ("Удалить", self.delete_version, self.colors['bg_light'], self.colors['bg_lighter'], "normal"),
            ("Обновить список", self.refresh_versions, self.colors['bg_light'], self.colors['bg_lighter'], "normal")
        ]
        
        for text, cmd, bg, abg, weight in btns:
            tk.Button(buttons_frame, text=text, command=cmd, bg=bg, fg=self.colors['fg'],
                      activebackground=abg, bd=0 if weight=="bold" else 1, padx=20, pady=8, 
                      font=("Segoe UI", 10, weight)).pack(fill=tk.X, pady=2)

    def create_screenshots_tab(self):
        content = tk.Frame(self.screenshots_frame, bg=self.colors['bg'])
        content.pack(fill=tk.BOTH, expand=True, pady=10)
        
        left_panel = tk.Frame(content, bg=self.colors['bg'], width=300)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_panel.pack_propagate(False)
        
        self.screenshots_listbox = tk.Listbox(left_panel, bg=self.colors['bg_light'], fg=self.colors['fg'],
                                             selectbackground=self.colors['accent'], bd=0, font=("Segoe UI", 9))
        self.screenshots_listbox.pack(fill=tk.BOTH, expand=True)
        self.screenshots_listbox.bind('<<ListboxSelect>>', self.on_screenshot_select)
        
        tk.Button(left_panel, text="Обновить список", command=self.refresh_screenshots, 
                  bg=self.colors['bg_light'], fg=self.colors['fg']).pack(fill=tk.X, pady=5)
        
        right_panel = tk.Frame(content, bg=self.colors['bg'])
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.preview_frame = tk.Frame(right_panel, bg=self.colors['bg_lighter'], bd=2, relief=tk.SUNKEN)
        self.preview_frame.pack(fill=tk.BOTH, expand=True)
        self.screenshot_label = tk.Label(self.preview_frame, bg=self.colors['bg_lighter'])
        self.screenshot_label.pack(fill=tk.BOTH, expand=True)
        self.preview_frame.bind('<Configure>', lambda e: self._render_screenshot())
        
        info_bar = tk.Frame(right_panel, bg=self.colors['bg'], height=40)
        info_bar.pack(fill=tk.X, pady=5)
        self.screenshot_name_label = tk.Label(info_bar, text="Ничего не выбрано", bg=self.colors['bg'], fg=self.colors['fg_secondary'])
        self.screenshot_name_label.pack(side=tk.LEFT)
        
        tk.Button(info_bar, text="Удалить", command=self.delete_screenshot, bg="#a33").pack(side=tk.RIGHT, padx=5)
        tk.Button(info_bar, text="Открыть файл", command=self.open_selected_screenshot_folder, bg=self.colors['bg_light']).pack(side=tk.RIGHT)

    def create_settings_tab(self):
        card = tk.Frame(self.settings_frame, bg=self.colors['bg_light'], bd=2, relief=tk.SOLID)
        card.pack(fill=tk.BOTH, expand=True, pady=10)
        
        tk.Label(card, text="Настройки лаунчера", font=("Segoe UI", 14, "bold"), 
                 bg=self.colors['bg_light'], fg=self.colors['fg']).pack(anchor=tk.W, padx=20, pady=(15, 15))
        
        tk.Label(card, text="Выделенная память (RAM в MB):", font=("Segoe UI", 11, "bold"), 
                 bg=self.colors['bg_light'], fg=self.colors['fg']).pack(anchor=tk.W, padx=20)
        r_frame = tk.Frame(card, bg=self.colors['bg_light'])
        r_frame.pack(fill=tk.X, padx=20, pady=(5, 15))
        
        self.ram_var = tk.StringVar(value=str(self.config_manager.data["max_ram"]))
        tk.Entry(r_frame, textvariable=self.ram_var, bg=self.colors['bg'], fg=self.colors['fg'],
                 insertbackground=self.colors['fg'], bd=2, font=("Segoe UI", 10)).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        
        tk.Label(card, text="Путь к Java (javaw.exe):", font=("Segoe UI", 11, "bold"), 
                 bg=self.colors['bg_light'], fg=self.colors['fg']).pack(anchor=tk.W, padx=20)
        j_frame = tk.Frame(card, bg=self.colors['bg_light'])
        j_frame.pack(fill=tk.X, padx=20, pady=(5, 15))
        
        self.java_var = tk.StringVar(value=self.config_manager.data.get("java_path", ""))
        tk.Entry(j_frame, textvariable=self.java_var, bg=self.colors['bg'], fg=self.colors['fg'],
                 insertbackground=self.colors['fg'], bd=2, font=("Segoe UI", 10)).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 10))
        tk.Button(j_frame, text="Обзор", command=self.browse_java, bg=self.colors['bg'], fg=self.colors['fg'], bd=2).pack(side=tk.RIGHT)
        tk.Label(card, text="* Оставьте пустым, чтобы использовать системную Java", bg=self.colors['bg_light'], fg=self.colors['fg_secondary']).pack(anchor=tk.W, padx=20, pady=(0, 15))

        tk.Label(card, text="Дополнительные аргументы Java:", font=("Segoe UI", 11, "bold"), 
                 bg=self.colors['bg_light'], fg=self.colors['fg']).pack(anchor=tk.W, padx=20)
        self.args_var = tk.StringVar(value=self.config_manager.data.get("java_args", ""))
        tk.Entry(card, textvariable=self.args_var, bg=self.colors['bg'], fg=self.colors['fg'],
                 insertbackground=self.colors['fg'], bd=2, font=("Segoe UI", 10)).pack(fill=tk.X, padx=20, pady=(5, 5), ipady=5)
        
        tk.Button(card, text="Сохранить настройки", command=self.save_settings, bg=self.colors['accent'], 
                  fg=self.colors['fg'], bd=0, padx=30, pady=10, font=("Segoe UI", 11, "bold")).pack(pady=20)
        
        tk.Button(card, text="Очистить кеш игры", command=self.core.clear_cache, bg=self.colors['accent'], 
                  fg=self.colors['fg'], bd=0, padx=30, pady=10, font=("Segoe UI", 11, "bold")).pack(pady=20)

    def create_bottom_bar(self):
        bottom_bar = tk.Frame(self.root, bg=self.colors['bg_light'], height=60)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        bottom_bar.pack_propagate(False)
        
        left_frame = tk.Frame(bottom_bar, bg=self.colors['bg_light'])
        left_frame.pack(side=tk.LEFT, padx=20, pady=10)
        tk.Label(left_frame, text="RAM:", bg=self.colors['bg_light'], fg=self.colors['fg']).pack(side=tk.LEFT)
        self.bottom_ram_info = tk.Label(left_frame, text=f'{self.config_manager.data["max_ram"]} MB', 
                                        bg=self.colors['bg_light'], fg=self.colors['accent'], font=("Segoe UI", 12, "bold"))
        self.bottom_ram_info.pack(side=tk.LEFT, padx=5)
        
        right_frame = tk.Frame(bottom_bar, bg=self.colors['bg_light'])
        right_frame.pack(side=tk.RIGHT, padx=20, pady=10)
        tk.Label(right_frame, text="Ник:", bg=self.colors['bg_light'], fg=self.colors['fg']).pack(side=tk.LEFT)
        
        self.username_combo = ttk.Combobox(right_frame, textvariable=self.username, 
                                          values=self.config_manager.data["usernames"], width=20)
        self.username_combo.pack(side=tk.LEFT, padx=8, ipady=2)
        tk.Button(right_frame, text="Настроить", command=self.manage_usernames_dialog, bg=self.colors['accent'], 
                  fg=self.colors['fg'], bd=0, padx=10).pack(side=tk.LEFT)

    def browse_java(self):
        filetypes = [("Executables", "*.exe")] if platform.system() == "Windows" else [("All files", "*")]
        path = filedialog.askopenfilename(title="Выберите javaw.exe", filetypes=filetypes)
        if path:
            self.java_var.set(path)

    def save_settings(self):
        try:
            ram_val = int(self.ram_var.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка", "Значение RAM должно быть числом.")
            return

        self.config_manager.data["max_ram"] = ram_val
        self.config_manager.data["java_path"] = self.java_var.get().strip()
        self.config_manager.data["java_args"] = self.args_var.get().strip()
        self.config_manager.save()
        
        self.bottom_ram_info.config(text=f'{ram_val} MB')
        messagebox.showinfo("Успех", "Настройки сохранены")

    def refresh_versions(self):
        if self.versions_listbox is None: return

        logging.info("Обновление списка установленных версий...")
        self.versions_listbox.delete(0, tk.END)
        
        try:
            self.installed_versions_cache = self.core.get_installed_versions()
        except Exception as e:
            logging.error(f"Ошибка при чтении папок: {e}")
            return

        if not self.installed_versions_cache:
            self.versions_listbox.insert(tk.END, "  Версии не найдены")
            return

        for v in self.installed_versions_cache:
            v_lower = v.lower()
            if "fabric" in v_lower:
                prefix = "[Fabric] "
            elif "forge" in v_lower:
                prefix = "[Forge] "
            else:
                prefix = "[Vanilla] "
            # Получаем кастомное имя из конфига (или оставляем v, если его нет)
            display_name = self.config_manager.data["version_names"].get(v, v)
            self.versions_listbox.insert(tk.END, f"  {prefix}{display_name}")

    def on_version_select(self, event):
        selection = self.versions_listbox.curselection()
        if selection:
            idx = selection[0]
            self.selected_version = self.installed_versions_cache[idx]
            
            self.config_manager.data["last_version"] = self.selected_version
            self.config_manager.save()
            
            display = self.config_manager.data["version_names"].get(self.selected_version, self.selected_version)
            version_dir = Path(self.core.mc_dir) / "versions" / self.selected_version
            size_mb = sum(f.stat().st_size for f in version_dir.rglob('*') if f.is_file()) / (1024 * 1024) if version_dir.exists() else 0
            
            v_type = "Fabric/Forge (Изолированная)" if "fabric" in self.selected_version.lower() or "forge" in self.selected_version.lower() else "Vanilla (Общая)"
            
            self.info_label.config(text=f"Название: {display}\nВерсия: {self.selected_version}\nТип: {v_type}\nРазмер: {size_mb:.1f} MB")

    def open_mc_folder(self):
        open_folder_crossplatform(self.core.mc_dir)

    def launch_version(self):
        if not self.selected_version:
            messagebox.showwarning("Предупреждение", "Выберите версию")
            return
        try:
            process = self.core.launch(self.selected_version, self.username.get().strip() or "Steve")
            
            def monitor_and_log():
                logging.info("=== Захват вывода Minecraft ===")
                for line in iter(process.stdout.readline, ''):
                    if line:
                        logging.info(f"[Minecraft] {line.strip()}")
                
                process.stdout.close()
                process.wait()
                
                self.core.is_running = False
                logging.info("=== Minecraft закрыт ===")
                
            threading.Thread(target=monitor_and_log, daemon=True).start()
        except Exception as e:
            logging.error(f"Ошибка запуска: {e}")
            messagebox.showerror("Ошибка", str(e))

    def install_version_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Установка версии")
        dialog.geometry("450x420")
        dialog.configure(bg=self.colors['bg_light'])

        frame = tk.Frame(dialog, bg=self.colors['bg_light'], padx=20, pady=20)
        frame.pack(fill=tk.X)

        tk.Label(frame, text="Выберите версию:", bg=self.colors['bg_light'], fg=self.colors['fg']).pack(anchor=tk.W)
        
        try:
            versions = [v['id'] for v in minecraft_launcher_lib.utils.get_version_list()]
        except:
            versions = ["1.20.1", "1.19.2", "1.18.2", "1.16.5", "1.12.2"]

        version_var = tk.StringVar(value="1.20.1")
        version_combo = ttk.Combobox(frame, textvariable=version_var, values=versions)
        version_combo.pack(fill=tk.X, pady=5)

        tk.Label(frame, text="Тип установки:", bg=self.colors['bg_light'], fg=self.colors['fg']).pack(anchor=tk.W, pady=(10, 0))
        mod_type_var = tk.StringVar(value="Vanilla")
        ttk.Combobox(frame, textvariable=mod_type_var, values=["Vanilla", "Fabric", "Forge"], state="readonly").pack(fill=tk.X, pady=5)

        status = tk.Label(frame, text="Готов к установке", bg=self.colors['bg_light'], fg=self.colors['fg_secondary'], wraplength=350)
        status.pack(pady=10)

        progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=300, mode='determinate')
        progress.pack(fill=tk.X, pady=5)

        def task():
            v = version_var.get()
            m_type = mod_type_var.get()
            
            callback_dict = {
                "setStatus": lambda text: dialog.after(0, lambda: status.config(text=text)),
                "setProgress": lambda value: dialog.after(0, lambda: progress.configure(value=value)),
                "setMax": lambda value: dialog.after(0, lambda: progress.configure(maximum=value))
            }

            attempt = 1
            while True:
                if not dialog.winfo_exists():
                    logging.info("Установка отменена пользователем (окно закрыто).")
                    return

                try:
                    dialog.after(0, lambda: status.config(text=f"Попытка скачивания {attempt}..."))
                    final_v = self.core.install_version(v, m_type, callback_dict)
                    
                    dialog.after(0, lambda: messagebox.showinfo("Успех", f"Версия {final_v} установлена!"))
                    dialog.after(0, dialog.destroy)
                    break 
                
                except (requests.exceptions.RequestException, urllib.error.URLError, ConnectionError, TimeoutError) as e:
                    logging.warning(f"Сетевая ошибка (попытка {attempt}): {e}")
                    attempt += 1
                    time.sleep(2) 
                except Exception as e:
                    logging.error(f"Критическая ошибка (попытка {attempt}): {e}")
                    # Несетевые ошибки прерывают бесконечный цикл во избежание захламления диска
                    dialog.after(0, lambda err=e: messagebox.showerror("Ошибка", f"Критическая ошибка установки:\n{err}"))
                    break

        def start_install():
            install_btn.config(state=tk.DISABLED)
            threading.Thread(target=task, daemon=True).start()

        install_btn = ttk.Button(frame, text="Начать установку", command=start_install)
        install_btn.pack(pady=20)

    def rename_version_dialog(self):
        if not self.selected_version: return
        dialog, frame = self._create_centered_dialog("Переименовать", 450, 250)
        
        tk.Label(frame, text=f"Кастомное имя для {self.selected_version}:", bg=self.colors['bg_light'], fg=self.colors['fg']).pack()
        name_var = tk.StringVar(value=self.config_manager.data["version_names"].get(self.selected_version, ""))
        tk.Entry(frame, textvariable=name_var).pack(fill=tk.X, pady=10, ipady=5)
        
        def save():
            n = name_var.get().strip()
            if n:
                self.config_manager.data["version_names"][self.selected_version] = n
            else:
                self.config_manager.data["version_names"].pop(self.selected_version, None)
            self.config_manager.save()
            self.refresh_versions()
            dialog.destroy()
            
        tk.Button(frame, text="Сохранить", command=save, bg=self.colors['accent'], fg=self.colors['fg']).pack()

    def delete_version(self):
        if not self.selected_version: return
        if messagebox.askyesno("Удаление", f"Удалить версию {self.selected_version} со всеми её файлами?"):
            try:
                shutil.rmtree(os.path.join(self.core.mc_dir, "versions", self.selected_version))
                self.config_manager.data["version_names"].pop(self.selected_version, None)
                if self.config_manager.data.get("last_version") == self.selected_version:
                    self.config_manager.data["last_version"] = None
                self.config_manager.save()
                self.selected_version = None
                self.info_label.config(text="Версия не выбрана")
                self.refresh_versions()
            except Exception as e:
                logging.error(f"Ошибка удаления: {e}")

    def manage_usernames_dialog(self):
        dialog, frame = self._create_centered_dialog("Ники", 450, 400)
        
        listbox = tk.Listbox(frame, bg=self.colors['bg'], fg=self.colors['fg'])
        listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        for n in self.config_manager.data["usernames"]: listbox.insert(tk.END, n)
        
        new_var = tk.StringVar()
        entry_frame = tk.Frame(frame, bg=self.colors['bg_light'])
        entry_frame.pack(fill=tk.X)
        tk.Entry(entry_frame, textvariable=new_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        def add():
            n = new_var.get().strip()
            if n and n not in self.config_manager.data["usernames"]:
                self.config_manager.data["usernames"].append(n)
                self.config_manager.save()
                listbox.insert(tk.END, n)
                self.username_combo['values'] = self.config_manager.data["usernames"]
                new_var.set("")
                
        def delete():
            sel = listbox.curselection()
            if sel and len(self.config_manager.data["usernames"]) > 1:
                n = listbox.get(sel[0])
                self.config_manager.data["usernames"].remove(n)
                self.config_manager.save()
                listbox.delete(sel[0])
                self.username_combo['values'] = self.config_manager.data["usernames"]
                if self.username.get() == n: self.username.set(self.config_manager.data["usernames"][0])
                
        tk.Button(entry_frame, text="Добавить", command=add).pack(side=tk.RIGHT)
        tk.Button(frame, text="Удалить выбранный", command=delete).pack(fill=tk.X, pady=5)

    def refresh_screenshots(self):
        """Сканирует общую папку и папки всех версий на наличие скриншотов"""
        logging.info("Глобальное сканирование скриншотов...")
        self.screenshots_data = []
        self.screenshots_listbox.delete(0, tk.END)
        
        mc_path = Path(self.core.mc_dir)
        
        # 1. Сканируем главную папку .minecraft/screenshots
        main_ss = mc_path / "screenshots"
        if main_ss.exists():
            for f in main_ss.glob("*"):
                if f.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    self.screenshots_data.append((f.name, str(f)))
        
        # 2. Сканируем папки версий .minecraft/versions/*/screenshots
        versions_dir = mc_path / "versions"
        if versions_dir.exists():
            for v_dir in versions_dir.iterdir():
                if v_dir.is_dir():
                    v_ss = v_dir / "screenshots"
                    if v_ss.exists():
                        for f in v_ss.glob("*"):
                            if f.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                                display_name = f"[{v_dir.name}] {f.name}"
                                self.screenshots_data.append((display_name, str(f)))

        # Сортируем по дате изменения файла (самые новые вверху)
        self.screenshots_data.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)

        for display, _ in self.screenshots_data:
            # Обрезаем длинные имена для красоты
            short_name = (display[:45] + '...') if len(display) > 48 else display
            self.screenshots_listbox.insert(tk.END, f"  {short_name}")
        
        if not self.screenshots_data:
            self.screenshots_listbox.insert(tk.END, "  Скриншоты не найдены")

    def on_screenshot_select(self, event):
        sel = self.screenshots_listbox.curselection()
        if sel and self.screenshots_data:
            idx = sel[0]
            display_name, full_path = self.screenshots_data[idx]
            self.screenshot_name_label.config(text=f"Файл: {os.path.basename(full_path)}")
            self._load_screenshot(full_path)

    def _load_screenshot(self, filepath):
        if not os.path.exists(filepath): return
        try:
            self.current_pil_image = Image.open(filepath)
            self._render_screenshot()
        except Exception as e:
            logging.error(f"Ошибка загрузки изображения: {e}")

    def _render_screenshot(self):
        if not self.current_pil_image: return
        pw = self.preview_frame.winfo_width()
        ph = self.preview_frame.winfo_height()
        if pw < 10 or ph < 10: return
        
        iw, ih = self.current_pil_image.size
        scale = min(pw/iw, ph/ih, 1.0)
        
        nw, nh = int(iw * scale), int(ih * scale)
        resized = self.current_pil_image.resize((nw, nh), Image.Resampling.LANCZOS)
        self.current_photo = ImageTk.PhotoImage(resized)
        self.screenshot_label.config(image=self.current_photo)

    def on_preview_resize(self, event):
        if self.current_pil_image:
            self._render_screenshot()

    def open_selected_screenshot_folder(self):
        sel = self.screenshots_listbox.curselection()
        if sel and self.screenshots_data:
            path = self.screenshots_data[sel[0]][1]
            open_folder_crossplatform(os.path.dirname(path))
            
    def delete_screenshot(self):
        sel = self.screenshots_listbox.curselection()
        if not sel or not self.screenshots_data: return
        
        display, path = self.screenshots_data[sel[0]]
        if messagebox.askyesno("Удаление", f"Удалить скриншот?\n{display}"):
            try:
                os.remove(path)
                self.screenshot_label.config(image='')
                self.current_pil_image = None
                self.refresh_screenshots()
            except Exception as e:
                logging.error(f"Ошибка удаления: {e}")

def on_closing(app, root):
    """Корректное завершение работы лаунчера при закрытии окна"""
    app.core.terminate()
    root.destroy()

def main():
    logging.info("=== Запуск Seryj's minecraft Launcher ===")
    root = tk.Tk()
    sv_ttk.set_theme("dark")
    app = MinecraftLauncherGUI(root)
    # Привязываем завершение к закрытию окна
    root.protocol("WM_DELETE_WINDOW", lambda: on_closing(app, root))
    root.mainloop()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(f"Критическая ошибка: {e}", exc_info=True)
        input("Нажмите Enter для выхода...")