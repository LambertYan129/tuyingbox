from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from PIL import Image, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

import douyin
import media
from conversion_ui import ConversionPanel
from display import Display
from pdf_ui import PdfPanel


BG = '#edf2ef'
SURFACE = '#ffffff'
WELL = '#f5f8f6'
INK = '#142b23'
MUTED = '#4b6358'
ACCENT = '#14654f'
PRESSED = '#0d4939'
PALE = '#d9eee3'
LINE = '#cbd8d1'
FIELD_LINE = '#82978b'
ERROR = '#a92730'
MODULE_DIR = Path(__file__).resolve().parent
ART = (MODULE_DIR if getattr(sys, 'frozen', False) else MODULE_DIR.parent) / 'assets'
IMAGE_TYPES = [('图片', '*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.avif'), ('所有文件', '*.*')]
PLATFORMS = {'X / Twitter': 'twitter', 'Instagram': 'instagram', '抖音图文': 'douyin'}
DEFAULT_DOWNLOAD_DIR = r'%USERPROFILE%\Downloads\图影盒'


class App:
    def __init__(self, root, drag_enabled=True):
        self.root = root
        self.drag_enabled = drag_enabled
        root.title('图影盒 v1.1.4')
        self.display = Display(root)
        self.dpi = self.display.dpi()
        root.tk.call('tk', 'scaling', self.dpi / 72)
        self.set_window_size()
        root.iconbitmap(default=str(ART / 'app.ico'))
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.config_file = media.app_directory() / 'settings.json'
        self.settings = self.read_settings()
        self.output = tk.StringVar(value=self.settings.get('output') or DEFAULT_DOWNLOAD_DIR)
        self.status = tk.StringVar(value='就绪')
        self.progress = tk.DoubleVar()
        self.events = queue.Queue()
        self.busy = False
        self.task_control = None
        self.close_after_task = False
        self.source_images = []
        self.action_buttons = []
        self.workspace_layout = None
        self.density = None
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        self.fonts = {name: font.Font(root=root, family='Microsoft YaHei UI', weight=weight)
                      for name, weight in [('body', 'normal'), ('small', 'normal'),
                                           ('action', 'bold'), ('title', 'bold'), ('brand', 'bold')]}
        self.configure_style()

        self.shell = shell = ttk.Frame(root, padding=self.spacing(24, 16, 24, 12))
        shell.grid(sticky='nsew')
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=4)
        shell.rowconfigure(3, weight=2, minsize=self.px(88))

        header = ttk.Frame(shell)
        header.grid(sticky='ew', pady=(0, self.px(14)))
        header.columnconfigure(3, weight=1)
        self.mark = ttk.Label(header)
        self.mark.grid(row=0, column=0, sticky='w', padx=(0, self.px(10)))
        self.set_mark()
        ttk.Label(header, text='图影盒', style='Brand.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Label(header, text='v1.1.4', style='Muted.TLabel').grid(row=0, column=2, padx=(self.px(8), 0), sticky='s', pady=(0, self.px(4)))
        self.cookie_button = ttk.Button(header, text='Cookies 设置', command=self.edit_cookies)
        self.cookie_button.grid(row=0, column=4, sticky='e')

        self.tabs = ttk.Notebook(shell)
        self.tabs.grid(row=1, column=0, sticky='nsew')
        self.add_images_tab(self.add_tab('下载图片'))
        self.add_video_tab(self.add_tab('下载视频'))
        self.add_collage_tab(self.add_tab('编辑图片'))
        self.conversion = ConversionPanel(self, self.add_tab('格式转换'))
        self.pdf = PdfPanel(self, self.add_tab('PDF 转 PNG'))
        self.tabs.enable_traversal()
        self.tabs.bind('<<NotebookTabChanged>>', self.layout_workarea)

        self.cookie_panel = self.create_cookie_panel(shell)
        self.cookie_panel.grid(row=1, column=0, sticky='nsew')
        self.cookie_panel.grid_remove()
        root.bind('<Escape>', self.close_cookie_panel, add='+')

        folder = self.download_controls = ttk.Frame(shell)
        folder.grid(row=2, column=0, sticky='ew', pady=(self.px(12), self.px(10)))
        folder.columnconfigure(1, weight=1)
        ttk.Label(folder, text='下载目录').grid(row=0, column=0, padx=(0, 9))
        ttk.Entry(folder, textvariable=self.output, width=1).grid(row=0, column=1, sticky='ew')
        ttk.Button(folder, text='浏览', command=self.browse_output).grid(row=0, column=2, padx=(8, 5))
        ttk.Button(folder, text='打开目录', command=self.open_output).grid(row=0, column=3)

        self.log_panel = logs = ttk.LabelFrame(shell, text='任务日志', style='Log.TLabelframe',
                                               padding=self.spacing(8, 4))
        logs.grid(row=3, column=0, sticky='nsew')
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log_view = tk.Text(logs, height=3, width=1, font=self.fonts['small'], wrap='word', bg=SURFACE, fg=INK,
                                relief='flat', padx=self.px(8), pady=self.px(4), state='disabled', highlightthickness=0,
                                selectbackground=PALE, selectforeground=INK)
        self.log_view.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(logs, command=self.log_view.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.log_view.configure(yscrollcommand=scroll.set)

        footer = ttk.Frame(shell)
        footer.grid(row=4, column=0, sticky='ew', pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(footer, textvariable=self.status, style='Muted.TLabel', wraplength=650)
        self.status_label.grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.bar = ttk.Progressbar(footer, length=self.px(136), maximum=100, variable=self.progress)
        self.bar.grid(row=0, column=1, sticky='e')
        footer.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(self.px(120), event.width - self.px(152))))
        if not self.drag_enabled:
            self.log('当前环境无法启用拖放，可使用文件选择按钮。')
        root.after_idle(self.layout_workarea)
        root.after(80, self.poll)

    def px(self, value):
        return round(value * self.dpi / 96)

    def spacing(self, *values):
        return tuple(self.px(value) for value in values)

    def set_window_size(self, width=1000, height=700):
        work_width, work_height = self.display.work_size()
        max_width = max(1, work_width - self.px(24))
        max_height = max(1, work_height - self.px(48))
        self.root.minsize(min(self.px(720), max_width), min(self.px(570), max_height))
        if self.root.state() not in ('zoomed', 'iconic'):
            self.root.geometry(f'{min(self.px(width), max_width)}x{min(self.px(height), max_height)}')

    def set_mark(self):
        with Image.open(ART / 'app.png') as source:
            size = self.px(38)
            mark = source.resize((size, size), Image.Resampling.LANCZOS)
        self.brand_photo = ImageTk.PhotoImage(mark, master=self.root)
        self.mark.configure(image=self.brand_photo)

    def refresh_display(self):
        dpi = self.display.dpi()
        if dpi == self.dpi:
            return
        root = self.root
        width = round(root.winfo_width() * 96 / self.dpi)
        height = round(root.winfo_height() * 96 / self.dpi)
        self.dpi = dpi
        root.tk.call('tk', 'scaling', dpi / 72)
        self.configure_style()
        self.style.configure('Conversion.Treeview', rowheight=self.px(23))
        self.conversion.tree.column('state', width=self.px(108), minwidth=self.px(96))
        self.log_panel.configure(padding=self.spacing(8, 4))
        self.preview_canvas.configure(width=self.px(136))
        for name in self.tabs.tabs():
            self.tabs.nametowidget(name).configure(padding=self.spacing(20, 14, 20, 14))
        self.cookie_panel.configure(padding=self.spacing(20, 14, 20, 14))
        self.bar.configure(length=self.px(136))
        self.set_mark()
        self.set_window_size(width, height)
        root.after_idle(self.layout_workarea)

    def configure_style(self):
        for name, size in [('body', 14), ('small', 12), ('action', 14), ('title', 19), ('brand', 25)]:
            self.fonts[name].configure(size=-self.px(size))
        style = self.style
        style.configure('.', background=BG, foreground=INK, font=self.fonts['body'], focuscolor=ACCENT)
        style.configure('TButton', width=0, padding=self.spacing(11, 5), background=SURFACE, borderwidth=1,
                        lightcolor=SURFACE, darkcolor=SURFACE, bordercolor=FIELD_LINE, focusthickness=2)
        style.map('TButton', background=[('pressed', PALE), ('active', WELL)],
                  bordercolor=[('disabled', LINE), ('focus', ACCENT), ('active', ACCENT)],
                  foreground=[('disabled', MUTED)])
        style.configure('Action.TButton', background=ACCENT, foreground='white', bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT, focuscolor='white', focusthickness=2,
                        font=self.fonts['action'], padding=self.spacing(16, 7))
        style.map('Action.TButton', background=[('disabled', PALE), ('pressed', PRESSED), ('active', '#105540')],
                  bordercolor=[('disabled', LINE), ('active', PRESSED)], foreground=[('disabled', MUTED)])
        style.configure('Brand.TLabel', font=self.fonts['brand'], foreground=INK)
        style.configure('Title.TLabel', font=self.fonts['title'], background=SURFACE)
        style.configure('Muted.TLabel', foreground=MUTED, font=self.fonts['small'])
        style.configure('Card.TFrame', background=SURFACE)
        style.configure('Card.TLabel', background=SURFACE)
        style.configure('Hint.TLabel', background=SURFACE, foreground=MUTED, font=self.fonts['small'])
        style.configure('CookieError.TLabel', background=SURFACE, foreground=ERROR)
        for toggle in ('Card.TCheckbutton', 'Card.TRadiobutton'):
            style.configure(toggle, background=SURFACE, indicatorsize=self.px(13),
                            indicatormargin=self.spacing(2, 2, 6, 2), indicatorforeground=ACCENT,
                            upperbordercolor=FIELD_LINE, lowerbordercolor=FIELD_LINE)
            style.map(toggle, background=[('active', SURFACE)], indicatorbackground=[('selected', PALE)])
        style.configure('TNotebook', background=BG, borderwidth=1, bordercolor=LINE,
                        lightcolor=LINE, darkcolor=LINE, padding=0, tabmargins=(0, 0, 0, 0))
        style.configure('TNotebook.Tab', background=BG, padding=self.spacing(19, 8), borderwidth=1,
                        lightcolor=BG, darkcolor=BG, bordercolor=BG)
        style.map('TNotebook.Tab', background=[('selected', PALE), ('active', WELL)],
                  foreground=[('selected', PRESSED)], expand=[('selected', (0, 0, 0, 0))],
                  padding=[('selected', self.spacing(19, 8))])
        for field in ('TEntry', 'TCombobox'):
            style.configure(field, padding=self.spacing(8, 5), fieldbackground=SURFACE,
                            bordercolor=FIELD_LINE, lightcolor=SURFACE, darkcolor=SURFACE,
                            selectbackground=PALE, selectforeground=INK, insertcolor=INK)
            style.map(field, bordercolor=[('focus', ACCENT)], fieldbackground=[('readonly', SURFACE)])
        style.configure('TCombobox', arrowsize=self.px(14), arrowcolor=INK, background=WELL)
        style.configure('Log.TLabelframe', borderwidth=1, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        style.configure('Log.TLabelframe.Label', foreground=MUTED, font=self.fonts['small'])
        style.configure('Vertical.TScrollbar', gripcount=0, arrowsize=self.px(10), background=LINE,
                        troughcolor=WELL, lightcolor=LINE, darkcolor=LINE, bordercolor=WELL)
        style.configure('Horizontal.TProgressbar', background=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                        troughcolor=LINE, bordercolor=LINE, borderwidth=0)

    def add_tab(self, name):
        tab = ttk.Frame(self.tabs, style='Card.TFrame', padding=self.spacing(20, 14, 20, 14))
        self.tabs.add(tab, text=name)
        tab.columnconfigure(0, weight=1)
        return tab

    def layout_workarea(self, _event=None):
        compact = 1 < self.root.winfo_height() < self.px(580)
        density = (self.dpi, compact)
        if density != self.density:
            self.density = density
            self.shell.configure(padding=self.spacing(24, 10 if compact else 16, 24, 8 if compact else 12))
            self.shell.rowconfigure(3, minsize=self.px(48 if compact else 88))
            self.video_text.configure(height=2 if compact else 4)
            self.preview_canvas.configure(height=self.px(104 if compact else 152))
            for index, field in enumerate(self.twitter_options.winfo_children()):
                row, column = (0, index) if compact else (index % 2, index // 2)
                field.grid_configure(row=row, column=column, padx=(0, self.px(14)), pady=(3 if row else 0, 0))
        if self.cookie_panel.winfo_manager():
            if self.workspace_layout != ('cookies',):
                self.workspace_layout = ('cookies',)
                self.shell.rowconfigure(1, weight=0)
            return
        selected = self.tabs.select()
        panel = self.tabs.nametowidget(selected)
        converting = panel is self.conversion.tab
        layout = (selected, panel.winfo_reqheight(), density)
        if self.workspace_layout == layout:
            return
        self.workspace_layout = layout
        editing_images = self.tabs.tab(selected, 'text') == '编辑图片'
        if converting or panel is self.pdf.tab:
            self.download_controls.grid_remove()
        else:
            self.download_controls.grid()
            self.download_controls.grid_configure(pady=self.spacing(7, 6) if compact else self.spacing(12, 10))
        self.shell.rowconfigure(1, weight=4 if editing_images or converting else 0)
        self.shell.rowconfigure(3, weight=1 if converting else 2)
        self.tabs.configure(height=layout[1])

    def action(self, parent, text, callback, row):
        button = ttk.Button(parent, text=text, style='Action.TButton', command=callback)
        button.grid(row=row, column=0, sticky='w', pady=(9, 0))
        self.action_buttons.append(button)
        return button

    def add_images_tab(self, tab):
        source = ttk.Frame(tab, style='Card.TFrame')
        source.grid(row=0, column=0, sticky='w', pady=(0, 2))
        ttk.Label(source, text='图片来源', style='Title.TLabel').pack(side='left', padx=(0, self.px(16)))
        self.platform = tk.StringVar(value='X / Twitter')
        platform = ttk.Combobox(source, textvariable=self.platform, values=list(PLATFORMS), state='readonly', width=20)
        platform.pack(side='left')
        platform.bind('<<ComboboxSelected>>', self.update_image_form)
        self.image_raw = {key: tk.StringVar() for key in PLATFORMS.values()}
        self.image_label = ttk.Label(tab, style='Card.TLabel')
        self.image_label.grid(row=2, column=0, sticky='w', pady=(10, 3))
        self.image_entry = ttk.Entry(tab, width=1)
        self.image_entry.grid(row=3, column=0, sticky='ew')
        self.twitter_options = ttk.Frame(tab, style='Card.TFrame')
        self.twitter_options.grid(row=4, column=0, sticky='w', pady=(9, 0))
        self.since = tk.StringVar()
        self.limit = tk.StringVar(value='50')
        ttk.Label(self.twitter_options, text='起始日期（可选，YYYY-MM-DD）', style='Card.TLabel').grid(
            row=0, column=0, sticky='w', padx=(0, self.px(20)))
        ttk.Entry(self.twitter_options, width=16, textvariable=self.since).grid(row=1, column=0, sticky='w', pady=(3, 0))
        ttk.Label(self.twitter_options, text='最多图片数', style='Card.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Entry(self.twitter_options, width=8, textvariable=self.limit).grid(row=1, column=1, sticky='w', pady=(3, 0))
        self.image_action = self.action(tab, '下载图片', self.start_image, 5)
        self.update_image_form()

    def update_image_form(self, event=None):
        site = PLATFORMS[self.platform.get()]
        labels = {'twitter': '账号、主页或帖子链接', 'instagram': 'Instagram 帖子或 Reel 链接（保存其中的图片和视频）',
                  'douyin': '抖音图文链接或分享文案'}
        self.image_label.configure(text=labels[site])
        self.image_action.configure(text='下载图片和视频' if site == 'instagram' else '下载图片')
        self.image_entry.configure(textvariable=self.image_raw[site])
        if site == 'twitter':
            self.twitter_options.grid()
        else:
            self.twitter_options.grid_remove()
        self.root.after_idle(self.layout_workarea)

    def add_video_tab(self, tab):
        ttk.Label(tab, text='视频链接', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(tab, text='YouTube、X / Twitter、哔哩哔哩、抖音、Instagram · 一行一个链接',
                  style='Hint.TLabel').grid(row=1, column=0, sticky='w', pady=(3, 7))
        self.video_text = tk.Text(tab, height=4, width=1, wrap='word', undo=True, font=self.fonts['body'],
                                  fg=INK, bg=SURFACE, insertbackground=INK, selectbackground=PALE, selectforeground=INK,
                                  highlightthickness=1, highlightbackground=FIELD_LINE,
                                  highlightcolor=ACCENT, relief='flat', padx=self.px(8), pady=self.px(6))
        self.video_text.grid(row=2, column=0, sticky='ew')
        self.playlist = tk.BooleanVar()
        ttk.Checkbutton(tab, text='允许下载完整播放列表', variable=self.playlist,
                        style='Card.TCheckbutton').grid(row=3, column=0, sticky='w', pady=(7, 0))
        self.action(tab, '下载视频', self.start_video, 4)

    def add_collage_tab(self, tab):
        tab.rowconfigure(2, weight=1)
        ttk.Label(tab, text='拼图', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        caption = '以第一张图为尺寸基准。'
        if self.drag_enabled:
            caption += '可拖入图片。'
        ttk.Label(tab, text=caption,
                  style='Hint.TLabel').grid(row=1, column=0, sticky='w', pady=(3, 8))
        content = ttk.Frame(tab, style='Card.TFrame')
        content.grid(row=2, column=0, sticky='nsew')
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        order = ttk.Frame(content, style='Card.TFrame')
        order.grid(row=0, column=0, sticky='nsew', padx=(0, self.px(16)))
        order.columnconfigure(0, weight=1)
        order.rowconfigure(1, weight=1)
        ttk.Label(order, text='图片顺序', style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 5))
        self.image_list = tk.Listbox(order, width=25, height=4, selectmode='browse', exportselection=False,
                                     font=self.fonts['body'], fg=INK, bg=SURFACE, selectbackground=PALE,
                                     selectforeground=INK, relief='flat', highlightthickness=1,
                                     highlightbackground=FIELD_LINE, highlightcolor=ACCENT)
        self.image_list.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(order, command=self.image_list.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        self.image_list.configure(yscrollcommand=scroll.set)
        if self.drag_enabled:
            self.image_list.drop_target_register(DND_FILES)
            self.image_list.dnd_bind('<<Drop>>', lambda event: self.add_images(self.root.tk.splitlist(event.data)))
        controls = ttk.Frame(order, style='Card.TFrame')
        controls.grid(row=2, column=0, columnspan=2, sticky='w', pady=(7, 0))
        ttk.Button(controls, text='添加图片', command=self.browse_images).pack(side='left', padx=(0, 6))
        ttk.Button(controls, text='上移', command=lambda: self.change_image(-1)).pack(side='left', padx=(0, 4))
        ttk.Button(controls, text='下移', command=lambda: self.change_image(1)).pack(side='left', padx=(0, 4))
        ttk.Button(controls, text='移除', command=lambda: self.change_image(0)).pack(side='left')
        direction = ttk.Frame(order, style='Card.TFrame')
        direction.grid(row=3, column=0, columnspan=2, sticky='w', pady=(7, 0))
        self.direction = tk.StringVar(value='竖向')
        ttk.Radiobutton(direction, text='竖向 ↓', variable=self.direction, value='竖向',
                        style='Card.TRadiobutton').pack(side='left', padx=(0, 14))
        ttk.Radiobutton(direction, text='横向 →', variable=self.direction, value='横向',
                        style='Card.TRadiobutton').pack(side='left')

        preview = ttk.Frame(content, style='Card.TFrame')
        preview.grid(row=0, column=1, sticky='nsew')
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=1)
        ttk.Label(preview, text='拼图预览', style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 5))
        self.preview_canvas = tk.Canvas(preview, width=self.px(136), height=self.px(152), bg=WELL,
                                        highlightthickness=1, highlightbackground=LINE)
        self.preview_canvas.grid(row=1, column=0, sticky='nsew')
        self.preview_info = tk.StringVar()
        ttk.Label(preview, textvariable=self.preview_info, style='Hint.TLabel').grid(
            row=2, column=0, sticky='w', pady=(5, 0))
        self.preview_photo = None
        self.preview_serial = 0
        self.preview_timer = None
        self.preview_running = False
        self.preview_canvas.bind('<Configure>', self.request_preview)
        self.direction.trace_add('write', self.request_preview)
        self.action(tab, '生成 PNG', self.start_collage, 3)

    def read_settings(self):
        try:
            data = json.loads(self.config_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        output = data.get('output')
        cookies = data.get('cookies')
        return {
            'output': output if isinstance(output, str) else '',
            'cookies': {site: path for site, path in cookies.items() if site in media.SITES and isinstance(path, str)}
            if isinstance(cookies, dict) else {},
        }

    def save_settings(self):
        with media.output_file(self.config_file, overwrite=True) as temporary:
            temporary.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf-8')

    def create_cookie_panel(self, parent):
        body = ttk.Frame(parent, style='Card.TFrame', padding=self.spacing(20, 14, 20, 14))
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text='Cookies 设置', style='Title.TLabel').grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(body, text='导出时请选择 Netscape（.txt）。JSON 和 Header String 不支持。',
                  style='Hint.TLabel').grid(row=1, column=0, columnspan=3, sticky='w', pady=(3, 8))
        self.cookie_paths = {}
        self.cookie_error = tk.StringVar(master=self.root)
        for row, (site, (label, _)) in enumerate(media.SITES.items(), 2):
            variable = self.cookie_paths[site] = tk.StringVar(master=self.root)
            ttk.Label(body, text=label, style='Card.TLabel').grid(row=row, column=0, padx=(0, 10), pady=3, sticky='w')
            entry = ttk.Entry(body, textvariable=variable, width=1)
            entry.grid(row=row, column=1, sticky='ew')
            if row == 2:
                self.first_cookie_entry = entry
            ttk.Button(body, text='浏览', command=lambda var=variable: self.browse_cookie(var)).grid(
                row=row, column=2, padx=(8, 0))

        controls = ttk.Frame(body, style='Card.TFrame')
        controls.grid(row=len(media.SITES) + 2, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        controls.columnconfigure(0, weight=1)
        error = ttk.Label(controls, textvariable=self.cookie_error, style='CookieError.TLabel', wraplength=460)
        error.grid(row=0, column=0, sticky='w', padx=(0, 12))
        controls.bind('<Configure>', lambda event: error.configure(wraplength=max(self.px(100), event.width - self.px(210))))
        ttk.Button(controls, text='取消', command=self.close_cookie_panel).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(controls, text='保存设置', style='Action.TButton', command=self.save_cookies).grid(row=0, column=2)
        return body

    def edit_cookies(self):
        cookies = self.settings.get('cookies', {})
        for site, variable in self.cookie_paths.items():
            variable.set(cookies.get(site, ''))
        self.cookie_error.set('')
        self.tabs.grid_remove()
        self.download_controls.grid_remove()
        self.cookie_button.grid_remove()
        self.cookie_panel.grid()
        self.layout_workarea()
        self.first_cookie_entry.focus_set()

    def close_cookie_panel(self, event=None):
        if not self.cookie_panel.winfo_manager():
            return
        self.cookie_panel.grid_remove()
        self.tabs.grid()
        self.density = None
        self.cookie_button.grid()
        self.layout_workarea()
        self.cookie_button.focus_set()
        return 'break'

    def save_cookies(self):
        previous = self.settings.copy()
        try:
            paths = {site: media.cookie_path(var.get(), site) for site, var in self.cookie_paths.items()}
            self.settings['cookies'] = {site: str(path) for site, path in paths.items() if path}
            self.save_settings()
        except (OSError, ValueError) as exc:
            self.settings = previous
            self.cookie_error.set(str(exc))
            return
        self.close_cookie_panel()

    def browse_cookie(self, variable):
        path = filedialog.askopenfilename(parent=self.root, title='选择 Cookies 文件',
                                          filetypes=[('Cookies 文本', '*.txt'), ('所有文件', '*.*')])
        if path:
            variable.set(path)

    def browse_output(self):
        path = filedialog.askdirectory(parent=self.root)
        if path:
            self.output.set(path)

    def download_folder(self):
        value = self.output.get().strip()
        if not value:
            raise ValueError('请选择下载目录。')
        path = Path.home() / 'Downloads' / '图影盒' if value == DEFAULT_DOWNLOAD_DIR else media.clean_path(value)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def open_output(self):
        try:
            os.startfile(self.download_folder())
        except (OSError, ValueError) as exc:
            messagebox.showerror('无法打开目录', str(exc), parent=self.root)

    def browse_images(self):
        self.add_images(filedialog.askopenfilenames(parent=self.root, filetypes=IMAGE_TYPES))

    def add_images(self, paths):
        count = len(self.source_images)
        for path in paths:
            source = Path(path)
            if source.is_file():
                self.source_images.append(source)
                self.image_list.insert('end', source.name)
        if len(self.source_images) != count:
            self.request_preview()

    def change_image(self, offset):
        selection = self.image_list.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + offset
        if not 0 <= target < len(self.source_images):
            return
        source = self.source_images.pop(index)
        self.image_list.delete(index)
        if offset:
            self.source_images.insert(target, source)
            self.image_list.insert(target, source.name)
            self.image_list.selection_set(target)
        self.request_preview()

    def request_preview(self, *_args):
        self.preview_serial += 1
        if self.preview_timer is not None:
            self.root.after_cancel(self.preview_timer)
            self.preview_timer = None
        if not self.source_images:
            self.show_preview_message('添加图片后显示预览')
        elif not self.preview_running:
            self.preview_info.set('正在生成预览…')
            self.preview_timer = self.root.after(80, self.build_preview)

    def show_preview_message(self, message):
        canvas = self.preview_canvas
        canvas.delete('all')
        self.preview_photo = None
        canvas.create_text(canvas.winfo_width() // 2, canvas.winfo_height() // 2,
                           text=message, font=self.fonts['body'], fill=MUTED, justify='center',
                           width=max(1, canvas.winfo_width() - self.px(24)))
        self.preview_info.set('')

    def build_preview(self):
        self.preview_timer = None
        self.preview_running = True
        serial = self.preview_serial
        horizontal = self.direction.get() == '横向'
        sources = tuple(self.source_images)
        bounds = (max(1, self.preview_canvas.winfo_width() - self.px(20)),
                  max(1, self.preview_canvas.winfo_height() - self.px(20)))

        def run():
            try:
                image, final_size = media.preview_collage(sources, horizontal, bounds)
            except Exception as exc:
                self.events.put(('preview', (serial, None, None, str(exc))))
            else:
                self.events.put(('preview', (serial, image, final_size, None)))

        threading.Thread(target=run, daemon=True).start()

    def display_preview(self, serial, image, final_size, error):
        self.preview_running = False
        if serial != self.preview_serial:
            if image is not None:
                image.close()
            self.request_preview()
            return
        if image is None:
            self.show_preview_message(f'无法预览：{error}')
            return
        canvas = self.preview_canvas
        with image:
            photo = ImageTk.PhotoImage(image, master=self.root)
        canvas.delete('all')
        self.preview_photo = photo
        canvas.create_image(canvas.winfo_width() // 2, canvas.winfo_height() // 2, image=photo)
        width, height = final_size
        self.preview_info.set(f'成品尺寸 {width} × {height} px')

    def log(self, text):
        self.events.put(('log', text))

    def start_image(self):
        site = PLATFORMS[self.platform.get()]
        value = self.image_raw[site].get().strip()
        try:
            if site == 'twitter':
                media.twitter_target(value)
            else:
                media.site_url(value, (site,))
            cookie = media.cookie_path(self.settings.get('cookies', {}).get(site, ''), site)
            target = self.download_folder()
        except (OSError, ValueError) as exc:
            messagebox.showerror('检查下载设置', str(exc), parent=self.root)
            return
        since, limit = self.since.get().strip(), self.limit.get().strip()
        if site == 'douyin':
            self.launch('下载抖音图文', lambda: douyin.download_note(value, target, cookie, self.log), download=target)
        else:
            label = '下载 Instagram 帖子媒体' if site == 'instagram' else '下载 X / Twitter 图片'
            self.launch(label,
                        lambda: media.download_gallery(site, value, target, cookie, since, limit, self.log),
                        download=target)

    def start_video(self):
        raw = self.video_text.get('1.0', 'end').strip()
        if not raw:
            messagebox.showerror('缺少链接', '请输入至少一个视频链接。', parent=self.root)
            return
        try:
            target = self.download_folder()
        except (OSError, ValueError) as exc:
            messagebox.showerror('检查下载设置', str(exc), parent=self.root)
            return
        cookies = {site: self.settings.get('cookies', {}).get(site, '') for site in media.VIDEO_SITES}
        playlist = self.playlist.get()
        self.launch('下载视频', lambda: media.download_video(raw, target, cookies, playlist,
                    douyin.download_video_from_page, self.log), download=target)

    def start_collage(self):
        sources = tuple(self.source_images)
        if not sources:
            messagebox.showerror('缺少图片', '请先添加图片。', parent=self.root)
            return
        direction = self.direction.get()
        name = f'拼图_{direction}_{datetime.now():%Y%m%d_%H%M%S}.png'
        path = filedialog.asksaveasfilename(parent=self.root, initialdir=sources[0].parent,
                                           initialfile=name, defaultextension='.png', filetypes=[('PNG 图片', '*.png')])
        if path:
            target = media.clean_path(path)
            if target.suffix.lower() != '.png' or target in sources:
                messagebox.showerror('文件无效', '请选择独立的 .png 输出路径。', parent=self.root)
                return
            existed = target.exists()
            self.launch('拼接图片', lambda: media.join_images(sources, direction == '横向', target, existed, self.log))

    def launch(self, label, operation, *, download=None, determinate=False, control=None):
        if self.busy:
            return
        if download:
            self.settings['output'] = DEFAULT_DOWNLOAD_DIR if self.output.get().strip() == DEFAULT_DOWNLOAD_DIR else str(download)
            try:
                self.save_settings()
            except OSError:
                self.log('无法保存下载目录设置，本次任务仍可继续。')
        self.busy = True
        self.task_control = control
        for button in self.action_buttons:
            button.state(['disabled'])
        self.status.set(f'正在{label}…')
        self.progress.set(0)
        self.bar.configure(mode='determinate' if determinate else 'indeterminate')
        if not determinate:
            self.bar.start(12)
        self.log(f'[{datetime.now():%H:%M:%S}] {label}')

        def run():
            try:
                result = operation()
            except media.TaskCancelled as exc:
                self.events.put(('cancelled', str(exc)))
            except Exception as exc:
                self.events.put(('error', str(exc) or type(exc).__name__))
            else:
                self.events.put(('done', result))

        threading.Thread(target=run, daemon=True).start()

    def stop_conversion(self):
        if self.task_control is None or self.task_control.cancelled.is_set():
            return
        for panel in (self.conversion, self.pdf):
            if panel.running:
                panel.stop_button.state(['disabled'])
        self.status.set('正在停止转换…')
        try:
            self.task_control.cancel()
        except OSError as exc:
            self.log(f'结束转换进程时出错 · {exc}')

    def poll(self):
        self.refresh_display()
        self.layout_workarea()
        # 每次只处理有限事件，日志输出很密集时也能响应 UI 操作。
        for _ in range(150):
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == 'progress':
                self.progress.set(value)
                continue
            if event == 'preview':
                self.display_preview(*value)
                continue
            if event == 'conversion_probe':
                self.conversion.apply_probe(*value)
                continue
            if event == 'conversion_row':
                self.conversion.apply_row(*value)
                continue
            if event in ('done', 'error', 'cancelled'):
                self.busy = False
                self.task_control = None
                if self.close_after_task:
                    self.root.destroy()
                    return
                for panel in (self.conversion, self.pdf):
                    if panel.running:
                        panel.edit_state(True)
                self.bar.stop()
                self.bar.configure(mode='determinate')
                self.progress.set(100 if event == 'done' else 0)
                for button in self.action_buttons:
                    button.state(['!disabled'])
                status = {'done': '任务完成，详情见日志。', 'error': '任务失败，详情见日志。',
                          'cancelled': '转换已停止。'}
                self.status.set(status[event])
                if event != 'cancelled':
                    value = ('错误 · ' if event == 'error' else '完成 · ') + value
            self.log_view.configure(state='normal')
            self.log_view.insert('end', value + '\n')
            if int(self.log_view.index('end-1c').split('.')[0]) > 1500:
                self.log_view.delete('1.0', '100.0')
            self.log_view.see('end')
            self.log_view.configure(state='disabled')
        self.root.after(80, self.poll)

    def close(self):
        if not self.busy:
            self.root.destroy()
        elif self.task_control is None:
            messagebox.showinfo('任务运行中', '请等待当前任务结束后关闭。', parent=self.root)
        elif self.close_after_task:
            self.root.destroy()
        elif messagebox.askyesno('停止转换并退出', '停止当前转换并关闭图影盒？已完成的文件会保留。',
                                 parent=self.root, default='no'):
            if not self.busy:
                self.root.destroy()
                return
            self.close_after_task = True
            self.stop_conversion()
            self.root.after(8000, self.root.destroy)


def main(report_error):
    # 建立完 Tk 根窗口后才加载可选拖放库，加载失败时保留同一个窗口。
    root = tk.Tk()
    try:
        TkinterDnD._require(root)
    except RuntimeError:
        drag_enabled = False
    else:
        drag_enabled = True

    def callback_error(kind, value, details):
        info = report_error(kind, value, details)
        messagebox.showerror('操作失败', info, parent=root)

    root.report_callback_exception = callback_error
    App(root, drag_enabled)
    root.mainloop()
    return 0
