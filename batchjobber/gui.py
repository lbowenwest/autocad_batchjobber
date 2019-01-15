import glob
import logging
import logging.handlers
import multiprocessing as mp
import queue
import tkinter as tk
from os import path
import re
from typing import List
from tkinter import ttk, filedialog, messagebox as mbox

from .log_handlers import LogDispatcher
from .pipeline import DrawingProcessor
from .utility import autocad_console


class LogDisplay(ttk.LabelFrame):
    """
    Simple tkinter frame for a log console window. Creates a queue 
    which is checked every 100ms for new log entries. Queue expects 
    entries to be a string, a log handler should be in charge of 
    formatting the string
    """
    def __init__(self, master, **options):
        """
        Initialise log window, starts checking for messages immediately

        :param master: tk master widget
        :param options: options to passthrough to tk.Frame
        """
        super(LogDisplay, self).__init__(master, **options)
        self.queue = mp.Queue()
        self.console = tk.Text(self, height=10)
        self.console.grid(stick="nesw")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.process_logs()

    def add(self, msg: str):
        """
        Add message to end of console window and scroll to see it

        :param msg: formatted message to add
        """
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, msg)
        self.console.configure(state=tk.DISABLED)
        self.console.see(tk.END)

    def process_logs(self):
        """
        Get message from queue, if message add it to the window,
        otherwise do nothing. Checks every 100ms while application is running
        """
        try:
            msg = self.queue.get(timeout=0.01)
        except queue.Empty:
            pass
        else:
            self.add(msg)
        self.after(100, self.process_logs)


class DirectoryChooser(ttk.Frame):
    """
    Tkinter widget consisting of a label and a browse button.
    When the browse button is clicked a file dialog prompt is shown
    for the user to choose a directory
    """

    def __init__(self, master, label_text="", **options):
        super(DirectoryChooser, self).__init__(master, **options)
        self.logger = logging.getLogger('gui')

        self._label = ttk.Label(self, text=label_text)
        self.dir_var = tk.StringVar()
        self.dir_label = ttk.Label(self, textvariable=self.dir_var, background="white")

        self.dir_button = ttk.Button(self, text="Browse", command=self.prompt)

        self._label.grid(row=0, column=0, stick="w")
        self.dir_button.grid(row=0, column=1, stick="e")
        self.dir_label.grid(row=1, column=0, columnspan=2, stick="ew", pady=5)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def prompt(self, title="", **options) -> str:
        """
        Open directory chooser dialog

        :param title: title of dialog box
        :param options: passed through to tk.filedialog
        :return: chosen directory
        """
        self.logger.debug("Launching directory file dialog...")
        out = filedialog.askdirectory(title=title, **options)
        if out:
            self.logger.debug(f"Directory chosen: {out}")
            self.dir_var.set(out)
            self.event_generate("<<path_updated>>")
        else:
            self.logger.debug("Directory dialog cancelled")
        return self.get()

    def get(self) -> str:
        """
        Directory chosen by user, blank if cancelled

        :return: chosen directory
        """
        return self.dir_var.get()


class FileList(ttk.Frame):
    """
    Tkinter widget used to show a list of files matching an extension
    in a certain directory
    """
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

        self.logger = logging.getLogger('gui')

        self.listbox.grid(row=1, column=0, columnspan=2, stick="nesw")
        self.clear_btn.grid(row=0, column=1, pady=5)
        self.all_btn.grid(row=0, column=0, pady=5)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

    def clear_selection(self):
        """
        Clears list selection
        """
        self.logger.debug("Clearing selection")
        self.listbox.selection_clear(0, tk.END)

    def select_all(self):
        """
        Selects all in file list
        """
        self.logger.debug("Selecting all items in file list")
        self.listbox.selection_set(0, tk.END)

    def update_list(self, directory):
        """
        Updates list to files in directory

        :param directory: directory to search
        """
        self.logger.debug("Updating file list...")
        files = [
            path.basename(f)
            for f in glob.glob(path.join(directory, f"*.{self.extension}"))
        ]
        self.file_list.set(sorted(files))

    def get_list(self) -> List[str]:
        """
        Gets list of all files in list

        :return: file list
        """
        files = re.sub(r"[()']", "", self.file_list.get()).split(',')
        return [s.strip() for s in files]

    def get_selected(self) -> List[str]:
        """
        Gets list of all selected files

        :return: selected file list
        """
        try:
            return self.listbox.selection_get().split('\n')
        except tk.TclError:
            return []

    def set_selected(self, dwgs: List[str]):
        """
        Sets selection in file list to dwgs, by searching total list

        :param dwgs: drawings to select in list
        """
        self.clear_selection()
        self.logger.debug(f"Changing selected drawings to {dwgs}")
        files = self.get_list()
        for d in dwgs:
            idx = files.index(d)
            self.listbox.selection_set(idx, idx)


class BatchJobber(object):
    """
    Main window class
    """

    def __init__(self, master: tk.Tk):
        self.master = master
        self.title = "AutoCAD Batch Jobs"

        self.log_window = LogDisplay(master)
        self.drawing_dir = DirectoryChooser(master, label_text="Drawing Folder")
        self.drawing_list = FileList(master, extension="dwg")
        self.publish_option_var = tk.BooleanVar(value=True)
        self.publish_option = ttk.Checkbutton(master, text="Publish PDF", variable=self.publish_option_var)
        self.run_button = ttk.Button(master, text="Run", command=self.run)
        self.progress_bar = ttk.Progressbar(master, mode='determinate')

        self.ui_bindings()
        self.ui_build()

        manager = mp.Manager()
        self.job_running = False

        self.log_queue = manager.Queue(-1)
        self.failed_drawings = manager.Queue()
        self.has_failed_drawings = False
        self.failed_list = {'all': [], 'open': [], 'xref': [], 'unknown': []}
        self.drawing_filter = DrawingProcessor(self.log_queue, fail_queue=self.failed_drawings)

        self.log_dispatcher = LogDispatcher(self.log_queue, self.log_window.queue)

        autocad_console()

    def ui_bindings(self):
        """
        Attach bindings for ui functions and events
        """
        self.master.protocol("WM_DELETE_WINDOW", self.on_quit)
        self.master.bind("<<filter_finished>>", self.filtering_done)
        self.master.bind("<<build_finished>>", self.processing_done)
        self.master.bind("<<build_error>>", self.processing_error)
        self.drawing_dir.bind("<<path_updated>>", self.update_drawing_list)

    def ui_build(self):
        """
        Add the ui elements to the widget
        """
        self.master.title(self.title)

        self.drawing_dir.grid(row=0, column=0, columnspan=2, stick="ew", padx=5, pady=5)
        self.drawing_list.grid(row=1, column=0, columnspan=2, stick="nesw", padx=5)
        self.publish_option.grid(row=2, column=0, padx=5, pady=5)
        self.run_button.grid(row=2, column=1, padx=10, pady=5)
        self.progress_bar.grid(row=3, column=0, columnspan=2, padx=10, stick="ew")
        self.progress_bar.grid_remove()
        self.log_window.grid(row=4, column=0, columnspan=2, stick="nesw")

        self.master.grid_rowconfigure(1, weight=3)
        self.master.grid_rowconfigure(4, weight=1)
        self.master.grid_columnconfigure(0, weight=1)
        self.master.grid_columnconfigure(1, weight=1)

    def update_drawing_list(self, event):
        """
        Event triggered when new directory is chosen. Refreshes file list

        :param event:
        """
        logging.info(f"Changed drawing directory to {self.drawing_dir.get()}")
        self.drawing_list.update_list(self.drawing_dir.get())

    def run(self):
        """

        :return:
        """
        drawings = self.drawing_list.get_selected()

        if not drawings:
            logging.error("No drawings selected")
            return

        self.run_button.configure(state=tk.DISABLED)
        self.progress_bar.grid()
        self.progress_bar.configure(mode='indeterminate')
        self.progress_bar.start(25)

        self.job_running = True
        self.has_failed_drawings = False

        self.drawing_filter.set_build_options(publish=self.publish_option_var.get())
        self.drawing_filter.process(
            drawings,
            self.drawing_dir.get(),
            filter_callback=lambda: self.master.event_generate("<<filter_finished>>"),
            build_callback=lambda: self.master.event_generate("<<build_finished>>"),
            error_callback=lambda e: self.master.event_generate("<<build_error>>", data=str(e))
        )

    def filtering_done(self, event):
        """
        Event generated when drawing processor has finished filtering.
        Filters all failed drawings to the correct list based on reason for failing,
        and updates file list selection to failed drawings.
        If no failed drawings, only clears selection

        :param event:
        """
        self.failed_list['all'].clear()
        self.failed_list['open'].clear()
        self.failed_list['xref'].clear()
        self.failed_list['unknown'].clear()
        for dwg in iter(self.failed_drawings.get, None):
            self.has_failed_drawings = True
            self.failed_list['all'].append(dwg['dwg'])
            if dwg['reason'] == 'open':
                self.failed_list['open'].append(dwg['dwg'])
            elif dwg['reason'] == 'xref':
                self.failed_list['xref'].append(dwg['dwg'])
            else:
                self.failed_list['unknown'].append(dwg['dwg'])
        if self.has_failed_drawings:
            mbox.showwarning(self.title + " Warning", self.generate_failed_string())
            self.drawing_list.set_selected(self.failed_list['all'])
        else:
            self.drawing_list.clear_selection()

    def generate_failed_string(self) -> str:
        """
        Generates warning string for message box using failed drawings

        :return: string for warning box
        """
        failed_string = ""
        if self.failed_list['open']:
            failed_string += "These drawings are open, please close them:\n"
            failed_string += '\n'.join(self.failed_list['open']) + '\n\n'
        if self.failed_list['xref']:
            failed_string += "These drawings have unbound xrefs, please check them:\n"
            failed_string += '\n'.join(self.failed_list['xref']) + '\n\n'
        if self.failed_list['unknown']:
            failed_string += "\nSomething is wrong with these drawings:\n"
            failed_string += '\n'.join(self.failed_list['unknown']) + '\n\n'
        return failed_string

    def processing_done(self, event):
        """
        Triggered when drawing processor has finished building drawings.
        Resets ui so that a new job can be triggered.

        :param event:
        """
        self.run_button.configure(state=tk.NORMAL)
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.job_running = False
        if not self.has_failed_drawings:
            mbox.showinfo(self.title, "All done!")
        else:
            for dwg in self.failed_list['open']:
                logging.warning(f"{dwg} is open in AutoCAD please close it to process")
            for dwg in self.failed_list['xref']:
                logging.warning(f"{dwg} has unbound xrefs, fix in AutoCAD and rerun")
            for dwg in self.failed_list['unknown']:
                logging.warning(f"{dwg} has failed for some reason :(")
            mbox.showwarning(self.title, "All done!\nSome drawings had errors and weren't processed.\n"
                                         "See the log window for more detail")

    def processing_error(self, event):
        """
        Triggered when something bad happens in the processor.
        Logs the error and shows a messagebox, and resets ui.
        If this happens God help you.

        :param event:
        """
        self.run_button.configure(state=tk.NORMAL)
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.job_running = False
        logging.critical(event.data)
        mbox.showerror(self.title + " Error", "No drawings were processed. Something bad happened")

    def on_quit(self):
        """
        Triggered when main window closed. Stops logger and all drawing processes.
        If job is running, warns user and does nothing.
        """
        if self.job_running:
            logging.warning("Tried to quit with job running")
            mbox.showwarning(self.title, "Job is still running!")
            return
        self.drawing_filter.stop()
        logging.info("Quitting...")
        self.log_dispatcher.stop()
        self.master.destroy()
