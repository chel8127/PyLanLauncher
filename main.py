import sys
import json
import os
import subprocess
import re
import html
import urllib.parse
import urllib.request
import uuid
import time
import threading
import http.server
import socketserver
import ctypes
import zipfile
import shutil
import webbrowser
import glob
import tempfile
import minecraft_launcher_lib
try:
    from pypresence import Presence
except Exception:
    Presence = None
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QScrollArea, 
                             QFrame, QDialog, QLineEdit, QComboBox, QFormLayout, 
                             QGridLayout, QStackedWidget, QProgressBar, QFileDialog, QListWidget,
                             QTabWidget, QMessageBox, QListWidgetItem, QTextEdit, QSpinBox, QInputDialog, QSplitter,
                             QGraphicsOpacityEffect, QCheckBox, QColorDialog, QMenu)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMimeData, QPropertyAnimation, QEasingCurve, QTimer, QPoint
from PyQt6.QtGui import QPixmap, QDrag, QColor
from datetime import datetime

# --- КОНФИГУРАЦИЯ ---
LAUNCHER_NAME = "PyLan Launcher"
BASE_DIR = minecraft_launcher_lib.utils.get_minecraft_directory().replace("minecraft", LAUNCHER_NAME.lower())
DATA_FILE = os.path.join(BASE_DIR, "instances.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
APP_VERSION = "0.8.0"
GITHUB_REPO = "chel8127/PyLanLauncher"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

if not os.path.exists(BASE_DIR): os.makedirs(BASE_DIR)


def hide_console_if_frozen():
    if os.name != "nt":
        return
    if not getattr(sys, "frozen", False):
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass

# --- ОКНО НОВОСТЕЙ ---
class MinecraftNewsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новости Minecraft")
        self.setFixedSize(760, 600)
        self.news_links = []
        self.setup_ui()
        self.load_news()

    def setup_ui(self):
        self.setStyleSheet("""
            QDialog { background: #121212; color: white; font-family: 'Segoe UI'; }
            QLabel { color: #D6D6D6; }
            QListWidget { background: #1A1A1A; border: 1px solid #333; border-radius: 8px; color: #EEE; }
            QPushButton { background: #252525; border-radius: 6px; padding: 8px; color: white; border: 1px solid #333; }
            QPushButton:hover { background: #2D2D2D; }
            #PrimaryBtn { background: #0078D4; border: none; font-weight: bold; }
        """)

        l = QVBoxLayout(self)
        l.addWidget(QLabel("Свежие публикации с minecraft.net"))

        self.news_list = QListWidget()
        l.addWidget(self.news_list)

        hb = QHBoxLayout()
        refresh_b = QPushButton("🔄 Обновить")
        refresh_b.clicked.connect(self.load_news)
        open_b = QPushButton("🌐 Открыть новость")
        open_b.setObjectName("PrimaryBtn")
        open_b.clicked.connect(self.open_selected_news)
        hb.addWidget(refresh_b)
        hb.addWidget(open_b)
        l.addLayout(hb)

    def _fetch_html(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "PyLanLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read().decode("utf-8", errors="ignore")

    def load_news(self):
        self.news_list.clear()
        self.news_links = []

        try:
            html_doc = self._fetch_html("https://www.minecraft.net/en-us/articles")
            matches = re.findall(r'href="(/en-us/article/[^"]+)"[^>]*>(.*?)</a>', html_doc, flags=re.IGNORECASE | re.DOTALL)

            seen = set()
            for rel_link, raw_title in matches:
                link = "https://www.minecraft.net" + rel_link
                title = re.sub(r"<[^>]+>", "", raw_title)
                title = html.unescape(" ".join(title.split()))
                if not title or link in seen:
                    continue
                seen.add(link)
                self.news_links.append(link)
                self.news_list.addItem(title)
                if len(self.news_links) >= 30:
                    break

            if not self.news_links:
                self.news_list.addItem("Не удалось получить новости. Проверь подключение к интернету.")
        except Exception as e:
            self.news_list.addItem(f"Ошибка загрузки новостей: {e}")

    def open_selected_news(self):
        row = self.news_list.currentRow()
        if row < 0 or row >= len(self.news_links):
            return
        os.startfile(self.news_links[row])

# --- ОКНО МОДОВ ---
class ModsManagerDialog(QDialog):
    def __init__(self, instance_data, parent=None, all_instances=None):
        super().__init__(parent)
        self.all_instances = all_instances[:] if all_instances else [instance_data]
        self.instance_data = instance_data or {}

        if not self.instance_data and self.all_instances:
            self.instance_data = self.all_instances[0]

        self.instance_path = ""
        self.game_version = ""
        self.loader = "vanilla"
        self.mods_dir = ""

        self.modrinth_cache = []
        self.curseforge_cache = []

        self.setWindowTitle("Установка модов")
        self.setFixedSize(760, 640)

        self.setup_ui()
        self._set_instance(self.instance_data)

    def _instance_title(self, inst):
        group = inst.get("group", "Main")
        name = inst.get("name", "Unnamed")
        return f"[{group}] {name}"

    def _set_instance(self, inst):
        self.instance_data = inst or {}
        self.instance_path = self.instance_data.get('path', '')
        self.game_version = self.instance_data.get('version', '')
        self.loader = self.instance_data.get('installer', 'vanilla')

        self.mods_dir = os.path.join(self.instance_path, "mods") if self.instance_path else ""
        if self.mods_dir and not os.path.exists(self.mods_dir):
            os.makedirs(self.mods_dir)

        self.header.setText(f"Цель: {self._instance_title(self.instance_data)} | Minecraft {self.game_version} | {self.loader}")
        self.refresh_list()

    def setup_ui(self):
        self.setStyleSheet("""
            QDialog { background: #121212; color: white; font-family: 'Segoe UI'; }
            QLabel { color: #DDDDDD; }
            QLineEdit, QListWidget, QComboBox {
                background: #1A1A1A; border: 1px solid #333; border-radius: 8px; color: #EEE; padding: 6px;
            }
            QTabWidget::pane { border: 1px solid #333; top: -1px; }
            QTabBar::tab { background: #1A1A1A; color: #AAA; padding: 8px 12px; border: 1px solid #333; }
            QTabBar::tab:selected { color: white; background: #222; }
            QPushButton { background: #252525; border-radius: 6px; padding: 8px; color: white; border: 1px solid #333; }
            QPushButton:hover { background: #2D2D2D; }
            #DeleteBtn { background: #442222; color: #FF8888; }
            #PrimaryBtn { background: #0078D4; border: none; color: white; font-weight: bold; }
        """)

        layout = QVBoxLayout(self)

        if len(self.all_instances) > 1:
            pick_row = QHBoxLayout()
            pick_row.addWidget(QLabel("Установка:"))
            self.instance_box = QComboBox()
            for inst in self.all_instances:
                self.instance_box.addItem(self._instance_title(inst))
            self.instance_box.currentIndexChanged.connect(self._on_instance_changed)
            pick_row.addWidget(self.instance_box)
            layout.addLayout(pick_row)
        else:
            self.instance_box = None

        self.header = QLabel("")
        self.header.setStyleSheet("color: #9AA0A6;")
        layout.addWidget(self.header)

        layout.addWidget(QLabel("Установленные моды (.jar):"))
        self.mlist = QListWidget()
        layout.addWidget(self.mlist)

        local_buttons = QHBoxLayout()
        open_b = QPushButton("📂 Папка")
        open_b.clicked.connect(lambda: os.startfile(self.mods_dir) if self.mods_dir else None)
        del_b = QPushButton("🗑 Удалить")
        del_b.setObjectName("DeleteBtn")
        del_b.clicked.connect(self.delete_mod)
        ref_b = QPushButton("🔄 Обновить")
        ref_b.clicked.connect(self.refresh_list)
        local_buttons.addWidget(open_b)
        local_buttons.addWidget(del_b)
        local_buttons.addWidget(ref_b)
        layout.addLayout(local_buttons)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_modrinth_tab()
        self._build_curseforge_tab()

    def _on_instance_changed(self, idx):
        if idx < 0 or idx >= len(self.all_instances):
            return
        self._set_instance(self.all_instances[idx])

    def _build_modrinth_tab(self):
        tab = QWidget()
        l = QVBoxLayout(tab)

        search_row = QHBoxLayout()
        self.modrinth_q = QLineEdit()
        self.modrinth_q.setPlaceholderText("Название мода для Modrinth")
        search_btn = QPushButton("Искать")
        search_btn.clicked.connect(self.search_modrinth)
        search_row.addWidget(self.modrinth_q)
        search_row.addWidget(search_btn)

        self.modrinth_list = QListWidget()

        dl_btn = QPushButton("⬇ Установить из Modrinth")
        dl_btn.setObjectName("PrimaryBtn")
        dl_btn.clicked.connect(self.download_modrinth)

        l.addLayout(search_row)
        l.addWidget(self.modrinth_list)
        l.addWidget(dl_btn)

        self.tabs.addTab(tab, "Modrinth")

    def _build_curseforge_tab(self):
        tab = QWidget()
        l = QVBoxLayout(tab)

        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("API Key:"))
        self.cf_key = QLineEdit(os.getenv("CURSEFORGE_API_KEY", ""))
        self.cf_key.setPlaceholderText("CurseForge API key")
        api_row.addWidget(self.cf_key)

        search_row = QHBoxLayout()
        self.cf_q = QLineEdit()
        self.cf_q.setPlaceholderText("Название мода для CurseForge")
        search_btn = QPushButton("Искать")
        search_btn.clicked.connect(self.search_curseforge)
        search_row.addWidget(self.cf_q)
        search_row.addWidget(search_btn)

        hint = QLabel("Для CurseForge нужен API key. Получить: console.curseforge.com")
        hint.setStyleSheet("color: #8C8C8C;")

        self.cf_list = QListWidget()

        dl_btn = QPushButton("⬇ Установить из CurseForge")
        dl_btn.setObjectName("PrimaryBtn")
        dl_btn.clicked.connect(self.download_curseforge)

        l.addLayout(api_row)
        l.addLayout(search_row)
        l.addWidget(hint)
        l.addWidget(self.cf_list)
        l.addWidget(dl_btn)

        self.tabs.addTab(tab, "CurseForge")

    def _show_error(self, text):
        QMessageBox.warning(self, "Ошибка", text)

    def _http_json(self, url, headers=None):
        req_headers = {"User-Agent": "PyLanLauncher/1.0"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))

    def check_launcher_updates(self, manual=False):
        url = self.settings.get("update_manifest_url", "").strip()
        if not url:
            if manual:
                QMessageBox.information(self, "Обновления", "Укажите URL манифеста обновлений в настройках.")
            return
        try:
            data = self._http_json(url)
            remote_ver = str(data.get("version", "0.0.0"))
            download_url = str(data.get("url", "")).strip()
            notes = str(data.get("notes", "")).strip()
            if self.version_tuple(remote_ver) > self.version_tuple(APP_VERSION):
                txt = f"Доступна новая версия: {remote_ver}\nТекущая: {APP_VERSION}"
                if notes:
                    txt += f"\n\n{notes}"
                if download_url and QMessageBox.question(self, "Обновление лаунчера", txt + "\n\nОткрыть страницу загрузки?") == QMessageBox.StandardButton.Yes:
                    os.startfile(download_url)
            elif manual:
                QMessageBox.information(self, "Обновления", f"У вас актуальная версия ({APP_VERSION}).")
        except Exception as e:
            if manual:
                QMessageBox.warning(self, "Обновления", f"Не удалось проверить обновления: {e}")

    def _safe_filename(self, filename):
        bad = '<>:"/\\|?*'
        clean = ''.join('_' if ch in bad else ch for ch in filename)
        return clean or "mod.jar"

    def _download_to_mods(self, url, filename=None, headers=None):
        if not self.mods_dir:
            raise RuntimeError("Не выбрана установка для модов")

        if not filename:
            parsed = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed.path) or "mod.jar"
        filename = self._safe_filename(filename)

        target = os.path.join(self.mods_dir, filename)
        name, ext = os.path.splitext(target)
        i = 1
        while os.path.exists(target):
            target = f"{name}_{i}{ext}"
            i += 1

        req_headers = {"User-Agent": "PyLanLauncher/1.0"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=60) as response, open(target, "wb") as out:
            out.write(response.read())
        return target

    def refresh_list(self):
        self.mlist.clear()
        if not self.mods_dir:
            self.mlist.addItem("Не выбрана установка")
            return

        files = [f for f in os.listdir(self.mods_dir) if f.endswith(".jar")]
        if files:
            self.mlist.addItems(sorted(files))
        else:
            self.mlist.addItem("Модов пока нет")

    def delete_mod(self):
        curr = self.mlist.currentItem()
        if curr and curr.text() != "Модов пока нет" and curr.text() != "Не выбрана установка":
            os.remove(os.path.join(self.mods_dir, curr.text()))
            self.refresh_list()

    def search_modrinth(self):
        query = self.modrinth_q.text().strip()
        if not query:
            self._show_error("Введите название мода для поиска")
            return

        try:
            facets = [["project_type:mod"]]
            if self.game_version:
                facets.append([f"versions:{self.game_version}"])
            if self.loader and self.loader != "vanilla":
                facets.append([f"categories:{self.loader}"])

            params = {
                "query": query,
                "limit": "30",
                "index": "relevance",
                "facets": json.dumps(facets, ensure_ascii=False)
            }
            url = "https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(params)
            data = self._http_json(url)
            self.modrinth_cache = data.get("hits", [])

            self.modrinth_list.clear()
            for hit in self.modrinth_cache:
                title = hit.get("title", "Unknown")
                author = hit.get("author", "unknown")
                desc = (hit.get("description", "") or "")[:90]
                self.modrinth_list.addItem(QListWidgetItem(f"{title} — {author}\n{desc}"))

            if not self.modrinth_cache:
                self.modrinth_list.addItem("Ничего не найдено")
        except Exception as e:
            self._show_error(f"Ошибка поиска Modrinth: {e}")

    def download_modrinth(self):
        row = self.modrinth_list.currentRow()
        if row < 0 or row >= len(self.modrinth_cache):
            self._show_error("Выберите мод в списке Modrinth")
            return

        project = self.modrinth_cache[row]
        project_id = project.get("project_id")
        if not project_id:
            self._show_error("Не удалось определить проект")
            return

        try:
            params = {}
            if self.game_version:
                params["game_versions"] = json.dumps([self.game_version])
            if self.loader and self.loader != "vanilla":
                params["loaders"] = json.dumps([self.loader])

            base_url = f"https://api.modrinth.com/v2/project/{project_id}/version"
            url = base_url + ("?" + urllib.parse.urlencode(params) if params else "")
            versions = self._http_json(url)
            if not versions:
                self._show_error("Не найдено подходящих версий файла")
                return

            files = versions[0].get("files", [])
            if not files:
                self._show_error("У версии нет файлов для скачивания")
                return

            file_info = next((f for f in files if f.get("primary")), files[0])
            download_url = file_info.get("url")
            filename = file_info.get("filename", "mod.jar")
            if not download_url:
                self._show_error("У файла нет ссылки на скачивание")
                return

            saved = self._download_to_mods(download_url, filename)
            self.refresh_list()
            QMessageBox.information(self, "Готово", f"Мод установлен:\n{saved}")
        except Exception as e:
            self._show_error(f"Ошибка скачивания Modrinth: {e}")

    def _cf_loader_type(self):
        mapping = {
            "forge": 1,
            "fabric": 4
        }
        return mapping.get(self.loader)

    def _cf_headers(self):
        key = self.cf_key.text().strip()
        if not key:
            raise RuntimeError("Введите CurseForge API key")
        return {"x-api-key": key, "Accept": "application/json"}

    def search_curseforge(self):
        query = self.cf_q.text().strip()
        if not query:
            self._show_error("Введите название мода для поиска")
            return

        try:
            params = {
                "gameId": "432",
                "classId": "6",
                "searchFilter": query,
                "pageSize": "30",
                "sortField": "2",
                "sortOrder": "desc"
            }
            if self.game_version:
                params["gameVersion"] = self.game_version
            loader_type = self._cf_loader_type()
            if loader_type is not None:
                params["modLoaderType"] = str(loader_type)

            url = "https://api.curseforge.com/v1/mods/search?" + urllib.parse.urlencode(params)
            data = self._http_json(url, self._cf_headers())
            self.curseforge_cache = data.get("data", [])

            self.cf_list.clear()
            for mod in self.curseforge_cache:
                name = mod.get("name", "Unknown")
                summary = (mod.get("summary", "") or "")[:90]
                self.cf_list.addItem(QListWidgetItem(f"{name}\n{summary}"))

            if not self.curseforge_cache:
                self.cf_list.addItem("Ничего не найдено")
        except Exception as e:
            self._show_error(f"Ошибка поиска CurseForge: {e}")

    def download_curseforge(self):
        row = self.cf_list.currentRow()
        if row < 0 or row >= len(self.curseforge_cache):
            self._show_error("Выберите мод в списке CurseForge")
            return

        mod = self.curseforge_cache[row]
        mod_id = mod.get("id")
        if not mod_id:
            self._show_error("Не удалось определить проект")
            return

        try:
            params = {"pageSize": "50"}
            if self.game_version:
                params["gameVersion"] = self.game_version
            loader_type = self._cf_loader_type()
            if loader_type is not None:
                params["modLoaderType"] = str(loader_type)

            url = f"https://api.curseforge.com/v1/mods/{mod_id}/files?" + urllib.parse.urlencode(params)
            files_data = self._http_json(url, self._cf_headers()).get("data", [])
            if not files_data:
                self._show_error("Не найдено файлов для этой версии")
                return

            chosen = None
            for f in files_data:
                if f.get("isAvailable") and f.get("downloadUrl"):
                    chosen = f
                    break
            if not chosen:
                self._show_error("Для выбранного мода нет прямой ссылки downloadUrl")
                return

            saved = self._download_to_mods(chosen["downloadUrl"], chosen.get("fileName", "mod.jar"))
            self.refresh_list()
            QMessageBox.information(self, "Готово", f"Мод установлен:\n{saved}")
        except Exception as e:
            self._show_error(f"Ошибка скачивания CurseForge: {e}")


class InstanceSelectDialog(QDialog):
    def __init__(self, instances, parent=None):
        super().__init__(parent)
        self.instances = instances or []
        self.setWindowTitle("Выбор установки")
        self.setFixedSize(420, 150)
        self.setStyleSheet("""
            QDialog { background: #141414; color: white; font-family: 'Segoe UI'; }
            QLabel { color: #DDD; }
            QComboBox { background: #1E1E1E; color: white; border: 1px solid #333; border-radius: 8px; padding: 6px; }
            QPushButton { background: #252525; color: white; border: 1px solid #333; border-radius: 8px; padding: 8px; }
            QPushButton:hover { background: #2D2D2D; }
            #PrimaryBtn { background: #0078D4; border: none; }
        """)

        l = QVBoxLayout(self)
        l.addWidget(QLabel("Выберите установку, куда скачать мод:"))
        self.box = QComboBox()
        for inst in self.instances:
            self.box.addItem(f"[{inst.get('group', 'Main')}] {inst.get('name', 'Unnamed')} | {inst.get('version', '?')}")
        l.addWidget(self.box)

        hb = QHBoxLayout()
        cancel_b = QPushButton("Отмена")
        ok_b = QPushButton("Установить")
        ok_b.setObjectName("PrimaryBtn")
        cancel_b.clicked.connect(self.reject)
        ok_b.clicked.connect(self.accept)
        hb.addWidget(cancel_b)
        hb.addWidget(ok_b)
        l.addLayout(hb)

    def selected_instance(self):
        idx = self.box.currentIndex()
        if idx < 0 or idx >= len(self.instances):
            return None
        return self.instances[idx]


class GroupDropButton(QPushButton):
    dropped = pyqtSignal(str, str)

    def __init__(self, group_name, text, parent=None):
        super().__init__(text, parent)
        self.group_name = group_name
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        instance_path = event.mimeData().text().strip()
        if instance_path:
            self.dropped.emit(instance_path, self.group_name)
            event.acceptProposedAction()
        else:
            event.ignore()


class InstanceCard(QFrame):
    def __init__(self, instance_data, on_select, parent=None):
        super().__init__(parent)
        self.instance_data = instance_data
        self.on_select = on_select
        self.drag_start_pos = None
        self.setObjectName("Card")
        self.setFixedSize(150, 170)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_pos = event.pos()
            self.on_select(self.instance_data)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self.drag_start_pos is None:
            return
        if (event.pos() - self.drag_start_pos).manhattanLength() < 8:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.instance_data.get("path", ""))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)
# --- ПОТОК ЗАПУСКА ---
class LaunchThread(QThread):
    progress = pyqtSignal(int, str)
    log_line = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, data):
        super().__init__()
        self.data = data
        self.proc = None

    def stop_minecraft(self):
        if self.proc and self.proc.poll() is None:
            self.log_line.emit("Экстренная остановка Minecraft...")
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

    def run(self):
        try:
            p, mc_version = self.data['path'], self.data['version']
            installer = self.data.get('installer', 'vanilla')
            loader_version = self.data.get('loader_version') or None
            ram_mb = int(self.data.get("ram_mb", 2048))
            account = self.data.get("account") or {}
            java_path = (self.data.get("java_path") or "").strip()
            callback = {
                "setStatus": lambda t: self.progress.emit(50, str(t)),
                "setProgress": lambda v: self.progress.emit(max(0, min(100, int(v))), "")
            }
            launch_version = mc_version

            if installer == "fabric":
                if not loader_version:
                    loader_version = minecraft_launcher_lib.fabric.get_latest_loader_version()
                minecraft_launcher_lib.fabric.install_fabric(mc_version, p, loader_version=loader_version, callback=callback)
                launch_version = f"fabric-loader-{loader_version}-{mc_version}"
            elif installer == "forge":
                forge_version = loader_version or minecraft_launcher_lib.forge.find_forge_version(mc_version)
                if not forge_version:
                    raise RuntimeError(f"Forge версия для Minecraft {mc_version} не найдена")
                minecraft_launcher_lib.forge.install_forge_version(forge_version, p, callback=callback)
                launch_version = minecraft_launcher_lib.forge.forge_to_installed_version(forge_version)
            elif installer == "quilt":
                if not loader_version:
                    loader_version = minecraft_launcher_lib.quilt.get_latest_loader_version()
                minecraft_launcher_lib.quilt.install_quilt(mc_version, p, loader_version=loader_version, callback=callback)
                launch_version = f"quilt-loader-{loader_version}-{mc_version}"
            else:
                minecraft_launcher_lib.install.install_minecraft_version(mc_version, p, callback=callback)
            is_ms = account.get("type") == "microsoft"
            opt = {
                "username": account.get("username", "Player"),
                "uuid": account.get("uuid", "0"),
                "token": account.get("access_token", "0") if is_ms else "0",
                "jvmArguments": [f"-Xms1024M", f"-Xmx{ram_mb}M"]
            }
            if java_path:
                opt["executablePath"] = java_path
            cmd = minecraft_launcher_lib.command.get_minecraft_command(launch_version, p, opt)
            self.log_line.emit("Запуск процесса Minecraft...")
            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = subprocess.CREATE_NO_WINDOW
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            if self.proc.stdout:
                for line in self.proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.log_line.emit(line)
            self.proc.wait()
            self.log_line.emit(f"Minecraft завершен с кодом: {self.proc.returncode}")
        except Exception as e:
            self.progress.emit(0, str(e))
        finally:
            self.finished.emit()


class ModSearchThread(QThread):
    done = pyqtSignal(int, object, bool)
    failed = pyqtSignal(int, str)

    def __init__(self, request_id, query, page, page_size):
        super().__init__()
        self.request_id = int(request_id)
        self.query = query
        self.page = int(page)
        self.page_size = int(page_size)

    def run(self):
        try:
            url = "https://api.modrinth.com/v2/search?" + urllib.parse.urlencode({
                "query": self.query,
                "limit": str(self.page_size),
                "offset": str(self.page * self.page_size),
                "index": "downloads",
                "facets": json.dumps([["project_type:mod"]], ensure_ascii=False)
            })
            req = urllib.request.Request(url, headers={"User-Agent": "PyLanLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=25) as response:
                data = json.loads(response.read().decode("utf-8"))
            hits = data.get("hits", [])
            mapped = []
            for hit in hits:
                avatar_data = None
                icon_url = hit.get("icon_url")
                if icon_url:
                    try:
                        ireq = urllib.request.Request(icon_url, headers={"User-Agent": "PyLanLauncher/1.0"})
                        with urllib.request.urlopen(ireq, timeout=4) as ir:
                            avatar_data = ir.read()
                    except Exception:
                        avatar_data = None
                mapped.append({
                    "provider": "Modrinth",
                    "id": hit.get("project_id"),
                    "title": hit.get("title", "Unknown"),
                    "description": (hit.get("description", "") or "")[:180],
                    "avatar": avatar_data
                })
            self.done.emit(self.request_id, mapped, len(hits) >= self.page_size)
        except Exception as e:
            self.failed.emit(self.request_id, str(e))

# --- ГЛАВНОЕ ОКНО ---
class LauncherMain(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        self.lang = self.settings.get("language", "ru")
        self.setWindowTitle("PyLan Launcher")
        self.resize(1150, 720)
        self.instance_data = {}
        self.selected_instance = None
        self.news_items = []
        self.mods_results = []
        self.mods_page = 0
        self.mods_page_size = 25
        self.mods_has_next = False
        self.install_logs = []
        self.log_dialog = None
        self.log_text = None
        self.download_items = []
        self.download_seq = 0
        self.download_dialog = None
        self.download_list = None
        self.library_update_task_id = None
        self.mod_search_thread = None
        self.mod_search_req_id = 0
        self.launch_started_at = None
        self.launch_instance_path = ""
        self.rpc = None
        self.rpc_connected = False
        self.server_status_name = ""
        self.group_collapsed = {}
        self._page_anim = None
        self.setup_ui()
        self.load_data()
        QTimer.singleShot(1200, self.check_new_minecraft_release)

    def load_settings(self):
        default = {
            "language": "ru",
            "ram_mb": 2048,
            "auto_ram": True,
            "sidebar_width": 70,
            "theme": "blue",
            "custom_theme": {
                "accent": "#0078D4",
                "side_active": "#4A8DF0"
            },
            "auto_update_check": False,
            "last_notified_github_release": "",
            "ms_client_id": "",
            "auto_cleanup_enabled": True,
            "cleanup_days": 14,
            "server_ip": "",
            "discord_rpc_enabled": False,
            "playtime_total_sec": 0,
            "playtime_by_path": {},
            "last_seen_mc_release": "",
            "accounts": [{
                "type": "offline",
                "username": "Player",
                "uuid": uuid.uuid3(uuid.NAMESPACE_DNS, "player").hex,
                "skin_path": "",
                "cape_path": ""
            }],
            "active_account": 0
        }
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in default.items():
                        if k not in data:
                            data[k] = v
                    if not data.get("accounts"):
                        data["accounts"] = default["accounts"]
                    if data.get("active_account", 0) >= len(data["accounts"]):
                        data["active_account"] = 0
                    return data
            except Exception:
                return default
        return default

    def save_settings(self):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4, ensure_ascii=False)

    def version_tuple(self, version_text):
        try:
            raw = str(version_text).strip().lower().lstrip("v")
            m = re.search(r"\d+(?:\.\d+)*", raw)
            if not m:
                return (0,)
            return tuple(int(x) for x in m.group(0).split("."))
        except Exception:
            return (0,)

    def check_launcher_updates(self, manual=False):
        self.check_github_release_updates(manual=manual)

    def check_github_release_updates(self, manual=False):
        repo = GITHUB_REPO
        if not repo or "/" not in repo:
            if manual:
                QMessageBox.warning(self, "GitHub обновления", "В коде не задан корректный GITHUB_REPO.")
            return
        try:
            data = self._http_json(GITHUB_LATEST_API, headers={"Accept": "application/vnd.github+json"})
            if data.get("draft") or data.get("prerelease"):
                if manual:
                    QMessageBox.information(self, "GitHub обновления", "Последний релиз является draft/prerelease.")
                return
            tag = str(data.get("tag_name", "")).strip()
            html_url = str(data.get("html_url", "")).strip() or GITHUB_RELEASES_URL
            name = str(data.get("name", "")).strip() or tag
            notes = str(data.get("body", "")).strip()
            published_at = str(data.get("published_at", "")).strip()
            if not tag:
                if manual:
                    QMessageBox.warning(self, "GitHub обновления", "Не удалось прочитать tag_name последнего релиза.")
                return
            if self.version_tuple(tag) > self.version_tuple(APP_VERSION):
                last_shown = str(self.settings.get("last_notified_github_release", "")).strip()
                # Автопроверка: не спамим одним и тем же релизом
                if manual or last_shown != tag:
                    self.settings["last_notified_github_release"] = tag
                    self.save_settings()
                    self.show_update_dialog(
                        source=f"GitHub ({repo})",
                        remote_ver=tag,
                        current_ver=APP_VERSION,
                        download_url=html_url,
                        title=name,
                        notes=notes,
                        published_at=published_at
                    )
            elif manual:
                QMessageBox.information(self, "GitHub обновления", f"У вас актуальная версия ({APP_VERSION}).")
        except Exception as e:
            if manual:
                QMessageBox.warning(self, "GitHub обновления", f"Не удалось проверить релизы GitHub: {e}")

    def show_update_dialog(self, source, remote_ver, current_ver, download_url, title, notes, published_at):
        d = QDialog(self)
        d.setWindowTitle("Доступно обновление лаунчера")
        d.resize(620, 420)
        d.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QLabel { color:#E8E8E8; }
            QTextEdit { background:#171717; color:#D7D7D7; border:1px solid #333; border-radius:8px; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px 12px; }
            QPushButton:hover { background:#2D2D2D; }
            #PrimaryBtn { background:#0078D4; border:none; font-weight:700; }
        """)
        l = QVBoxLayout(d)
        head = QLabel("🚀 Обновление доступно")
        head.setStyleSheet("font-size:22px; font-weight:900; color:white;")
        l.addWidget(head)
        l.addWidget(QLabel(f"Источник: {source}"))
        l.addWidget(QLabel(f"Новая версия: {remote_ver}"))
        l.addWidget(QLabel(f"Текущая версия: {current_ver}"))
        if published_at:
            l.addWidget(QLabel(f"Дата релиза: {published_at}"))
        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("font-weight:700; color:#AFC7F2;")
        l.addWidget(title_lbl)
        tx = QTextEdit()
        tx.setReadOnly(True)
        tx.setPlainText(notes or "Описание релиза не указано.")
        l.addWidget(tx)
        hb = QHBoxLayout()
        later = QPushButton("Позже")
        update_now = QPushButton("Обновить сейчас")
        update_now.setObjectName("PrimaryBtn")
        hb.addStretch()
        hb.addWidget(later)
        hb.addWidget(update_now)
        l.addLayout(hb)

        later.clicked.connect(d.accept)
        update_now.clicked.connect(lambda: (os.startfile(download_url) if download_url else None, d.accept()))
        d.exec()

    def format_seconds(self, sec):
        sec = max(0, int(sec or 0))
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def update_playtime_labels(self):
        by_path = self.settings.get("playtime_by_path", {})
        total = int(self.settings.get("playtime_total_sec", 0))
        if self.selected_instance:
            ip = self.selected_instance.get("path", "")
            sec = int(by_path.get(ip, 0))
            self.bottom_left_time.setText(f"Время в установке: {self.format_seconds(sec)}")
        else:
            self.bottom_left_time.setText("Время в установке: 00:00:00")
        self.bottom_right_total.setText(f"Общее время в Minecraft: {self.format_seconds(total)}")

    def set_instance_prop(self, inst_path, key, value):
        for g in self.instance_data:
            for i, it in enumerate(self.instance_data[g]):
                if it.get("path") == inst_path:
                    self.instance_data[g][i][key] = value
                    if self.selected_instance and self.selected_instance.get("path") == inst_path:
                        self.selected_instance = self.instance_data[g][i]
                    self.save_data()
                    return True
        return False

    def toggle_favorite_selected(self):
        if not self.selected_instance:
            return
        path = self.selected_instance.get("path", "")
        new_val = not bool(self.selected_instance.get("favorite", False))
        self.set_instance_prop(path, "favorite", new_val)
        self.refresh_grid()
        self.select_instance(self.selected_instance)

    def set_color_label_selected(self):
        if not self.selected_instance:
            return
        items = ["None", "Red", "Orange", "Yellow", "Green", "Cyan", "Blue", "Purple", "Pink"]
        current = self.selected_instance.get("color_label", "None")
        idx = items.index(current) if current in items else 0
        val, ok = QInputDialog.getItem(self, "Метка цвета", "Выберите цвет установки:", items, idx, False)
        if not ok:
            return
        self.set_instance_prop(self.selected_instance.get("path", ""), "color_label", val)
        self.refresh_grid()
        self.select_instance(self.selected_instance)

    def cleanup_old_data(self, manual=False):
        days = max(1, int(self.settings.get("cleanup_days", 14)))
        cutoff = time.time() - days * 86400
        removed = 0
        try:
            # launcher backups
            bdir = self.backups_dir()
            for fn in os.listdir(bdir):
                p = os.path.join(bdir, fn)
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p); removed += 1
            # temp java archives
            jdir = os.path.join(BASE_DIR, "java")
            if os.path.exists(jdir):
                for root, _, files in os.walk(jdir):
                    for fn in files:
                        if fn.lower().endswith(".zip"):
                            p = os.path.join(root, fn)
                            if os.path.getmtime(p) < cutoff:
                                os.remove(p); removed += 1
            # per-instance logs and old crash reports
            for inst in self.get_all_instances():
                ip = inst.get("path", "")
                for rel in ["logs", "crash-reports"]:
                    d = os.path.join(ip, rel)
                    if not os.path.exists(d):
                        continue
                    for fn in os.listdir(d):
                        p = os.path.join(d, fn)
                        if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                            os.remove(p); removed += 1
            self.log_event(f"Автоочистка: удалено файлов {removed}")
            if manual:
                QMessageBox.information(self, "Очистка", f"Удалено файлов: {removed}")
        except Exception as e:
            if manual:
                QMessageBox.warning(self, "Очистка", f"Ошибка очистки: {e}")

    def query_server_status(self, addr):
        addr = (addr or "").strip()
        if not addr:
            return {"online": False, "text": "IP не указан"}
        url = "https://api.mcsrvstat.us/2/" + urllib.parse.quote(addr)
        t0 = time.perf_counter()
        data = self._http_json(url)
        ping_ms = int((time.perf_counter() - t0) * 1000)
        online = bool(data.get("online"))
        t = getattr(self, "lang_labels", {}) or {}
        online_txt = t.get("server_online", "Онлайн")
        offline_txt = t.get("server_offline", "Оффлайн")
        ping_lbl = t.get("ping_label", "пинг")
        if not online:
            return {"online": False, "text": f"{offline_txt} | {ping_lbl}: —", "name": addr, "ping": None}
        txt = f"{online_txt} | {ping_lbl}: {ping_ms} ms"
        return {"online": True, "text": txt, "name": addr, "ping": ping_ms}

    def refresh_server_status(self):
        addr = self.server_ip_edit.text().strip() if hasattr(self, "server_ip_edit") else ""
        self.settings["server_ip"] = addr
        self.save_settings()
        try:
            st = self.query_server_status(addr)
            self.server_status_name = st.get("name", "") if st.get("online") else ""
            self.server_status_lbl.setText(st.get("text", ""))
            self.server_status_lbl.setStyleSheet("color:#9FD9A8;" if st.get("online") else "color:#D9A29F;")
        except Exception as e:
            self.server_status_name = ""
            self.server_status_lbl.setText(f"Ошибка сервера: {e}")
            self.server_status_lbl.setStyleSheet("color:#D9A29F;")
        self.update_discord_presence()

    def _build_edit_menu(self):
        self.edit_menu.clear()
        self.menu_actions = {}
        self._edit_instance_actions = set()

        def add_action(key, text, slot, requires_instance=True):
            act = self.edit_menu.addAction(text)
            act.triggered.connect(slot)
            self.menu_actions[key] = act
            if requires_instance:
                self._edit_instance_actions.add(key)
            return act

        add_action("edit", "✏ Изменить...", self.open_edit_instance_dialog)
        add_action("edit_group", "🗂 Изменить группу...", self.change_group_selected)
        add_action("export", "📤 Экспортировать", self.export_selected_instance)
        self.edit_menu.addSeparator()
        add_action("mods", "🧩 Менеджер модов", self.open_mods)
        add_action("favorite", "⭐ В избранное", self.toggle_favorite_selected)
        add_action("color", "🎨 Цвет метки", self.set_color_label_selected)
        add_action("graphics", "🎮 Профиль графики", self.open_graphics_profile_dialog)
        add_action("crash", "💥 Crash-отчеты", self.open_crash_reports)
        add_action("java", "☕ Java", self.open_java_manager)
        add_action("packs", "🎨 Ресурсы и шейдеры", self.open_assets_manager)
        add_action("worlds", "🌍 Миры и скриншоты", self.open_worlds_manager)
        add_action("backups", "🗃 Бэкапы", self.open_backups_manager)
        add_action("repair", "🩺 Починить установку", self.repair_selected_instance)
        add_action("logs", "📜 Логи установки", self.open_install_logs, requires_instance=False)
        self.edit_menu.addSeparator()
        add_action("console", "🧾 Консоль", self.show_console_page, requires_instance=False)

        self._update_edit_menu_state()

    def show_edit_menu(self):
        if not self.selected_instance:
            QMessageBox.information(self, "Изменить", "Сначала выберите установку.")
            return
        if hasattr(self, "edit_dialog") and self.edit_dialog is not None:
            self.edit_dialog.show()
            self.edit_dialog.raise_()
            self.edit_dialog.activateWindow()
            return
        self.edit_dialog = EditMenuDialog(self)
        self.edit_dialog.finished.connect(lambda _: setattr(self, "edit_dialog", None))
        self.edit_dialog.show()

    def _update_edit_menu_state(self):
        has_inst = bool(self.selected_instance)
        for key, act in (self.menu_actions or {}).items():
            if key in self._edit_instance_actions:
                act.setEnabled(has_inst)
        if has_inst:
            fav = bool(self.selected_instance.get("favorite", False))
            if "favorite" in self.menu_actions:
                t = getattr(self, "lang_labels", {}) or {}
                txt = t.get("menu_favorite_remove") if fav else t.get("menu_favorite_add", t.get("menu_favorite", "В избранное"))
                self.menu_actions["favorite"].setText("⭐ " + txt)

    def change_group_selected(self):
        if not self.selected_instance:
            return
        groups = list(self.instance_data.keys()) or ["Main"]
        curr = self.selected_instance.get("group", "Main")
        group, ok = QInputDialog.getItem(self, "Изменить группу", "Группа:", groups, max(0, groups.index(curr)) if curr in groups else 0, True)
        if not ok:
            return
        new_group = (group or "").strip() or "Main"
        self._move_instance_to_group(self.selected_instance.get("path", ""), new_group)

    def _move_instance_to_group(self, instance_path, target_group):
        source_group = None
        instance_obj = None
        for g, insts in self.instance_data.items():
            for inst in insts:
                if inst.get("path") == instance_path:
                    source_group = g
                    instance_obj = inst
                    break
            if instance_obj:
                break
        if not instance_obj or source_group is None:
            return
        if source_group != target_group:
            self.instance_data[source_group] = [i for i in self.instance_data[source_group] if i.get("path") != instance_path]
            self.instance_data.setdefault(target_group, []).append(instance_obj)
            instance_obj["group"] = target_group
            self.save_data()
            self.refresh_grid()
            self.log_event(f"Сборка '{instance_obj.get('name', 'Unnamed')}' перемещена: {source_group} -> {target_group}")

    def _skin_head_url_for_account(self, acc):
        uid = (acc or {}).get("uuid", "")
        if uid and len(uid) >= 8:
            return f"https://crafatar.com/avatars/{uid}?size=128&overlay"
        return ""

    def is_discord_running(self):
        try:
            if os.name == "nt":
                out = subprocess.check_output(["tasklist"], text=True, errors="ignore")
                return ("discord.exe" in out.lower()) or ("discordcanary.exe" in out.lower()) or ("discordptb.exe" in out.lower())
            out = subprocess.check_output(["ps", "aux"], text=True, errors="ignore")
            return "discord" in out.lower()
        except Exception:
            return False

    def start_discord_rpc(self):
        if not bool(self.settings.get("discord_rpc_enabled", False)):
            return
        if Presence is None:
            return
        if self.rpc_connected:
            return
        if not self.is_discord_running():
            return
        client_id = (self.settings.get("discord_client_id", "") or os.getenv("DISCORD_CLIENT_ID", "")).strip()
        if not client_id:
            return
        try:
            self.rpc = Presence(client_id)
            self.rpc.connect()
            self.rpc_connected = True
        except Exception:
            self.rpc = None
            self.rpc_connected = False

    def stop_discord_rpc(self):
        if self.rpc is not None:
            try:
                self.rpc.clear()
            except Exception:
                pass
            try:
                self.rpc.close()
            except Exception:
                pass
        self.rpc = None
        self.rpc_connected = False

    def update_discord_presence(self):
        if not self.rpc_connected or self.rpc is None:
            self.start_discord_rpc()
        if not self.rpc_connected or self.rpc is None:
            return
        try:
            inst = self.selected_instance or {}
            acc = self.get_active_account()
            nick = acc.get("username", "Player")
            srv = self.server_status_name or "Без сервера"
            details = f"{inst.get('name', 'PyLan Launcher')} | {inst.get('version', '?')}"
            state = f"{nick} | {srv}"
            buttons = [{"label": "Релизы", "url": GITHUB_RELEASES_URL}]
            head = self._skin_head_url_for_account(acc)
            if head:
                buttons.insert(0, {"label": "Голова скина", "url": head})
            self.rpc.update(
                details=details[:128],
                state=state[:128],
                buttons=buttons[:2]
            )
        except Exception:
            pass

    def detect_total_ram_mb(self):
        try:
            if os.name == "nt":
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_uint32),
                        ("dwMemoryLoad", ctypes.c_uint32),
                        ("ullTotalPhys", ctypes.c_uint64),
                        ("ullAvailPhys", ctypes.c_uint64),
                        ("ullTotalPageFile", ctypes.c_uint64),
                        ("ullAvailPageFile", ctypes.c_uint64),
                        ("ullTotalVirtual", ctypes.c_uint64),
                        ("ullAvailVirtual", ctypes.c_uint64),
                        ("ullAvailExtendedVirtual", ctypes.c_uint64),
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                return int(stat.ullTotalPhys // (1024 * 1024))
        except Exception:
            pass
        return 8192

    def recommended_ram_mb(self):
        total = self.detect_total_ram_mb()
        if total <= 4096:
            return 2048
        if total <= 8192:
            return 3072
        if total <= 16384:
            return 4096
        if total <= 32768:
            return 6144
        return min(16384, max(8192, total // 3))

    def check_disk_space(self, target_path, required_gb=3):
        try:
            base = target_path or BASE_DIR
            if not os.path.exists(base):
                base = os.path.dirname(base) or BASE_DIR
            usage = shutil.disk_usage(base)
            free = usage.free
            need = int(required_gb * 1024 * 1024 * 1024)
            if free < need:
                free_gb = free / (1024 * 1024 * 1024)
                return False, free_gb
            return True, free / (1024 * 1024 * 1024)
        except Exception:
            return True, 0.0

    def check_new_minecraft_release(self):
        try:
            versions = minecraft_launcher_lib.utils.get_version_list()
            releases = [v for v in versions if v.get("type") == "release"]
            if not releases:
                return
            latest = releases[0].get("id", "")
            if not latest:
                return
            prev = str(self.settings.get("last_seen_mc_release", "")).strip()
            self.settings["last_seen_mc_release"] = latest
            self.save_settings()
            if prev and prev != latest:
                QMessageBox.information(self, "Новая версия Minecraft", f"Доступна новая версия: {latest}\n(раньше была {prev})")
                self.log_event(f"Новая версия Minecraft: {latest} (было {prev})")
        except Exception:
            pass

    def backups_dir(self):
        path = os.path.join(BASE_DIR, "backups")
        if not os.path.exists(path):
            os.makedirs(path)
        return path

    def mods_index_path(self, instance):
        return os.path.join(instance.get("path", ""), "mods", ".mods_index.json")

    def read_mods_index(self, instance):
        p = self.mods_index_path(instance)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def write_mods_index(self, instance, data):
        p = self.mods_index_path(instance)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_active_account(self):
        accounts = self.settings.get("accounts", [])
        if not accounts:
            return {"type": "offline", "username": "Player", "uuid": uuid.uuid3(uuid.NAMESPACE_DNS, "player").hex}
        idx = self.settings.get("active_account", 0)
        if idx < 0 or idx >= len(accounts):
            idx = 0
            self.settings["active_account"] = 0
        return accounts[idx]

    def refresh_microsoft_account_token(self, account):
        if not account or account.get("type") != "microsoft":
            return account
        refresh_token = (account.get("refresh_token", "") or "").strip()
        if not refresh_token:
            return account
        client_id = (self.settings.get("ms_client_id", "") or os.getenv("MS_CLIENT_ID", "")).strip() or "00000000402b5328"
        try:
            data = minecraft_launcher_lib.microsoft_account.complete_refresh(client_id, None, None, refresh_token)
            if isinstance(data, dict):
                access_token = data.get("access_token", "") or data.get("accessToken", "")
                new_refresh = data.get("refresh_token", "") or data.get("refreshToken", "")
                name = data.get("name", "") or account.get("username", "MicrosoftUser")
                uid = data.get("id", "") or account.get("uuid", uuid.uuid4().hex)
            else:
                access_token = getattr(data, "access_token", "")
                new_refresh = getattr(data, "refresh_token", "")
                name = getattr(data, "name", "") or account.get("username", "MicrosoftUser")
                uid = getattr(data, "id", "") or account.get("uuid", uuid.uuid4().hex)
            if access_token:
                updated = dict(account)
                updated["access_token"] = access_token
                if new_refresh:
                    updated["refresh_token"] = new_refresh
                updated["username"] = name
                updated["uuid"] = uid
                return updated
        except Exception as e:
            self.log_event(f"Microsoft token refresh failed: {e}")
        return account

    def _extract_java_major(self, version_text):
        v = (version_text or "").strip().lower()
        if not v:
            return 0
        if v.startswith("1."):
            m = re.search(r"1\.(\d+)", v)
            return int(m.group(1)) if m else 0
        m = re.search(r"(\d+)", v)
        return int(m.group(1)) if m else 0

    def _java_version_info(self, java_exe):
        try:
            out = subprocess.check_output([java_exe, "-version"], stderr=subprocess.STDOUT, text=True, timeout=7)
            line = out.splitlines()[0] if out else ""
            m = re.search(r"version\s+\"([^\"]+)\"", line)
            ver = m.group(1) if m else line.strip()
            return ver, self._extract_java_major(ver)
        except Exception:
            return "", 0

    def detect_java_installations(self):
        found = {}

        def add_candidate(path, source):
            if not path:
                return
            p = os.path.normpath(path)
            if not os.path.exists(p):
                return
            key = p.lower()
            if key in found:
                return
            ver_text, major = self._java_version_info(p)
            found[key] = {
                "path": p,
                "source": source,
                "version": ver_text or "unknown",
                "major": major
            }

        java_home = os.getenv("JAVA_HOME", "").strip()
        if java_home:
            add_candidate(os.path.join(java_home, "bin", "javaw.exe"), "JAVA_HOME")
            add_candidate(os.path.join(java_home, "bin", "java.exe"), "JAVA_HOME")

        for ex in ["javaw.exe", "java.exe"]:
            try:
                out = subprocess.check_output(["where", ex], text=True, stderr=subprocess.STDOUT, timeout=5)
                for line in out.splitlines():
                    add_candidate(line.strip(), "PATH")
            except Exception:
                pass

        patterns = [
            r"C:\Program Files\Java\*\bin\javaw.exe",
            r"C:\Program Files\Java\*\bin\java.exe",
            r"C:\Program Files\Eclipse Adoptium\*\bin\javaw.exe",
            r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
            r"C:\Program Files\AdoptOpenJDK\*\bin\javaw.exe",
            r"C:\Program Files\AdoptOpenJDK\*\bin\java.exe",
            os.path.join(BASE_DIR, "java", "*", "bin", "javaw.exe"),
            os.path.join(BASE_DIR, "java", "*", "bin", "java.exe"),
        ]
        for pat in patterns:
            for path in glob.glob(pat):
                add_candidate(path, "scan")

        items = list(found.values())
        items.sort(key=lambda x: (x.get("major", 0), x.get("version", ""), x.get("path", "")), reverse=True)
        return items

    def required_java_major(self, instance):
        mc = str((instance or {}).get("version", "")).strip()
        t = self.version_tuple(mc)
        if t >= (1, 20, 5):
            return 21
        if t >= (1, 17):
            return 17
        return 8

    def ensure_java_downloaded(self, major):
        java_root = os.path.join(BASE_DIR, "java")
        os.makedirs(java_root, exist_ok=True)
        url = (
            f"https://api.adoptium.net/v3/binary/latest/{int(major)}/ga/"
            "windows/x64/jdk/hotspot/normal/eclipse"
        )
        archive = os.path.join(java_root, f"temurin_{int(major)}.zip")
        self.log_event(f"Скачивание Java {major}...")
        self._stream_download(url, archive, f"Java {major}", timeout=180)
        self.log_event(f"Java архив загружен: {archive}")

        extract_dir = os.path.join(java_root, f"jdk-{int(major)}")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(extract_dir)

        java_candidates = glob.glob(os.path.join(extract_dir, "**", "javaw.exe"), recursive=True)
        if not java_candidates:
            java_candidates = glob.glob(os.path.join(extract_dir, "**", "java.exe"), recursive=True)
        if not java_candidates:
            raise RuntimeError("Java скачана, но java.exe не найден.")
        java_path = os.path.normpath(java_candidates[0])
        self.log_event(f"Java готова: {java_path}")
        return java_path

    def resolve_java_for_instance(self, instance, parent=None):
        req_major = self.required_java_major(instance)
        custom = (instance or {}).get("java_path", "").strip()
        if custom and custom.lower() != "auto":
            if os.path.exists(custom):
                _, m = self._java_version_info(custom)
                if m >= req_major:
                    return custom
            QMessageBox.warning(parent or self, "Java", "Выбранная Java не найдена или не подходит. Будет использован автопоиск.")

        detected = self.detect_java_installations()
        suitable = [j for j in detected if int(j.get("major", 0)) >= req_major]
        if suitable:
            return suitable[0]["path"]

        ask = QMessageBox.question(
            parent or self,
            "Java не найдена",
            f"Подходящая Java {req_major}+ не найдена.\nСкачать и установить автоматически?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if ask != QMessageBox.StandardButton.Yes:
            return None
        try:
            return self.ensure_java_downloaded(req_major)
        except Exception as e:
            QMessageBox.warning(parent or self, "Ошибка Java", f"Не удалось скачать Java: {e}")
            return None

    def theme_presets(self):
        return {
            "blue": {"name": "Ocean Blue", "accent": "#0078D4", "accent2": "#4A8DF0", "side_active": "#0078D4"},
            "emerald": {"name": "Emerald", "accent": "#00A66A", "accent2": "#3CCB93", "side_active": "#00C07A"},
            "sunset": {"name": "Sunset", "accent": "#D46B00", "accent2": "#F0994A", "side_active": "#FF8A1F"},
            "rose": {"name": "Rose", "accent": "#C63E65", "accent2": "#EA6C8F", "side_active": "#E0527A"},
            "custom": {"name": "Своя тема"}
        }

    def theme_palette(self):
        theme_id = str(self.settings.get("theme", "blue"))
        presets = self.theme_presets()
        if theme_id == "custom":
            custom_colors = self.settings.get("custom_theme", {})
            base_colors = presets["blue"].copy()
            base_colors.update(custom_colors)
            return base_colors
        return presets.get(theme_id, presets["blue"])

    def apply_theme(self):
        pal = self.theme_palette()
        accent = pal["accent"]
        side_active = pal["side_active"]
        self.setStyleSheet(f"""
            QMainWindow {{ background: #0F0F0F; font-family: 'Segoe UI'; }}
            #Sidebar {{ background: #121212; border-right: 1px solid #222; }}
            #SideBtn {{ background: transparent; border: none; color: white; font-size: 18px; padding: 15px; }}
            #SideBtn:hover {{ color: white; background: #1A1A1A; }}
            #SideBtn[active="true"] {{ color: {side_active}; border-left: 3px solid {side_active}; background: #1A1A1A; }}
            #Inspector {{ background: #141414; border-left: 1px solid #252525; min-width: 300px; }}
            #Card {{ background: #181818; border: 1px solid #333; border-radius: 12px; }}
            #Card[selected="true"] {{ border: 2px solid {accent}; background: #1E1E1E; }}
            #PlayBtn {{ background: {accent}; color: white; font-weight: bold; border-radius: 8px; height: 48px; border: none; }}
            #ActionBtn {{ background: #222; color: white; border-radius: 6px; padding: 12px; text-align: left; border: 1px solid #333; }}
            #ActionBtn:hover {{ background: #282828; color: white; }}
            QMenu {{ background: #1A1A1A; color: white; border: 1px solid #333; }}
            QMenu::item {{ padding: 6px 16px; }}
            QMenu::item:selected {{ background: {accent}; color: white; }}
            QProgressBar {{ background: #000; border-radius: 2px; height: 4px; border: none; }}
            QProgressBar::chunk {{ background: {accent}; }}
        """)

    def primary_btn_css(self):
        pal = self.theme_palette()
        return (
            f"background:{pal['accent']};color:white;border:none;border-radius:8px;"
            "padding:8px 16px;font-weight:700;"
        )

    def refresh_theme_widgets(self):
        css = self.primary_btn_css()
        for name in [
            "lib_add", "mods_search_btn", "mods_update_all_btn", "save_lang_btn",
            "account_btn", "check_updates_btn"
        ]:
            if hasattr(self, name):
                w = getattr(self, name)
                if w is None:
                    continue
                if name == "account_btn":
                    w.setStyleSheet("background:#202020;color:white;border:1px solid #333;border-radius:8px;padding:8px 12px;")
                elif name == "check_updates_btn":
                    w.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:8px 14px;")
                else:
                    w.setStyleSheet(css)

    def on_theme_changed(self, theme_name):
        is_custom = theme_name == "Своя тема" or theme_name == "Custom"
        self.custom_theme_widget.setVisible(is_custom)

    def open_color_picker(self, setting_key, button):
        current_color = self.settings.get("custom_theme", {}).get(setting_key, "#000000")
        color = QColorDialog.getColor(QColor(current_color), self, "Выберите цвет")
        if color.isValid():
            hex_color = color.name()
            self.settings.setdefault("custom_theme", {})[setting_key] = hex_color
            button.setStyleSheet(f"background-color: {hex_color}; border-radius: 8px; border: 1px solid #555;")
            # If the custom theme is active, re-apply it immediately
            if self.settings.get("theme") == "custom":
                self.apply_theme()
                self.refresh_theme_widgets()

    def setup_ui(self):
        self.apply_theme()

        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout(central); main_layout.setContentsMargins(0,0,0,0); main_layout.setSpacing(0)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self.main_splitter)

        # 1. SIDEBAR
        self.sidebar = QFrame(); self.sidebar.setObjectName("Sidebar"); self.sidebar.setFixedWidth(int(self.settings.get("sidebar_width", 70)))
        side_l = QVBoxLayout(self.sidebar); side_l.setContentsMargins(0, 20, 0, 0); side_l.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.side_library = QPushButton("📦"); self.side_library.setObjectName("SideBtn"); self.side_library.setFixedSize(70, 60)
        self.side_news = QPushButton("🏠"); self.side_news.setObjectName("SideBtn"); self.side_news.setFixedSize(70, 60)
        self.side_mods = QPushButton("🧩"); self.side_mods.setObjectName("SideBtn"); self.side_mods.setFixedSize(70, 60)
        self.side_settings = QPushButton("⚙️"); self.side_settings.setObjectName("SideBtn"); self.side_settings.setFixedSize(70, 60)
        self.side_library.clicked.connect(self.show_library_page)
        self.side_news.clicked.connect(self.show_news_page)
        self.side_mods.clicked.connect(self.show_mods_page)
        self.side_settings.clicked.connect(self.show_settings_page)
        side_l.addWidget(self.side_library)
        side_l.addWidget(self.side_news)
        side_l.addWidget(self.side_mods)
        side_l.addWidget(self.side_settings)
        self.main_splitter.addWidget(self.sidebar)

        # 2. ЦЕНТРАЛЬНЫЕ СТРАНИЦЫ
        center_host = QWidget()
        center_host_l = QVBoxLayout(center_host)
        center_host_l.setContentsMargins(0, 0, 0, 0)
        center_host_l.setSpacing(0)

        topbar = QHBoxLayout()
        topbar.setContentsMargins(12, 10, 12, 6)
        self.server_ip_edit = QLineEdit(self.settings.get("server_ip", ""))
        self.server_ip_edit.setPlaceholderText("server:port")
        self.server_ip_edit.setFixedWidth(220)
        self.server_ip_edit.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:6px;")
        self.server_ping_btn = QPushButton("Пинг")
        self.server_ping_btn.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:6px 10px;")
        self.server_ping_btn.clicked.connect(self.refresh_server_status)
        self.server_status_lbl = QLabel("Сервер не выбран")
        self.server_status_lbl.setStyleSheet("color:#AAB4CA;")
        topbar.addWidget(self.server_ip_edit)
        topbar.addWidget(self.server_ping_btn)
        topbar.addWidget(self.server_status_lbl, 1)
        topbar.addStretch()
        self.account_btn = QPushButton("")
        self.account_btn.setStyleSheet("background:#202020;color:white;border:1px solid #333;border-radius:8px;padding:8px 12px;")
        self.account_btn.clicked.connect(self.open_account_manager)
        topbar.addWidget(self.account_btn)
        center_host_l.addLayout(topbar)

        self.pages = QStackedWidget()
        center_host_l.addWidget(self.pages)
        self.main_splitter.addWidget(center_host)

        # Библиотека установок
        self.page_library = QWidget()
        cl = QVBoxLayout(self.page_library); cl.setContentsMargins(30, 30, 30, 30)
        header = QHBoxLayout()
        self.lib_title = QLabel("Мои установки"); self.lib_title.setStyleSheet("font-size: 24px; font-weight: bold; color: white;")
        self.lib_import = QPushButton("📥 Импорт ZIP"); self.lib_import.setFixedSize(130, 32); self.lib_import.setStyleSheet("background: #252525; color: white; border:1px solid #333; border-radius: 16px; font-weight: bold;")
        self.lib_import.clicked.connect(self.import_instance_zip)
        self.lib_add = QPushButton("+ Добавить"); self.lib_add.setFixedSize(110, 32); self.lib_add.setStyleSheet("background: #0078D4; color: white; border-radius: 16px; font-weight: bold;")
        self.lib_add.clicked.connect(self.open_create)
        header.addWidget(self.lib_title); header.addStretch(); header.addWidget(self.lib_import); header.addWidget(self.lib_add)
        cl.addLayout(header)
        self.instances_search = QLineEdit()
        self.instances_search.setPlaceholderText("Поиск по установкам и группам")
        self.instances_search.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.instances_search.textChanged.connect(self.refresh_grid)
        cl.addWidget(self.instances_search)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setStyleSheet("background: transparent; border: none;")
        self.grid_w = QWidget(); self.grid = QGridLayout(self.grid_w)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft); self.grid.setSpacing(20)
        self.scroll.setWidget(self.grid_w); cl.addWidget(self.scroll)
        self.pages.addWidget(self.page_library)

        # Новости
        self.page_news = QWidget()
        nl = QVBoxLayout(self.page_news); nl.setContentsMargins(24, 24, 24, 24); nl.setSpacing(12)
        news_head = QHBoxLayout()
        self.news_title = QLabel("Новости Minecraft")
        self.news_title.setStyleSheet("font-size: 24px; font-weight: 800; color: white;")
        self.news_refresh = QPushButton("🔄 Обновить")
        self.news_refresh.setObjectName("ActionBtn")
        self.news_refresh.clicked.connect(self.load_news_page)
        news_head.addWidget(self.news_title); news_head.addStretch(); news_head.addWidget(self.news_refresh)
        nl.addLayout(news_head)
        self.news_scroll = QScrollArea(); self.news_scroll.setWidgetResizable(True); self.news_scroll.setStyleSheet("background: transparent; border: none;")
        self.news_wrap = QWidget(); self.news_l = QVBoxLayout(self.news_wrap); self.news_l.setAlignment(Qt.AlignmentFlag.AlignTop); self.news_l.setSpacing(10)
        self.news_scroll.setWidget(self.news_wrap); nl.addWidget(self.news_scroll)
        self.pages.addWidget(self.page_news)

        # Моды
        self.page_mods = QWidget()
        ml = QVBoxLayout(self.page_mods); ml.setContentsMargins(24, 24, 24, 24); ml.setSpacing(12)
        mods_head = QHBoxLayout()
        self.mods_title = QLabel("Установка модов")
        self.mods_title.setStyleSheet("font-size: 24px; font-weight: 800; color: white;")
        mods_head.addWidget(self.mods_title); mods_head.addStretch()
        ml.addLayout(mods_head)

        mod_filters = QHBoxLayout()
        self.mods_provider = QComboBox(); self.mods_provider.addItems(["Modrinth"])
        self.mods_provider.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:6px;")
        self.mods_query = QLineEdit(); self.mods_query.setPlaceholderText("Название мода")
        self.mods_query.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.mods_search_btn = QPushButton("Искать")
        self.mods_search_btn.setStyleSheet("background:#0078D4;color:white;border:none;border-radius:8px;padding:8px 16px;font-weight:700;")
        self.mods_search_btn.clicked.connect(lambda: self.search_mods_page(reset_page=True))
        mod_filters.addWidget(self.mods_provider); mod_filters.addWidget(self.mods_query); mod_filters.addWidget(self.mods_search_btn)
        ml.addLayout(mod_filters)

        upd_row = QHBoxLayout()
        self.mods_check_updates_btn = QPushButton("Проверить обновления")
        self.mods_check_updates_btn.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:7px 12px;")
        self.mods_check_updates_btn.clicked.connect(self.check_mod_updates)
        self.mods_update_all_btn = QPushButton("Обновить всё")
        self.mods_update_all_btn.setStyleSheet("background:#0078D4;color:white;border:none;border-radius:8px;padding:7px 14px;font-weight:700;")
        self.mods_update_all_btn.clicked.connect(self.update_all_mods)
        self.mods_conflicts_btn = QPushButton("Проверить конфликты")
        self.mods_conflicts_btn.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:7px 12px;")
        self.mods_conflicts_btn.clicked.connect(self.check_mod_conflicts)
        upd_row.addWidget(self.mods_check_updates_btn)
        upd_row.addWidget(self.mods_update_all_btn)
        upd_row.addWidget(self.mods_conflicts_btn)
        upd_row.addStretch()
        ml.addLayout(upd_row)

        mods_pager = QHBoxLayout()
        self.mods_prev_btn = QPushButton("← Назад")
        self.mods_prev_btn.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:7px 12px;")
        self.mods_prev_btn.clicked.connect(self.mods_prev_page)
        self.mods_page_lbl = QLabel("Страница 1")
        self.mods_page_lbl.setStyleSheet("color:#AFC7F2; font-weight:700;")
        self.mods_next_btn = QPushButton("Вперёд →")
        self.mods_next_btn.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:7px 12px;")
        self.mods_next_btn.clicked.connect(self.mods_next_page)
        mods_pager.addWidget(self.mods_prev_btn)
        mods_pager.addWidget(self.mods_page_lbl)
        mods_pager.addStretch()
        mods_pager.addWidget(self.mods_next_btn)
        ml.addLayout(mods_pager)

        self.mods_scroll = QScrollArea(); self.mods_scroll.setWidgetResizable(True); self.mods_scroll.setStyleSheet("background: transparent; border: none;")
        self.mods_wrap = QWidget(); self.mods_l = QVBoxLayout(self.mods_wrap); self.mods_l.setAlignment(Qt.AlignmentFlag.AlignTop); self.mods_l.setSpacing(10)
        self.mods_scroll.setWidget(self.mods_wrap); ml.addWidget(self.mods_scroll)
        self.pages.addWidget(self.page_mods)

        # Консоль
        self.page_console = QWidget()
        conl = QVBoxLayout(self.page_console); conl.setContentsMargins(24, 24, 24, 24); conl.setSpacing(12)
        con_head = QHBoxLayout()
        self.con_title = QLabel("Игровая консоль")
        self.con_title.setStyleSheet("font-size: 24px; font-weight: 800; color: white;")
        con_head.addWidget(self.con_title); con_head.addStretch()
        
        self.console_clear_btn = QPushButton("🗑 Очистить")
        self.console_clear_btn.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:7px 12px;")
        self.console_clear_btn.clicked.connect(self.clear_console)
        
        self.console_autoscroll_check = QCheckBox("Автопрокрутка")
        self.console_autoscroll_check.setChecked(True)
        self.console_autoscroll_check.setStyleSheet("color:white;")

        con_head.addWidget(self.console_autoscroll_check)
        con_head.addWidget(self.console_clear_btn)
        conl.addLayout(con_head)
        
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setStyleSheet("background:#0A0A0A; color:#E0E0E0; font-family: Consolas, 'Courier New', monospace; border: 1px solid #333; border-radius: 8px;")
        conl.addWidget(self.console_output)
        self.pages.addWidget(self.page_console)

        # Настройки
        self.page_settings = QWidget()
        self.page_settings.setStyleSheet("QLabel { color: white; }")
        sl = QVBoxLayout(self.page_settings); sl.setContentsMargins(30, 30, 30, 30); sl.setSpacing(16)
        self.settings_title = QLabel("Настройки")
        self.settings_title.setStyleSheet("font-size: 24px; font-weight: 800; color: white;")
        sl.addWidget(self.settings_title)
        form_settings = QFormLayout()
        self.lang_box = QComboBox()
        self.lang_box.addItems(["Русский", "English", "Українська"])
        lang_index = {"ru": 0, "en": 1, "uk": 2}.get(self.lang, 0)
        self.lang_box.setCurrentIndex(lang_index)
        self.lang_box.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.lang_label = QLabel("Язык лаунчера")
        form_settings.addRow(self.lang_label, self.lang_box)

        self.theme_box = QComboBox()
        themes = self.theme_presets()
        self.theme_ids = list(themes.keys())
        for tid in self.theme_ids:
            self.theme_box.addItem(themes[tid]["name"])
        cur_theme = str(self.settings.get("theme", "blue"))
        cur_idx = self.theme_ids.index(cur_theme) if cur_theme in self.theme_ids else 0
        self.theme_box.setCurrentIndex(cur_idx)
        self.theme_box.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.theme_label = QLabel("Тема лаунчера")
        form_settings.addRow(self.theme_label, self.theme_box)
        
        self.custom_theme_widget = QWidget()
        custom_theme_layout = QFormLayout(self.custom_theme_widget)
        custom_theme_layout.setContentsMargins(0, 10, 0, 0)
        self.accent_color_btn = QPushButton()
        self.accent_color_btn.setFixedSize(120, 28)
        self.accent_color_btn.clicked.connect(lambda: self.open_color_picker("accent", self.accent_color_btn))
        custom_theme_layout.addRow("Основной акцент:", self.accent_color_btn)
        
        self.sidebar_color_btn = QPushButton()
        self.sidebar_color_btn.setFixedSize(120, 28)
        self.sidebar_color_btn.clicked.connect(lambda: self.open_color_picker("side_active", self.sidebar_color_btn))
        custom_theme_layout.addRow("Акцент боковой панели:", self.sidebar_color_btn)
        form_settings.addRow(self.custom_theme_widget)

        self.ram_spin = QSpinBox()
        self.ram_spin.setRange(1024, 32768)
        self.ram_spin.setSingleStep(512)
        self.ram_spin.setSuffix(" MB")
        self.ram_spin.setValue(int(self.settings.get("ram_mb", 2048)))
        self.ram_spin.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.ram_label = QLabel("Оперативная память для Minecraft")
        form_settings.addRow(self.ram_label, self.ram_spin)
        self.auto_ram_check = QCheckBox("Автоподбор RAM по системе")
        self.auto_ram_check.setChecked(bool(self.settings.get("auto_ram", True)))
        self.auto_ram_check.setStyleSheet("color:white;")
        self.ram_spin.setEnabled(not self.auto_ram_check.isChecked())
        self.auto_ram_check.toggled.connect(lambda v: self.ram_spin.setEnabled(not v))
        form_settings.addRow("", self.auto_ram_check)

        self.sidebar_spin = QSpinBox()
        self.sidebar_spin.setRange(70, 260)
        self.sidebar_spin.setSingleStep(10)
        self.sidebar_spin.setValue(int(self.settings.get("sidebar_width", 70)))
        self.sidebar_spin.setSuffix(" px")
        self.sidebar_spin.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.sidebar_label = QLabel("Ширина бокового меню")
        form_settings.addRow(self.sidebar_label, self.sidebar_spin)

        self.update_check_box = QCheckBox("Проверять обновления лаунчера при старте")
        self.update_check_box.setChecked(bool(self.settings.get("auto_update_check", False)))
        self.update_check_box.setStyleSheet("color:white;")
        form_settings.addRow("", self.update_check_box)

        self.cleanup_check = QCheckBox("Автоочистка старых логов/кэша")
        self.cleanup_check.setChecked(bool(self.settings.get("auto_cleanup_enabled", True)))
        self.cleanup_check.setStyleSheet("color:white;")
        form_settings.addRow("", self.cleanup_check)

        self.cleanup_days_spin = QSpinBox()
        self.cleanup_days_spin.setRange(1, 180)
        self.cleanup_days_spin.setValue(int(self.settings.get("cleanup_days", 14)))
        self.cleanup_days_spin.setSuffix(" дн")
        self.cleanup_days_spin.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.cleanup_days_label = QLabel("Хранить логи/кэш")
        form_settings.addRow(self.cleanup_days_label, self.cleanup_days_spin)

        self.ms_client_edit = QLineEdit(self.settings.get("ms_client_id", ""))
        self.ms_client_edit.setPlaceholderText("Microsoft App Client ID (для loopback входа)")
        self.ms_client_edit.setStyleSheet("background:#1A1A1A;color:white;border:1px solid #333;border-radius:8px;padding:8px;")
        self.ms_client_label = QLabel("Microsoft Client ID")
        form_settings.addRow(self.ms_client_label, self.ms_client_edit)

        self.discord_rpc_check = QCheckBox("Discord Rich Presence")
        self.discord_rpc_check.setChecked(bool(self.settings.get("discord_rpc_enabled", False)))
        self.discord_rpc_check.setStyleSheet("color:white;")
        form_settings.addRow("", self.discord_rpc_check)

        sl.addLayout(form_settings)
        sl.addStretch()
        bottom_row = QHBoxLayout()
        self.check_updates_btn = QPushButton("Проверить обновления")
        self.check_updates_btn.setStyleSheet("background:#252525;color:white;border:1px solid #333;border-radius:8px;padding:8px 14px;")
        self.check_updates_btn.clicked.connect(lambda: self.check_launcher_updates(manual=True))
        bottom_row.addWidget(self.check_updates_btn)
        bottom_row.addStretch()
        bottom_row.addStretch()
        self.save_lang_btn = QPushButton("Сохранить")
        self.save_lang_btn.setStyleSheet("background:#0078D4;color:white;border:none;border-radius:8px;padding:8px 16px;font-weight:700;")
        self.save_lang_btn.clicked.connect(self.save_language)
        bottom_row.addWidget(self.save_lang_btn)
        sl.addLayout(bottom_row)
        self.pages.addWidget(self.page_settings)
        
        self.theme_box.currentTextChanged.connect(self.on_theme_changed)
        self.on_theme_changed(self.theme_box.currentText())
        custom_theme_settings = self.settings.get("custom_theme", {})
        self.accent_color_btn.setStyleSheet(f"background-color: {custom_theme_settings.get('accent', '#0078D4')}; border-radius: 8px; border: 1px solid #555;")
        self.sidebar_color_btn.setStyleSheet(f"background-color: {custom_theme_settings.get('side_active', '#4A8DF0')}; border-radius: 8px; border: 1px solid #555;")


        # 3. ИНСПЕКТОР (Правая панель)
        self.inspector = QFrame(); self.inspector.setObjectName("Inspector"); self.inspector.setVisible(False)
        self.ins_l = QVBoxLayout(self.inspector); self.ins_l.setContentsMargins(20, 40, 20, 20)
        
        self.ins_title = QLabel("Name"); self.ins_title.setStyleSheet("font-size: 20px; font-weight: bold; color: white;")
        self.ins_info = QLabel("Version"); self.ins_info.setStyleSheet("color: #666; margin-bottom: 20px;")
        self.ins_l.addWidget(self.ins_title); self.ins_l.addWidget(self.ins_info)

        self.play_btn = QPushButton("ИГРАТЬ"); self.play_btn.setObjectName("PlayBtn"); self.play_btn.clicked.connect(self.handle_launch)
        self.pbar = QProgressBar(); self.pbar.setVisible(False)
        self.ins_l.addWidget(self.play_btn); self.ins_l.addWidget(self.pbar)
        
        self.ins_l.addSpacing(30)
        
        # Основные действия (вернулись в инспектор)
        self.btn_launch = QPushButton("▶ Запустить"); self.btn_launch.setObjectName("ActionBtn"); self.btn_launch.clicked.connect(self.handle_launch)
        self.btn_stop = QPushButton("⏹ Остановить"); self.btn_stop.setObjectName("ActionBtn"); self.btn_stop.clicked.connect(self.force_stop_minecraft)
        self.btn_folder = QPushButton("📁 Папка"); self.btn_folder.setObjectName("ActionBtn"); self.btn_folder.clicked.connect(self.open_instance_folder)
        self.btn_copy = QPushButton("🧬 Копировать"); self.btn_copy.setObjectName("ActionBtn"); self.btn_copy.clicked.connect(self.duplicate_selected_instance)
        self.btn_shortcut = QPushButton("🚀 Создать ярлык"); self.btn_shortcut.setObjectName("ActionBtn"); self.btn_shortcut.clicked.connect(self.create_instance_shortcut)
        self.btn_delete = QPushButton("🗑 Удалить"); self.btn_delete.setObjectName("ActionBtn"); self.btn_delete.clicked.connect(self.delete_current)
        self.btn_delete.setStyleSheet("background:#2A1A1A;color:#FFB0B0;border:1px solid #6A2A2A;border-radius:6px;padding:12px;text-align:left;")
        for b in [self.btn_launch, self.btn_stop, self.btn_folder, self.btn_copy, self.btn_shortcut, self.btn_delete]:
            self.ins_l.addWidget(b)
            b.setEnabled(False)

        self.ins_l.addSpacing(12)

        # Кнопка "Изменить..." с меню действий
        self.edit_btn = QPushButton("Изменить…")
        self.edit_btn.setObjectName("ActionBtn")
        self.edit_menu = QMenu(self)
        self.edit_btn.clicked.connect(self.show_edit_menu)
        self.ins_l.addWidget(self.edit_btn)

        self._build_edit_menu()
        self.edit_btn.setEnabled(False)
        self.ins_l.addStretch()
        
        self.main_splitter.addWidget(self.inspector)
        self.main_splitter.setSizes([int(self.settings.get("sidebar_width", 70)), 760, 300])
        self.main_splitter.splitterMoved.connect(self.on_splitter_moved)
        self.bottom_left_time = QLabel("")
        self.bottom_left_time.setStyleSheet("color:#AAB4CA;padding:4px 12px 10px 12px;")
        self.bottom_right_total = QLabel("")
        self.bottom_right_total.setStyleSheet("color:#AAB4CA;padding:4px 12px 10px 12px;")
        bbar = QHBoxLayout()
        bbar.addWidget(self.bottom_left_time)
        bbar.addStretch()
        bbar.addWidget(self.bottom_right_total)
        center_host_l.addLayout(bbar)
        self.show_library_page()
        self.apply_sidebar_width()
        self.refresh_account_button()
        self.apply_language()
        self.refresh_theme_widgets()
        self.update_playtime_labels()
        if self.settings.get("auto_update_check", False):
            self.check_launcher_updates(manual=False)
        if bool(self.settings.get("auto_cleanup_enabled", True)):
            QTimer.singleShot(2000, lambda: self.cleanup_old_data(manual=False))
        QTimer.singleShot(1200, self.refresh_server_status)

    def select_instance(self, data):
        self.selected_instance = data
        self.ins_title.setText(data['name'])
        installer = data.get('installer', 'vanilla').capitalize()
        java_txt = data.get("java_path", "") or "auto"
        if java_txt and java_txt.lower() != "auto":
            java_txt = f"custom ({os.path.basename(java_txt)})"
        else:
            java_txt = "auto"
        self.ins_info.setText(f"Minecraft {data['version']} | {installer} | Java: {java_txt}")
        for b in [self.btn_launch, self.btn_stop, self.btn_folder, self.btn_copy, self.btn_shortcut, self.btn_delete]:
            b.setEnabled(True)
        self.edit_btn.setEnabled(True)
        self._update_edit_menu_state()
        self.inspector.setVisible(self.pages.currentWidget() == self.page_library)
        self.update_playtime_labels()
        self.refresh_grid()
        self.update_discord_presence()

    def open_mods(self):
        self.show_mods_page()

    def open_mod_market(self):
        self.show_mods_page()

    def open_news(self):
        self.show_news_page()

    def open_edit_instance_dialog(self):
        if not self.selected_instance:
            return
        inst = self._find_instance_by_path(self.selected_instance.get("path", "")) or self.selected_instance
        d = EditInstanceDialog(self, inst, list(self.instance_data.keys()))
        if d.exec():
            data = d.get_data()
            path = inst.get("path", "")
            if not path:
                return

            old_group = inst.get("group", "Main")
            new_group = data.get("group", old_group)
            if new_group != old_group:
                self._move_instance_to_group(path, new_group)

            updates = {
                "name": data.get("name", inst.get("name", "")),
                "emoji": data.get("emoji", inst.get("emoji", "")),
                "installer": data.get("installer", inst.get("installer", "vanilla")),
                "loader_version": data.get("loader_version", inst.get("loader_version", "")),
            }
            self._update_instance_data(path, updates)

            apply_loader = bool(data.get("apply_loader", False))
            if apply_loader and updates["installer"] != "vanilla":
                try:
                    real_ver = self.install_loader_for_instance(self._find_instance_by_path(path), updates["installer"], updates.get("loader_version", ""))
                    if real_ver:
                        self._update_instance_data(path, {"loader_version": real_ver})
                    t = getattr(self, "lang_labels", {}) or {}
                    QMessageBox.information(self, "Готово", t.get("loader_done", "Загрузчик установлен/обновлён."))
                except Exception as e:
                    t = getattr(self, "lang_labels", {}) or {}
                    QMessageBox.warning(self, "Ошибка", t.get("loader_fail", "Не удалось установить загрузчик: {e}").format(e=e))

            self.save_data()
            self.refresh_grid()
            inst2 = self._find_instance_by_path(path)
            if inst2:
                self.select_instance(inst2)

    def _update_instance_data(self, inst_path, updates):
        for g in self.instance_data:
            for i, it in enumerate(self.instance_data[g]):
                if it.get("path") == inst_path:
                    self.instance_data[g][i].update(updates)
                    if self.selected_instance and self.selected_instance.get("path") == inst_path:
                        self.selected_instance = self.instance_data[g][i]
                    return

    def _find_instance_by_path(self, inst_path):
        for g, insts in self.instance_data.items():
            for inst in insts:
                if inst.get("path") == inst_path:
                    inst["group"] = g
                    return inst
        return None

    def install_loader_for_instance(self, inst, loader, loader_version):
        if not inst:
            raise RuntimeError("Установка не найдена.")
        p = inst.get("path", "")
        mc_version = inst.get("version", "")
        if not p or not mc_version:
            raise RuntimeError("Некорректные данные установки.")

        callback = {"setStatus": lambda t: self.log_event(f"[loader] {t}"), "setProgress": lambda v: None}
        loader = str(loader or "vanilla").lower()
        if loader == "fabric":
            if not loader_version or loader_version in ("—", "latest"):
                loader_version = minecraft_launcher_lib.fabric.get_latest_loader_version()
            minecraft_launcher_lib.fabric.install_fabric(mc_version, p, loader_version=loader_version, callback=callback)
            return loader_version
        if loader == "quilt":
            if not loader_version or loader_version in ("—", "latest"):
                loader_version = minecraft_launcher_lib.quilt.get_latest_loader_version()
            minecraft_launcher_lib.quilt.install_quilt(mc_version, p, loader_version=loader_version, callback=callback)
            return loader_version
        if loader == "forge":
            forge_version = loader_version
            if not forge_version or forge_version in ("—", "latest"):
                forge_version = minecraft_launcher_lib.forge.find_forge_version(mc_version)
            if not forge_version:
                raise RuntimeError("Forge версия не найдена.")
            minecraft_launcher_lib.forge.install_forge_version(forge_version, p, callback=callback)
            return forge_version
        return ""

    def _set_active_sidebar(self, active_btn):
        for btn in [self.side_library, self.side_news, self.side_mods, self.side_settings]:
            btn.setProperty("active", "true" if btn is active_btn else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def show_library_page(self):
        self.switch_page_animated(self.page_library)
        self.inspector.setVisible(self.selected_instance is not None)
        self._set_active_sidebar(self.side_library)

    def show_news_page(self):
        self.switch_page_animated(self.page_news)
        self.inspector.setVisible(False)
        self.load_news_page()
        self._set_active_sidebar(self.side_news)

    def show_mods_page(self):
        self.switch_page_animated(self.page_mods)
        self.inspector.setVisible(False)
        self._set_active_sidebar(self.side_mods)

    def show_console_page(self):
        self.switch_page_animated(self.page_console)
        self.inspector.setVisible(False)

    def _console_color_for_text(self, text):
        low = (text or "").lower()
        if "error" in low or "ошиб" in low or "exception" in low:
            return "#FF7A7A"
        if "warn" in low or "предуп" in low:
            return "#FFD166"
        if "success" in low or "готов" in low or "успеш" in low:
            return "#7BE495"
        if "launch" in low or "запуск" in low or "starting" in low:
            return "#7EC8FF"
        return "#E0E0E0"

    def append_log_message(self, text):
        color = self._console_color_for_text(text)
        safe = html.escape(text)
        self.console_output.append(f'<span style="color:{color}">{safe}</span>')
        if self.console_autoscroll_check.isChecked():
            self.console_output.verticalScrollBar().setValue(self.console_output.verticalScrollBar().maximum())

    def clear_console(self):
        self.console_output.clear()

    def update_mods_pager(self):
        self.mods_page_lbl.setText(f"Страница {self.mods_page + 1}")
        self.mods_prev_btn.setEnabled(self.mods_page > 0)
        self.mods_next_btn.setEnabled(self.mods_has_next)

    def mods_prev_page(self):
        if self.mods_page <= 0:
            return
        self.mods_page -= 1
        self.search_mods_page()

    def mods_next_page(self):
        if not self.mods_has_next:
            return
        self.mods_page += 1
        self.search_mods_page()

    def show_settings_page(self):
        self.switch_page_animated(self.page_settings)
        self.inspector.setVisible(False)
        self._set_active_sidebar(self.side_settings)

    def switch_page_animated(self, target):
        if self.pages.currentWidget() == target:
            return
        self.pages.setCurrentWidget(target)
        effect = QGraphicsOpacityEffect(target)
        target.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.finished.connect(lambda: target.setGraphicsEffect(None))
        self._page_anim = anim
        anim.start()

    def apply_sidebar_width(self):
        width = int(self.settings.get("sidebar_width", 70))
        width = max(70, min(260, width))
        self.sidebar.setFixedWidth(width)

        t = getattr(self, "lang_labels", {}) or {}
        labels = [
            (self.side_library, "📦", " " + t.get("tab_library", "Установки")),
            (self.side_news, "🏠", " " + t.get("tab_news", "Новости")),
            (self.side_mods, "🧩", " " + t.get("tab_mods", "Моды")),
            (self.side_settings, "⚙️", " " + t.get("tab_settings", "Настройки")),
        ]
        show_text = width >= 130
        for btn, icon, txt in labels:
            btn.setFixedHeight(44 if show_text else 60)
            btn.setFixedWidth(width - 8 if show_text else 70)
            btn.setText(icon + txt if show_text else icon)
            btn.setStyleSheet(
                "background: transparent; border: none; color: white; "
                f"font-size: 17px; text-align: {'left' if show_text else 'center'}; padding: {10 if show_text else 15}px;"
            )

    def on_splitter_moved(self, *_):
        width = self.sidebar.width()
        width = max(70, min(260, width))
        if self.settings.get("sidebar_width") != width:
            self.settings["sidebar_width"] = width
            self.sidebar_spin.setValue(width)
            self.apply_sidebar_width()

    def refresh_account_button(self):
        acc = self.get_active_account()
        acc_type = "MS" if acc.get("type") == "microsoft" else "Offline"
        self.account_btn.setText(f"👤 {acc.get('username', 'Player')} ({acc_type})")
        self.update_discord_presence()

    def _microsoft_login(self):
        custom_client_id = (self.settings.get("ms_client_id", "") or os.getenv("MS_CLIENT_ID", "")).strip()
        default_client_id = "00000000402b5328"
        desktop_redirect = "https://login.live.com/oauth20_desktop.srf"

        def login_desktop_manual():
            login_url, state, code_verifier = minecraft_launcher_lib.microsoft_account.get_secure_login_data(default_client_id, desktop_redirect)
            if os.name == "nt":
                os.startfile(login_url)
            else:
                webbrowser.open(login_url)
            pasted_url, ok = QInputDialog.getText(
                self,
                "Microsoft Login",
                "Если видите страницу 'Вы попали на страницу, которая обычно не отображается' — это нормально.\n"
                "Скопируйте полный URL из адресной строки (или только параметр code=...) и вставьте сюда:"
            )
            if not ok or not pasted_url.strip():
                return None
            pasted = pasted_url.strip()
            auth_code = None
            try:
                # Standard case: full redirected URL
                auth_code = minecraft_launcher_lib.microsoft_account.parse_auth_code_url(pasted, state)
            except Exception:
                # Fallback: user pasted only code or query part
                raw = pasted
                if raw.startswith("code="):
                    raw = raw[5:]
                else:
                    try:
                        parsed = urllib.parse.urlparse(pasted)
                        qs = urllib.parse.parse_qs(parsed.query)
                        if "code" in qs and qs["code"]:
                            raw = qs["code"][0]
                    except Exception:
                        pass
                auth_code = urllib.parse.unquote(raw).strip()
                if not auth_code:
                    raise RuntimeError("Не удалось извлечь code из вставленного текста.")
            return minecraft_launcher_lib.microsoft_account.complete_login(default_client_id, None, desktop_redirect, auth_code, code_verifier)

        def login_loopback(client_id):
            auth_url = {"value": None}
            event = threading.Event()

            class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path.startswith("/auth/callback"):
                        auth_url["value"] = f"http://127.0.0.1:{self.server.server_address[1]}{self.path}"
                        event.set()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(
                            "<html><body style='background:#111;color:#eee;font-family:Segoe UI'>"
                            "<h3>Вход успешно получен</h3><p>Можно закрыть вкладку и вернуться в лаунчер.</p>"
                            "</body></html>".encode("utf-8")
                        )
                    else:
                        self.send_response(404)
                        self.end_headers()

                def log_message(self, *_):
                    return

            server = None
            redirect_uri = "http://127.0.0.1:53682/auth/callback"
            try:
                server = socketserver.TCPServer(("127.0.0.1", 53682), OAuthCallbackHandler)
                login_url, state, code_verifier = minecraft_launcher_lib.microsoft_account.get_secure_login_data(client_id, redirect_uri)
                if os.name == "nt":
                    os.startfile(login_url)
                else:
                    webbrowser.open(login_url)
                t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
                t.start()
                deadline = time.time() + 300
                while time.time() < deadline and not event.is_set():
                    QApplication.processEvents()
                    time.sleep(0.1)
                callback_url = auth_url["value"]
                if not callback_url:
                    raise RuntimeError("Не удалось получить callback от браузера (таймаут 5 минут).")
                auth_code = minecraft_launcher_lib.microsoft_account.parse_auth_code_url(callback_url, state)
                return minecraft_launcher_lib.microsoft_account.complete_login(client_id, None, redirect_uri, auth_code, code_verifier)
            finally:
                if server is not None:
                    try:
                        server.shutdown()
                    except Exception:
                        pass
                    try:
                        server.server_close()
                    except Exception:
                        pass

        login_data = None
        # 1) Custom Azure App with localhost callback (auto, no manual copy)
        if custom_client_id:
            try:
                login_data = login_loopback(custom_client_id)
            except Exception as e:
                self.log_event(f"Microsoft loopback login fallback: {e}")
                # fallback below

        # 2) Reliable fallback: official desktop redirect + manual URL paste
        if login_data is None:
            login_data = login_desktop_manual()
            if login_data is None:
                return None

        def _g(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        err = _g(login_data, "error", None)
        if err:
            raise RuntimeError(_g(login_data, "errorMessage", "Ошибка авторизации Microsoft"))

        access_token = _g(login_data, "access_token", "") or ""
        username = _g(login_data, "name", "") or ""
        user_uuid = _g(login_data, "id", "") or ""
        refresh_token = _g(login_data, "refresh_token", "") or ""
        if not access_token:
            raise RuntimeError("Microsoft вход не вернул access_token. Попробуйте снова.")

        store = minecraft_launcher_lib.microsoft_account.get_store_information(access_token)
        items = _g(store, "items", []) if not isinstance(store, dict) else store.get("items", [])
        has_license = False
        for item in items or []:
            nm = (item.get("name", "") if isinstance(item, dict) else getattr(item, "name", "")) or ""
            if "minecraft" in nm.lower():
                has_license = True
                break
        if not has_license:
            QMessageBox.warning(self, "Лицензия не найдена", "На Microsoft-аккаунте не найдена лицензия Minecraft.")
            return None

        return {
            "type": "microsoft",
            "username": username or "MicrosoftUser",
            "uuid": user_uuid or uuid.uuid4().hex,
            "access_token": access_token,
            "refresh_token": refresh_token
        }

    def open_account_manager(self):
        d = QDialog(self)
        d.setWindowTitle("Аккаунты")
        d.resize(560, 430)
        d.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QListWidget { background:#1A1A1A; color:#E7E7E7; border:1px solid #333; border-radius:8px; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
            QPushButton:hover { background:#2D2D2D; }
            #PrimaryBtn { background:#0078D4; border:none; }
        """)
        l = QVBoxLayout(d)
        lst = QListWidget()
        l.addWidget(lst)

        def refresh_list():
            lst.clear()
            accounts = self.settings.get("accounts", [])
            active = self.settings.get("active_account", 0)
            for i, acc in enumerate(accounts):
                mark = "✅ " if i == active else ""
                typ = "Microsoft" if acc.get("type") == "microsoft" else "Пиратский"
                lst.addItem(f"{mark}{acc.get('username', 'Unknown')} | {typ}")

        refresh_list()

        hb = QHBoxLayout()
        add_offline = QPushButton("Добавить пиратский")
        add_ms = QPushButton("Добавить Microsoft (браузер)")
        skin_btn = QPushButton("Скин/Кейп")
        activate = QPushButton("Сделать активным")
        delete = QPushButton("Удалить")
        close = QPushButton("Закрыть"); close.setObjectName("PrimaryBtn")
        hb.addWidget(add_offline); hb.addWidget(add_ms); hb.addWidget(skin_btn); hb.addWidget(activate); hb.addWidget(delete); hb.addWidget(close)
        l.addLayout(hb)

        def on_add_offline():
            nick, ok = QInputDialog.getText(d, "Пиратский аккаунт", "Введите ник (минимум 3 символа):")
            nick = nick.strip()
            if not ok:
                return
            if len(nick) < 3:
                QMessageBox.warning(d, "Ошибка", "Ник должен быть минимум 3 символа.")
                return
            acc = {"type": "offline", "username": nick, "uuid": uuid.uuid3(uuid.NAMESPACE_DNS, nick).hex}
            self.settings.setdefault("accounts", []).append(acc)
            self.save_settings()
            refresh_list()
            self.refresh_account_button()

        def on_add_ms():
            try:
                acc = self._microsoft_login()
                if not acc:
                    return
                self.settings.setdefault("accounts", []).append(acc)
                self.save_settings()
                refresh_list()
                self.refresh_account_button()
            except Exception as e:
                QMessageBox.warning(d, "Ошибка", f"Microsoft вход не удался: {e}")

        def on_activate():
            idx = lst.currentRow()
            if idx < 0:
                return
            self.settings["active_account"] = idx
            self.save_settings()
            refresh_list()
            self.refresh_account_button()

        def on_delete():
            idx = lst.currentRow()
            accounts = self.settings.get("accounts", [])
            if idx < 0 or idx >= len(accounts):
                return
            del accounts[idx]
            if not accounts:
                accounts.append({"type": "offline", "username": "Player", "uuid": uuid.uuid3(uuid.NAMESPACE_DNS, "player").hex})
            self.settings["accounts"] = accounts
            self.settings["active_account"] = min(self.settings.get("active_account", 0), len(accounts) - 1)
            self.save_settings()
            refresh_list()
            self.refresh_account_button()

        def on_skin_cape():
            idx = lst.currentRow()
            accounts = self.settings.get("accounts", [])
            if idx < 0 or idx >= len(accounts):
                return
            acc = accounts[idx]
            if acc.get("type") != "offline":
                QMessageBox.information(d, "Информация", "Скин/Кейп настраивается только для пиратских аккаунтов.")
                return
            skin, _ = QFileDialog.getOpenFileName(d, "Выбрать скин", "", "Images (*.png)")
            if skin:
                acc["skin_path"] = skin
            cape, _ = QFileDialog.getOpenFileName(d, "Выбрать кейп (необязательно)", "", "Images (*.png)")
            if cape:
                acc["cape_path"] = cape
            accounts[idx] = acc
            self.settings["accounts"] = accounts
            self.save_settings()
            QMessageBox.information(d, "Готово", "Скин/Кейп сохранены для аккаунта.")

        add_offline.clicked.connect(on_add_offline)
        add_ms.clicked.connect(on_add_ms)
        skin_btn.clicked.connect(on_skin_cape)
        activate.clicked.connect(on_activate)
        delete.clicked.connect(on_delete)
        close.clicked.connect(d.accept)
        d.exec()

    def _fetch_html(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "PyLanLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def load_news_page(self):
        self._clear_layout(self.news_l)
        try:
            html_doc = self._fetch_html("https://www.minecraft.net/en-us/articles")
            matches = re.findall(r'href="(/en-us/article/[^"]+)"[^>]*>(.*?)</a>', html_doc, flags=re.IGNORECASE | re.DOTALL)
            self.news_items = []
            seen = set()
            for rel_link, raw_title in matches:
                link = "https://www.minecraft.net" + rel_link
                title = re.sub(r"<[^>]+>", "", raw_title)
                title = html.unescape(" ".join(title.split()))
                if not title or link in seen:
                    continue
                seen.add(link)
                self.news_items.append({"title": title, "link": link})
                if len(self.news_items) >= 20:
                    break

            if not self.news_items:
                self.news_l.addWidget(QLabel("Не удалось получить новости."))
                return

            for item in self.news_items:
                card = QFrame()
                card.setStyleSheet("background:#171717;border:1px solid #2E2E2E;border-radius:12px;")
                row = QHBoxLayout(card); row.setContentsMargins(12, 12, 12, 12)
                txt = QVBoxLayout()
                t = QLabel(item["title"]); t.setWordWrap(True); t.setStyleSheet("color:white;font-size:15px;font-weight:700;")
                s = QLabel("minecraft.net article"); s.setStyleSheet("color:#8AA0C8;")
                txt.addWidget(t); txt.addWidget(s)
                open_b = QPushButton("Открыть")
                open_b.setStyleSheet("background:#0078D4;color:white;border:none;border-radius:8px;padding:8px 14px;font-weight:700;")
                open_b.clicked.connect(lambda _, url=item["link"]: os.startfile(url))
                row.addLayout(txt); row.addStretch(); row.addWidget(open_b)
                self.news_l.addWidget(card)
        except Exception as e:
            self.news_l.addWidget(QLabel(f"Ошибка загрузки новостей: {e}"))

    def _http_json(self, url, headers=None):
        req_headers = {"User-Agent": "PyLanLauncher/1.0"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))

    def _download_to_instance_mods(self, instance, url, filename):
        mods_dir = os.path.join(instance.get("path", ""), "mods")
        if not os.path.exists(mods_dir):
            os.makedirs(mods_dir)
        bad = '<>:"/\\|?*'
        filename = ''.join('_' if ch in bad else ch for ch in (filename or "mod.jar"))
        target = os.path.join(mods_dir, filename)
        base, ext = os.path.splitext(target)
        n = 1
        while os.path.exists(target):
            target = f"{base}_{n}{ext}"
            n += 1
        self._stream_download(url, target, f"Мод: {filename}", timeout=120)
        return target

    def create_instance_backup(self, inst, reason="manual"):
        inst_path = inst.get("path", "")
        if not inst_path or not os.path.exists(inst_path):
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", inst.get("name", "instance"))
        backup_name = f"{safe_name}_{reason}_{ts}.zip"
        backup_path = os.path.join(self.backups_dir(), backup_name)
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(inst_path):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, inst_path)
                    zf.write(full, arcname=rel)
        self.log_event(f"Создан бэкап: {backup_name}")
        return backup_path

    def list_instance_backups(self, inst):
        bdir = self.backups_dir()
        prefix = re.sub(r"[^a-zA-Z0-9._-]+", "_", inst.get("name", "instance")) + "_"
        files = [f for f in os.listdir(bdir) if f.startswith(prefix) and f.endswith(".zip")]
        files.sort(reverse=True)
        return files

    def restore_instance_backup(self, inst, backup_file):
        bpath = os.path.join(self.backups_dir(), backup_file)
        inst_path = inst.get("path", "")
        if not os.path.exists(bpath) or not inst_path:
            raise RuntimeError("Бэкап или путь установки не найден")
        if os.path.exists(inst_path):
            shutil.rmtree(inst_path, ignore_errors=True)
        os.makedirs(inst_path, exist_ok=True)
        with zipfile.ZipFile(bpath, "r") as zf:
            zf.extractall(inst_path)
        self.log_event(f"Восстановлен бэкап: {backup_file}")

    def open_backups_manager(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        d = QDialog(self)
        d.setWindowTitle(f"Бэкапы: {inst.get('name', 'Unnamed')}")
        d.resize(650, 420)
        d.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QListWidget { background:#1A1A1A; color:#EAEAEA; border:1px solid #333; border-radius:8px; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
            QPushButton:hover { background:#2D2D2D; }
            #PrimaryBtn { background:#0078D4; border:none; }
        """)
        l = QVBoxLayout(d)
        lst = QListWidget()
        l.addWidget(lst)

        def refill():
            lst.clear()
            for f in self.list_instance_backups(inst):
                lst.addItem(f)

        refill()
        hb = QHBoxLayout()
        mk = QPushButton("Создать бэкап")
        restore = QPushButton("Восстановить")
        delete = QPushButton("Удалить")
        close = QPushButton("Закрыть"); close.setObjectName("PrimaryBtn")
        hb.addWidget(mk); hb.addWidget(restore); hb.addWidget(delete); hb.addStretch(); hb.addWidget(close)
        l.addLayout(hb)

        mk.clicked.connect(lambda: (self.create_instance_backup(inst, "manual"), refill()))
        def do_restore():
            row = lst.currentRow()
            if row < 0:
                return
            name = lst.item(row).text()
            if QMessageBox.question(d, "Подтверждение", f"Восстановить бэкап?\n{name}") != QMessageBox.StandardButton.Yes:
                return
            self.restore_instance_backup(inst, name)
            QMessageBox.information(d, "Готово", "Бэкап восстановлен.")
        restore.clicked.connect(do_restore)
        def do_delete():
            row = lst.currentRow()
            if row < 0:
                return
            name = lst.item(row).text()
            try:
                os.remove(os.path.join(self.backups_dir(), name))
                refill()
            except Exception as e:
                QMessageBox.warning(d, "Ошибка", str(e))
        delete.clicked.connect(do_delete)
        close.clicked.connect(d.accept)
        d.exec()

    def open_assets_manager(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        d = QDialog(self)
        d.setWindowTitle(f"Ресурсы/Шейдеры: {inst.get('name', 'Unnamed')}")
        d.resize(900, 620)
        primary_css = self.primary_btn_css() if hasattr(self, "primary_btn_css") else "background:#0078D4;color:white;border:none;border-radius:8px;padding:8px 16px;font-weight:700;"
        d.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QLabel { color:#DDD; }
            QLineEdit, QComboBox, QListWidget {
                background:#1A1A1A; color:white; border:1px solid #333; border-radius:8px; padding:8px;
            }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #2A2A2A; }
            QListWidget::item:selected { background:#202020; color:white; }
            QTabWidget::pane { border: 1px solid #333; top: -1px; }
            QTabBar::tab { background: #1A1A1A; color: #AAA; padding: 8px 12px; border: 1px solid #333; }
            QTabBar::tab:selected { color: white; background: #222; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
            QPushButton:hover { background:#2D2D2D; }
            #PrimaryBtn { background:#0078D4; border:none; }
        """)
        root = QVBoxLayout(d)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Ресурсы и шейдеры")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: white;")
        root.addWidget(title)

        tabs = QTabWidget()
        root.addWidget(tabs)

        # local
        local_tab = QWidget(); ll = QVBoxLayout(local_tab)
        ll.setSpacing(10)
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        type_row.addWidget(QLabel("Тип:"))
        asset_type = QComboBox(); asset_type.addItems(["resourcepack", "shader"])
        type_row.addWidget(asset_type)
        import_btn = QPushButton("Импорт файла")
        import_btn.setStyleSheet(primary_css)
        type_row.addWidget(import_btn)
        toggle_btn = QPushButton("Вкл/Выкл")
        type_row.addWidget(toggle_btn)
        up_btn = QPushButton("↑ Приоритет")
        down_btn = QPushButton("↓ Приоритет")
        type_row.addWidget(up_btn)
        type_row.addWidget(down_btn)
        type_row.addStretch()
        ll.addLayout(type_row)
        local_list = QListWidget(); ll.addWidget(local_list)
        tabs.addTab(local_tab, "Локальные")

        def asset_dir():
            base = inst.get("path", "")
            t = asset_type.currentText()
            if t == "resourcepack":
                p = os.path.join(base, "resourcepacks")
            else:
                p = os.path.join(base, "shaderpacks")
            os.makedirs(p, exist_ok=True)
            return p

        def refill_local():
            local_list.clear()
            p = asset_dir()
            for f in sorted(os.listdir(p)):
                if f.lower().endswith((".zip", ".disabled", ".jar")):
                    local_list.addItem(f)

        asset_type.currentTextChanged.connect(lambda *_: refill_local())
        import_btn.clicked.connect(lambda: self._import_asset_file(inst, asset_dir(), refill_local, d))
        toggle_btn.clicked.connect(lambda: self._toggle_asset_state(asset_dir(), local_list, refill_local))
        up_btn.clicked.connect(lambda: self._move_asset_priority(asset_dir(), local_list, -1, refill_local))
        down_btn.clicked.connect(lambda: self._move_asset_priority(asset_dir(), local_list, 1, refill_local))
        refill_local()

        # online
        online_tab = QWidget(); ol = QVBoxLayout(online_tab)
        ol.setSpacing(10)
        qrow = QHBoxLayout()
        qrow.setSpacing(8)
        q = QLineEdit(); q.setPlaceholderText("Поиск в Modrinth")
        type2 = QComboBox(); type2.addItems(["resourcepack", "shader"])
        sb = QPushButton("Искать"); sb.setObjectName("PrimaryBtn")
        qrow.addWidget(type2); qrow.addWidget(q); qrow.addWidget(sb)
        ol.addLayout(qrow)
        online_scroll = QScrollArea()
        online_scroll.setWidgetResizable(True)
        online_scroll.setStyleSheet("background: transparent; border: none;")
        online_wrap = QWidget()
        online_l = QVBoxLayout(online_wrap)
        online_l.setAlignment(Qt.AlignmentFlag.AlignTop)
        online_l.setSpacing(10)
        online_scroll.setWidget(online_wrap)
        ol.addWidget(online_scroll)
        tabs.addTab(online_tab, "Онлайн")

        cache = []
        def install_online_hit(hit, asset_kind):
            try:
                self.create_instance_backup(inst, reason="before_asset_install")
                project_id = hit.get("project_id")
                versions = self._http_json(f"https://api.modrinth.com/v2/project/{project_id}/version")
                if not versions:
                    raise RuntimeError("Версии не найдены")
                target_mc = str(inst.get("version", "")).strip()
                chosen_ver = None
                if target_mc:
                    for ver in versions:
                        gvs = ver.get("game_versions") or []
                        if target_mc in gvs:
                            chosen_ver = ver
                            break
                if not chosen_ver:
                    chosen_ver = versions[0]
                files = chosen_ver.get("files", [])
                if not files:
                    raise RuntimeError("Файлы не найдены")
                fi = next((f for f in files if f.get("primary")), files[0])
                target_dir = os.path.join(inst.get("path", ""), "resourcepacks" if asset_kind == "resourcepack" else "shaderpacks")
                os.makedirs(target_dir, exist_ok=True)
                saved = self._download_to_path(fi.get("url"), target_dir, fi.get("filename", "asset.zip"))
                self.log_event(f"Установлен asset: {os.path.basename(saved)}")
                QMessageBox.information(d, "Готово", f"Установлено: {os.path.basename(saved)}")
                refill_local()
            except Exception as e:
                QMessageBox.warning(d, "Ошибка", str(e))

        def render_online_cards():
            self._clear_layout(online_l)
            if not cache:
                empty = QLabel("Ничего не найдено.")
                empty.setStyleSheet("color:#CFCFCF; padding:8px;")
                online_l.addWidget(empty)
                return
            for hit in cache:
                card = QFrame()
                card.setStyleSheet("background:#171717;border:1px solid #2E2E2E;border-radius:12px;")
                row = QHBoxLayout(card)
                row.setContentsMargins(12, 12, 12, 12)
                row.setSpacing(12)
                row.addWidget(self._load_avatar(hit.get("icon_url")))

                info = QVBoxLayout()
                title = QLabel(hit.get("title", "Unknown"))
                title.setStyleSheet("color:white;font-size:16px;font-weight:800;")
                desc = QLabel((hit.get("description", "") or "").strip())
                desc.setWordWrap(True)
                desc.setStyleSheet("color:#B9B9B9;")
                info.addWidget(title)
                info.addWidget(desc)

                install_b = QPushButton("Установить")
                install_b.setStyleSheet(primary_css)
                install_b.clicked.connect(lambda _, h=hit, t=type2.currentText(): install_online_hit(h, t))
                row.addLayout(info)
                row.addStretch()
                row.addWidget(install_b)
                online_l.addWidget(card)

        def search_online():
            cache.clear()
            params = {"query": q.text().strip(), "limit": "30", "index": "downloads", "facets": json.dumps([[f"project_type:{type2.currentText()}"]])}
            data = self._http_json("https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(params))
            for hit in data.get("hits", []):
                cache.append(hit)
            render_online_cards()
        sb.clicked.connect(search_online)
        type2.currentTextChanged.connect(search_online)
        search_online()

        d.exec()

    def _download_to_path(self, url, dir_path, filename):
        bad = '<>:"/\\|?*'
        filename = ''.join('_' if ch in bad else ch for ch in (filename or "file.bin"))
        target = os.path.join(dir_path, filename)
        base, ext = os.path.splitext(target)
        n = 1
        while os.path.exists(target):
            target = f"{base}_{n}{ext}"
            n += 1
        self._stream_download(url, target, f"Файл: {filename}", timeout=120)
        return target

    def _import_asset_file(self, inst, target_dir, refill_cb, parent):
        src, _ = QFileDialog.getOpenFileName(parent, "Выбрать файл", "", "Packs (*.zip *.jar);;All (*.*)")
        if not src:
            return
        os.makedirs(target_dir, exist_ok=True)
        dst = os.path.join(target_dir, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        self.log_event(f"Импортирован asset: {os.path.basename(dst)}")
        refill_cb()

    def _toggle_asset_state(self, target_dir, list_widget, refill_cb):
        row = list_widget.currentRow()
        if row < 0:
            return
        name = list_widget.item(row).text()
        src = os.path.join(target_dir, name)
        if name.endswith(".disabled"):
            dst = os.path.join(target_dir, name[:-9])
        else:
            dst = os.path.join(target_dir, name + ".disabled")
        os.rename(src, dst)
        refill_cb()

    def _move_asset_priority(self, target_dir, list_widget, direction, refill_cb):
        row = list_widget.currentRow()
        if row < 0:
            return
        name = list_widget.item(row).text()
        files = [f for f in sorted(os.listdir(target_dir)) if f.lower().endswith((".zip", ".jar", ".disabled"))]
        if name not in files:
            return
        i = files.index(name)
        j = i + direction
        if j < 0 or j >= len(files):
            return
        a = os.path.join(target_dir, files[i])
        b = os.path.join(target_dir, files[j])
        tmp = os.path.join(target_dir, "__tmp_swap__.tmp")
        os.rename(a, tmp)
        os.rename(b, a)
        os.rename(tmp, b)
        refill_cb()

    def _cf_loader_type_for_instance(self, inst):
        loader_map = {"forge": 1, "fabric": 4}
        return loader_map.get(inst.get("installer", "vanilla"))

    def _resolve_modrinth_version(self, project_id, inst):
        params = {"game_versions": json.dumps([inst.get("version")])}
        loader = inst.get("installer", "vanilla")
        if loader != "vanilla":
            params["loaders"] = json.dumps([loader])
        url = f"https://api.modrinth.com/v2/project/{project_id}/version?" + urllib.parse.urlencode(params)
        versions = self._http_json(url)
        if not versions:
            raise RuntimeError(f"Modrinth: нет версий под {inst.get('version')} ({loader})")
        return versions[0]

    def _install_modrinth_project_recursive(self, project_id, inst, visited, installed, index_data=None):
        if project_id in visited:
            return
        visited.add(project_id)

        version = self._resolve_modrinth_version(project_id, inst)
        deps = version.get("dependencies", [])
        for dep in deps:
            if dep.get("dependency_type") == "required" and dep.get("project_id"):
                self.log_event(f"Modrinth dependency: {dep.get('project_id')}")
                self._install_modrinth_project_recursive(dep.get("project_id"), inst, visited, installed, index_data=index_data)

        files = version.get("files", [])
        if not files:
            raise RuntimeError("У версии Modrinth нет файлов")
        file_info = next((f for f in files if f.get("primary")), files[0])
        url = file_info.get("url")
        if not url:
            raise RuntimeError("У файла Modrinth нет URL")
        saved = self._download_to_instance_mods(inst, url, file_info.get("filename", "mod.jar"))
        installed.append(saved)
        self.log_event(f"Установлен мод (Modrinth): {os.path.basename(saved)}")
        if index_data is not None:
            index_data[str(project_id)] = {
                "provider": "Modrinth",
                "project_id": str(project_id),
                "version_id": version.get("id", ""),
                "file_name": os.path.basename(saved),
                "updated_at": datetime.now().isoformat(timespec="seconds")
            }

    def _resolve_curseforge_file(self, mod_id, inst, headers):
        params = {"pageSize": "50", "gameVersion": inst.get("version", "")}
        loader_type = self._cf_loader_type_for_instance(inst)
        if loader_type is not None:
            params["modLoaderType"] = str(loader_type)
        url = f"https://api.curseforge.com/v1/mods/{mod_id}/files?" + urllib.parse.urlencode(params)
        files_data = self._http_json(url, headers).get("data", [])
        chosen = next((f for f in files_data if f.get("isAvailable") and f.get("downloadUrl")), None)
        if not chosen:
            raise RuntimeError(f"CurseForge: нет доступного файла для modId={mod_id}")
        return chosen

    def _install_curseforge_mod_recursive(self, mod_id, inst, headers, visited, installed):
        if mod_id in visited:
            return
        visited.add(mod_id)

        file_info = self._resolve_curseforge_file(mod_id, inst, headers)

        for dep in file_info.get("dependencies", []):
            # relationType=3 -> required dependency
            if dep.get("relationType") == 3 and dep.get("modId"):
                dep_id = dep.get("modId")
                self.log_event(f"CurseForge dependency: {dep_id}")
                self._install_curseforge_mod_recursive(dep_id, inst, headers, visited, installed)

        saved = self._download_to_instance_mods(inst, file_info["downloadUrl"], file_info.get("fileName", "mod.jar"))
        installed.append(saved)
        self.log_event(f"Установлен мод (CurseForge): {os.path.basename(saved)}")

    def search_mods_page(self, reset_page=False):
        if reset_page:
            self.mods_page = 0
        query = self.mods_query.text().strip()
        self.mods_results = []
        self._clear_layout(self.mods_l)
        self.mods_l.addWidget(QLabel("Загрузка модов..."))
        self.mods_search_btn.setEnabled(False)
        self.mods_prev_btn.setEnabled(False)
        self.mods_next_btn.setEnabled(False)
        self.mod_search_req_id += 1
        req_id = self.mod_search_req_id
        self.mod_search_thread = ModSearchThread(req_id, query, self.mods_page, self.mods_page_size)
        self.mod_search_thread.done.connect(self.on_mod_search_done)
        self.mod_search_thread.failed.connect(self.on_mod_search_failed)
        self.mod_search_thread.start()

    def on_mod_search_done(self, req_id, results, has_next):
        if req_id != self.mod_search_req_id:
            return
        self.mods_results = results or []
        self.mods_has_next = bool(has_next)
        self.update_mods_pager()
        self.render_mod_cards()
        self.mods_search_btn.setEnabled(True)
        self.mods_prev_btn.setEnabled(self.mods_page > 0)
        self.mods_next_btn.setEnabled(self.mods_has_next)

    def on_mod_search_failed(self, req_id, error):
        if req_id != self.mod_search_req_id:
            return
        self.mods_results = []
        self.mods_has_next = False
        self.update_mods_pager()
        self._clear_layout(self.mods_l)
        self.mods_l.addWidget(QLabel("Не удалось загрузить моды."))
        self.mods_search_btn.setEnabled(True)
        self.mods_prev_btn.setEnabled(self.mods_page > 0)
        self.mods_next_btn.setEnabled(False)
        QMessageBox.warning(self, "Ошибка", f"Поиск модов не удался: {error}")

    def _load_avatar(self, payload):
        lbl = QLabel("🧩")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFixedSize(64, 64)
        lbl.setStyleSheet("background:#1F1F1F;border:1px solid #333;border-radius:10px;color:#8CA2D1;font-size:24px;")
        if not payload:
            return lbl
        try:
            data = payload if isinstance(payload, (bytes, bytearray)) else None
            if not data:
                return lbl
            pix = QPixmap()
            if pix.loadFromData(data):
                lbl.setPixmap(pix.scaled(62, 62, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                lbl.setStyleSheet("border:1px solid #333;border-radius:10px;")
        except Exception:
            pass
        return lbl

    def render_mod_cards(self):
        self._clear_layout(self.mods_l)
        if not self.mods_results:
            self.mods_l.addWidget(QLabel("Ничего не найдено."))
            return
        for mod in self.mods_results:
            card = QFrame()
            card.setStyleSheet("background:#171717;border:1px solid #2E2E2E;border-radius:12px;")
            row = QHBoxLayout(card); row.setContentsMargins(12, 12, 12, 12); row.setSpacing(12)
            row.addWidget(self._load_avatar(mod.get("avatar")))
            info = QVBoxLayout()
            title = QLabel(mod.get("title", "Unknown")); title.setStyleSheet("color:white;font-size:16px;font-weight:800;")
            desc = QLabel(mod.get("description", "")); desc.setWordWrap(True); desc.setStyleSheet("color:#B9B9B9;")
            info.addWidget(title); info.addWidget(desc)
            install_b = QPushButton("Установить")
            install_b.setStyleSheet("background:#0078D4;color:white;border:none;border-radius:8px;padding:8px 14px;font-weight:700;")
            install_b.clicked.connect(lambda _, m=mod: self.install_mod_to_selected_instance(m))
            row.addLayout(info); row.addStretch(); row.addWidget(install_b)
            self.mods_l.addWidget(card)

    def install_mod_to_selected_instance(self, mod):
        instances = self.get_all_instances()
        if not instances:
            QMessageBox.warning(self, "Ошибка", "Нет установок для установки мода.")
            return
        d = InstanceSelectDialog(instances, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        inst = d.selected_instance()
        if not inst:
            return

        self.log_event(f"Начата установка мода '{mod.get('title', 'Unknown')}' в {inst.get('name', 'Unnamed')} ({inst.get('version')})")
        try:
            self.create_instance_backup(inst, reason="before_mod_install")
            index_data = self.read_mods_index(inst)
            installed_files = []
            self._install_modrinth_project_recursive(mod["id"], inst, set(), installed_files, index_data=index_data)
            self.write_mods_index(inst, index_data)

            summary = "\n".join(os.path.basename(x) for x in installed_files[:10])
            if len(installed_files) > 10:
                summary += f"\n... и ещё {len(installed_files) - 10}"
            QMessageBox.information(self, "Готово", f"Установлено файлов: {len(installed_files)}\n{summary}")
            self.log_event(f"Установка завершена. Файлов: {len(installed_files)}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось установить мод: {e}")
            self.log_event(f"Ошибка установки мода: {e}")

    def _latest_modrinth_version_info(self, project_id, inst):
        params = {"game_versions": json.dumps([inst.get("version")])}
        loader = inst.get("installer", "vanilla")
        if loader != "vanilla":
            params["loaders"] = json.dumps([loader])
        url = f"https://api.modrinth.com/v2/project/{project_id}/version?" + urllib.parse.urlencode(params)
        versions = self._http_json(url)
        if not versions:
            return None
        return versions[0]

    def check_mod_updates(self):
        instances = self.get_all_instances()
        if not instances:
            QMessageBox.warning(self, "Ошибка", "Нет установок.")
            return
        d = InstanceSelectDialog(instances, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        inst = d.selected_instance()
        if not inst:
            return
        try:
            idx = self.read_mods_index(inst)
            updates = []
            for project_id, meta in idx.items():
                if meta.get("provider") != "Modrinth":
                    continue
                latest = self._latest_modrinth_version_info(project_id, inst)
                if not latest:
                    continue
                latest_id = latest.get("id", "")
                if latest_id and latest_id != meta.get("version_id", ""):
                    updates.append((project_id, meta.get("file_name", project_id), latest))
            if not updates:
                QMessageBox.information(self, "Моды", "Обновлений не найдено.")
                return
            lines = [f"Найдено обновлений: {len(updates)}", ""]
            for _, name, _ in updates[:20]:
                lines.append(f"• {name}")
            if len(updates) > 20:
                lines.append(f"... и ещё {len(updates)-20}")
            QMessageBox.information(self, "Обновления модов", "\n".join(lines))
            self.log_event(f"Проверка обновлений: найдено {len(updates)}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Проверка обновлений не удалась: {e}")

    def update_all_mods(self):
        instances = self.get_all_instances()
        if not instances:
            QMessageBox.warning(self, "Ошибка", "Нет установок.")
            return
        d = InstanceSelectDialog(instances, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        inst = d.selected_instance()
        if not inst:
            return
        try:
            idx = self.read_mods_index(inst)
            updates = []
            for project_id, meta in idx.items():
                if meta.get("provider") != "Modrinth":
                    continue
                latest = self._latest_modrinth_version_info(project_id, inst)
                if not latest:
                    continue
                latest_id = latest.get("id", "")
                if latest_id and latest_id != meta.get("version_id", ""):
                    updates.append((project_id, latest))
            if not updates:
                QMessageBox.information(self, "Моды", "Нечего обновлять.")
                return

            self.create_instance_backup(inst, reason="before_mods_update")
            installed = []
            for project_id, _ in updates:
                self._install_modrinth_project_recursive(project_id, inst, set(), installed, index_data=idx)
            self.write_mods_index(inst, idx)
            QMessageBox.information(self, "Готово", f"Обновлено модов/зависимостей: {len(installed)}")
            self.log_event(f"Обновление модов завершено. Файлов: {len(installed)}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Обновление модов не удалось: {e}")

    def save_language(self):
        m = {0: "ru", 1: "en", 2: "uk"}
        self.lang = m.get(self.lang_box.currentIndex(), "ru")
        self.settings["language"] = self.lang
        if hasattr(self, "theme_ids") and self.theme_ids:
            idx = max(0, min(self.theme_box.currentIndex(), len(self.theme_ids) - 1))
            self.settings["theme"] = self.theme_ids[idx]
        self.settings["ram_mb"] = int(self.ram_spin.value())
        self.settings["auto_ram"] = bool(self.auto_ram_check.isChecked())
        self.settings["sidebar_width"] = int(self.sidebar_spin.value())
        self.settings["auto_update_check"] = bool(self.update_check_box.isChecked())
        self.settings["auto_cleanup_enabled"] = bool(self.cleanup_check.isChecked())
        self.settings["cleanup_days"] = int(self.cleanup_days_spin.value())
        self.settings["ms_client_id"] = self.ms_client_edit.text().strip()
        self.settings["discord_rpc_enabled"] = bool(self.discord_rpc_check.isChecked())
        self.save_settings()
        self.apply_theme()
        self.apply_sidebar_width()
        self.apply_language()
        self.refresh_theme_widgets()
        if not self.settings.get("discord_rpc_enabled", False):
            self.stop_discord_rpc()
        else:
            self.start_discord_rpc()
            self.update_discord_presence()

    def apply_language(self):
        labels = {
            "ru": {
                "lib": "Мои установки", "add": "+ Добавить", "mods": "Установка модов",
                "news": "Новости Minecraft", "settings": "Настройки", "manage": "УПРАВЛЕНИЕ",
                "play": "ИГРАТЬ", "lang": "Язык лаунчера", "save": "Сохранить", "search": "Искать",
                "ram": "Оперативная память для Minecraft", "sidebar": "Ширина бокового меню",
                "auto_ram": "Автоподбор RAM по системе", "import_zip": "Импорт ZIP", "clone": "Дублировать",
                "search_instances": "Поиск по установкам и группам",
                "favorite": "В избранное", "color_label": "Цвет метки", "graphics": "Профиль графики", "crashes": "Crash-отчеты",
                "theme": "Тема лаунчера", "ms_client": "Microsoft Client ID",
                "update_check": "Проверять обновления лаунчера при старте",
                "update_now": "Проверить обновления",
                "cleanup_check": "Автоочистка старых логов/кэша", "cleanup_days": "Хранить логи/кеш",
                "discord_rpc": "Discord Rich Presence",
                "server_ph": "server:port",
                "mods_check": "Проверить обновления",
                "mods_update": "Обновить всё",
                "mods_conflicts": "Проверить конфликты",
                "java": "Java",
                "export": "Экспортировать",
                "shortcut": "Ярлык запуска",
                "packs": "Ресурсы и шейдеры",
                "backups": "Бэкапы",
                "worlds": "Миры и скриншоты",
                "repair": "Починить установку",
                "edit_btn": "Изменить…",
                "menu_launch": "Запустить",
                "menu_stop": "Остановить",
                "menu_edit": "Изменить...",
                "menu_edit_group": "Изменить группу...",
                "menu_folder": "Папка",
                "menu_export": "Экспортировать",
                "menu_copy": "Копировать",
                "menu_shortcut": "Создать ярлык",
                "menu_delete": "Удалить",
                "menu_mods": "Менеджер модов",
                "menu_favorite": "В избранное",
                "menu_favorite_add": "В избранное",
                "menu_favorite_remove": "Убрать из избранного",
                "menu_color": "Цвет метки",
                "menu_graphics": "Профиль графики",
                "menu_crash": "Crash-отчеты",
                "menu_java": "Java",
                "menu_packs": "Ресурсы и шейдеры",
                "menu_worlds": "Миры и скриншоты",
                "menu_backups": "Бэкапы",
                "menu_repair": "Починить установку",
                "menu_logs": "Логи установки",
                "menu_console": "Консоль",
                "favorites_group": "★ Избранные",
                "server_online": "Онлайн",
                "server_offline": "Оффлайн",
                "ping_label": "пинг",
                "edit_title": "Изменить установку",
                "edit_name": "Название",
                "edit_group": "Группа",
                "edit_group_new_ph": "Введите название новой группы",
                "edit_loader": "Загрузчик",
                "edit_loader_ver": "Версия загрузчика",
                "edit_emoji": "Эмодзи",
                "edit_save": "Сохранить",
                "edit_cancel": "Отмена",
                "edit_apply_loader": "Установить/обновить загрузчик",
                "loader_done": "Загрузчик установлен/обновлён.",
                "loader_fail": "Не удалось установить загрузчик: {e}",
                "edit_menu_title": "Меню установки",
                "edit_menu_journal": "Журнал Minecraft",
                "edit_menu_version": "Версия",
                "edit_menu_mods": "Моды",
                "edit_menu_rpacks": "Resource packs",
                "edit_menu_spacks": "Shader packs",
                "edit_menu_worlds": "Миры",
                "edit_menu_servers": "Серверы",
                "edit_menu_shots": "Снимки экрана",
                "edit_menu_params": "Параметры",
                "edit_menu_logs": "Other logs",
                "edit_menu_more": "Другое",
                "tab_library": "Установки", "tab_news": "Новости", "tab_mods": "Моды", "tab_console": "Консоль", "tab_settings": "Настройки"
            },
            "en": {
                "lib": "My Instances", "add": "+ Add", "mods": "Mods Installation",
                "news": "Minecraft News", "settings": "Settings", "manage": "MANAGE",
                "play": "PLAY", "lang": "Launcher Language", "save": "Save", "search": "Search",
                "ram": "Memory for Minecraft", "sidebar": "Sidebar width",
                "auto_ram": "Auto RAM by system", "import_zip": "Import ZIP", "clone": "Duplicate",
                "search_instances": "Search instances and groups",
                "favorite": "Favorite", "color_label": "Color label", "graphics": "Graphics profile", "crashes": "Crash reports",
                "theme": "Launcher Theme", "ms_client": "Microsoft Client ID",
                "update_check": "Check launcher updates on startup",
                "update_now": "Check updates",
                "cleanup_check": "Auto cleanup old logs/cache", "cleanup_days": "Keep logs/cache",
                "discord_rpc": "Discord Rich Presence",
                "server_ph": "server:port",
                "mods_check": "Check updates",
                "mods_update": "Update all",
                "mods_conflicts": "Check conflicts",
                "java": "Java",
                "export": "Export",
                "shortcut": "Launch shortcut",
                "packs": "Resources and shaders",
                "backups": "Backups",
                "worlds": "Worlds and screenshots",
                "repair": "Repair instance",
                "edit_btn": "Edit…",
                "menu_launch": "Launch",
                "menu_stop": "Stop",
                "menu_edit": "Edit...",
                "menu_edit_group": "Change group...",
                "menu_folder": "Folder",
                "menu_export": "Export",
                "menu_copy": "Duplicate",
                "menu_shortcut": "Create shortcut",
                "menu_delete": "Delete",
                "menu_mods": "Mods manager",
                "menu_favorite": "Favorite",
                "menu_favorite_add": "Favorite",
                "menu_favorite_remove": "Remove favorite",
                "menu_color": "Color label",
                "menu_graphics": "Graphics profile",
                "menu_crash": "Crash reports",
                "menu_java": "Java",
                "menu_packs": "Resources and shaders",
                "menu_worlds": "Worlds and screenshots",
                "menu_backups": "Backups",
                "menu_repair": "Repair instance",
                "menu_logs": "Install logs",
                "menu_console": "Console",
                "favorites_group": "★ Favorites",
                "server_online": "Online",
                "server_offline": "Offline",
                "ping_label": "ping",
                "edit_title": "Edit instance",
                "edit_name": "Name",
                "edit_group": "Group",
                "edit_group_new_ph": "Enter new group name",
                "edit_loader": "Loader",
                "edit_loader_ver": "Loader version",
                "edit_emoji": "Emoji",
                "edit_save": "Save",
                "edit_cancel": "Cancel",
                "edit_apply_loader": "Install/update loader",
                "loader_done": "Loader installed/updated.",
                "loader_fail": "Failed to install loader: {e}",
                "edit_menu_title": "Instance menu",
                "edit_menu_journal": "Minecraft Journal",
                "edit_menu_version": "Version",
                "edit_menu_mods": "Mods",
                "edit_menu_rpacks": "Resource packs",
                "edit_menu_spacks": "Shader packs",
                "edit_menu_worlds": "Worlds",
                "edit_menu_servers": "Servers",
                "edit_menu_shots": "Screenshots",
                "edit_menu_params": "Parameters",
                "edit_menu_logs": "Other logs",
                "edit_menu_more": "More",
                "tab_library": "Instances", "tab_news": "News", "tab_mods": "Mods", "tab_console": "Console", "tab_settings": "Settings"
            },
            "uk": {
                "lib": "Мої збірки", "add": "+ Додати", "mods": "Встановлення модів",
                "news": "Новини Minecraft", "settings": "Налаштування", "manage": "КЕРУВАННЯ",
                "play": "ГРАТИ", "lang": "Мова лаунчера", "save": "Зберегти", "search": "Пошук",
                "ram": "Оперативна пам'ять для Minecraft", "sidebar": "Ширина бічного меню",
                "auto_ram": "Автопідбір RAM за системою", "import_zip": "Імпорт ZIP", "clone": "Дублювати",
                "search_instances": "Пошук по збірках і групах",
                "favorite": "В обране", "color_label": "Колір мітки", "graphics": "Профіль графіки", "crashes": "Crash-звіти",
                "theme": "Тема лаунчера", "ms_client": "Microsoft Client ID",
                "update_check": "Перевіряти оновлення лаунчера при старті",
                "update_now": "Перевірити оновлення",
                "cleanup_check": "Автоочищення старих логів/кешу", "cleanup_days": "Зберігати логи/кеш",
                "discord_rpc": "Discord Rich Presence",
                "server_ph": "server:port",
                "mods_check": "Перевірити оновлення",
                "mods_update": "Оновити все",
                "mods_conflicts": "Перевірити конфлікти",
                "java": "Java",
                "export": "Експортувати",
                "shortcut": "Ярлик запуску",
                "packs": "Ресурси та шейдери",
                "backups": "Бекапи",
                "worlds": "Світи і скриншоти",
                "repair": "Полагодити збірку",
                "tab_library": "Збірки", "tab_news": "Новини", "tab_mods": "Моди", "tab_console": "Консоль", "tab_settings": "Налаштування",

                "edit_btn": "????????",
                "menu_launch": "?????????",
                "menu_stop": "????????",
                "menu_edit": "???????...",
                "menu_edit_group": "??????? ?????...",
                "menu_folder": "?????",
                "menu_export": "????????????",
                "menu_copy": "?????????",
                "menu_shortcut": "???????? ?????",
                "menu_delete": "????????",
                "menu_mods": "???????? ?????",
                "menu_favorite": "? ??????",
                "menu_favorite_add": "? ??????",
                "menu_favorite_remove": "????? ? ????????",
                "menu_color": "????? ?????",
                "menu_graphics": "??????? ???????",
                "menu_crash": "Crash-?????",
                "menu_java": "Java",
                "menu_packs": "??????? ?? ???????",
                "menu_worlds": "????? ? ?????????",
                "menu_backups": "??????",
                "menu_repair": "?????????? ??????",
                "menu_logs": "???? ????????????",
                "menu_console": "???????",
                "favorites_group": "? ??????",
                "server_online": "??????",
                "server_offline": "??????",
                "ping_label": "????",
                "edit_title": "??????? ??????",
                "edit_name": "?????",
                "edit_group": "?????",
                "edit_group_new_ph": "??????? ????? ????? ?????",
                "edit_loader": "????????????",
                "edit_loader_ver": "?????? ?????????????",
                "edit_emoji": "??????",
                "edit_save": "????????",
                "edit_cancel": "?????????",
                "edit_apply_loader": "??????????/??????? ????????????",
                "loader_done": "???????????? ???????????/????????.",
                "loader_fail": "?? ??????? ?????????? ????????????: {e}",
                "edit_menu_title": "???? ??????",
                "edit_menu_journal": "?????? Minecraft",
                "edit_menu_version": "??????",
                "edit_menu_mods": "????",
                "edit_menu_rpacks": "Resource packs",
                "edit_menu_spacks": "Shader packs",
                "edit_menu_worlds": "?????",
                "edit_menu_servers": "???????",
                "edit_menu_shots": "?????????",
                "edit_menu_params": "?????????",
                "edit_menu_logs": "Other logs",
                "edit_menu_more": "????",


            },
        }
        t = labels.get(self.lang, labels["ru"])
        self.lang_labels = t
        self.lib_title.setText(t["lib"])
        self.lib_add.setText(t["add"])
        self.mods_title.setText(t["mods"])
        self.news_title.setText(t["news"])
        self.settings_title.setText(t["settings"])
        self.play_btn.setText(t["play"])
        self.lang_label.setText(t["lang"])
        self.ram_label.setText(t["ram"])
        self.auto_ram_check.setText(t["auto_ram"])
        self.sidebar_label.setText(t["sidebar"])
        self.theme_label.setText(t["theme"])
        self.ms_client_label.setText(t["ms_client"])
        self.update_check_box.setText(t["update_check"])
        self.cleanup_check.setText(t["cleanup_check"])
        self.cleanup_days_label.setText(t["cleanup_days"])
        self.discord_rpc_check.setText(t["discord_rpc"])
        self.server_ip_edit.setPlaceholderText(t["server_ph"])
        self.check_updates_btn.setText(t["update_now"])
        self.save_lang_btn.setText(t["save"])
        self.mods_search_btn.setText(t["search"])
        self.mods_check_updates_btn.setText(t["mods_check"])
        self.mods_update_all_btn.setText(t["mods_update"])
        self.mods_conflicts_btn.setText(t["mods_conflicts"])
        if hasattr(self, "edit_btn"):
            self.edit_btn.setText(t["edit_btn"])
        if hasattr(self, "btn_launch"):
            self.btn_launch.setText("▶ " + t["menu_launch"])
            self.btn_stop.setText("⏹ " + t["menu_stop"])
            self.btn_folder.setText("📁 " + t["menu_folder"])
            self.btn_copy.setText("🧬 " + t["menu_copy"])
            self.btn_shortcut.setText("🚀 " + t["menu_shortcut"])
            self.btn_delete.setText("🗑 " + t["menu_delete"])
        if hasattr(self, "menu_actions") and self.menu_actions:
            if "edit" in self.menu_actions: self.menu_actions["edit"].setText("✏ " + t["menu_edit"])
            if "edit_group" in self.menu_actions: self.menu_actions["edit_group"].setText("🗂 " + t["menu_edit_group"])
            if "export" in self.menu_actions: self.menu_actions["export"].setText("📤 " + t["menu_export"])
            if "mods" in self.menu_actions: self.menu_actions["mods"].setText("🧩 " + t["menu_mods"])
            if "favorite" in self.menu_actions: self.menu_actions["favorite"].setText("⭐ " + t["menu_favorite"])
            if "color" in self.menu_actions: self.menu_actions["color"].setText("🎨 " + t["menu_color"])
            if "graphics" in self.menu_actions: self.menu_actions["graphics"].setText("🎮 " + t["menu_graphics"])
            if "crash" in self.menu_actions: self.menu_actions["crash"].setText("💥 " + t["menu_crash"])
            if "java" in self.menu_actions: self.menu_actions["java"].setText("☕ " + t["menu_java"])
            if "packs" in self.menu_actions: self.menu_actions["packs"].setText("🎨 " + t["menu_packs"])
            if "worlds" in self.menu_actions: self.menu_actions["worlds"].setText("🌍 " + t["menu_worlds"])
            if "backups" in self.menu_actions: self.menu_actions["backups"].setText("🗃 " + t["menu_backups"])
            if "repair" in self.menu_actions: self.menu_actions["repair"].setText("🩺 " + t["menu_repair"])
            if "logs" in self.menu_actions: self.menu_actions["logs"].setText("📜 " + t["menu_logs"])
            if "console" in self.menu_actions: self.menu_actions["console"].setText("🧾 " + t["menu_console"])
        self.side_library.setToolTip(t["tab_library"])
        self.side_news.setToolTip(t["tab_news"])
        self.side_mods.setToolTip(t["tab_mods"])
        self.side_settings.setToolTip(t["tab_settings"])
        self.lib_import.setText("📥 " + t["import_zip"])
        self.instances_search.setPlaceholderText(t["search_instances"])
        self.refresh_account_button()
        self.update_playtime_labels()
        self.apply_sidebar_width()
        self._update_edit_menu_state()

    def get_all_instances(self):
        result = []
        for group, insts in self.instance_data.items():
            for inst in insts:
                inst_copy = dict(inst)
                inst_copy["group"] = group
                result.append(inst_copy)
        return result

    def open_instance_folder(self):
        if self.selected_instance:
            os.startfile(self.selected_instance['path'])

    def import_instance_zip(self):
        zip_path, _ = QFileDialog.getOpenFileName(self, "Импорт установки из ZIP", "", "ZIP (*.zip)")
        if not zip_path:
            return
        name, ok = QInputDialog.getText(self, "Импорт установки", "Имя установки:")
        if not ok:
            return
        name = (name or "").strip() or os.path.splitext(os.path.basename(zip_path))[0]
        groups = list(self.instance_data.keys()) or ["Main"]
        group, ok = QInputDialog.getItem(self, "Импорт установки", "Группа:", groups, 0, True)
        if not ok:
            return
        group = (group or "").strip() or "Main"
        path = os.path.join(BASE_DIR, re.sub(r"[^a-zA-Z0-9._-]+", "_", name))
        if os.path.exists(path):
            QMessageBox.warning(self, "Ошибка", "Папка установки уже существует. Выберите другое имя.")
            return
        ok_space, free_gb = self.check_disk_space(path, required_gb=2.5)
        if not ok_space:
            QMessageBox.warning(self, "Недостаточно места", f"Свободно только {free_gb:.2f} GB. Нужно минимум ~2.5 GB.")
            return
        try:
            os.makedirs(path, exist_ok=True)
            if not zipfile.is_zipfile(zip_path):
                raise RuntimeError("Файл не является корректным ZIP архивом.")
            base_norm = os.path.normcase(os.path.normpath(path))
            with zipfile.ZipFile(zip_path, "r") as zf:
                infos = zf.infolist()
                for i, info in enumerate(infos):
                    rel = info.filename.replace("\\", "/")
                    if not rel or rel.endswith("/"):
                        continue
                    parts = [p for p in rel.split("/") if p not in ("", ".")]
                    if any(p == ".." for p in parts):
                        continue
                    target = os.path.normpath(os.path.join(path, *parts))
                    target_norm = os.path.normcase(target)
                    if target_norm != base_norm and not target_norm.startswith(base_norm + os.sep):
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(info, "r") as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out, 1024 * 256)
                    if i % 20 == 0:
                        QApplication.processEvents()
            inst = {
                "name": name,
                "group": group,
                "version": "1.20.1",
                "path": path,
                "installer": "vanilla",
                "loader_version": "",
                "emoji": "📦"
            }
            self.instance_data.setdefault(group, []).append(inst)
            self.save_data()
            self.refresh_grid()
            self.log_event(f"Импортирована установка из ZIP: {name}")
            QMessageBox.information(self, "Готово", f"Установка импортирована:\n{name}")
        except Exception as e:
            try:
                if os.path.exists(path):
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass
            QMessageBox.warning(self, "Ошибка", f"Импорт не удался: {e}")

    def duplicate_selected_instance(self):
        if not self.selected_instance:
            return
        src = self.selected_instance
        src_path = src.get("path", "")
        if not src_path or not os.path.exists(src_path):
            QMessageBox.warning(self, "Ошибка", "Исходная папка установки не найдена.")
            return
        base_name = src.get("name", "Instance")
        new_name = f"{base_name} (copy)"
        i = 2
        existing_names = {inst.get("name", "") for inst in self.get_all_instances()}
        while new_name in existing_names:
            new_name = f"{base_name} (copy {i})"
            i += 1
        dst_path = os.path.join(BASE_DIR, re.sub(r"[^a-zA-Z0-9._-]+", "_", new_name))
        j = 2
        while os.path.exists(dst_path):
            dst_path = os.path.join(BASE_DIR, re.sub(r"[^a-zA-Z0-9._-]+", "_", f"{new_name}_{j}"))
            j += 1
        ok_space, free_gb = self.check_disk_space(dst_path, required_gb=2.5)
        if not ok_space:
            QMessageBox.warning(self, "Недостаточно места", f"Свободно только {free_gb:.2f} GB. Нужно минимум ~2.5 GB.")
            return
        try:
            shutil.copytree(src_path, dst_path)
            new_inst = dict(src)
            new_inst["name"] = new_name
            new_inst["path"] = dst_path
            group = new_inst.get("group", "Main")
            self.instance_data.setdefault(group, []).append(new_inst)
            self.save_data()
            self.refresh_grid()
            self.log_event(f"Создана копия установки: {new_name}")
            QMessageBox.information(self, "Готово", f"Копия создана:\n{new_name}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Дублирование не удалось: {e}")

    def _download_task_start(self, title, total=0, unit="bytes"):
        self.download_seq += 1
        task = {
            "id": self.download_seq,
            "title": str(title),
            "total": int(total or 0),
            "done": 0,
            "status": "in_progress",
            "error": "",
            "unit": unit
        }
        self.download_items.append(task)
        if len(self.download_items) > 300:
            self.download_items = self.download_items[-300:]
        self._refresh_downloads_view()
        return task["id"]

    def _download_task_progress(self, task_id, done):
        for task in self.download_items:
            if task.get("id") == task_id:
                task["done"] = int(done or 0)
                break
        self._refresh_downloads_view()

    def _download_task_finish(self, task_id, ok=True, error=""):
        for task in self.download_items:
            if task.get("id") == task_id:
                task["status"] = "done" if ok else "error"
                task["error"] = str(error or "")
                break
        self._refresh_downloads_view()

    def _refresh_downloads_view(self):
        if self.download_list is None:
            return
        self.download_list.clear()
        for task in reversed(self.download_items):
            status = {"in_progress": "⏳", "done": "✅", "error": "❌"}.get(task.get("status"), "•")
            total = int(task.get("total", 0))
            done = int(task.get("done", 0))
            if task.get("unit") == "percent":
                size_text = f"{max(0, min(100, done))}%"
            elif total > 0:
                pct = int((done * 100) / total) if done <= total else 100
                size_text = f"{done // 1024}KB / {total // 1024}KB ({pct}%)"
            else:
                size_text = f"{done // 1024}KB"
            line = f"{status} {task.get('title', 'download')} — {size_text}"
            if task.get("status") == "error" and task.get("error"):
                line += f" | {task.get('error')}"
            self.download_list.addItem(line)
        self.download_list.scrollToTop()

    def _stream_download(self, url, target_path, task_title, headers=None, timeout=60):
        req_headers = {"User-Agent": "PyLanLauncher/1.0"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers)
        task_id = self._download_task_start(task_title, 0, unit="bytes")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response, open(target_path, "wb") as out:
                total = int(response.headers.get("Content-Length", "0") or "0")
                if total > 0:
                    for task in self.download_items:
                        if task.get("id") == task_id:
                            task["total"] = total
                            break
                    self._refresh_downloads_view()
                downloaded = 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    self._download_task_progress(task_id, downloaded)
                    QApplication.processEvents()
            self._download_task_finish(task_id, ok=True)
        except Exception as e:
            self._download_task_finish(task_id, ok=False, error=str(e))
            raise

    def open_downloads_window(self):
        if self.download_dialog is not None:
            self.download_dialog.show()
            self.download_dialog.raise_()
            self.download_dialog.activateWindow()
            self._refresh_downloads_view()
            return
        self.download_dialog = QDialog(self)
        self.download_dialog.setWindowTitle("Текущие загрузки")
        self.download_dialog.resize(760, 440)
        self.download_dialog.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QListWidget { background:#171717; color:#E0E0E0; border:1px solid #333; border-radius:8px; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
        """)
        l = QVBoxLayout(self.download_dialog)
        self.download_list = QListWidget()
        l.addWidget(self.download_list)
        hb = QHBoxLayout()
        clear_done = QPushButton("Очистить завершенные")
        close = QPushButton("Закрыть")
        clear_done.clicked.connect(lambda: (setattr(self, "download_items", [x for x in self.download_items if x.get("status") == "in_progress"]), self._refresh_downloads_view()))
        close.clicked.connect(self.download_dialog.close)
        hb.addWidget(clear_done)
        hb.addStretch()
        hb.addWidget(close)
        l.addLayout(hb)
        self.download_dialog.finished.connect(lambda _: (setattr(self, "download_dialog", None), setattr(self, "download_list", None)))
        self._refresh_downloads_view()
        self.download_dialog.show()

    def export_selected_instance(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        inst_path = inst.get("path", "")
        if not inst_path or not os.path.exists(inst_path):
            QMessageBox.warning(self, "Ошибка", "Папка установки не найдена.")
            return
        default_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", inst.get("name", "instance")) + ".zip"
        out_path, _ = QFileDialog.getSaveFileName(self, "Экспортировать установку", os.path.join(BASE_DIR, default_name), "ZIP (*.zip)")
        if not out_path:
            return
        if not out_path.lower().endswith(".zip"):
            out_path += ".zip"
        try:
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(inst_path):
                    for fn in files:
                        full = os.path.join(root, fn)
                        rel = os.path.relpath(full, inst_path)
                        zf.write(full, arcname=rel)
            self.log_event(f"Экспорт установки: {out_path}")
            QMessageBox.information(self, "Готово", f"Установка экспортирована:\n{out_path}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Экспорт не удался: {e}")

    def create_instance_shortcut(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        inst_path = inst.get("path", "")
        if not inst_path:
            return
        emoji = inst.get("emoji", "📦")
        safe_name = inst.get("name", "instance").strip() or "instance"
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        default_lnk = os.path.join(desktop, f"{emoji} {safe_name}.lnk")
        out_path, _ = QFileDialog.getSaveFileName(self, "Создать ярлык запуска", default_lnk, "Shortcut (*.lnk)")
        if not out_path:
            return
        if not out_path.lower().endswith(".lnk"):
            out_path += ".lnk"
        try:
            if getattr(sys, "frozen", False):
                target_path = sys.executable
                arguments = f'--launch-instance "{inst_path}"'
            else:
                target_path = sys.executable
                arguments = f'"{os.path.abspath(__file__)}" --launch-instance "{inst_path}"'
            working_dir = os.path.dirname(target_path)
            desc = f"{emoji} {inst.get('name', 'Instance')}"
            ps_content = """param(
    [string]$ShortcutPath,
    [string]$TargetPath,
    [string]$Arguments,
    [string]$WorkingDirectory,
    [string]$Description
)
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.Arguments = $Arguments
$Shortcut.WorkingDirectory = $WorkingDirectory
$Shortcut.WindowStyle = 1
$Shortcut.Description = $Description
$Shortcut.Save()
"""
            ps_tmp = None
            try:
                fd, ps_tmp = tempfile.mkstemp(suffix=".ps1")
                os.close(fd)
                with open(ps_tmp, "w", encoding="utf-8-sig") as f:
                    f.write(ps_content)
                subprocess.check_call(
                    [
                        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", ps_tmp, out_path, target_path, arguments, working_dir, desc
                    ],
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )
            finally:
                if ps_tmp and os.path.exists(ps_tmp):
                    try:
                        os.remove(ps_tmp)
                    except Exception:
                        pass
            self.log_event(f"Создан ярлык запуска: {out_path}")
            QMessageBox.information(self, "Готово", f"Ярлык создан:\n{out_path}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось создать ярлык: {e}")

    def open_java_manager(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        req_major = self.required_java_major(inst)
        detected = self.detect_java_installations()

        d = QDialog(self)
        d.setWindowTitle(f"Java для {inst.get('name', 'Unnamed')}")
        d.resize(760, 440)
        d.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QListWidget { background:#1A1A1A; color:#EEE; border:1px solid #333; border-radius:8px; }
            QLabel { color:#DDD; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
            QPushButton:hover { background:#2D2D2D; }
            #PrimaryBtn { background:#0078D4; border:none; }
        """)
        l = QVBoxLayout(d)
        info = QLabel(f"Требуемая Java для этой установки: {req_major}+")
        l.addWidget(info)
        lst = QListWidget()
        l.addWidget(lst)

        paths = []
        auto_item = f"[AUTO] Автовыбор (Java {req_major}+)"
        lst.addItem(auto_item)
        paths.append("auto")
        for j in detected:
            mark = "✅" if int(j.get("major", 0)) >= req_major else "⚠"
            lst.addItem(f"{mark} Java {j.get('version', 'unknown')} | {j.get('path')}")
            paths.append(j.get("path", ""))

        current = (inst.get("java_path", "") or "auto").strip()
        current_idx = 0
        for i, p in enumerate(paths):
            if p and current and os.path.normcase(p) == os.path.normcase(current):
                current_idx = i
                break
        lst.setCurrentRow(current_idx)

        hb = QHBoxLayout()
        browse = QPushButton("Выбрать вручную")
        dl = QPushButton(f"Скачать Java {req_major}")
        save = QPushButton("Сохранить"); save.setObjectName("PrimaryBtn")
        close = QPushButton("Закрыть")
        hb.addWidget(browse)
        hb.addWidget(dl)
        hb.addStretch()
        hb.addWidget(save)
        hb.addWidget(close)
        l.addLayout(hb)

        manual_path = {"value": ""}

        def on_browse():
            p, _ = QFileDialog.getOpenFileName(d, "Выберите javaw.exe", "", "Java (javaw.exe java.exe)")
            if not p:
                return
            manual_path["value"] = p
            lst.addItem(f"🛠 Вручную | {p}")
            paths.append(p)
            lst.setCurrentRow(lst.count() - 1)

        def on_download():
            java_path = self.ensure_java_downloaded(req_major)
            QMessageBox.information(d, "Готово", f"Java установлена:\n{java_path}")
            d.accept()
            self.open_java_manager()

        def on_save():
            idx = lst.currentRow()
            if idx < 0:
                return
            chosen = paths[idx] if idx < len(paths) else "auto"
            if chosen != "auto":
                _, major = self._java_version_info(chosen)
                if major and major < req_major:
                    QMessageBox.warning(d, "Java", f"Выбранная Java {major}, требуется {req_major}+.")
                    return
            for g in self.instance_data:
                for i, it in enumerate(self.instance_data[g]):
                    if it.get("path") == inst.get("path"):
                        self.instance_data[g][i]["java_path"] = chosen
                        self.selected_instance = self.instance_data[g][i]
                        self.save_data()
                        self.select_instance(self.selected_instance)
                        QMessageBox.information(d, "Готово", "Java сохранена для установки.")
                        d.accept()
                        return

        browse.clicked.connect(on_browse)
        dl.clicked.connect(on_download)
        save.clicked.connect(on_save)
        close.clicked.connect(d.accept)
        d.exec()

    def open_worlds_manager(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        inst_path = inst.get("path", "")
        if not inst_path:
            return
        saves_dir = os.path.join(inst_path, "saves")
        shots_dir = os.path.join(inst_path, "screenshots")
        os.makedirs(saves_dir, exist_ok=True)
        os.makedirs(shots_dir, exist_ok=True)

        d = QDialog(self)
        d.setWindowTitle(f"Миры и скриншоты: {inst.get('name', 'Unnamed')}")
        d.resize(820, 520)
        d.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QListWidget { background:#1A1A1A; color:#EEE; border:1px solid #333; border-radius:8px; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
            QPushButton:hover { background:#2D2D2D; }
            #PrimaryBtn { background:#0078D4; border:none; }
        """)
        root = QVBoxLayout(d)
        tabs = QTabWidget()
        root.addWidget(tabs)

        worlds_tab = QWidget()
        wl = QVBoxLayout(worlds_tab)
        worlds_list = QListWidget()
        wl.addWidget(worlds_list)
        worlds_btns = QHBoxLayout()
        w_open = QPushButton("Открыть папку")
        w_backup = QPushButton("Бэкап мира")
        w_delete = QPushButton("Удалить")
        worlds_btns.addWidget(w_open)
        worlds_btns.addWidget(w_backup)
        worlds_btns.addWidget(w_delete)
        worlds_btns.addStretch()
        wl.addLayout(worlds_btns)
        tabs.addTab(worlds_tab, "Миры")

        shots_tab = QWidget()
        sl = QVBoxLayout(shots_tab)
        shots_list = QListWidget()
        sl.addWidget(shots_list)
        shots_btns = QHBoxLayout()
        s_open_dir = QPushButton("Открыть папку")
        s_open = QPushButton("Открыть файл")
        s_delete = QPushButton("Удалить")
        shots_btns.addWidget(s_open_dir)
        shots_btns.addWidget(s_open)
        shots_btns.addWidget(s_delete)
        shots_btns.addStretch()
        sl.addLayout(shots_btns)
        tabs.addTab(shots_tab, "Скриншоты")

        close = QPushButton("Закрыть")
        close.setObjectName("PrimaryBtn")
        root.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

        def refill_worlds():
            worlds_list.clear()
            for name in sorted(os.listdir(saves_dir)):
                p = os.path.join(saves_dir, name)
                if os.path.isdir(p):
                    worlds_list.addItem(name)

        def refill_shots():
            shots_list.clear()
            for name in sorted(os.listdir(shots_dir), reverse=True):
                if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    shots_list.addItem(name)

        def delete_world():
            row = worlds_list.currentRow()
            if row < 0:
                return
            name = worlds_list.item(row).text()
            p = os.path.join(saves_dir, name)
            if QMessageBox.question(d, "Подтверждение", f"Удалить мир '{name}'?") != QMessageBox.StandardButton.Yes:
                return
            shutil.rmtree(p, ignore_errors=True)
            self.log_event(f"Удален мир: {name}")
            refill_worlds()

        def backup_world():
            row = worlds_list.currentRow()
            if row < 0:
                return
            name = worlds_list.item(row).text()
            src = os.path.join(saves_dir, name)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_name = f"{re.sub(r'[^a-zA-Z0-9._-]+', '_', name)}_world_{ts}.zip"
            out_path = os.path.join(self.backups_dir(), out_name)
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root_dir, _, files in os.walk(src):
                    for fn in files:
                        full = os.path.join(root_dir, fn)
                        rel = os.path.relpath(full, src)
                        zf.write(full, arcname=rel)
            self.log_event(f"Создан бэкап мира: {out_name}")
            QMessageBox.information(d, "Готово", f"Бэкап создан:\n{out_name}")

        def delete_shot():
            row = shots_list.currentRow()
            if row < 0:
                return
            name = shots_list.item(row).text()
            p = os.path.join(shots_dir, name)
            if QMessageBox.question(d, "Подтверждение", f"Удалить скриншот '{name}'?") != QMessageBox.StandardButton.Yes:
                return
            try:
                os.remove(p)
                self.log_event(f"Удален скриншот: {name}")
            except Exception as e:
                QMessageBox.warning(d, "Ошибка", str(e))
            refill_shots()

        def open_path(path):
            try:
                os.startfile(path)
            except Exception:
                pass

        w_open.clicked.connect(lambda: open_path(saves_dir))
        w_backup.clicked.connect(backup_world)
        w_delete.clicked.connect(delete_world)
        s_open_dir.clicked.connect(lambda: open_path(shots_dir))
        s_open.clicked.connect(lambda: open_path(os.path.join(shots_dir, shots_list.currentItem().text())) if shots_list.currentItem() else None)
        s_delete.clicked.connect(delete_shot)
        close.clicked.connect(d.accept)

        refill_worlds()
        refill_shots()
        d.exec()

    def _read_options_txt(self, path):
        data = {}
        if not os.path.exists(path):
            return data
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if ":" in line:
                        k, v = line.split(":", 1)
                        data[k] = v
        except Exception:
            pass
        return data

    def _write_options_txt(self, path, data):
        lines = [f"{k}:{v}" for k, v in data.items()]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))

    def apply_graphics_profile(self, inst, profile):
        profile_map = {
            "Low": {"graphicsMode": "0", "renderDistance": "6", "simulationDistance": "5", "particles": "0", "entityShadows": "false", "mipmapLevels": "0", "maxFps": "120"},
            "Medium": {"graphicsMode": "1", "renderDistance": "10", "simulationDistance": "8", "particles": "1", "entityShadows": "true", "mipmapLevels": "2", "maxFps": "144"},
            "High": {"graphicsMode": "1", "renderDistance": "16", "simulationDistance": "12", "particles": "2", "entityShadows": "true", "mipmapLevels": "4", "maxFps": "240"},
            "Ultra": {"graphicsMode": "1", "renderDistance": "24", "simulationDistance": "16", "particles": "2", "entityShadows": "true", "mipmapLevels": "4", "maxFps": "0"},
        }
        cfg = profile_map.get(profile)
        if not cfg:
            return
        options_path = os.path.join(inst.get("path", ""), "options.txt")
        opts = self._read_options_txt(options_path)
        for k, v in cfg.items():
            opts[k] = v
        self._write_options_txt(options_path, opts)
        self.set_instance_prop(inst.get("path", ""), "graphics_profile", profile)
        self.log_event(f"Применен профиль графики {profile} для {inst.get('name', 'Unnamed')}")

    def open_graphics_profile_dialog(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        items = ["Low", "Medium", "High", "Ultra"]
        cur = inst.get("graphics_profile", "Medium")
        idx = items.index(cur) if cur in items else 1
        profile, ok = QInputDialog.getItem(self, "Профиль графики", "Выберите профиль:", items, idx, False)
        if not ok:
            return
        try:
            self.apply_graphics_profile(inst, profile)
            QMessageBox.information(self, "Готово", f"Профиль {profile} применен.")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось применить профиль: {e}")

    def open_crash_reports(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        base = inst.get("path", "")
        crash_dir = os.path.join(base, "crash-reports")
        d = QDialog(self)
        d.setWindowTitle(f"Crash-отчеты: {inst.get('name', 'Unnamed')}")
        d.resize(900, 560)
        d.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QListWidget { background:#1A1A1A; color:#EEE; border:1px solid #333; border-radius:8px; }
            QTextEdit { background:#171717; color:#DDD; border:1px solid #333; border-radius:8px; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
        """)
        root = QHBoxLayout(d)
        left = QVBoxLayout()
        lst = QListWidget()
        left.addWidget(lst)
        hb = QHBoxLayout()
        open_dir = QPushButton("Открыть папку")
        delete = QPushButton("Удалить")
        hb.addWidget(open_dir); hb.addWidget(delete)
        left.addLayout(hb)
        txt = QTextEdit(); txt.setReadOnly(True)
        root.addLayout(left, 1)
        root.addWidget(txt, 2)

        files = []
        if os.path.exists(crash_dir):
            for fn in os.listdir(crash_dir):
                if fn.lower().endswith((".txt", ".log")):
                    files.append(os.path.join(crash_dir, fn))
        for fn in os.listdir(base) if os.path.exists(base) else []:
            if fn.lower().startswith("hs_err_pid") and fn.lower().endswith(".log"):
                files.append(os.path.join(base, fn))
        files = sorted(files, key=lambda p: os.path.getmtime(p), reverse=True)
        for p in files:
            lst.addItem(os.path.basename(p))

        def show_sel():
            row = lst.currentRow()
            if row < 0 or row >= len(files):
                txt.setPlainText("")
                return
            p = files[row]
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    txt.setPlainText(f.read())
            except Exception as e:
                txt.setPlainText(str(e))

        def del_sel():
            row = lst.currentRow()
            if row < 0 or row >= len(files):
                return
            p = files[row]
            try:
                os.remove(p)
                files.pop(row)
                lst.takeItem(row)
                txt.setPlainText("")
            except Exception as e:
                QMessageBox.warning(d, "Ошибка", str(e))

        lst.currentRowChanged.connect(lambda *_: show_sel())
        open_dir.clicked.connect(lambda: os.startfile(crash_dir) if os.path.exists(crash_dir) else None)
        delete.clicked.connect(del_sel)
        d.exec()

    def repair_selected_instance(self):
        if not self.selected_instance:
            return
        inst = self.selected_instance
        if QMessageBox.question(
            self,
            "Починить установку",
            f"Проверить и починить установку '{inst.get('name', 'Unnamed')}'?\n"
            "Перед починкой будет создан бэкап."
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.create_instance_backup(inst, reason="before_repair")
            p = inst.get("path", "")
            mc_version = inst.get("version", "")
            installer = inst.get("installer", "vanilla")
            loader_version = inst.get("loader_version") or None
            if not p or not mc_version:
                raise RuntimeError("Некорректные данные установки.")
            self.log_event(f"Починка начата: {inst.get('name', 'Unnamed')} ({mc_version}, {installer})")
            callback = {"setStatus": lambda t: self.log_event(f"[repair] {t}"), "setProgress": lambda v: None}
            minecraft_launcher_lib.install.install_minecraft_version(mc_version, p, callback=callback)
            if installer == "fabric":
                if not loader_version:
                    loader_version = minecraft_launcher_lib.fabric.get_latest_loader_version()
                minecraft_launcher_lib.fabric.install_fabric(mc_version, p, loader_version=loader_version, callback=callback)
            elif installer == "forge":
                forge_version = loader_version or minecraft_launcher_lib.forge.find_forge_version(mc_version)
                if forge_version:
                    minecraft_launcher_lib.forge.install_forge_version(forge_version, p, callback=callback)
            elif installer == "quilt":
                if not loader_version:
                    loader_version = minecraft_launcher_lib.quilt.get_latest_loader_version()
                minecraft_launcher_lib.quilt.install_quilt(mc_version, p, loader_version=loader_version, callback=callback)
            os.makedirs(os.path.join(p, "mods"), exist_ok=True)
            os.makedirs(os.path.join(p, "resourcepacks"), exist_ok=True)
            os.makedirs(os.path.join(p, "shaderpacks"), exist_ok=True)
            os.makedirs(os.path.join(p, "saves"), exist_ok=True)
            os.makedirs(os.path.join(p, "screenshots"), exist_ok=True)
            self.log_event("Починка завершена успешно.")
            QMessageBox.information(self, "Готово", "Починка установки завершена.")
        except Exception as e:
            self.log_event(f"Ошибка починки: {e}")
            QMessageBox.warning(self, "Ошибка", f"Починка не удалась: {e}")

    def _mod_loader_tags(self, filename):
        n = filename.lower()
        tags = set()
        if "fabric" in n:
            tags.add("fabric")
        if "quilt" in n:
            tags.add("quilt")
        if "forge" in n:
            tags.add("forge")
        if "neoforge" in n or "neo-forge" in n:
            tags.add("forge")
        return tags

    def _mod_base_key(self, filename):
        base = filename.rsplit(".", 1)[0].lower()
        base = re.sub(r"[\-_ ](mc)?\d+\.\d+(\.\d+)?([\-_.][\w+]+)?$", "", base)
        base = re.sub(r"[\-_ ]v?\d+(\.\d+){0,3}([\-_.][\w+]+)?$", "", base)
        base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
        return base or filename.lower()

    def check_mod_conflicts(self):
        inst = self.selected_instance
        if not inst:
            instances = self.get_all_instances()
            if not instances:
                QMessageBox.warning(self, "Ошибка", "Нет установок.")
                return
            d = InstanceSelectDialog(instances, self)
            if d.exec() != QDialog.DialogCode.Accepted:
                return
            inst = d.selected_instance()
            if not inst:
                return
        mods_dir = os.path.join(inst.get("path", ""), "mods")
        if not os.path.exists(mods_dir):
            QMessageBox.information(self, "Проверка", "Папка mods отсутствует.")
            return

        loader = str(inst.get("installer", "vanilla")).lower()
        mc_version = str(inst.get("version", "")).strip()
        jars = [f for f in os.listdir(mods_dir) if f.lower().endswith(".jar")]
        conflicts = []
        warnings = []
        by_key = {}

        if loader == "vanilla" and jars:
            warnings.append("Для vanilla-установки обнаружены моды. Они, скорее всего, не запустятся.")

        for fn in jars:
            key = self._mod_base_key(fn)
            by_key.setdefault(key, []).append(fn)
            tags = self._mod_loader_tags(fn)
            if loader == "forge" and ("fabric" in tags or "quilt" in tags):
                conflicts.append(f"{fn}: похоже на Fabric/Quilt мод для Forge-установки.")
            if loader == "fabric" and "forge" in tags:
                conflicts.append(f"{fn}: похоже на Forge мод для Fabric-установки.")
            if loader == "quilt" and "forge" in tags:
                conflicts.append(f"{fn}: похоже на Forge мод для Quilt-установки.")
            found_versions = re.findall(r"\b1\.\d+(?:\.\d+)?\b", fn)
            if mc_version and found_versions and all(not mc_version.startswith(v) and not v.startswith(mc_version) for v in found_versions):
                warnings.append(f"{fn}: в названии указаны версии {', '.join(sorted(set(found_versions)))} (установка {mc_version}).")

        for _, files in by_key.items():
            if len(files) > 1:
                conflicts.append("Возможный дубликат мода: " + ", ".join(files))

        report = []
        report.append(f"Установка: {inst.get('name', 'Unnamed')} | Minecraft {mc_version} | {loader}")
        report.append(f"Найдено jar-модов: {len(jars)}")
        report.append("")
        if conflicts:
            report.append(f"Критичные конфликты: {len(conflicts)}")
            report.extend(f"- {x}" for x in conflicts[:100])
        else:
            report.append("Критичных конфликтов не найдено.")
        report.append("")
        if warnings:
            report.append(f"Предупреждения: {len(warnings)}")
            report.extend(f"- {x}" for x in warnings[:150])
        else:
            report.append("Предупреждений нет.")

        self.log_event(f"Проверка конфликтов модов: {inst.get('name', 'Unnamed')} | conflicts={len(conflicts)}, warnings={len(warnings)}")
        dlg = QDialog(self)
        dlg.setWindowTitle("Проверка конфликтов модов")
        dlg.resize(900, 560)
        dlg.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QTextEdit { background:#171717; color:#DCDCDC; border:1px solid #333; border-radius:8px; }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
            #PrimaryBtn { background:#0078D4; border:none; }
        """)
        l = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText("\n".join(report))
        l.addWidget(txt)
        hb = QHBoxLayout()
        close = QPushButton("Закрыть")
        close.setObjectName("PrimaryBtn")
        close.clicked.connect(dlg.accept)
        hb.addStretch()
        hb.addWidget(close)
        l.addLayout(hb)
        dlg.exec()

    def log_event(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {text}"
        self.install_logs.append(entry)
        if len(self.install_logs) > 500:
            self.install_logs = self.install_logs[-500:]
        if hasattr(self, "log_text") and self.log_text is not None:
            self.log_text.append(entry)

    def open_install_logs(self):
        if hasattr(self, "log_dialog") and self.log_dialog is not None:
            self.log_dialog.show()
            self.log_dialog.raise_()
            self.log_dialog.activateWindow()
            return

        self.log_dialog = QDialog(self)
        self.log_dialog.setWindowTitle("Логи установки")
        self.log_dialog.resize(780, 480)
        self.log_dialog.setStyleSheet("""
            QDialog { background: #121212; color: white; font-family: 'Segoe UI'; }
            QTextEdit { background: #171717; color: #DCDCDC; border: 1px solid #333; border-radius: 8px; }
            QPushButton { background: #252525; color: white; border: 1px solid #333; border-radius: 8px; padding: 8px; }
            QPushButton:hover { background: #2D2D2D; }
        """)
        l = QVBoxLayout(self.log_dialog)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlainText("\n".join(self.install_logs) if self.install_logs else "Логи пока пусты.")
        l.addWidget(self.log_text)
        hb = QHBoxLayout()
        clear_b = QPushButton("Очистить")
        close_b = QPushButton("Закрыть")
        clear_b.clicked.connect(lambda: (self.install_logs.clear(), self.log_text.setPlainText("Логи очищены.")))
        close_b.clicked.connect(self.log_dialog.close)
        hb.addWidget(clear_b); hb.addStretch(); hb.addWidget(close_b)
        l.addLayout(hb)
        self.log_dialog.finished.connect(lambda _: (setattr(self, "log_dialog", None), setattr(self, "log_text", None)))
        self.log_dialog.show()

    def handle_launch(self):
        if not self.selected_instance:
            return
        account = self.get_active_account()
        if account.get("type") == "microsoft":
            refreshed = self.refresh_microsoft_account_token(account)
            account = refreshed or account
            # persist refreshed token in settings for next launches
            accounts = self.settings.get("accounts", [])
            idx = int(self.settings.get("active_account", 0))
            if 0 <= idx < len(accounts):
                accounts[idx] = account
                self.settings["accounts"] = accounts
                self.save_settings()
        self.log_event(f"Запуск установки: {self.selected_instance.get('name', 'Unnamed')} | аккаунт: {account.get('username', 'Player')}")
        
        self.clear_console()
        self.show_console_page()

        ok_space, free_gb = self.check_disk_space(self.selected_instance.get("path", ""), required_gb=2.0)
        if not ok_space:
            QMessageBox.warning(self, "Недостаточно места", f"Свободно только {free_gb:.2f} GB. Для запуска нужно минимум ~2 GB.")
            self.log_event("Запуск отменен: недостаточно свободного места.")
            self.append_log_message("ЗАПУСК ОТМЕНЕН: НЕДОСТАТОЧНО МЕСТА НА ДИСКЕ.")
            return
        java_path = self.resolve_java_for_instance(self.selected_instance, parent=self)
        if not java_path:
            self.log_event("Запуск отменен: Java не выбрана.")
            self.append_log_message("ЗАПУСК ОТМЕНЕН: JAVA НЕ ВЫБРАНА.")
            return
        self.pbar.setVisible(True); self.play_btn.setEnabled(False)
        launch_data = dict(self.selected_instance)
        if bool(self.settings.get("auto_ram", True)):
            launch_data["ram_mb"] = int(self.recommended_ram_mb())
            self.log_event(f"Автоподбор RAM: {launch_data['ram_mb']} MB")
        else:
            launch_data["ram_mb"] = int(self.settings.get("ram_mb", 2048))
        launch_data["account"] = account
        launch_data["java_path"] = java_path
        self.launch_started_at = time.time()
        self.launch_instance_path = self.selected_instance.get("path", "")
        self.thread = LaunchThread(launch_data)
        self.thread.progress.connect(self.on_launch_progress)
        self.thread.log_line.connect(self.append_log_message)
        self.thread.finished.connect(self.on_launch_finished)
        self.start_discord_rpc()
        self.update_discord_presence()
        self.thread.start()

    def on_launch_progress(self, v, t):
        self.pbar.setValue(v)
        if t:
            self.log_event(t)
            low = str(t).lower()
            if any(x in low for x in ["download", "скач", "library", "библиот"]):
                if self.library_update_task_id is None:
                    self.library_update_task_id = self._download_task_start("Обновление библиотеки Minecraft", 100, unit="percent")
                    self.open_downloads_window()
                self._download_task_progress(self.library_update_task_id, int(v))

    def on_launch_finished(self):
        self.pbar.setVisible(False)
        self.play_btn.setEnabled(True)
        self._update_edit_menu_state()
        if self.launch_started_at and self.launch_instance_path:
            elapsed = max(0, int(time.time() - self.launch_started_at))
            if elapsed > 0:
                by_path = self.settings.setdefault("playtime_by_path", {})
                by_path[self.launch_instance_path] = int(by_path.get(self.launch_instance_path, 0)) + elapsed
                self.settings["playtime_total_sec"] = int(self.settings.get("playtime_total_sec", 0)) + elapsed
                self.save_settings()
                self.update_playtime_labels()
                self.log_event(f"Время сессии: {self.format_seconds(elapsed)}")
        self.launch_started_at = None
        self.launch_instance_path = ""
        if self.library_update_task_id is not None:
            self._download_task_progress(self.library_update_task_id, 100)
            self._download_task_finish(self.library_update_task_id, ok=True)
            self.library_update_task_id = None
        self.stop_discord_rpc()

    def launch_instance_by_path(self, instance_path):
        p = os.path.normcase(os.path.normpath(str(instance_path or "")))
        if not p:
            return False
        for _, insts in self.instance_data.items():
            for inst in insts:
                ip = os.path.normcase(os.path.normpath(inst.get("path", "")))
                if ip == p:
                    self.select_instance(inst)
                    self.show_library_page()
                    self.handle_launch()
                    return True
        self.log_event(f"Автозапуск: установка не найдена по пути {instance_path}")
        return False

    def force_stop_minecraft(self):
        if hasattr(self, "thread") and self.thread is not None and self.thread.isRunning():
            self.thread.stop_minecraft()
            self.log_event("Команда экстренной остановки отправлена.")
        else:
            self.log_event("Экстренная остановка: процесс Minecraft не запущен.")

    def refresh_grid(self):
        for i in reversed(range(self.grid.count())): self.grid.itemAt(i).widget().setParent(None)
        row = 0
        col_count = 4
        q = ""
        if hasattr(self, "instances_search") and self.instances_search is not None:
            q = self.instances_search.text().strip().lower()
        # Favorites block on top
        favorites = []
        for g, insts in self.instance_data.items():
            for it in insts:
                if not it.get("favorite"):
                    continue
                if q:
                    if q not in str(it.get("name", "")).lower() and q not in str(it.get("version", "")).lower() and q not in str(g).lower():
                        continue
                favorites.append(it)
        if favorites:
            fav_title = (getattr(self, "lang_labels", {}) or {}).get("favorites_group", "★ Избранные")
            fav_lbl = QLabel(fav_title)
            fav_lbl.setStyleSheet("background:#1A1A1A;color:#FFD166;font-weight:700;font-size:14px;border:1px solid #2D2D2D;border-radius:8px;padding:8px;")
            self.grid.addWidget(fav_lbl, row, 0, 1, col_count)
            row += 1
            idx = 0
            favorites = sorted(favorites, key=lambda it: str(it.get("name", "")).lower())
            for inst in favorites:
                card = InstanceCard(inst, self.select_instance)
                if self.selected_instance and inst.get('path') == self.selected_instance.get('path'):
                    card.setProperty("selected", "true")
                color_map = {
                    "Red": "#C84C4C", "Orange": "#D68742", "Yellow": "#CDB548", "Green": "#4FAE6A",
                    "Cyan": "#4AA7C8", "Blue": "#4D78C8", "Purple": "#8E63CC", "Pink": "#C06AA8"
                }
                c = color_map.get(inst.get("color_label", ""))
                if c:
                    card.setStyleSheet(f"background:#181818;border:2px solid {c};border-radius:12px;")
                l = QVBoxLayout(card)
                icon = QLabel(inst.get('emoji', "📦")); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); icon.setStyleSheet("font-size: 35px; border: none;")
                fav = "★ " if inst.get("favorite") else ""
                name = QLabel(f"{fav}{inst['name']}"); name.setAlignment(Qt.AlignmentFlag.AlignCenter); name.setStyleSheet("font-weight: bold; color: white; border: none;")
                tag = QLabel(inst.get("color_label", "") if inst.get("color_label", "") not in ("", "None") else "")
                tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tag.setStyleSheet("font-size:11px;color:#BFC7DA;border:none;")
                l.addStretch(); l.addWidget(icon); l.addWidget(name); l.addWidget(tag); l.addStretch()
                self.grid.addWidget(card, row + (idx // col_count), idx % col_count)
                idx += 1
            row += (idx + col_count - 1) // col_count
        for g, insts in self.instance_data.items():
            filtered = [it for it in insts if not it.get("favorite")]
            if q:
                if q in str(g).lower():
                    filtered = [it for it in insts if not it.get("favorite")]
                else:
                    filtered = [it for it in insts if not it.get("favorite") and (q in str(it.get("name", "")).lower() or q in str(it.get("version", "")).lower())]
            if q and not filtered:
                continue
            filtered = sorted(filtered, key=lambda it: (0 if it.get("favorite") else 1, str(it.get("name", "")).lower()))
            collapsed = self.group_collapsed.get(g, False)
            arrow = "▶" if collapsed else "▼"
            grp_btn = GroupDropButton(g, f"{arrow} {g}")
            grp_btn.setStyleSheet("background:#1A1A1A;color:#8FB9FF;font-weight:700;font-size:14px;border:1px solid #2D2D2D;border-radius:8px;padding:8px;text-align:left;")
            grp_btn.clicked.connect(lambda _, group=g: self.toggle_group(group))
            grp_btn.dropped.connect(self.move_instance_to_group)
            self.grid.addWidget(grp_btn, row, 0, 1, col_count)
            row += 1
            if collapsed:
                continue
            idx = 0
            for inst in filtered:
                card = InstanceCard(inst, self.select_instance)
                if self.selected_instance and inst.get('path') == self.selected_instance.get('path'):
                    card.setProperty("selected", "true")
                color_map = {
                    "Red": "#C84C4C", "Orange": "#D68742", "Yellow": "#CDB548", "Green": "#4FAE6A",
                    "Cyan": "#4AA7C8", "Blue": "#4D78C8", "Purple": "#8E63CC", "Pink": "#C06AA8"
                }
                c = color_map.get(inst.get("color_label", ""))
                if c:
                    card.setStyleSheet(f"background:#181818;border:2px solid {c};border-radius:12px;")
                l = QVBoxLayout(card)
                icon = QLabel(inst.get('emoji', "📦")); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); icon.setStyleSheet("font-size: 35px; border: none;")
                fav = "★ " if inst.get("favorite") else ""
                name = QLabel(f"{fav}{inst['name']}"); name.setAlignment(Qt.AlignmentFlag.AlignCenter); name.setStyleSheet("font-weight: bold; color: white; border: none;")
                tag = QLabel(inst.get("color_label", "") if inst.get("color_label", "") not in ("", "None") else "")
                tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tag.setStyleSheet("font-size:11px;color:#BFC7DA;border:none;")
                l.addStretch(); l.addWidget(icon); l.addWidget(name); l.addWidget(tag); l.addStretch()
                self.grid.addWidget(card, row + (idx // col_count), idx % col_count)
                idx += 1
            row += (idx + col_count - 1) // col_count

    def toggle_group(self, group):
        self.group_collapsed[group] = not self.group_collapsed.get(group, False)
        self.refresh_grid()

    def move_instance_to_group(self, instance_path, target_group):
        self._move_instance_to_group(instance_path, target_group)

    def open_create(self):
        self.show_library_page()
        d = CreateInstanceDialog(self, list(self.instance_data.keys()))
        if d.exec():
            data = d.get_data()
            ok_space, free_gb = self.check_disk_space(data.get("path", ""), required_gb=2.0)
            if not ok_space:
                QMessageBox.warning(self, "Недостаточно места", f"Свободно только {free_gb:.2f} GB. Нужно минимум ~2 GB.")
                return
            g = data['group']
            if g not in self.instance_data: self.instance_data[g] = []
            self.instance_data[g].append(data); self.save_data(); self.refresh_grid()

    def delete_current(self):
        if not self.selected_instance: return
        for g in self.instance_data:
            self.instance_data[g] = [i for i in self.instance_data[g] if i.get('path') != self.selected_instance.get('path')]
        self.selected_instance = None
        for b in [self.btn_launch, self.btn_stop, self.btn_folder, self.btn_copy, self.btn_shortcut, self.btn_delete]:
            b.setEnabled(False)
        self.edit_btn.setEnabled(False)
        self._update_edit_menu_state()
        self.update_playtime_labels()
        self.save_data(); self.refresh_grid(); self.inspector.setVisible(False)

    def save_data(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f: json.dump(self.instance_data, f, indent=4)
    def load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                self.instance_data = json.load(f); self.refresh_grid()

class EditMenuDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        t = getattr(parent, "lang_labels", {}) or {}

        self.setWindowTitle(t.get("edit_menu_title", "Меню установки"))
        self.resize(980, 600)
        self.setStyleSheet("""
            QDialog { background:#2B2B2B; color:white; font-family:'Segoe UI'; }
            QListWidget { background:#222; color:white; border:none; }
            QListWidget::item { padding: 8px 10px; }
            QListWidget::item:selected { background:#6ABF4B; color:black; }
            QLabel { color:#DDD; }
            QPushButton { background:#3B3B3B; color:white; border:1px solid #4A4A4A; border-radius:6px; padding:6px 10px; }
            QPushButton:hover { background:#444; }
            #Header { color:white; font-size:18px; font-weight:800; }
            #Panel { background:#333; border:1px solid #444; border-radius:6px; }
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.nav = QListWidget()
        self.nav.setFixedWidth(210)
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        def add_page(title, emoji, widget):
            self.nav.addItem(f"{emoji} {title}")
            self.stack.addWidget(widget)

        add_page(t.get("edit_menu_journal", "Журнал Minecraft"), "📖", self._page_journal(t))
        add_page(t.get("edit_menu_version", "Версия"), "🧱", self._page_version(t))
        add_page(t.get("edit_menu_mods", "Моды"), "🧩", self._page_mods(t))
        add_page(t.get("edit_menu_rpacks", "Resource packs"), "🧰", self._page_assets(t, t.get("edit_menu_rpacks", "Resource packs")))
        add_page(t.get("edit_menu_spacks", "Shader packs"), "✨", self._page_assets(t, t.get("edit_menu_spacks", "Shader packs")))
        add_page(t.get("edit_menu_worlds", "Миры"), "🌍", self._page_worlds(t))
        add_page(t.get("edit_menu_servers", "Серверы"), "🛰", self._page_servers(t))
        add_page(t.get("edit_menu_shots", "Снимки экрана"), "🖼", self._page_shots(t))
        add_page(t.get("edit_menu_params", "Параметры"), "⚙️", self._page_params(t))
        add_page(t.get("edit_menu_logs", "Other logs"), "📜", self._page_logs(t))
        add_page(t.get("edit_menu_more", "Другое"), "⭐", self._page_more(t))

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    def _panel(self, title):
        w = QFrame()
        w.setObjectName("Panel")
        l = QVBoxLayout(w)
        l.setContentsMargins(14, 14, 14, 14)
        l.setSpacing(10)
        head = QLabel(title)
        head.setObjectName("Header")
        l.addWidget(head)
        return w, l

    def _page_journal(self, t):
        w, l = self._panel(t.get("edit_menu_journal", "Журнал Minecraft"))
        b1 = QPushButton("Открыть консоль"); b1.clicked.connect(self.parent.show_console_page)
        b2 = QPushButton("Логи установки"); b2.clicked.connect(self.parent.open_install_logs)
        b3 = QPushButton("Очистить консоль"); b3.clicked.connect(self.parent.clear_console)
        for b in [b1, b2, b3]: l.addWidget(b)
        l.addStretch()
        return w

    def _page_version(self, t):
        w, l = self._panel(t.get("edit_menu_version", "Версия"))
        b1 = QPushButton("Изменить установку"); b1.clicked.connect(self.parent.open_edit_instance_dialog)
        b2 = QPushButton("Java"); b2.clicked.connect(self.parent.open_java_manager)
        b3 = QPushButton("Починить установку"); b3.clicked.connect(self.parent.repair_selected_instance)
        for b in [b1, b2, b3]: l.addWidget(b)
        l.addStretch()
        return w

    def _page_mods(self, t):
        w, l = self._panel(t.get("edit_menu_mods", "Моды"))
        b1 = QPushButton("Менеджер модов"); b1.clicked.connect(self.parent.open_mods)
        b2 = QPushButton("Проверить обновления"); b2.clicked.connect(self.parent.check_mod_updates)
        b3 = QPushButton("Обновить всё"); b3.clicked.connect(self.parent.update_all_mods)
        b4 = QPushButton("Проверить конфликты"); b4.clicked.connect(self.parent.check_mod_conflicts)
        for b in [b1, b2, b3, b4]: l.addWidget(b)
        l.addStretch()
        return w

    def _page_assets(self, t, title):
        w, l = self._panel(title)
        b1 = QPushButton("Открыть менеджер ресурсов/шейдеров"); b1.clicked.connect(self.parent.open_assets_manager)
        l.addWidget(b1); l.addStretch()
        return w

    def _page_worlds(self, t):
        w, l = self._panel(t.get("edit_menu_worlds", "Миры"))
        b1 = QPushButton("Открыть миры и скриншоты"); b1.clicked.connect(self.parent.open_worlds_manager)
        l.addWidget(b1); l.addStretch()
        return w

    def _page_servers(self, t):
        w, l = self._panel(t.get("edit_menu_servers", "Серверы"))
        b1 = QPushButton("Обновить статус"); b1.clicked.connect(self.parent.refresh_server_status)
        b2 = QPushButton("Открыть настройки"); b2.clicked.connect(self.parent.show_settings_page)
        l.addWidget(b1); l.addWidget(b2); l.addStretch()
        return w

    def _page_shots(self, t):
        w, l = self._panel(t.get("edit_menu_shots", "Снимки экрана"))
        b1 = QPushButton("Открыть миры и скриншоты"); b1.clicked.connect(self.parent.open_worlds_manager)
        l.addWidget(b1); l.addStretch()
        return w

    def _page_params(self, t):
        w, l = self._panel(t.get("edit_menu_params", "Параметры"))
        b1 = QPushButton("Открыть настройки"); b1.clicked.connect(self.parent.show_settings_page)
        b2 = QPushButton("Профиль графики"); b2.clicked.connect(self.parent.open_graphics_profile_dialog)
        b3 = QPushButton("Цвет метки"); b3.clicked.connect(self.parent.set_color_label_selected)
        b4 = QPushButton("В избранное"); b4.clicked.connect(self.parent.toggle_favorite_selected)
        for b in [b1, b2, b3, b4]: l.addWidget(b)
        l.addStretch()
        return w

    def _page_logs(self, t):
        w, l = self._panel(t.get("edit_menu_logs", "Other logs"))
        b1 = QPushButton("Логи установки"); b1.clicked.connect(self.parent.open_install_logs)
        b2 = QPushButton("Crash-отчеты"); b2.clicked.connect(self.parent.open_crash_reports)
        l.addWidget(b1); l.addWidget(b2); l.addStretch()
        return w

    def _page_more(self, t):
        w, l = self._panel(t.get("edit_menu_more", "Другое"))
        b1 = QPushButton("Экспортировать"); b1.clicked.connect(self.parent.export_selected_instance)
        b2 = QPushButton("Бэкапы"); b2.clicked.connect(self.parent.open_backups_manager)
        l.addWidget(b1); l.addWidget(b2); l.addStretch()
        return w

class EditInstanceDialog(QDialog):
    def __init__(self, parent, instance, existing_groups=None):
        super().__init__(parent)
        self.inst = instance or {}
        self.existing_groups = [g for g in (existing_groups or []) if g]
        self.labels = getattr(parent, "lang_labels", {}) or {}

        self.setWindowTitle(self.labels.get("edit_title", "Изменить установку"))
        self.setFixedSize(520, 520)
        self.setStyleSheet("""
            QDialog { background:#121212; color:white; font-family:'Segoe UI'; }
            QLabel { color:#DDD; font-size:13px; }
            QLineEdit, QComboBox {
                background:#1A1A1A; color:white; border:1px solid #333; border-radius:8px; padding:8px;
            }
            QPushButton { background:#252525; color:white; border:1px solid #333; border-radius:8px; padding:8px; }
            QPushButton:hover { background:#2D2D2D; }
            #PrimaryBtn { background:#0078D4; border:none; font-weight:700; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        title = QLabel(self.labels.get("edit_title", "Изменить установку"))
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: white;")
        root.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setSpacing(8)

        self.n = QLineEdit(self.inst.get("name", ""))
        self.group_box = QComboBox()
        groups = self.existing_groups if self.existing_groups else ["Main"]
        self.group_box.addItems(groups)
        self.group_box.addItem("➕ Новая группа...")
        cur_group = self.inst.get("group", "Main")
        if cur_group in groups:
            self.group_box.setCurrentText(cur_group)
        self.new_group = QLineEdit()
        self.new_group.setPlaceholderText(self.labels.get("edit_group_new_ph", "Введите название новой группы"))
        self.new_group.setVisible(False)

        self.emoji = QComboBox()
        self.emoji.addItems(["📦", "⚔️", "🧪", "🏗️", "🌋", "🛰️", "🐉", "🔥", "❄️"])
        cur_emoji = self.inst.get("emoji", "📦")
        if cur_emoji in [self.emoji.itemText(i) for i in range(self.emoji.count())]:
            self.emoji.setCurrentText(cur_emoji)

        self.loader = QComboBox()
        self.loader.addItems(["vanilla", "fabric", "forge", "quilt"])
        self.loader.setCurrentText(self.inst.get("installer", "vanilla"))

        self.loader_v = QComboBox()
        self.loader_v.setMinimumWidth(220)

        self.mc_lbl = QLabel(f"Minecraft: {self.inst.get('version', '')}")
        self.mc_lbl.setStyleSheet("color:#8C8C8C;")

        self.apply_loader_check = QCheckBox(self.labels.get("edit_apply_loader", "Установить/обновить загрузчик"))
        self.apply_loader_check.setStyleSheet("color:white;")

        form.addRow(self.labels.get("edit_name", "Название"), self.n)
        form.addRow(self.labels.get("edit_group", "Группа"), self.group_box)
        form.addRow("", self.new_group)
        form.addRow(self.labels.get("edit_loader", "Загрузчик"), self.loader)
        form.addRow(self.labels.get("edit_loader_ver", "Версия загрузчика"), self.loader_v)
        form.addRow(self.labels.get("edit_emoji", "Эмодзи"), self.emoji)
        root.addLayout(form)
        root.addWidget(self.mc_lbl)
        root.addWidget(self.apply_loader_check)

        btns = QHBoxLayout()
        cancel = QPushButton(self.labels.get("edit_cancel", "Отмена"))
        ok = QPushButton(self.labels.get("edit_save", "Сохранить"))
        ok.setObjectName("PrimaryBtn")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self.group_box.currentTextChanged.connect(self._toggle_group_input)
        self.loader.currentTextChanged.connect(self.refresh_loader_versions)
        self.loader_v.currentTextChanged.connect(lambda *_: self._sync_apply_loader_default())
        self.refresh_loader_versions()
        self._sync_apply_loader_default()

    def _toggle_group_input(self, *_):
        is_new = self.group_box.currentText().startswith("➕")
        self.new_group.setVisible(is_new)

    def _sync_apply_loader_default(self):
        cur_loader = self.inst.get("installer", "vanilla")
        cur_ver = self.inst.get("loader_version", "")
        new_loader = self.loader.currentText()
        new_ver = "" if new_loader == "vanilla" else self.loader_v.currentText()
        self.apply_loader_check.setChecked(new_loader != cur_loader or (new_loader != "vanilla" and new_ver != cur_ver))

    def refresh_loader_versions(self):
        loader = self.loader.currentText()
        mc_version = str(self.inst.get("version", "")).strip()
        self.loader_v.clear()

        if loader == "vanilla":
            self.loader_v.addItem("—")
            self.loader_v.setEnabled(False)
            self._sync_apply_loader_default()
            return

        self.loader_v.setEnabled(True)
        try:
            if loader == "fabric":
                versions = [x["version"] if isinstance(x, dict) else x.version for x in minecraft_launcher_lib.fabric.get_all_loader_versions()]
                self.loader_v.addItems(versions[:50] if versions else [minecraft_launcher_lib.fabric.get_latest_loader_version()])
            elif loader == "quilt":
                versions = [x["version"] if isinstance(x, dict) else x.version for x in minecraft_launcher_lib.quilt.get_all_loader_versions()]
                self.loader_v.addItems(versions[:50] if versions else [minecraft_launcher_lib.quilt.get_latest_loader_version()])
            elif loader == "forge":
                all_forge = minecraft_launcher_lib.forge.list_forge_versions()
                filtered = [fv for fv in all_forge if fv.startswith(f"{mc_version}-")]
                items = filtered[:80] if filtered else all_forge[:80]
                self.loader_v.addItems(items if items else [minecraft_launcher_lib.forge.find_forge_version(mc_version) or "latest"])
        except Exception:
            self.loader_v.addItems(["latest"])
        self._sync_apply_loader_default()

    def get_data(self):
        group_value = self.group_box.currentText()
        if group_value.startswith("➕"):
            group_value = self.new_group.text().strip() or "Main"
        loader = self.loader.currentText()
        loader_version = "" if loader == "vanilla" else self.loader_v.currentText()
        return {
            "name": self.n.text().strip() or self.inst.get("name", "New"),
            "group": group_value,
            "emoji": self.emoji.currentText(),
            "installer": loader,
            "loader_version": loader_version,
            "apply_loader": bool(self.apply_loader_check.isChecked())
        }

class CreateInstanceDialog(QDialog):
    def __init__(self, parent, existing_groups=None):
        super().__init__(parent)
        self.existing_groups = [g for g in (existing_groups or []) if g]
        self.setWindowTitle("Создать установку")
        self.setFixedSize(520, 560)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #101018, stop:1 #13141D);
                color: #EEE; font-family: 'Segoe UI';
            }
            QLabel { color: #DDD; font-size: 13px; }
            #Card {
                background: rgba(28, 30, 44, 0.85);
                border: 1px solid #30354A;
                border-radius: 14px;
            }
            QLineEdit, QComboBox {
                background: #181A26; color: white; border: 1px solid #39405A;
                border-radius: 10px; padding: 9px;
            }
            QComboBox::drop-down { border: none; }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078D4, stop:1 #4A8DF0);
                color: white; border: none; border-radius: 12px; padding: 11px; font-weight: bold;
            }
            QPushButton:hover { background: #2F8FF0; }
            #Hint { color: #8C8C8C; font-size: 11px; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Создать установку")
        title.setStyleSheet("font-size: 26px; font-weight: 900; color: white;")
        root.addWidget(title)

        subtitle = QLabel("Установка — это отдельная папка с Minecraft, её версии, модами и настройками. Можно создать несколько установок для разных целей.")
        subtitle.setStyleSheet("color: #A9B2CE;")
        root.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body)

        left = QFrame()
        left.setObjectName("Card")
        left.setFixedWidth(165)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(14, 14, 14, 14)
        left_icon = QLabel("📦")
        left_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_icon.setStyleSheet("font-size: 46px;")
        left_t = QLabel("Новый экземпляр")
        left_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_t.setStyleSheet("font-weight: 800; color: white;")
        left_s = QLabel("Выберите группу, версию и загрузчик.\nПотом можно изменить всё в настройках сборки.")
        left_s.setWordWrap(True)
        left_s.setStyleSheet("color:#9EA8C8; font-size:12px;")
        left_l.addWidget(left_icon)
        left_l.addWidget(left_t)
        left_l.addWidget(left_s)
        left_l.addStretch()
        body.addWidget(left)

        card = QFrame()
        card.setObjectName("Card")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(16, 16, 16, 16)
        card_l.setSpacing(12)
        body.addWidget(card)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setSpacing(10)

        self.n = QLineEdit()
        self.n.setPlaceholderText("Например: Tech Pack 1.20.1")

        self.v = QComboBox()
        self.show_snapshots = QCheckBox("Snapshot")
        self.show_alpha_beta = QCheckBox("Alpha/Beta")
        self.show_snapshots.setStyleSheet("color:#C8D3F0;")
        self.show_alpha_beta.setStyleSheet("color:#C8D3F0;")
        self._fill_mc_versions()

        self.loader = QComboBox()
        self.loader.addItems(["vanilla", "fabric", "forge", "quilt"])

        self.loader_v = QComboBox()
        self.loader_v.setMinimumWidth(220)

        self.emoji = QComboBox()
        self.emoji.addItems(["📦", "⚔️", "🧪", "🏗️", "🌋", "🛰️", "🐉", "🔥", "❄️"])

        self.group_box = QComboBox()
        groups = self.existing_groups if self.existing_groups else ["Main"]
        self.group_box.addItems(groups)
        self.group_box.addItem("➕ Новая группа...")
        self.new_group = QLineEdit()
        self.new_group.setPlaceholderText("Введите название новой группы")
        self.new_group.setVisible(False)

        form.addRow("Название", self.n)
        form.addRow("Группа", self.group_box)
        form.addRow("", self.new_group)
        form.addRow("Minecraft", self.v)
        checks_row = QHBoxLayout()
        checks_row.addWidget(self.show_snapshots)
        checks_row.addWidget(self.show_alpha_beta)
        checks_row.addStretch()
        checks_wrap = QWidget(); checks_wrap.setLayout(checks_row)
        form.addRow("", checks_wrap)
        form.addRow("Установщик", self.loader)
        form.addRow("Версия установщика", self.loader_v)
        form.addRow("Эмодзи", self.emoji)
        card_l.addLayout(form)

        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        card_l.addWidget(self.hint)
        root.addStretch()

        b = QPushButton("СОЗДАТЬ УСТАНОВКУ")
        b.setFixedHeight(46)
        b.clicked.connect(self.accept)
        root.addWidget(b)

        self.loader.currentTextChanged.connect(self.refresh_loader_versions)
        self.v.currentTextChanged.connect(self.refresh_loader_versions)
        self.group_box.currentTextChanged.connect(self._toggle_group_input)
        self.show_snapshots.stateChanged.connect(lambda *_: self._fill_mc_versions())
        self.show_alpha_beta.stateChanged.connect(lambda *_: self._fill_mc_versions())
        self.refresh_loader_versions()

    def _toggle_group_input(self, *_):
        is_new = self.group_box.currentText().startswith("➕")
        self.new_group.setVisible(is_new)

    def _fill_mc_versions(self):
        try:
            old = self.v.currentText()
            show_sn = self.show_snapshots.isChecked()
            show_ab = self.show_alpha_beta.isChecked()
            full = minecraft_launcher_lib.utils.get_version_list()
            allowed = {"release"}
            if show_sn:
                allowed.add("snapshot")
            if show_ab:
                allowed.update({"old_alpha", "old_beta"})
            versions = [v['id'] for v in full if v.get('type') in allowed]
            self.v.clear()
            self.v.addItems(versions if versions else ["1.20.1"])
            idx = self.v.findText(old)
            if idx >= 0:
                self.v.setCurrentIndex(idx)
        except Exception:
            self.v.clear()
            self.v.addItems(["1.20.1"])

    def refresh_loader_versions(self):
        loader = self.loader.currentText()
        mc_version = self.v.currentText()
        self.loader_v.clear()

        if loader == "vanilla":
            self.loader_v.addItem("—")
            self.loader_v.setEnabled(False)
            self.hint.setText("Обычная ванильная установка.")
            return

        self.loader_v.setEnabled(True)

        try:
            if loader == "fabric":
                versions = [x["version"] if isinstance(x, dict) else x.version for x in minecraft_launcher_lib.fabric.get_all_loader_versions()]
                self.loader_v.addItems(versions[:50] if versions else [minecraft_launcher_lib.fabric.get_latest_loader_version()])
                self.hint.setText("Fabric: можно использовать современные моды с поддержкой новых версий Minecraft. Лёгкий и быстрый.")
            elif loader == "quilt":
                versions = [x["version"] if isinstance(x, dict) else x.version for x in minecraft_launcher_lib.quilt.get_all_loader_versions()]
                self.loader_v.addItems(versions[:50] if versions else [minecraft_launcher_lib.quilt.get_latest_loader_version()])
                self.hint.setText("Quilt: современный форк Fabric с расширенными API.")
            elif loader == "forge":
                all_forge = minecraft_launcher_lib.forge.list_forge_versions()
                filtered = [fv for fv in all_forge if fv.startswith(f"{mc_version}-")]
                items = filtered[:80] if filtered else all_forge[:80]
                self.loader_v.addItems(items if items else [minecraft_launcher_lib.forge.find_forge_version(mc_version) or "latest"])
                self.hint.setText("Forge: классический загрузчик с огромной базой модов, но может быть тяжёлым и медленным на новых версиях.")
        except Exception:
            self.loader_v.addItems(["latest"])
            self.hint.setText("Не удалось получить версии установщика, будет использована latest.")

    def get_data(self):
        p = os.path.join(BASE_DIR, self.n.text().replace(" ", "_"))
        loader = self.loader.currentText()
        loader_version = "" if loader == "vanilla" else self.loader_v.currentText()
        group_value = self.group_box.currentText()
        if group_value.startswith("➕"):
            group_value = self.new_group.text().strip() or "Main"
        return {
            "name": self.n.text() or "New",
            "group": group_value,
            "version": self.v.currentText(),
            "path": p,
            "installer": loader,
            "loader_version": loader_version,
            "emoji": self.emoji.currentText()
        }
if __name__ == "__main__":
    hide_console_if_frozen()
    auto_launch_instance = ""
    if "--launch-instance" in sys.argv:
        try:
            i = sys.argv.index("--launch-instance")
            if i + 1 < len(sys.argv):
                auto_launch_instance = sys.argv[i + 1]
        except Exception:
            auto_launch_instance = ""
    app = QApplication(sys.argv)
    w = LauncherMain(); w.show()
    if auto_launch_instance:
        QTimer.singleShot(400, lambda p=auto_launch_instance: w.launch_instance_by_path(p))
    sys.exit(app.exec())

