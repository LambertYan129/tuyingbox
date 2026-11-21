from __future__ import annotations

import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import DND_FILES

import conversion
import media


MODES = {'视频格式转换': 'video', '视频变速': 'speed', '提取视频音频': 'extract',
         '音频格式转换': 'audio', '网易云音乐 NCM': 'ncm', '图片格式转换': 'image'}
FIXED_RATE = '固定倍率'
FIXED_DURATION = '固定时长'
SCALES = {'100%': 1, '75%': 0.75, '25%': 0.25}
ROTATIONS = {'不旋转': 0, '向左 90°': 90, '向右 90°': -90}


class ConversionPanel:
    def __init__(self, app, tab):
        self.app = app
        self.root = app.root
        self.tab = tab
        self.queue = {}
        self.details = {}
        self.running = False
        self.probe_serial = 0
        self.probe_job = None
        self.info = None
        self.labels = {}
        self.mode_var = tk.StringVar(value=next(iter(MODES)))
        self.format_var = tk.StringVar(value='MP4')
        self.encode_var = tk.StringVar(value='自动')
        self.quality_var = tk.StringVar(value='标准')
        self.speed_mode = tk.StringVar(value=FIXED_RATE)
        self.speed_rate = tk.StringVar(value='1.5')
        self.speed_duration = tk.StringVar()
        self.track_var = tk.StringVar(value='第 1 条')
        self.scale_var = tk.StringVar(value='100%')
        self.rotation_var = tk.StringVar(value='不旋转')
        self.directory = tk.StringVar()
        self.hint = tk.StringVar()
        self.detail = tk.StringVar()

        form = ttk.Frame(tab, style='Card.TFrame')
        form.grid(row=0, column=0, sticky='ew')
        self.mode_box = self.combo(form, '任务', self.mode_var, tuple(MODES), 0, 0, 16)
        self.mode_box.bind('<<ComboboxSelected>>', self.change_mode)
        self.format_box = self.combo(form, '输出格式', self.format_var, conversion.VIDEO_FORMATS, 0, 2, 19)
        self.format_box.bind('<<ComboboxSelected>>', self.form_changed)
        self.options = ttk.Frame(tab, style='Card.TFrame')
        self.options.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        self.kind = self.combo(self.options, '封装方式', self.encode_var, ('自动', '仅无损封装', '重新编码'), 0, 0, 15)
        self.kind.bind('<<ComboboxSelected>>', self.form_changed)
        self.quality = self.combo(self.options, '质量', self.quality_var, tuple(conversion.QUALITY), 0, 2, 18)
        self.speed_box = self.combo(self.options, '变速方式', self.speed_mode, (FIXED_RATE, FIXED_DURATION), 0, 0, 10)
        self.speed_box.bind('<<ComboboxSelected>>', self.form_changed)
        self.speed_label = ttk.Label(self.options, text='倍率', style='Card.TLabel')
        self.speed_entry = ttk.Entry(self.options, textvariable=self.speed_rate, width=13)
        self.speed_quality = self.combo(self.options, '质量', self.quality_var, tuple(conversion.QUALITY), 0, 4, 18)
        self.speed_rate.trace_add('write', self.update_hint)
        self.speed_duration.trace_add('write', self.update_hint)
        self.track_label = ttk.Label(self.options, text='音轨', style='Card.TLabel')
        self.track_box = ttk.Combobox(self.options, textvariable=self.track_var, width=24, state='readonly',
                                     values=('第 1 条',))
        self.scale = self.combo(self.options, '等比缩放', self.scale_var, tuple(SCALES), 0, 0, 8)
        self.rotation = self.combo(self.options, '旋转', self.rotation_var, tuple(ROTATIONS), 0, 2, 12)
        self.hint_label = ttk.Label(tab, textvariable=self.hint, style='Hint.TLabel')
        self.hint_label.grid(row=2, column=0, sticky='ew', pady=(4, 6))
        self.hint_label.bind('<Configure>', lambda event: self.hint_label.configure(wraplength=event.width)
                             if event.width > 1 else None)

        tab.rowconfigure(4, weight=1)
        bar = ttk.Frame(tab, style='Card.TFrame')
        bar.grid(row=3, column=0, sticky='ew', pady=(0, 4))
        self.add_button = ttk.Button(bar, text='添加文件', command=self.choose_files)
        self.add_button.pack(side='left')
        self.remove_button = ttk.Button(bar, text='移除所选', command=self.remove_selected)
        self.remove_button.pack(side='left', padx=6)
        if app.drag_enabled:
            ttk.Label(bar, text='也可拖入文件', style='Hint.TLabel').pack(side='left', padx=4)

        files = ttk.Frame(tab, style='Card.TFrame')
        files.grid(row=4, column=0, sticky='nsew')
        files.columnconfigure(0, weight=1)
        files.rowconfigure(0, weight=1)
        app.style.configure('Conversion.Treeview', rowheight=app.px(23))
        self.tree = ttk.Treeview(files, columns=('state',), show='tree headings', height=2,
                                 style='Conversion.Treeview', selectmode='extended')
        self.tree.heading('#0', text='文件', anchor='w')
        self.tree.heading('state', text='状态', anchor='w')
        self.tree.column('#0', minwidth=100, width=300)
        self.tree.column('state', width=app.px(108), minwidth=app.px(96), stretch=False)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(files, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        if app.drag_enabled:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind('<<Drop>>', self.drop_files)

        ttk.Label(tab, textvariable=self.detail, style='Hint.TLabel', width=1, anchor='w').grid(
            row=5, column=0, sticky='ew', pady=(2, 4))
        out = ttk.Frame(tab, style='Card.TFrame')
        out.grid(row=6, column=0, sticky='ew', pady=(0, 5))
        out.columnconfigure(1, weight=1)
        ttk.Label(out, text='输出目录', style='Card.TLabel').grid(row=0, column=0, padx=(0, 7))
        self.output_entry = ttk.Entry(out, textvariable=self.directory, width=1)
        self.output_entry.grid(row=0, column=1, sticky='ew')
        self.output_button = ttk.Button(out, text='浏览', command=self.choose_directory)
        self.output_button.grid(row=0, column=2, padx=6)
        ttk.Button(out, text='打开目录', command=self.open_directory).grid(row=0, column=3)
        actions = ttk.Frame(tab, style='Card.TFrame')
        actions.grid(row=7, column=0, sticky='w')
        self.start_button = ttk.Button(actions, text='开始转换', style='Action.TButton', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(actions, text='停止转换', command=app.stop_conversion, state='disabled')
        self.stop_button.pack(side='left', padx=(app.px(8), 0))
        app.action_buttons.append(self.start_button)
        self.change_mode()
        self.selection_changed()

    @property
    def mode(self):
        return MODES[self.mode_var.get()]

    def combo(self, parent, label, variable, values, row, column, width):
        caption = ttk.Label(parent, text=label, style='Card.TLabel')
        caption.grid(row=row, column=column, sticky='w', padx=(0, 7))
        box = ttk.Combobox(parent, textvariable=variable, values=values, width=width, state='readonly')
        box.grid(row=row, column=column + 1, sticky='w', padx=(0, 12))
        self.labels[box] = caption
        return box

    def change_mode(self, _event=None):
        self.format_box.configure(values=conversion.FORMATS[self.mode])
        self.format_box.current(0)
        self.form_changed()
        self.request_probe()

    def form_changed(self, _event=None):
        for widget in self.options.winfo_children():
            widget.grid_remove()
        mode = self.mode
        if mode == 'video':
            self.show_combo(self.kind)
            if self.encode_var.get() != '仅无损封装':
                self.show_combo(self.quality)
        elif mode == 'speed':
            self.show_combo(self.speed_box)
            by_duration = self.speed_mode.get() == FIXED_DURATION
            self.speed_label.configure(text='时长' if by_duration else '倍率')
            self.speed_label.grid(row=0, column=2, sticky='w', padx=(0, 7))
            self.speed_entry.configure(textvariable=self.speed_duration if by_duration else self.speed_rate)
            self.speed_entry.grid(row=0, column=3, sticky='w', padx=(0, 12))
            self.show_combo(self.speed_quality)
        elif mode == 'image':
            self.show_combo(self.scale)
            self.show_combo(self.rotation)
        elif mode in ('extract', 'audio'):
            self.track_label.grid(row=0, column=0, sticky='w', padx=(0, 7))
            self.track_box.grid(row=0, column=1, sticky='w', padx=(0, 12))
            if self.format_var.get() not in ('FLAC', 'WAV'):
                self.show_combo(self.quality)
        elif self.format_var.get() not in (conversion.FORMATS['ncm'][0], 'FLAC', 'WAV'):
            self.show_combo(self.quality)
        self.update_hint()

    def show_combo(self, box):
        self.labels[box].grid()
        box.grid()

    def update_hint(self, *_args):
        text = {
            'video': '自动模式优先无损封装，无法封装时重新编码。',
            'extract': '按音轨序号提取。批量处理时对每个文件使用同一序号。',
            'audio': '原文件保留。支持的输出格式会尽量保留标签和封面。',
            'image': '可直接转换，也可同时缩放和旋转。',
            'ncm': '原始格式保留文件内的 MP3 或 FLAC，以及可读取的标签和封面。',
        }.get(self.mode, '')
        if self.mode == 'speed':
            by_duration = self.speed_mode.get() == FIXED_DURATION
            value = self.speed_duration.get() if by_duration else self.speed_rate.get()
            text = '保持音高 · ' + ('可填秒数、分:秒或时:分:秒' if by_duration else '倍率范围 0.25×–4×')
            if self.info:
                duration = conversion.source_duration(self.info)
                if duration and value.strip():
                    options = conversion.Options('speed', self.format_var.get(), by_duration=by_duration, speed=value)
                    try:
                        rate, target = conversion.speed_plan(duration, options)
                    except ValueError:
                        pass
                    else:
                        text = f'保持音高 · 所选视频 {duration:.2f} 秒 → 约 {target:.2f} 秒 · {rate:.3g}×'
        self.hint.set(text)

    def choose_files(self):
        patterns = ' '.join('*.' + suffix for suffix in conversion.INPUTS[self.mode].split())
        paths = filedialog.askopenfilenames(parent=self.root, filetypes=[('适用文件', patterns), ('所有文件', '*.*')])
        self.add_paths(paths)

    def drop_files(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))

    def add_paths(self, paths):
        if self.running:
            return
        seen = set(self.queue.values())
        added = []
        for raw in paths:
            try:
                path = media.clean_path(raw)
            except (OSError, ValueError) as exc:
                self.app.log(str(exc))
                continue
            if path in seen:
                continue
            if path.is_dir():
                self.app.log(f'请添加文件。已跳过目录 {path}')
                continue
            key = self.tree.insert('', 'end', text=path.name, values=('待处理',))
            self.queue[key] = path
            seen.add(path)
            added.append(key)
        if added:
            self.tree.selection_set(added[0])
            self.tree.see(added[0])

    def remove_selected(self):
        if self.running:
            return
        for key in self.tree.selection():
            del self.queue[key]
            self.details.pop(key, None)
            self.tree.delete(key)
        self.selection_changed()

    def selected_key(self):
        selected = self.tree.selection()
        return selected[0] if selected else next(iter(self.queue), None)

    def selection_changed(self, _event=None):
        key = self.selected_key()
        self.detail.set(self.details.get(key) or (str(self.queue[key]) if key else '输出目录留空时，保存到各源文件所在目录。'))
        self.request_probe()

    def request_probe(self):
        if self.probe_job is not None:
            self.root.after_cancel(self.probe_job)
            self.probe_job = None
        self.probe_serial += 1
        self.info = None
        self.update_hint()
        key = self.selected_key()
        self.track_box.configure(values=('第 1 条',))
        self.track_box.current(0)
        if key and not self.running and self.mode in ('speed', 'extract', 'audio'):
            path = self.queue[key]
            self.probe_job = self.root.after(180, self.inspect, self.probe_serial, path)

    def inspect(self, serial, path):
        self.probe_job = None

        def run():
            try:
                info = conversion.probe(path)
            except (OSError, ValueError, subprocess.SubprocessError):
                info = None
            self.app.events.put(('conversion_probe', (serial, info)))

        threading.Thread(target=run, daemon=True).start()

    def apply_probe(self, serial, info):
        if serial != self.probe_serial or info is None or self.running:
            return
        self.info = info
        self.update_hint()
        tracks = []
        for index, stream in enumerate(conversion.audio_tracks(info), 1):
            tags = stream.get('tags', {})
            description = tags.get('title') or tags.get('language') or stream.get('codec_name', '')
            tracks.append(f'第 {index} 条 · {description}' if description else f'第 {index} 条')
        if tracks:
            self.track_box.configure(values=tracks)
            self.track_box.current(0)

    def choose_directory(self):
        directory = filedialog.askdirectory(parent=self.root)
        if directory:
            self.directory.set(directory)

    def open_directory(self):
        try:
            key = self.selected_key()
            if self.directory.get().strip():
                folder = media.clean_path(self.directory.get())
            elif key:
                folder = self.queue[key].parent
            else:
                raise ValueError('请先添加文件或选择输出目录。')
            os.startfile(folder)
        except (OSError, ValueError) as exc:
            messagebox.showerror('无法打开目录', str(exc), parent=self.root)

    def start(self):
        if self.app.busy:
            return
        if not self.queue:
            messagebox.showinfo('请选择文件', '请添加要转换的文件。', parent=self.root)
            return
        by_duration = self.speed_mode.get() == FIXED_DURATION
        options = conversion.Options(
            self.mode, self.format_var.get(), self.encode_var.get(), self.quality_var.get(),
            max(0, self.track_box.current()), by_duration,
            self.speed_duration.get() if by_duration else self.speed_rate.get(),
            SCALES[self.scale_var.get()], ROTATIONS[self.rotation_var.get()],
        )
        try:
            if options.mode == 'speed':
                conversion.parse_speed_value(options.speed, options.by_duration)
            raw = self.directory.get().strip()
            folder = media.clean_path(raw) if raw else None
        except (OSError, ValueError) as exc:
            messagebox.showerror('请检查设置', str(exc), parent=self.root)
            return
        keys = tuple(self.queue)
        sources = [self.queue[key] for key in keys]
        self.details.clear()
        for key in keys:
            self.tree.item(key, values=('等待中',))
        self.edit_state(False)
        control = media.ToolControl()

        def update(index, status, detail):
            self.app.events.put(('conversion_row', (keys[index], status, detail)))

        def progress(value):
            self.app.events.put(('progress', value))

        self.app.launch(self.mode_var.get(),
                        lambda: conversion.convert_batch(sources, folder, options, update, progress, self.app.log, control),
                        determinate=True, control=control)

    def edit_state(self, enabled):
        self.running = not enabled
        self.stop_button.state(['disabled' if enabled else '!disabled'])
        widgets = (self.mode_box, self.format_box, self.kind, self.quality, self.speed_box, self.speed_entry,
                   self.speed_quality, self.track_box, self.scale, self.rotation, self.add_button, self.remove_button,
                   self.output_entry, self.output_button)
        for widget in widgets:
            widget.state(['!disabled' if enabled else 'disabled'])

    def apply_row(self, key, status, detail):
        self.tree.item(key, values=(status,))
        if detail:
            self.details[key] = detail
            if key == self.selected_key():
                self.detail.set(detail)
