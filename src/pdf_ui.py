from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import DND_FILES

import media
from pdf_export import DEFAULT_DPI, PDF_DPI, export_pdf


class PdfPanel:
    def __init__(self, app, tab):
        self.app = app
        self.tab = tab
        self.running = False
        self.source = tk.StringVar()
        self.output = tk.StringVar()
        self.pages = tk.StringVar()
        self.dpi = tk.StringVar(value=str(DEFAULT_DPI))

        ttk.Label(tab, text='PDF 转 PNG', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(tab, text='直接渲染 PDF 页面。600 DPI 适合小字和细表格。',
                  style='Hint.TLabel').grid(row=1, column=0, sticky='w', pady=(4, 8))

        self.source_entry, self.source_button = self.path_field(tab, 2, 'PDF 文件', self.source, self.choose_pdf)
        if app.drag_enabled:
            self.source_entry.drop_target_register(DND_FILES)
            self.source_entry.dnd_bind('<<Drop>>', self.drop_pdf)

        options = ttk.Frame(tab, style='Card.TFrame')
        options.grid(row=3, column=0, sticky='ew', pady=(8, 8))
        options.columnconfigure(3, weight=1)
        ttk.Label(options, text='输出 DPI', style='Card.TLabel').grid(row=0, column=0, padx=(0, 7))
        self.dpi_box = ttk.Combobox(options, textvariable=self.dpi, values=PDF_DPI, width=7, state='readonly')
        self.dpi_box.grid(row=0, column=1, sticky='w', padx=(0, 16))
        ttk.Label(options, text='页码', style='Card.TLabel').grid(row=0, column=2, padx=(0, 7))
        self.pages_entry = ttk.Entry(options, textvariable=self.pages, width=12)
        self.pages_entry.grid(row=0, column=3, sticky='ew')
        ttk.Label(options, text='例 1-3,5 · 留空导出全部', style='Hint.TLabel').grid(
            row=0, column=4, sticky='w', padx=(8, 0))

        self.output_entry, self.output_button = self.path_field(tab, 4, '输出目录', self.output, self.choose_output)
        ttk.Label(tab, text='输出目录留空时，在 PDF 同目录下新建「文件名_PNG」文件夹。',
                  style='Hint.TLabel').grid(row=5, column=0, sticky='w', pady=(4, 8))
        actions = ttk.Frame(tab, style='Card.TFrame')
        actions.grid(row=6, column=0, sticky='w')
        start = ttk.Button(actions, text='导出 PNG', style='Action.TButton', command=self.start)
        start.pack(side='left')
        self.stop_button = ttk.Button(actions, text='停止转换', command=app.stop_conversion, state='disabled')
        self.stop_button.pack(side='left', padx=(app.px(8), 0))
        ttk.Button(actions, text='打开输出目录', command=self.open_output).pack(side='left', padx=(app.px(8), 0))
        app.action_buttons.append(start)

    def path_field(self, parent, row, label, variable, command):
        field = ttk.Frame(parent, style='Card.TFrame')
        field.grid(row=row, column=0, sticky='ew')
        field.columnconfigure(1, weight=1)
        ttk.Label(field, text=label, style='Card.TLabel', width=8).grid(row=0, column=0, sticky='w', padx=(0, 7))
        entry = ttk.Entry(field, textvariable=variable, width=1)
        entry.grid(row=0, column=1, sticky='ew')
        button = ttk.Button(field, text='浏览', command=command)
        button.grid(row=0, column=2, padx=(6, 0))
        return entry, button

    def choose_pdf(self):
        path = filedialog.askopenfilename(parent=self.app.root, title='选择 PDF', filetypes=[('PDF 文件', '*.pdf')])
        if path:
            self.source.set(path)

    def choose_output(self):
        path = filedialog.askdirectory(parent=self.app.root)
        if path:
            self.output.set(path)

    def drop_pdf(self, event):
        if self.running:
            return
        paths = self.app.root.tk.splitlist(event.data)
        if len(paths) == 1:
            self.source.set(paths[0])
        else:
            messagebox.showinfo('选择 PDF', '请一次拖入一份 PDF。', parent=self.app.root)

    def source_path(self):
        if not self.source.get().strip():
            raise ValueError('请先选择 PDF 文件。')
        source = media.clean_path(self.source.get())
        if source.suffix.lower() != '.pdf' or not source.is_file():
            raise ValueError('请选择存在的 PDF 文件。')
        return source

    def output_path(self, source):
        value = self.output.get().strip()
        return media.clean_path(value) if value else source.parent / f'{source.stem}_PNG'

    def open_output(self):
        try:
            output = self.output.get().strip()
            target = media.clean_path(output) if output else self.output_path(self.source_path())
            os.startfile(target)
        except (OSError, ValueError) as exc:
            messagebox.showerror('无法打开目录', str(exc), parent=self.app.root)

    def start(self):
        if self.app.busy:
            return
        try:
            source = self.source_path()
            output = self.output_path(source)
            dpi = int(self.dpi.get())
        except (OSError, ValueError) as exc:
            messagebox.showerror('检查 PDF 设置', str(exc), parent=self.app.root)
            return
        selection = self.pages.get()
        control = media.ToolControl()
        self.edit_state(False)
        self.app.launch('导出 PDF 页面', lambda: export_pdf(
            source, output, dpi, selection, lambda value: self.app.events.put(('progress', value)),
            self.app.log, control), determinate=True, control=control)

    def edit_state(self, enabled):
        self.running = not enabled
        self.stop_button.state(['disabled' if enabled else '!disabled'])
        for widget in (self.source_entry, self.source_button, self.output_entry, self.output_button,
                       self.pages_entry, self.dpi_box):
            widget.state(['!disabled' if enabled else 'disabled'])
