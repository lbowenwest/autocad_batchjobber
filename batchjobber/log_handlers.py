import logging
import multiprocessing as mp
import queue
import sys
import threading
import tkinter as tk
import traceback


def install_mp_handler(logger=None):
    if not logger:
        logger = logging.getLogger()
    for i, orig_handler in enumerate(list(logger.handlers)):
        handler = MultiProcessingHandler(
            f"mp-handler-{i}", sub_handler=orig_handler
        )
        logger.removeHandler(orig_handler)
        logger.addHandler(handler)


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
            self._receive_thread.join(2.0)  # Waits for receive queue to empty.

            self.sub_handler.close()
            super(MultiProcessingHandler, self).close()