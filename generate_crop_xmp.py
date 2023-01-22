# inspired by:
# https://github.com/z80z80z80/autocrop
# https://github.com/smc8050/Dias_Autocrop
import importlib.resources
import pathlib
import tempfile
from shutil import copy2

import cv2
import logzero
import pyexiv2
import rawpy
import yaml
from exiftool import ExifTool
from logzero import logger
from PIL import Image
from PIL import ImageChops
from PIL import ImageFilter

import xmp_editing_utils


logzero.logfile("crop_rotating_logfile.log", maxBytes=1e8, backupCount=3)
logger.setLevel(level="DEBUG")


default_device = cv2.ocl.Device_getDefault()

logger.debug(f"Default device: {default_device.name()}")

config = importlib.resources.files("untracked").joinpath("crop_config.yml")

with open(config) as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

root_path = pathlib.Path(config_data["root_path"])
debug = config_data["debug"]
crop_addition = config_data["crop_addition"]

if debug:
    debug_path = pathlib.Path(root_path, "debug")
    debug_path.mkdir(parents=True, exist_ok=True)


def process_file(
    filepath: pathlib.Path,
    debug_path: pathlib.Path,
    debug: bool,
    crop_addition: int,
    et: ExifTool,
):

    if filepath.suffix.upper() in xmp_editing_utils.raw_files:
        logger.debug("Processing as raw file")
        with rawpy.imread(filepath.as_posix()) as raw:
            imcv2 = raw.postprocess()
        img = Image.fromarray(imcv2)
        # convert from cv2 image file to pil image file
    elif filepath.suffix.upper() in xmp_editing_utils.other_files:
        logger.debug("Processing as regular file. Extension not in raw_files list.")
        imcv2 = cv2.imread(filepath.as_posix())
        img = Image.fromarray(
            cv2.cvtColor(imcv2, cv2.COLOR_BGR2RGB)
        )  # convert from cv2 image file to pil image file
    else:
        logger.error("Filetype not supported")
        return

    original_img = img
    w, h = original_img.size
    blurred_img = img.filter(
        ImageFilter.GaussianBlur(radius=4)
    )  # to remove outlier pixels
    binary_img = xmp_editing_utils.convert_to_binary(blurred_img, 45, 255)
    bg = Image.new(binary_img.mode, binary_img.size)
    diff = ImageChops.difference(binary_img, bg)
    bbox = diff.getbbox()
    # left, top, right, bottom
    # 0%, 0%, 100%, 100%

    if bbox == (0, 0, w, h):
        logger.error(f"No cropping detected for {filepath.as_posix()}")
        return
    elif bbox:
        color_control = xmp_editing_utils.get_control_value(original_img, bbox)
        if color_control > 15:
            logger.warning(f"Crop bounds may be problematic for {filepath.as_posix()}")
    else:
        raise RuntimeError("Could not find a bounding box for crop")

    # adjust based on cropp_addition

    if bbox[0] + crop_addition > 0:
        left = bbox[0] + crop_addition
    else:
        left = 0

    if bbox[1] + crop_addition > 0:
        top = bbox[1] + crop_addition
    else:
        top = 0

    if bbox[2] - crop_addition < w:
        right = bbox[2] - crop_addition
    else:
        right = w

    if bbox[3] - crop_addition < h:
        bottom = bbox[3] - crop_addition
    else:
        bottom = h

    new_box = (left, top, right, bottom)

    crop_parm = {}

    crop_parm["Xmp.crs.HasCrop"] = "True"
    crop_parm["Xmp.crs.CropLeft"] = left / w
    crop_parm["Xmp.crs.CropTop"] = top / h
    crop_parm["Xmp.crs.CropRight"] = right / w
    crop_parm["Xmp.crs.CropBottom"] = bottom / h
    crop_parm["Xmp.crs.CropAngle"] = 0
    crop_parm["Xmp.tiff.ImageWidth"] = w
    crop_parm["Xmp.tiff.ImageLength"] = h
    crop_parm["Xmp.tiff.Orientation"] = 1

    if filepath.suffix.upper() == ".DNG":
        crop_parm["Xmp.crs.Exposure2012"] = -0.01

    tempdir = tempfile.TemporaryDirectory(dir="/dev/shm")
    temp_dir_path = pathlib.Path(tempdir.name)

    temp_xmp_path = pathlib.Path(temp_dir_path, "orig.xmp")
    filepath_lr_xmp = filepath.with_suffix(".xmp")

    # Create temp files from extracted data
    with ExifTool() as et:
        xmp_editing_utils.copy_xmp_temp(filepath, temp_xmp_path, et=et)

    # write xmp
    with pyexiv2.Image(temp_xmp_path.as_posix()) as img:
        img.modify_xmp(crop_parm)
        img.read_xmp()

    copy2(temp_xmp_path, filepath_lr_xmp)

    tempdir.cleanup()

    if debug:
        im = xmp_editing_utils.draw_cropline(original_img, new_box)
        max_size = 800
        scale_factor = max_size / max([w, h])
        small_w, small_h = int(w * scale_factor), int(h * scale_factor)

        im = im.resize((small_w, small_h))

        debug_filename = pathlib.Path(debug_path, filepath.name + ".jpg")
        im.save(debug_filename, quality=100, subsampling=0)


def main():

    p = root_path.glob("*")
    files = [x for x in p if x.is_file()]

    supported_files = set.union(
        set(xmp_editing_utils.raw_files), set(xmp_editing_utils.other_files)
    )
    files = [x for x in files if x.suffix.upper() in supported_files]

    with ExifTool() as et:
        for filepath in files:
            # kept in a simple for loop because limited by network bandwidth
            logger.info(f"Processing: {filepath}")
            try:
                process_file(
                    filepath=filepath,
                    debug_path=debug_path,
                    debug=debug,
                    crop_addition=crop_addition,
                    et=et,
                )
            except Exception as e:
                logger.error(f"Failed to process: {filepath}")
                logger.error(f"Exception: {e}")


if __name__ == "__main__":
    logger.info("Running main()")
    main()
