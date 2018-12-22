import glob
import logging
import re
import platform
from os import path


def autocad_basepath(log=True):
    if "Windows" not in platform.platform():
        if log:
            logging.critical("Only windows is supported")
        return ""
    acad_versions = glob.glob(r"C:\Program Files\Autodesk\AutoCAD *")
    if not acad_versions:
        if log:
            logging.error("Could not find an installed version of AutoCAD")
        return ""
    for ver in sorted(acad_versions, reverse=True):
        if re.match(r"AutoCAD \d{4}", path.basename(ver)):
            if log:
                logging.info(f"Using {path.basename(ver)}")
                logging.debug(f"AutoCAD base path is {ver}")
            return ver


def autocad_console(log=True):
    base = autocad_basepath(log=log)
    console_path = path.join(base, "accoreconsole.exe")
    if not path.exists(console_path):
        logging.error("Console path doesn't exist!")
        raise Exception
    return console_path

if __name__ == '__main__':
    logging.basicConfig()
    print(autocad_console())
