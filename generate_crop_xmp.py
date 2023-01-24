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

if config_data.get("root_path") is not None:
    root_path = pathlib.Path(config_data["root_path"])  # default "untracked"
else:
    root_path = "untracked"

if config_data.get("debug") is not None:
    debug = config_data["debug"]
else:
    debug = False

if config_data.get("crop_addition") is not None:
    crop_addition = config_data["crop_addition"]  # default -5
else:
    crop_addition = 5

if config_data.get("threshold") is not None:
    threshold = config_data["threshold"]  # default 45
else:
    threshold = 50

if config_data.get("blur_radius") is not None:
    blur_radius = config_data["blur_radius"]  # default 4, if -1 auto
else:
    blur_radius = -1

if debug:
    debug_path = pathlib.Path(root_path, "debug")
    debug_path.mkdir(parents=True, exist_ok=True)


def process_file(
    filepath: pathlib.Path,
    debug_path: pathlib.Path,
    debug: bool,
    crop_addition: int,
    blur_radius: int,
    et: ExifTool,
):

    if filepath.suffix.upper() in xmp_editing_utils.raw_files:
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

    if blur_radius == -1:
        blur_radius = min([w, h]) // 400  # number picked based on few tests
        blur_radius = min(
            [blur_radius, 12]
        )  # apply a ceiling so it doesn't get too high
    blurred_img = img.filter(
        ImageFilter.GaussianBlur(radius=blur_radius)
    )  # to remove outlier pixels
    binary_img = xmp_editing_utils.convert_to_binary(blurred_img, threshold, 255)
    bg = Image.new(binary_img.mode, binary_img.size)
    diff = ImageChops.difference(binary_img, bg)
    bbox = diff.getbbox()
    # left, top, right, bottom
    # 0%, 0%, 100%, 100%

    xmp_param = {}

    if bbox == (0, 0, w, h):
        logger.error(f"No cropping detected for {filepath.as_posix()}")
    elif bbox:
        color_control = xmp_editing_utils.get_control_value(original_img, bbox)
        if color_control > threshold / 2:
            logger.warning(f"Crop bounds may be problematic for {filepath.as_posix()}")
        # adjust based on crop_addition

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

        xmp_param["Xmp.crs.HasCrop"] = "True"
        xmp_param["Xmp.crs.CropLeft"] = left / w
        xmp_param["Xmp.crs.CropTop"] = top / h
        xmp_param["Xmp.crs.CropRight"] = right / w
        xmp_param["Xmp.crs.CropBottom"] = bottom / h
        xmp_param["Xmp.crs.CropAngle"] = 0

        if debug:
            im = xmp_editing_utils.draw_cropline(original_img, new_box)
            max_size = 800
            scale_factor = max_size / max([w, h])
            small_w, small_h = int(w * scale_factor), int(h * scale_factor)

            im = im.resize((small_w, small_h))

            debug_filename = pathlib.Path(debug_path, filepath.name + ".jpg")
            im.save(debug_filename, quality=100, subsampling=0)

    else:
        raise RuntimeError("Could not find a bounding box for crop")

    xmp_param["Xmp.tiff.ImageWidth"] = w
    xmp_param["Xmp.tiff.ImageLength"] = h
    xmp_param["Xmp.tiff.Orientation"] = 1

    if filepath.suffix.upper() == ".DNG":
        xmp_param["Xmp.crs.Exposure2012"] = -0.01

    tempdir = tempfile.TemporaryDirectory(dir="/dev/shm")
    temp_dir_path = pathlib.Path(tempdir.name)

    temp_xmp_path = pathlib.Path(temp_dir_path, "orig.xmp")
    filepath_lr_xmp = filepath.with_suffix(".xmp")

    # Create temp files from extracted data
    with ExifTool() as et:
        xmp_editing_utils.copy_xmp_temp(filepath, temp_xmp_path, et=et)

    # write xmp
    with pyexiv2.Image(temp_xmp_path.as_posix()) as img:
        img.modify_xmp(xmp_param)
        img.read_xmp()

    copy2(temp_xmp_path, filepath_lr_xmp)

    tempdir.cleanup()


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
                    blur_radius=blur_radius,
                    et=et,
                )
            except Exception as e:
                logger.error(f"Failed to process: {filepath}")
                logger.error(f"Exception: {e}")


if __name__ == "__main__":
    logger.info("Running main()")
    main()
