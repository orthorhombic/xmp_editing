import importlib.resources
import pathlib
import concurrent.futures


import logzero
import pyexiv2
import yaml

from logzero import logger

import xmp_editing_utils
# create a function to find all supported image formats in xmp_editing_utils.raw_files or xmp_editing_utils.other_files and identify what the path to the corresponding filename.ext.xmp file would be. Using the function above, conduct two checks on that file. First, if it does not exist, log an error. If the file exists, parse the xmp file to see if it has the darktable:history_end key.



logzero.logfile("xmp_rotating_logfile.log", maxBytes=1e8, backupCount=3)
logger.setLevel(level="DEBUG")


config = importlib.resources.files("untracked").joinpath("crop_config.yml")

with open(config) as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

if config_data.get("root_path") is not None:
    root_path = pathlib.Path(config_data["root_path"])  # default "untracked"
else:
    root_path = "untracked"


def get_xmp_path(image_path):
    xmp_path = image_path.with_suffix(f"{image_path.suffix}.xmp")
    return xmp_path

def check_xmp_file(xmp_path):
    if not xmp_path.exists():
        logger.error(f"XMP file does not exist: {xmp_path}")
    else:
        with pyexiv2.Image(xmp_path.as_posix()) as img:
            xmp_data=img.read_xmp()
            history_end=xmp_data.get("Xmp.darktable.history_end","0")
            if int(history_end)<5:
                logger.error(f"XMP file does not have darktable edit history: {xmp_path}")

def main():

    p = root_path.rglob("*")
    files = [x for x in p if x.is_file()]

    supported_files = set.union(
        set(xmp_editing_utils.raw_files), set(xmp_editing_utils.other_files)
    )
    files = [x for x in files if x.suffix.upper() in supported_files]

    for file in files:
        expected_xmp=get_xmp_path(file)
        logger.info(f"Checking {file} with {expected_xmp.name}")
        check_xmp_file(expected_xmp)


if __name__ == "__main__":
    logger.info("Running main()")
    main()
