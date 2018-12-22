import logging
import tkinter as tk

from batchjobber.gui import BatchJobber
from batchjobber.log_handlers import MultiProcessingHandler


def setup_logger(logger=None):
    logging.basicConfig(level=logging.DEBUG)
    if not logger:
        logger = logging.getLogger()
    for i, orig_handler in enumerate(list(logger.handlers)):
        handler = MultiProcessingHandler(
            f"mp-handler-{i}", sub_handler=orig_handler
        )
        logger.removeHandler(orig_handler)
        logger.addHandler(handler)


def main_gui():
    root = tk.Tk()
    win = BatchJobber(root)
    root.mainloop()


if __name__ == '__main__':
    setup_logger()
    main_gui()
