import glob
import multiprocessing as mp
import re
import subprocess as sp
import logging
import logging.config
import logging.handlers
from functools import partial
from typing import List, Optional, Callable
from os import path

from .log_handlers import generate_worker_config
from .utility import autocad_console


class DrawingProcessor(object):
    """
    Class to filter drawing files based on certain checks
    to prevent broken drawings being passed to the builder
    """

    def __init__(self, log_queue: mp.Queue, fail_queue: Optional[mp.Queue] = None):
        """
        Initialise drawing processor. Creates manager for creating queues, and initiates
        processing pool as well as default values for callbacks and options

        :param log_queue: queue used for log messaging
        :param fail_queue: queue to pass failed drawings, if None creates its own
        """
        self.log_config = generate_worker_config(log_queue)
        logging.config.dictConfig(self.log_config)
        self.log_queue = log_queue
        self.logger = logging.getLogger('filter')

        self.manager = mp.Manager()
        self.pool = mp.Pool()

        self.fail_queue = fail_queue or self.manager.Queue()
        self.build_queue = None

        self.builders = []
        self.num_builders = 0

        self.drawing_dir = ""
        self.filter_callback = None
        self.build_callback = None
        self.publish_pdfs = True

    def reset_builders(self, drawing_dir: str, num_builders: Optional[int] = 0):
        """
        Resets all builder processes with correct arguments. If num_builders is provided
        makes that many builders, otherwise use cpu_count

        :param drawing_dir: drawing folder location
        :param num_builders: number of builder processes to start, or cpu_count if 0
        """
        for b in self.builders:
            b.terminate()
        self.build_queue = self.manager.JoinableQueue()
        self.num_builders = num_builders or mp.cpu_count()
        self.builders = [
            Builder(self.build_queue, drawing_dir, self.publish_pdfs, self.log_queue)
            for _ in range(self.num_builders)
        ]
        for b in self.builders:
            b.start()

    def stop(self):
        """
        Stops and kills builder processes and filtering pool
        """
        for b in self.builders:
            b.terminate()
        self.pool.terminate()

    def set_build_options(self, publish: bool = True):
        """
        Sets build options (currently only publish)

        :param publish:
        """
        self.publish_pdfs = publish

    # noinspection PyTypeChecker
    def process(self, drawings: List[str], drawing_dir: str,
                filter_callback: Optional[Callable[[], None]] = None,
                build_callback: Optional[Callable[[], None]] = None,
                error_callback: Optional[Callable[[BaseException], None]] = None) -> None:
        """
        Initiates filtering process on drawings, if checks are passed the drawings
        are then passed to the builder processes through a queue

        :param drawings: drawings to process
        :param drawing_dir: drawing folder location
        :param filter_callback: callback on filter complete
        :param build_callback: callback on build complete
        :param error_callback: callback on error in processing
        """
        self.logger.info(f"Starting checks...")

        self.drawing_dir = drawing_dir
        self.filter_callback = filter_callback
        self.build_callback = build_callback

        for idx, drawing in enumerate(drawings):
            if self.check_open(drawing):
                del drawings[idx]
                self.fail_queue.put({'dwg': drawing, 'reason': 'open'})
                self.logger.error(f"{drawing} is currently open and will not be processed, please close it")

        self.reset_builders(drawing_dir)

        if not drawings:
            filter_callback()
            error_callback()
            return

        self.pool = mp.Pool()
        self.pool.map_async(
            partial(
                self.check_drawing,
                drawing_dir=drawing_dir,
                pass_queue=self.build_queue,
                fail_queue=self.fail_queue,
                log_config=self.log_config
            ),
            drawings,
            callback=self.filter_complete
        )

    def filter_complete(self, val):
        """
        Callback function called when we have finished initial processing of teh drawings

        :param val:  return value from check_drawing
        """
        self.pool.close()
        self.fail_queue.put(None)
        for _ in range(self.num_builders):
            # need to add one sentinel for each builder process
            # to ensure all files are processed and we exit gracefully
            self.build_queue.put(None)

        if self.filter_callback:
            self.filter_callback()

        # wait for all the build processes to finish
        self.build_queue.join()
        self.logger.info("Build process done!")

        if self.build_callback:
            self.build_callback()

    def check_open(self, drawing: str) -> bool:
        """
        Checks if drawing is open in autocad by looking for dwl files in directory

        :param drawing: drawing to check
        :return: True if open
        """
        name = path.splitext(drawing)[0]
        files = glob.glob(path.join(path.abspath(self.drawing_dir), name + ".dwl"))
        if files:
            return True
        else:
            return False

    @staticmethod
    def check_drawing(drawing: str, drawing_dir: str, pass_queue: mp.Queue, fail_queue: mp.Queue, log_config: dict) -> bool:
        """
        Checks drawing to ensure no unbound xrefs

        :param drawing: drawing files to check
        :param drawing_dir: location of drawing
        :param pass_queue: place here if check passed
        :param fail_queue: place here if check failed
        :param log_config: ensures logging is handled properly
        :return: False if an error occured, True otherwise
        """
        logging.config.dictConfig(log_config)
        logging.debug(f"Checking {drawing}")
        # hard coded as autocad doesn't trust network locations by default
        script_dir = path.abspath(r"Z:\CAD Standards\Lisp & Script files")
        cmd = [
            autocad_console(log=False),
            "/i", path.join(path.abspath(drawing_dir), drawing),
            "/s", path.join(script_dir, "test_xrefs.scr")
        ]
        out = sp.check_output(cmd, shell=True, stderr=sp.DEVNULL)
        result = out.replace(b'\x00', b'').replace(b'\x08', b'').decode('ascii')
        match = re.match(r".+Total Xref\(s\): (\d+)", re.sub(r"[\r\n]", "", result))
        if not match:
            return False
        if int(match.group(1)) == 0:
            logging.info(f"{drawing} passed drawing check")
            pass_queue.put(drawing)
        else:
            logging.warning(f"{drawing} failed drawing check - has unbound xrefs")
            fail_queue.put({'dwg': drawing, 'reason': 'xref'})
        return True


class Builder(mp.Process):
    """
    Build process. Requires a queue containing drawing names to build, the directory they are located,
    whether or not PDFs should be published, and the log queue for message passing.
    """

    def __init__(self, queue: mp.JoinableQueue, drawing_dir: str, publish: bool, log_queue: mp.Queue):
        """
        Initialise build process

        :param queue: Build queue where drawings to be processed are placed
        :param drawing_dir: Root directory of drawings
        :param publish: Publish PDFs or not
        :param log_queue: Message queue for logging
        """
        super(Builder, self).__init__()
        self.log_config = generate_worker_config(log_queue)
        self.queue = queue
        self.drawing_dir = path.abspath(drawing_dir)
        # hard coded as autocad doesn't trust network locations by default
        self.script_dir = path.abspath(r"Z:\CAD Standards\Lisp & Script files")
        if publish:
            self.script = path.join(self.script_dir, "zipship_publish.scr")
        else:
            self.script = path.join(self.script_dir, "zipship.scr")

    def run(self) -> None:
        """
        Starts the build process
        """
        logging.config.dictConfig(self.log_config)
        while True:
            drawing = self.queue.get()
            if drawing is None:
                self.queue.task_done()
                break
            logging.debug(f"Building {drawing}...")
            self.build_drawing(drawing)
            logging.info(f"Built - {drawing}")
            self.queue.task_done()
        return

    def build_drawing(self, drawing: str) -> int:
        """
        Runs the build script on drawing in an autocad console window and returns the exit code

        :param drawing: drawing to run build script on
        :return: exit code of script (should always be 0)
        """
        cmd = [
            autocad_console(log=False),
            "/i", path.join(self.drawing_dir, drawing),
            "/s", path.join(self.script_dir, self.script)]
        out_code = sp.check_call(cmd, shell=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        return out_code
