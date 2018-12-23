import logging
import tkinter as tk
import multiprocessing as mp

from batchjobber.gui import BatchJobber


def main_gui():
    root = tk.Tk()
    win = BatchJobber(root)
    root.mainloop()


if __name__ == '__main__':
    mp.freeze_support()

    logging.basicConfig(level=logging.DEBUG)

    main_gui()
