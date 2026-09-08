"""GUI приложение ACRELIS для поиска организаций без сайтов на Яндекс.Картах."""
import os
import sys

# При запуске из собранного приложения указываем путь к встроенному Chromium.
if getattr(sys, "frozen", False):
    if sys.platform == "darwin":
        # На macOS браузер НЕ бандлим внутрь .app через PyInstaller --add-data:
        # PyInstaller пытается ad-hoc codesign'ить каждый Mach-O бинарник, который
        # к нему попадает, а вложенный .app самого Chromium (со своими Frameworks)
        # при таком переподписании ломается ("bundle format unrecognized").
        # Вместо этого папка ms-playwright лежит РЯДОМ с ParserYandex.app (см. build-macos.yml),
        # ищем её, поднимаясь от sys.executable до границы .app и на уровень выше.
        _dir = os.path.dirname(os.path.abspath(sys.executable))
        while _dir and not _dir.endswith(".app") and os.path.dirname(_dir) != _dir:
            _dir = os.path.dirname(_dir)
        _bundled = os.path.join(os.path.dirname(_dir), "ms-playwright") if _dir.endswith(".app") else ""
    else:
        _bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "ms-playwright")
    if _bundled and os.path.isdir(_bundled):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _bundled

import asyncio
import threading
from datetime import datetime
from tkinter import ttk, StringVar, IntVar, BooleanVar, END, filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from parser import search_async


# ══════════════════════════════════════════════════════════════════════════
# ACRELIS — ассеты (шрифт, логотип, иконка)
# ══════════════════════════════════════════════════════════════════════════

def _asset_path(*parts):
    """Путь к файлу в assets/ — работает и из исходников, и из собранного .exe (PyInstaller)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets", *parts)


def _load_logo_image(size=(26, 26)):
    """Логотип ACRELIS. Возвращает None, если файл недоступен — UI не должен падать из-за этого."""
    try:
        img = Image.open(_asset_path("acrelis_logo.png")).convert("RGBA")
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None


# ---- Фирменный шрифт Axiforma: приватная регистрация без установки в систему ----
# Каждое начертание в файлах Axiforma зарегистрировано как ОТДЕЛЬНОЕ семейство шрифта
# (например "Axiforma-ExtraBold"), а не как жирный вариант одного семейства "Axiforma".
_AXIFORMA_FAMILIES = {
    "regular": "Axiforma-Regular",
    "semibold": "Axiforma-SemiBold",
    "extrabold": "Axiforma-ExtraBold",
}
_axiforma_loaded = False


def _load_axiforma_fonts(root):
    """Пробуем подключить Axiforma. Любая проблема — тихо остаёмся на Segoe UI,
    шрифт не должен быть причиной падения приложения."""
    global _axiforma_loaded
    if os.name != "nt":
        return False
    try:
        import ctypes
        add_font = ctypes.windll.gdi32.AddFontResourceExW
        add_font.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
        add_font.restype = ctypes.c_int
        FR_PRIVATE = 0x10

        for fname in ("Axiforma-Regular.ttf", "Axiforma-SemiBold.ttf", "Axiforma-ExtraBold.ttf"):
            path = _asset_path("fonts", fname)
            if os.path.isfile(path):
                add_font(path, FR_PRIVATE, None)

        HWND_BROADCAST, WM_FONTCHANGE = 0xFFFF, 0x001D
        ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)

        import tkinter.font as tkfont
        available = set(tkfont.families(root))
        _axiforma_loaded = all(fam in available for fam in _AXIFORMA_FAMILIES.values())
    except Exception:
        _axiforma_loaded = False
    return _axiforma_loaded


_FALLBACK_FAMILY = "Segoe UI" if os.name == "nt" else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")


def F(size, weight="regular"):
    """Шрифт интерфейса: Axiforma, если удалось подключить, иначе системный шрифт платформы
    с синтетическим начертанием (Segoe UI на Windows, Helvetica Neue на macOS)."""
    if _axiforma_loaded:
        family = _AXIFORMA_FAMILIES.get(weight, _AXIFORMA_FAMILIES["regular"])
        return ctk.CTkFont(family=family, size=size)
    tk_weight = "bold" if weight in ("semibold", "extrabold") else "normal"
    return ctk.CTkFont(family=_FALLBACK_FAMILY, size=size, weight=tk_weight)


# ══════════════════════════════════════════════════════════════════════════
# Цветовая палитра ACRELIS — тёмная тема.
# ══════════════════════════════════════════════════════════════════════════
PAGE_BG = "#0E1619"         # Ink — фон окна
PANEL_BG = "#161F23"        # панель тулбара/нижней плашки
HEADER_BG = "#0A1013"       # чуть темнее страницы — шапка отделяется без явной границы
INPUT_BG = "#1C262B"
BORDER = "#26333A"
BORDER_STRONG = "#354247"
FLAME = "#FF050A"           # Пламя
IMPULSE = "#F82245"         # Импульс — основной фирменный красный
AMARANTH = "#F43367"        # Амарант
GARNET = "#AC225A"          # Гранат
ACCENT = IMPULSE
ACCENT_HOVER = GARNET
ACCENT_GREEN = "#22C55E"    # только как функциональный индикатор «успех», не декоративный цвет
TEXT_PRIMARY = "#F4F5F6"    # светлый текст на тёмном фоне
TEXT_SECONDARY = "#9AA6AB"
TEXT_MUTED = "#6B7880"
TABLE_ROW_ALT = "#141C20"
LOG_TEXT = "#9CA7AC"
LOG_MUTED = "#5C6A70"

R_PANEL = 14
R_FIELD = 9

SPHERES = [
    "Кафе", "Ресторан", "Кофейня", "Пиццерия", "Бар", "Столовая",
    "Барбершоп", "Парикмахерская", "Салон красоты", "Маникюрный салон",
    "Стоматология", "Медицинский центр", "Аптека", "Ветеринарная клиника",
    "Автосервис", "Автомойка", "Шиномонтаж",
    "Магазин одежды", "Цветочный магазин", "Зоомагазин",
    "Фитнес-клуб", "Йога-студия", "Танцевальная студия",
    "Юридические услуги", "Бухгалтерские услуги", "Агентство недвижимости",
    "Ремонт квартир", "Дизайн интерьера", "Архитектурное бюро",
    "Хостел", "Гостиница", "Турагентство",
    "Языковая школа", "Детский центр", "Автошкола",
]

CITIES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Самара", "Уфа", "Ростов-на-Дону",
    "Краснодар", "Омск", "Воронеж", "Пермь", "Волгоград",
    "Сочи", "Геленджик", "Анапа", "Новороссийск", "Калининград",
    "Тюмень", "Ижевск", "Барнаул", "Ульяновск", "Иркутск",
    "Хабаровск", "Владивосток", "Ярославль", "Махачкала", "Томск",
    "Оренбург", "Кемерово", "Рязань", "Тольятти", "Астрахань",
    "Пенза", "Липецк", "Тула", "Киров", "Чебоксары",
    "Калуга", "Брянск", "Курск", "Тверь", "Ставрополь",
    "Иваново", "Магнитогорск", "Сургут", "Белгород", "Владимир",
]


# ══════════════════════════════════════════════════════════════════════════
# Экспорт результатов в Word — фирменный стиль ACRELIS
# ══════════════════════════════════════════════════════════════════════════

def _docx_hex(hex_color):
    return hex_color.lstrip("#").upper()


def _docx_cell_shading(cell, hex_color):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), _docx_hex(hex_color))
    tcPr.append(shd)


def _docx_cell_borders(cell, color="E2E5E7", sz=4):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement("w:" + edge)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:color"), _docx_hex(color))
        borders.append(el)
    tcPr.append(borders)


def _build_word_report(path, results):
    """Собирает .docx с результатами поиска в фирменном стиле ACRELIS.
    Один найденный контакт = одна строка таблицы."""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_ORIENT

    IMPULSE_RGB = RGBColor(0xF8, 0x22, 0x45)
    ANTHRA_RGB = RGBColor(0x1E, 0x2F, 0x35)
    ASH_RGB = RGBColor(0x96, 0x96, 0x96)
    WHITE_RGB = RGBColor(0xFF, 0xFF, 0xFF)

    doc = Document()

    # Альбомная ориентация — семь колонок с адресами и сайтами не сжимаются в портретный лист
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    section.left_margin = section.right_margin = Cm(1.4)
    section.top_margin = section.bottom_margin = Cm(1.3)

    base_style = doc.styles["Normal"]
    base_style.font.name = "Calibri"
    base_style.font.size = Pt(10)

    # ── шапка: логотип + название ──
    header = doc.add_paragraph()
    logo_path = _asset_path("acrelis_logo_light.png")
    if os.path.isfile(logo_path):
        header.add_run().add_picture(logo_path, height=Cm(0.85))
        header.add_run("   ")
    name_run = header.add_run("ACRELIS")
    name_run.bold = True
    name_run.font.size = Pt(20)
    name_run.font.color.rgb = IMPULSE_RGB
    header.paragraph_format.space_after = Pt(16)

    # ── таблица: одна организация — одна строка ──
    headers = ["№", "Название", "Адрес", "Телефон", "Почта", "Сайт", "Сфера", "Город"]
    widths_cm = [1.0, 4.2, 5.4, 3.0, 3.8, 3.6, 2.6, 2.4]

    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False

    hdr_cells = table.rows[0].cells
    for i, (title, w) in enumerate(zip(headers, widths_cm)):
        cell = hdr_cells[i]
        cell.width = Cm(w)
        _docx_cell_shading(cell, "F82245")
        _docx_cell_borders(cell)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = WHITE_RGB

    for idx, r in enumerate(results, 1):
        row_cells = table.add_row().cells
        values = [
            str(idx), r.get("name", "") or "—", r.get("address", "") or "—",
            r.get("phone", "") or "—", r.get("email", "") or "—", r.get("site", "") or "—",
            r.get("category", "") or "—", r.get("city", "") or "—",
        ]
        for i, (val, w) in enumerate(zip(values, widths_cm)):
            cell = row_cells[i]
            cell.width = Cm(w)
            _docx_cell_borders(cell)
            if idx % 2 == 0:
                _docx_cell_shading(cell, "F4F5F6")
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(val)
            run.font.size = Pt(9.5)
            run.font.color.rgb = ANTHRA_RGB

    # ── футер ──
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(18)
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    frun = footer.add_run("ACRELIS · acrelis.ru · +7 (843) 210-59-91 · Telegram @acrelis_it")
    frun.font.size = Pt(9)
    frun.font.color.rgb = ASH_RGB

    doc.save(path)


# ══════════════════════════════════════════════════════════════════════════
# Экспорт результатов в Excel — фирменный стиль ACRELIS
# ══════════════════════════════════════════════════════════════════════════

def _build_excel_report(path, results):
    """Собирает .xlsx с результатами поиска.

    Чтобы столбцы гарантированно не наезжали друг на друга при любой длине
    контента (длинные адреса, URL с utm-метками и т.п.) — у каждой колонки
    явная ширина под реальные данные, и на каждой ячейке включён wrap_text:
    текст переносится ВНУТРИ своей ячейки, а не бесконтрольно "вылезает"
    поверх соседней. Высоту строк не фиксируем — Excel сам подгоняет её под
    перенесённый текст при открытии файла.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Организации"
    ws.sheet_view.showGridLines = False

    headers = ["№", "Название", "Адрес", "Телефон", "Почта", "Сайт", "Сфера", "Город"]
    widths = [5, 30, 36, 18, 26, 28, 18, 16]

    header_fill = PatternFill("solid", fgColor="F82245")
    header_font = Font(bold=True, color="FFFFFF", size=11, name="Calibri")
    body_font = Font(size=10, name="Calibri", color="1E2F35")
    thin = Side(border_style="thin", color="D9DCDD")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center_wrap = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_wrap = Alignment(horizontal="left", vertical="center", wrap_text=True)
    alt_fill = PatternFill("solid", fgColor="F4F5F6")

    for col_i, (title, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=col_i, value=title)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_wrap
        cell.border = border
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[1].height = 22

    for r_i, r in enumerate(results, 2):
        values = [
            r_i - 1, r.get("name", "") or "—", r.get("address", "") or "—",
            r.get("phone", "") or "—", r.get("email", "") or "—", r.get("site", "") or "—",
            r.get("category", "") or "—", r.get("city", "") or "—",
        ]
        for col_i, val in enumerate(values, 1):
            cell = ws.cell(row=r_i, column=col_i, value=val)
            cell.font = body_font
            cell.border = border
            cell.alignment = center_wrap if col_i == 1 else left_wrap
            if (r_i - 1) % 2 == 0:  # (r_i - 1) — порядковый номер строки данных, как idx в GUI/Word
                cell.fill = alt_fill

    ws.freeze_panes = "A2"
    wb.save(path)


# ══════════════════════════════════════════════════════════════════════════
# Приложение
# ══════════════════════════════════════════════════════════════════════════
class ParserApp:
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        _load_axiforma_fonts(self.root)  # после создания root — нужен активный Tk для font.families()

        self.root.title("ACRELIS · Поиск организаций без сайта")
        self.root.geometry("1240x760")
        self.root.minsize(1020, 620)
        self.root.configure(fg_color=PAGE_BG)
        try:
            self.root.iconbitmap(_asset_path("acrelis_icon.ico"))
        except Exception:
            pass

        self.worker_thread = None
        self.stop_requested = False
        self.results = []
        self.log_visible = True
        self._combos = []  # для пересинхронизации после старта, см. _resync_combos

        self._setup_treeview_style()
        self._build_ui()

        # CTkComboBox иногда визуально "теряет" текст вскоре после старта mainloop —
        # похоже на конфликт с автоматическим пересчётом DPI-масштаба у CTk сразу после
        # создания окна (сами данные при этом не теряются, виджет просто не перерисован).
        # Не отключаем DPI-awareness совсем (это портит реальный масштаб на экране) —
        # вместо этого один раз досинхронизируем отображение уже после того, как CTk
        # закончит свой internal DPI-пересчёт.
        self.root.after(400, self._resync_combos)

    def _resync_combos(self):
        for combo, variable in self._combos:
            combo.set(variable.get())

    # ---------- Стиль таблицы (ttk — рендерится в обход CTk, шрифт оставляем системный) ----------
    def _setup_treeview_style(self):
        # ttk не подхватывает Axiforma и на не-Windows платформах не знает "Segoe UI" —
        # берём системный шрифт платформы, чтобы кириллица не ломалась.
        tv_font = "Segoe UI" if os.name == "nt" else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")
        tv_font_bold = "Segoe UI Semibold" if os.name == "nt" else tv_font

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Modern.Treeview",
            background=PAGE_BG, foreground=TEXT_PRIMARY, fieldbackground=PAGE_BG,
            rowheight=32, borderwidth=0, font=(tv_font, 10),
        )
        style.configure(
            "Modern.Treeview.Heading",
            background=IMPULSE, foreground="white", font=(tv_font_bold, 10, "bold"),
            borderwidth=0, relief="flat", padding=(10, 9),
        )
        style.map("Modern.Treeview", background=[("selected", "#3A1620")], foreground=[("selected", TEXT_PRIMARY)])
        style.map("Modern.Treeview.Heading", background=[("active", IMPULSE)])
        style.layout("Modern.Treeview", [("Modern.Treeview.treearea", {"sticky": "nswe"})])

    # ---------- Горизонтальная "лента" из сплошных сегментов — фирменный градиент
    # Амарант → Пламя без единой картинки, только штатные CTkFrame: не ломается на разном DPI. ----------
    def _gradient_bar(self, parent, height=3, c1=AMARANTH, c2=FLAME, **pack_kwargs):
        bar = ctk.CTkFrame(parent, fg_color="transparent", height=height)
        bar.pack_propagate(False)
        segments = 28
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        for i in range(segments):
            t = i / (segments - 1)
            color = "#%02X%02X%02X" % (
                round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t), round(b1 + (b2 - b1) * t),
            )
            seg = ctk.CTkFrame(bar, fg_color=color, corner_radius=0)
            seg.pack(side="left", fill="both", expand=True)
        bar.pack(**pack_kwargs)
        return bar

    # ---------- Сборка UI ----------
    # Никакого сайдбара: тёмная шапка → плотный тулбар параметров → строка статуса →
    # таблица (главный элемент, занимает всё оставшееся место) → сворачиваемый журнал → нижняя панель.
    # Низ и журнал пакуются раньше таблицы, чтобы таблица гарантированно забрала весь остаток высоты.
    def _build_ui(self):
        self._build_header()
        self._build_toolbar()
        self._build_bottom_bar()
        self._build_log()
        self._build_status_row()
        self._build_table()

    # ---------- Шапка ----------
    def _build_header(self):
        header = ctk.CTkFrame(self.root, fg_color=HEADER_BG, corner_radius=0)
        header.pack(fill="x")

        row = ctk.CTkFrame(header, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(16, 14))

        icon_box = ctk.CTkFrame(row, width=38, height=38, corner_radius=10, fg_color=ACCENT)
        icon_box.pack(side="left")
        icon_box.pack_propagate(False)
        logo_img = _load_logo_image(size=(19, 19))
        if logo_img is not None:
            ctk.CTkLabel(icon_box, image=logo_img, text="").pack(expand=True)
        else:
            ctk.CTkLabel(icon_box, text="A", font=F(15, "extrabold"), text_color="white").pack(expand=True)

        title_row = ctk.CTkFrame(row, fg_color="transparent")
        title_row.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(title_row, text="ACRELIS", font=F(15, "extrabold"), text_color="white").pack(side="left")
        ctk.CTkLabel(
            title_row, text="   ·   Поиск организаций без сайта", font=F(13), text_color="#9AA6AB",
        ).pack(side="left")

        self.status_dot = ctk.CTkLabel(row, text="●", font=F(10), text_color="#5C6A70")
        self.status_dot.pack(side="right", padx=(0, 7))
        self.status_text = ctk.CTkLabel(row, text="Готов к работе", font=F(12), text_color="#9AA6AB")
        self.status_text.pack(side="right")

        self._gradient_bar(header, height=3, fill="x")

    # ---------- Тулбар параметров поиска (заменяет сайдбар) ----------
    def _build_toolbar(self):
        toolbar = ctk.CTkFrame(self.root, fg_color=PANEL_BG, corner_radius=0)
        toolbar.pack(fill="x")

        inner = ctk.CTkFrame(toolbar, fg_color="transparent")
        inner.pack(fill="x", padx=24, pady=16)
        inner.grid_columnconfigure(0, weight=3)
        inner.grid_columnconfigure(1, weight=3)
        inner.grid_columnconfigure(2, weight=1)

        f1 = ctk.CTkFrame(inner, fg_color="transparent")
        f1.grid(row=0, column=0, sticky="ew", padx=(0, 14))
        self._field_label(f1, "Сфера деятельности")
        self.sphere_var = StringVar(value=SPHERES[0])
        self._combo(f1, self.sphere_var, SPHERES).pack(fill="x")

        f2 = ctk.CTkFrame(inner, fg_color="transparent")
        f2.grid(row=0, column=1, sticky="ew", padx=(0, 14))
        self._field_label(f2, "Город — можно вписать любой")
        self.city_var = StringVar(value="Геленджик")
        self._combo(f2, self.city_var, CITIES).pack(fill="x")

        f3 = ctk.CTkFrame(inner, fg_color="transparent")
        f3.grid(row=0, column=2, sticky="ew")
        self._field_label(f3, "Максимум")
        self.max_var = IntVar(value=60)
        ctk.CTkEntry(
            f3, textvariable=self.max_var, height=36, corner_radius=R_FIELD,
            fg_color=INPUT_BG, border_color=BORDER_STRONG, border_width=1,
            text_color=TEXT_PRIMARY, font=F(12),
        ).pack(fill="x")

        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 0))

        self.only_no_site = BooleanVar(value=True)
        ctk.CTkCheckBox(
            row2, text="Только без сайта", variable=self.only_no_site,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY, border_color=BORDER_STRONG,
            font=F(12), corner_radius=5,
        ).pack(side="left", padx=(0, 22))

        self.headless_var = BooleanVar(value=True)
        ctk.CTkCheckBox(
            row2, text="Скрытый браузер", variable=self.headless_var,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY, border_color=BORDER_STRONG,
            font=F(12), corner_radius=5,
        ).pack(side="left")

        self.start_btn = ctk.CTkButton(
            row2, text="▶   Запустить поиск", command=self.start_search,
            height=38, corner_radius=R_FIELD, width=180,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
            font=F(12, "extrabold"),
        )
        self.start_btn.pack(side="right")

        self.stop_btn = ctk.CTkButton(
            row2, text="■   Остановить", command=self.stop_search,
            height=38, corner_radius=R_FIELD, width=140,
            fg_color="transparent", hover_color=BORDER,
            border_color=BORDER_STRONG, border_width=1, text_color=TEXT_SECONDARY,
            font=F(12, "semibold"), state="disabled",
        )
        self.stop_btn.pack(side="right", padx=(0, 10))

        ctk.CTkFrame(self.root, height=1, fg_color=BORDER).pack(fill="x")

    def _combo(self, parent, variable, values):
        combo = ctk.CTkComboBox(
            parent, values=values, variable=variable, state="normal",
            height=36, corner_radius=R_FIELD,
            fg_color=INPUT_BG, border_color=BORDER_STRONG, border_width=1,
            button_color=INPUT_BG, button_hover_color=BORDER_STRONG,
            dropdown_fg_color=INPUT_BG, dropdown_hover_color="#2A1219",
            text_color=TEXT_PRIMARY, dropdown_text_color=TEXT_PRIMARY,
            font=F(12),
        )
        combo.set(variable.get())
        self._combos.append((combo, variable))  # см. _resync_combos в __init__
        return combo

    def _field_label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text, font=F(10, "semibold"), text_color=TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, 5))

    # ---------- Строка статуса: компактные показатели + прогресс, без больших карточек ----------
    def _build_status_row(self):
        row = ctk.CTkFrame(self.root, fg_color=PAGE_BG)
        row.pack(fill="x", padx=24, pady=(14, 10))

        self.stat_found = self._status_chip(row, "Найдено", "0", AMARANTH)
        self.stat_processed = self._status_chip(row, "Обработано", "0", IMPULSE)
        self.stat_query = self._status_chip(row, "Запрос", "—", GARNET)

        self.progress = ctk.CTkProgressBar(
            row, height=4, corner_radius=2, progress_color=ACCENT, fg_color=BORDER_STRONG,
        )
        self.progress.pack(side="left", fill="x", expand=True, padx=(24, 0))
        self.progress.set(0)

    def _status_chip(self, parent, title, initial, accent):
        chip = ctk.CTkFrame(parent, fg_color="transparent")
        chip.pack(side="left", padx=(0, 26))
        dot = ctk.CTkFrame(chip, width=6, height=6, corner_radius=3, fg_color=accent)
        dot.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(chip, text=title + ":", font=F(11), text_color=TEXT_MUTED).pack(side="left", padx=(0, 5))
        val = ctk.CTkLabel(chip, text=initial, font=F(12, "extrabold"), text_color=TEXT_PRIMARY)
        val.pack(side="left")
        return val

    # ---------- Таблица результатов — главный элемент экрана ----------
    def _build_table(self):
        card = ctk.CTkFrame(self.root, fg_color=PAGE_BG, corner_radius=R_PANEL,
                             border_width=1, border_color=BORDER)
        card.pack(fill="both", expand=True, padx=24, pady=(0, 4))

        cols = ("idx", "name", "address", "phone", "email", "site", "category", "city")
        self.tree = ttk.Treeview(card, columns=cols, show="headings", style="Modern.Treeview")
        headers = {
            "idx": ("№", 46), "name": ("Название", 220), "address": ("Адрес", 250),
            "phone": ("Телефон", 130), "email": ("Почта", 150), "site": ("Сайт", 150),
            "category": ("Сфера", 110), "city": ("Город", 100),
        }
        for col, (title, w) in headers.items():
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="center" if col == "idx" else "w")

        self.tree.tag_configure("odd", background=PAGE_BG)
        self.tree.tag_configure("even", background=TABLE_ROW_ALT)

        vsb = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        vsb.pack(side="right", fill="y", padx=(0, 1), pady=1)

    # ---------- Журнал — тёмная "консоль" внутри светлого приложения, сворачиваемая ----------
    def _build_log(self):
        self.log_card = ctk.CTkFrame(self.root, fg_color=HEADER_BG, corner_radius=R_PANEL,
                                      height=150, border_width=1, border_color=BORDER)
        self.log_card.pack_propagate(False)

        inner = ctk.CTkFrame(self.log_card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=12)

        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(head, text="Журнал", font=F(11, "semibold"), text_color="#9AA6AB").pack(side="left")
        ctk.CTkButton(
            head, text="Очистить", command=self._clear_log,
            width=76, height=22, corner_radius=6,
            fg_color="transparent", hover_color="#1E2A2F",
            border_color="#2C3A40", border_width=1, text_color="#9AA6AB",
            font=F(9),
        ).pack(side="right")

        self.log = ctk.CTkTextbox(
            inner, fg_color=HEADER_BG, text_color=LOG_TEXT,
            font=ctk.CTkFont(family="Consolas", size=10),
            corner_radius=6, border_width=0, wrap="word",
        )
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("ok", foreground="#4ADE80")
        self.log.tag_config("err", foreground="#FF6B7A")
        self.log.tag_config("warn", foreground="#FBBF24")
        self.log.tag_config("dim", foreground=LOG_MUTED)

        if self.log_visible:
            self.log_card.pack(fill="x", side="bottom", padx=24, pady=(0, 10))

    # ---------- Нижняя панель: сворачивание журнала + экспорт ----------
    def _build_bottom_bar(self):
        bar = ctk.CTkFrame(self.root, fg_color=PANEL_BG, height=54, corner_radius=0)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=24)

        self.log_toggle_btn = ctk.CTkButton(
            inner, text="▾   Журнал", command=self._toggle_log,
            width=104, height=30, corner_radius=7,
            fg_color="transparent", hover_color=BORDER,
            border_color=BORDER_STRONG, border_width=1, text_color=TEXT_SECONDARY,
            font=F(11, "semibold"),
        )
        self.log_toggle_btn.pack(side="left", pady=12)

        self.export_word_btn = ctk.CTkButton(
            inner, text="↓   Word", command=self.export_word,
            height=34, corner_radius=R_FIELD, width=110,
            fg_color=INPUT_BG, hover_color=BORDER_STRONG, text_color=TEXT_PRIMARY,
            border_color=BORDER_STRONG, border_width=1,
            font=F(12, "semibold"), state="disabled",
        )
        self.export_word_btn.pack(side="right", pady=10)

        self.export_excel_btn = ctk.CTkButton(
            inner, text="↓   Excel", command=self.export_excel,
            height=34, corner_radius=R_FIELD, width=110,
            fg_color=INPUT_BG, hover_color=BORDER_STRONG, text_color=TEXT_PRIMARY,
            border_color=BORDER_STRONG, border_width=1,
            font=F(12, "semibold"), state="disabled",
        )
        self.export_excel_btn.pack(side="right", padx=(0, 8), pady=10)

        ctk.CTkLabel(inner, text="ACRELIS · acrelis.ru", font=F(10), text_color=TEXT_MUTED
                     ).pack(side="right", padx=(0, 18), pady=12)

    def _toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_card.pack(fill="x", side="bottom", padx=24, pady=(0, 10))
            self.log_toggle_btn.configure(text="▾   Журнал")
        else:
            self.log_card.pack_forget()
            self.log_toggle_btn.configure(text="▸   Журнал")

    # ---------- Поток ----------
    def start_search(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        sphere = self.sphere_var.get().strip()
        city = self.city_var.get().strip()
        if not sphere or not city:
            messagebox.showwarning("Пустые поля", "Укажи сферу и город.")
            return
        try:
            max_n = int(self.max_var.get())
        except Exception:
            max_n = 60

        self.results.clear()
        self.tree.delete(*self.tree.get_children())
        self._clear_log()
        self.stop_requested = False
        self.start_btn.configure(state="disabled", text="▶   Поиск идёт...")
        self.stop_btn.configure(state="normal")
        self.export_word_btn.configure(state="disabled")
        self.export_excel_btn.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status_dot.configure(text_color=ACCENT)
        self.status_text.configure(text="Идёт поиск...")
        self._update_stat(self.stat_found, "0")
        self._update_stat(self.stat_processed, "0")
        self._update_stat(self.stat_query, f"{sphere} · {city}")

        params = dict(
            category=sphere, city=city, max_results=max_n,
            headless=self.headless_var.get(), only_without_site=self.only_no_site.get(),
        )
        self.worker_thread = threading.Thread(target=self._run_worker, args=(params,), daemon=True)
        self.worker_thread.start()

    def stop_search(self):
        self.stop_requested = True
        self._log_safe("⏹ Получен сигнал остановки...")
        self.stop_btn.configure(state="disabled")

    def _run_worker(self, params):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                search_async(
                    log=self._log_safe, on_result=self._add_row_safe,
                    stop_flag=lambda: self.stop_requested, **params,
                )
            )
        except Exception as e:
            self._log_safe(f"❌ ОШИБКА: {e}")
        finally:
            loop.close()
            self.root.after(0, self._finish)

    def _finish(self):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1.0 if self.results else 0)
        self.start_btn.configure(state="normal", text="▶   Запустить поиск")
        self.stop_btn.configure(state="disabled")
        if self.results:
            self.export_word_btn.configure(state="normal")
            self.export_excel_btn.configure(state="normal")
            self.status_dot.configure(text_color=ACCENT_GREEN)
            self.status_text.configure(text=f"Готово · найдено {len(self.results)}")
        else:
            self.status_dot.configure(text_color=TEXT_MUTED)
            self.status_text.configure(text="Готов к работе")

    # ---------- Поток-сейф ----------
    def _log_safe(self, msg):
        self.root.after(0, lambda: self._append_log(msg))

    def _log_tag(self, msg):
        if "ОШИБКА" in msg or "❌" in msg or "не удалось" in msg.lower():
            return "err"
        if "] +" in msg or "Готово" in msg or "✅" in msg:
            return "ok"
        if "⏹" in msg or "остановлен" in msg.lower() or "пропуск" in msg.lower():
            return "warn"
        return "dim"

    def _append_log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert(END, f"[{timestamp}]  ", "dim")
        self.log.insert(END, f"{msg}\n", self._log_tag(msg))
        self.log.see(END)
        if msg.startswith("[") and "/" in msg:
            try:
                cur = msg.split("[")[1].split("/")[0]
                self._update_stat(self.stat_processed, cur)
            except Exception:
                pass

    def _clear_log(self):
        self.log.delete("1.0", END)

    def _add_row_safe(self, data):
        self.root.after(0, lambda: self._add_row(data))

    def _add_row(self, data):
        idx = len(self.results) + 1
        self.results.append(data)
        tag = "even" if idx % 2 == 0 else "odd"
        self.tree.insert(
            "", END,
            values=(
                idx, data.get("name", ""), data.get("address", ""),
                data.get("phone", "") or "—", data.get("email", "") or "—",
                data.get("site", "") or "—", data.get("category", ""), data.get("city", ""),
            ),
            tags=(tag,),
        )
        self._update_stat(self.stat_found, str(idx))

    def _update_stat(self, label, value):
        label.configure(text=value)

    # ---------- Экспорт в Word (фирменный стиль ACRELIS) ----------
    def export_word(self):
        if not self.results:
            return

        default_name = (
            f"acrelis_yandex_{self.sphere_var.get()}_{self.city_var.get()}_"
            f"{datetime.now():%Y%m%d_%H%M}.docx"
        ).replace(" ", "_")
        path = filedialog.asksaveasfilename(
            defaultextension=".docx", filetypes=[("Word", "*.docx")], initialfile=default_name,
        )
        if not path:
            return

        try:
            _build_word_report(path=path, results=self.results)
            messagebox.showinfo("Готово", f"Сохранено:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")

    # ---------- Экспорт в Excel (фирменный стиль ACRELIS) ----------
    def export_excel(self):
        if not self.results:
            return

        default_name = (
            f"acrelis_yandex_{self.sphere_var.get()}_{self.city_var.get()}_"
            f"{datetime.now():%Y%m%d_%H%M}.xlsx"
        ).replace(" ", "_")
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], initialfile=default_name,
        )
        if not path:
            return

        try:
            _build_excel_report(path=path, results=self.results)
            messagebox.showinfo("Готово", f"Сохранено:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")

    def run(self):
        self.root.mainloop()


def main():
    app = ParserApp()
    app.run()


if __name__ == "__main__":
    main()
