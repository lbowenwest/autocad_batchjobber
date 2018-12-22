import os
import queue
import random
import sys
import threading
import time
import traceback
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
from tkinter import messagebox as mbox


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


class MultiProcessingHandler(logging.Handler):

    def __init__(self, name, sub_handler=None):
        super(MultiProcessingHandler, self).__init__()

        if sub_handler is None:
            sub_handler = logging.StreamHandler()
        self.sub_handler = sub_handler

        self.setLevel(self.sub_handler.level)
        self.setFormatter(self.sub_handler.formatter)

        self.queue = mp.Queue(-1)
        self._is_closed = False
        # The thread handles receiving records asynchronously.
        self._receive_thread = threading.Thread(target=self._receive, name=name)
        self._receive_thread.daemon = True
        self._receive_thread.start()

    def setFormatter(self, fmt):
        super(MultiProcessingHandler, self).setFormatter(fmt)
        self.sub_handler.setFormatter(fmt)

    def _receive(self):
        while not (self._is_closed and self.queue.empty()):
            try:
                record = self.queue.get(timeout=0.2)
                self.sub_handler.emit(record)
            except (KeyboardInterrupt, SystemExit):
                raise
            except EOFError:
                break
            except queue.Empty:
                pass  # This periodically checks if the logger is closed.
            except:
                traceback.print_exc(file=sys.stderr)

        self.queue.close()
        self.queue.join_thread()

    def _send(self, s):
        self.queue.put_nowait(s)

    def _format_record(self, record):
        # ensure that exc_info and args
        # have been stringified. Removes any chance of
        # unpickleable things inside and possibly reduces
        # message size sent over the pipe.
        if record.args:
            record.msg = record.msg % record.args
            record.args = None
        if record.exc_info:
            self.format(record)
            record.exc_info = None

        return record

    def emit(self, record):
        try:
            s = self._format_record(record)
            self._send(s)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def close(self):
        if not self._is_closed:
            self._is_closed = True
            self._receive_thread.join(5.0)  # Waits for receive queue to empty.

            self.sub_handler.close()
            super(MultiProcessingHandler, self).close()


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
        self.log_handler = MultiProcessingHandler(
            "console-handler",
            ConsoleLogHandler(self.log_window.console)
        )

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

        manager = mp.Manager()
        self.job_running = False
        self.failed_drawings = manager.Queue()
        self.drawing_filter = DrawingFilter(
            fail_queue=self.failed_drawings,
            logger=self.logger
        )

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

        self.job_running = True

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
        self.run_button.configure(state=tk.NORMAL)
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.job_running = False
        mbox.showinfo("AutoCAD Batch Jobber", "All done!")

    def on_quit(self):
        if self.job_running:
            self.logger.warning("Tried to quit with job running")
            mbox.showwarning("AutoCAD Batch Jobber", "Job is still running!")
            return
        self.drawing_filter.stop()
        self.logger.info("Quitting...")
        self.master.destroy()


class DrawingFilter(object):
    """
    Class to filter drawing files based on certain checks
    to prevent broken drawings being passed to the builder
    """
    def __init__(self, fail_queue=None, logger=None):
        self.logger = logger

        self.pool = mp.Pool()
        self.manager = mp.Manager()

        self.fail_queue = fail_queue or self.manager.Queue()
        self.build_queue = None

        self.num_builders = mp.cpu_count()
        self.builders = []

        self.filter_callback = None
        self.build_callback = None

    def reset_builders(self):
        self.build_queue = self.manager.JoinableQueue()
        self.builders = [
            Builder(self.build_queue, self.logger)
            for _ in range(self.num_builders)
        ]
        for b in self.builders:
            b.start()

    def stop(self):
        self.pool.terminate()
        for b in self.builders:
            b.terminate()

    def set_build_options(self):
        pass

    def process(self, drawings, filter_callback=None, build_callback=None):
        if self.logger:
            self.logger.debug(f"Processing drawings...")

        self.filter_callback = filter_callback
        self.build_callback = build_callback

        self.reset_builders()

        self.pool.map_async(
            partial(
                self.check_drawing,
                pass_queue=self.build_queue,
                fail_queue=self.fail_queue,
                logger=self.logger
            ),
            drawings,
            callback=self.filter_complete
        )

    def filter_complete(self, val):
        self.fail_queue.put(None)
        for _ in range(self.num_builders):
            self.build_queue.put(None)

        if self.filter_callback:
            self.filter_callback()

        self.build_queue.join()
        if self.logger:
            self.logger.info("Build process done!")

        if self.build_callback:
            self.build_callback()

    @staticmethod
    def check_drawing(drawing, pass_queue, fail_queue, logger=None):
        if logger:
            logger.debug(f"Checking {drawing}")
        time.sleep(random.random())
        if re.match(r".?pass", drawing):
            if logger:
                logger.info(f"{drawing} passed drawing check")
            pass_queue.put(drawing)
        else:
            if logger:
                logger.warning(f"{drawing} failed drawing check")
            fail_queue.put(drawing)
        return True


class Builder(mp.Process):
    def __init__(self, queue: mp.JoinableQueue, logger=None):
        super(Builder, self).__init__()
        self.queue = queue
        self.logger = logger

    def run(self):
        while True:
            drawing = self.queue.get()
            if drawing is None:
                self.queue.task_done()
                break
            if self.logger:
                self.logger.debug(f"Building {drawing}...")
            self.build_drawing(drawing)
            self.queue.task_done()
        return

    def build_drawing(self, drawing):
        out = sp.check_output(
            [path.join(path.abspath(path.curdir), "command.sh"), drawing],
            shell=True
        )
        if self.logger:
            self.logger.info(f"Built - {drawing}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger()

    for i, orig_handler in enumerate(list(logger.handlers)):
        handler = MultiProcessingHandler(
            'mp-handler-{0}'.format(i), sub_handler=orig_handler)

        logger.removeHandler(orig_handler)
        logger.addHandler(handler)

    root = tk.Tk()
    win = BatchJobber(root)
    root.mainloop()
