import os
import random
import time
from os import path
import glob
import logging
import multiprocessing as mp
import subprocess as sp
import re
from functools import partial
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog


class LogDisplay(ttk.LabelFrame):
    """
    Simple tkinter frame for a console window
    """
    def __init__(self, master, **options):
        super(LogDisplay, self).__init__(master, **options)
        self.console = tk.Text(self, height=10)
        self.console.grid(stick="nesw")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)


class ConsoleLogHandler(logging.Handler):
    """
    Logging handler to redirect logs to console window
    """
    def __init__(self, console, formatter=None):
        super(ConsoleLogHandler, self).__init__()
        self.console = console
        self.formatter = formatter or logging.Formatter(fmt="%(levelname)s - %(message)s\n")
        self.setFormatter(self.formatter)

    def emit(self, message):
        formatted_message = self.format(message)
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, formatted_message)
        self.console.configure(state=tk.DISABLED)
        self.console.see(tk.END)


class DirectoryChooser(ttk.Frame):
    """
    Tkinter widget consisting of a label and a browse button.
    When the browse button is clicked a file dialog prompt is shown
    for the user to choose a directory
    """
    def __init__(self, master, prompt_title="", label_text="", **options):
        super(DirectoryChooser, self).__init__(master, **options)
        self._label = ttk.Label(self, text=label_text)
        self.dir_var = tk.StringVar()
        self.dir_label = ttk.Label(self, textvariable=self.dir_var, background="white")
        # self.dir_label.bind('<Configure>', self.label_format)

        self.dir_button = ttk.Button(self, text="Browse", command=self.prompt)

        self._label.grid(row=0, column=0, stick="w")
        self.dir_button.grid(row=0, column=1, stick="e")
        self.dir_label.grid(row=1, column=0, columnspan=2, stick="ew", pady=5)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def prompt(self, title="", **options):
        logging.debug("Launching directory file dialog...")
        out = filedialog.askdirectory(title=title, **options)
        if out:
            logging.debug(f"Directory chosen: {out}")
            self.dir_var.set(out)
            self.event_generate("<<path_updated>>")
        else:
            logging.debug("Directory dialog cancelled")

    def get(self):
        return self.dir_var.get()


class FileList(ttk.Frame):
    def __init__(self, master, extension="", **options):
        super(FileList, self).__init__(master, **options)
        self.extension = extension

        self.file_list = tk.StringVar(value=[])
        self.listbox = tk.Listbox(
            self,
            listvariable=self.file_list,
            selectmode="multiple"
        )
        self.clear_btn = ttk.Button(
            self,
            text="Clear Selection",
            command=self.clear_selection
        )
        self.all_btn = ttk.Button(
            self,
            text="Select All",
            command=self.select_all
        )

        self.listbox.grid(row=1, column=0, columnspan=2, stick="nesw")
        self.clear_btn.grid(row=0, column=1, pady=5)
        self.all_btn.grid(row=0, column=0, pady=5)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

    def clear_selection(self):
        logging.debug("Clearing selection")
        self.listbox.selection_clear(0, tk.END)

    def select_all(self):
        logging.debug("Selecting all items in file list")
        self.listbox.selection_set(0, tk.END)

    def update_list(self, directory):
        logging.debug("Updating file list...")
        files = [
            path.basename(f)
            for f in glob.glob(path.join(directory, f"*.{self.extension}"))
        ]
        self.file_list.set(sorted(files))

    def get_list(self):
        return self.file_list.get()

    def get_selected(self):
        try:
            return self.listbox.selection_get().split('\n')
        except tk.TclError:
            return []


class BatchJobber(object):
    def __init__(self, master: tk.Tk):
        self.master = master
        master.title("AutoCAD Batch Jobs")
        master.protocol("WM_DELETE_WINDOW", self.on_quit)
        master.bind("<<filter_finished>>", self.filtering_done)
        master.bind("<<build_finished>>", self.processing_done)

        self.log_window = LogDisplay(master)
        self.logger = logging.getLogger()
        self.log_handler = ConsoleLogHandler(self.log_window.console)
        self.logger.addHandler(self.log_handler)

        self.drawing_dir = DirectoryChooser(
            master,
            prompt_title="",
            label_text="Drawing Folder"
        )
        self.drawing_dir.bind("<<path_updated>>", self.update_drawing_list)
        self.drawing_list = FileList(master, extension="txt")
        self.publish_option_var = tk.BooleanVar(value=True)
        self.publish_option = ttk.Checkbutton(
            master,
            text="Publish PDF",
            variable=self.publish_option_var
        )
        self.run_button = ttk.Button(master, text="Run", command=self.run)
        self.progress_bar = ttk.Progressbar(master, mode='determinate')

        self.drawing_dir.grid(row=0, column=0, columnspan=2, stick="ew", padx=5, pady=5)
        self.drawing_list.grid(row=1, column=0, columnspan=2, stick="nesw", padx=5)
        self.publish_option.grid(row=2, column=0, padx=5, pady=5)
        self.run_button.grid(row=2, column=1, padx=10, pady=5)
        self.progress_bar.grid(row=3, column=0, columnspan=2, padx=10, stick="ew")
        self.progress_bar.grid_remove()
        self.log_window.grid(row=4, column=0, columnspan=2, stick="nesw")

        master.grid_rowconfigure(1, weight=3)
        master.grid_rowconfigure(4, weight=1)
        master.grid_columnconfigure(0, weight=1)
        master.grid_columnconfigure(1, weight=1)

        self.drawing_filter = DrawingFilter()

    def update_drawing_list(self, event):
        self.logger.debug(f"Changed drawing directory to {self.drawing_dir.get()}")
        self.drawing_list.update_list(self.drawing_dir.get())

    def run(self):
        drawings = self.drawing_list.get_selected()

        if not drawings:
            self.logger.error("No drawings selected")
            return

        self.run_button.configure(state=tk.DISABLED)
        self.progress_bar.grid()
        self.progress_bar.configure(mode='indeterminate')
        self.progress_bar.start(25)

        # TODO: get build options
        self.drawing_filter.set_build_options()
        self.drawing_filter.process(
            drawings,
            filter_callback=lambda: self.master.event_generate("<<filter_finished>>"),
            build_callback=lambda: self.master.event_generate("<<build_finished>>")
        )

    def filtering_done(self, event):
        pass

    def processing_done(self, event):
        self.logger.info("All drawings processed")
        self.run_button.configure(state=tk.NORMAL)
        self.progress_bar.stop()
        self.progress_bar.grid_remove()

    def on_quit(self):
        self.logger.info("Quitting...")
        self.master.destroy()


class DrawingFilter(object):
    """
    Class to filter drawing files based on certain checks
    to prevent broken drawings being passed to the builder
    """
    def __init__(self):
        self.pool = mp.Pool()
        manager = mp.Manager()

        self.pass_queue = manager.Queue()
        self.fail_queue = manager.Queue()

        self.pass_handler = None
        self.fail_handler = None

        self.num_builders = mp.cpu_count()
        self.build_queue = None
        self.builders = []

        self.filter_callback = None
        self.build_callback = None

    def start_handlers(self):
        self.pass_handler.start()
        self.fail_handler.start()

    def reset_handlers(self):
        self.stop()
        self.pass_handler = mp.Process(
            target=self.process_pass,
            args=(self.pass_queue, self.build_queue)
        )
        self.fail_handler = mp.Process(
            target=self.process_fail,
            args=(self.fail_queue,)
        )
        self.start_handlers()

    def reset_builders(self):
        self.build_queue = mp.JoinableQueue()
        self.builders = [Builder(self.build_queue) for _ in range(self.num_builders)]
        for b in self.builders:
            b.start()

    def stop(self):
        if self.pass_handler:
            self.pass_handler.terminate()
        if self.fail_handler:
            self.fail_handler.terminate()

    def set_build_options(self):
        pass

    def process_pass(self, queue, build_queue):
        while True:
            drawing = queue.get(block=True, timeout=None)
            if drawing is None:
                break
            print(f"Processing {drawing}")
            build_queue.put(drawing)

    def process_fail(self, queue):
        while True:
            drawing = queue.get(block=True, timeout=None)
            if drawing is None:
                break
            print(f"Warning - {drawing} failed check")

    def process(self, drawings, filter_callback=None, build_callback=None):
        self.filter_callback = filter_callback
        self.build_callback = build_callback

        self.reset_builders()
        self.reset_handlers()

        self.pool.map_async(
            partial(
                self.check_drawing,
                pass_queue=self.pass_queue,
                fail_queue=self.fail_queue
            ),
            drawings,
            callback=self.filter_complete
        )

    def filter_complete(self, val):
        self.fail_queue.put(None)
        self.pass_queue.put(None)
        for _ in range(self.num_builders):
            self.build_queue.put(None)

        if self.filter_callback:
            self.filter_callback()

        self.build_queue.join()
        print(f"Build process done")
        if self.build_callback:
            self.build_callback()

    @staticmethod
    def check_drawing(drawing: str, pass_queue: mp.Queue, fail_queue: mp.Queue):
        print(f"Checking {drawing}")
        time.sleep(random.random())
        if re.match(r".?pass", drawing):
            pass_queue.put(drawing)
        else:
            fail_queue.put(drawing)
        return True


class Builder(mp.Process):
    def __init__(self, queue: mp.JoinableQueue):
        super(Builder, self).__init__()
        self.queue = queue

    def run(self):
        while True:
            drawing = self.queue.get()
            if drawing is None:
                self.queue.task_done()
                break
            print(f"Building {drawing}...")
            self.build_drawing(drawing)
            self.queue.task_done()
        return

    def build_drawing(self, drawing):
        out = sp.check_output(
            [path.join(path.abspath(path.curdir), "command.sh"), drawing],
            shell=True
        )
        print(f"Built - {drawing}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    root = tk.Tk()
    win = BatchJobber(root)
    root.mainloop()
