import glob
import logging
import multiprocessing as mp
import tkinter as tk
from os import path
from tkinter import ttk, filedialog, messagebox as mbox

from batchjobber.log_handlers import MultiProcessingHandler, ConsoleLogHandler
from batchjobber.pipeline import DrawingFilter


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
        self.title = "AutoCAD Batch Jobs"
        master.title(self.title)
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
        mbox.showinfo(self.title, "All done!")

    def on_quit(self):
        if self.job_running:
            self.logger.warning("Tried to quit with job running")
            mbox.showwarning(self.title, "Job is still running!")
            return
        self.drawing_filter.stop()
        self.logger.info("Quitting...")
        self.master.destroy()
