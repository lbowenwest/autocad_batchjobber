import logging
import multiprocessing as mp
import tkinter as tk
from tkinter import messagebox as mbox
from tkinter import ttk

from gui import LogDisplay, DirectoryChooser, FileList
from log_handlers import ConsoleLogHandler, MultiProcessingHandler
from pipeline import DrawingFilter


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
