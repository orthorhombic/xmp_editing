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


config = importlib.resources.files("untracked").joinpath("crop_config.yml")

with open(config) as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

if config_data.get("root_path") is not None:
    root_path = pathlib.Path(config_data["root_path"])  # default "untracked"
else:
    root_path = "untracked"

if config_data.get("debug") is not None:
    debug = config_data["debug"]
else:
    debug = False

if debug:
    logger.setLevel(level="DEBUG")
else:
    logger.setLevel(level="INFO")


mirror_config = config_data.get("mirror",False) # default to not mirroring

def check_dt_xmp_file(image_path):
    xmp_path = image_path.with_suffix(f"{image_path.suffix}.xmp")
    error=0
    if not xmp_path.exists():
        logger.error(f"XMP file does not exist: {xmp_path}")
        error=1
    else:
        with pyexiv2.Image(xmp_path.as_posix()) as img:
            xmp_data=img.read_xmp()
            history_end=xmp_data.get("Xmp.darktable.history_end","0")
            if int(history_end)<5:
                error=1
                logger.error(f"XMP file does not have darktable edit history: {xmp_path}")
    return error

def check_base_xmp_file(image_path,mirror):
    xmp_path = image_path.with_suffix(".xmp")
    error=0
    if not xmp_path.exists():
        logger.error(f"XMP file does not exist: {xmp_path}")
    else:
        with pyexiv2.Image(xmp_path.as_posix()) as img:
            xmp_data=img.read_xmp()
            
            # Override mirror parameter with "no_mirror" tag
            if "no_mirror" in xmp_data.get("Xmp.dc.subject",list()):
                mirror = False

            orientation=xmp_data.get("Xmp.tiff.Orientation","0")
            mirrored= orientation in ["2","5","7","4"]
            if orientation=="0":
                error=1
                logger.error(f"XMP file has invalid rotation: {xmp_path}")
            elif mirror and not mirrored:
                error=1
                logger.error(f"XMP file not mirrored when it should be: {xmp_path}")
            elif not mirror and mirrored:
                error=1
                logger.error(f"XMP file mirrored when it should NOT be: {xmp_path}")
    return error

def main():

    p = root_path.rglob("*")
    files = [x for x in p if x.is_file()]

    supported_files = set.union(
        set(xmp_editing_utils.raw_files), set(xmp_editing_utils.other_files)
    )
    files = [x for x in files if x.suffix.upper() in supported_files]

    error_count=0
    for file in files:
        error=0
        logger.debug(f"Checking {file}")
        error+=check_base_xmp_file(file,mirror=mirror_config)
        error+=check_dt_xmp_file(file)
        if error>0:
            error_count+=1
    if error_count>0:
        logger.error(f"Completed with {error_count} errors")

if __name__ == "__main__":
    logger.info("Running main()")
    main()
