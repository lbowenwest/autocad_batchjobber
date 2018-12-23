import logging
import tkinter as tk


def logger_thread(q):
    while True:
        record = q.get(block=True, timeout=None)
        if record is None:
            break
        logger = logging.getLogger(record.name)
        logger.handle(record)


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
