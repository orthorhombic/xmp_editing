# inspired by:
# https://github.com/z80z80z80/autocrop
# https://github.com/smc8050/Dias_Autocrop
import pathlib
import tempfile
from shutil import copy2

import cv2
import logzero
import pyexiv2
import rawpy
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

# img_in_path = "untracked/test/raw0032.dng"

img_name = "raw0032.dng"

crop_addition = -5

debug = True

# root_path = pathlib.Path(config_data["root_path"])

root_path = pathlib.Path("untracked/test")
img_filename = "raw0032.dng"
filepath = pathlib.Path(root_path, img_filename)

if debug:
    debug_path = pathlib.Path(root_path, "debug")
    debug_path.mkdir(parents=True, exist_ok=True)


with rawpy.imread(filepath.as_posix()) as raw:
    imcv2 = raw.postprocess()

tempdir = tempfile.TemporaryDirectory(dir="/dev/shm")
temp_dir_path = pathlib.Path(tempdir.name)

temp_xmp_path = pathlib.Path(temp_dir_path, "orig.xmp")
base_name = img_name.split(".")[0]
filepath_lr_xmp = pathlib.Path(root_path, base_name + ".xmp")

# Create temp files from extracted data
with ExifTool() as et:
    xmp_editing_utils.copy_xmp_temp(filepath, temp_xmp_path, et=et)

# imcv2 = cv2.imread(filepath)

# TODO: Rotation before cropping has to be optimised (more accuracy)
# theta = get_rotation(imcv2)
# imcv2 = rotate_image(imcv2, 180 * theta / np.pi - 90)

img = Image.fromarray(
    cv2.cvtColor(imcv2, cv2.COLOR_BGR2RGB)
)  # convert from cv2 image file to pil image file
original_img = img
w, h = original_img.size
blurred_img = img.filter(ImageFilter.GaussianBlur(radius=4))  # to remove outlier pixels
binary_img = xmp_editing_utils.convert_to_binary(blurred_img, 40, 255)
bg = Image.new(binary_img.mode, binary_img.size)
diff = ImageChops.difference(binary_img, bg)
bbox = diff.getbbox()
# left, top, right, bottom
# 0%, 0%, 100%, 100%

if bbox:
    color_control = xmp_editing_utils.get_control_value(original_img, bbox)
    if color_control > 1.5:
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
crop_parm["Xmp.crs.Exposure2012"] = -0.01
crop_parm["Xmp.tiff.ImageWidth"] = w
crop_parm["Xmp.tiff.ImageLength"] = h
crop_parm["Xmp.tiff.Orientation"] = 1

# write xmp
with pyexiv2.Image(temp_xmp_path.as_posix()) as img:
    img.modify_xmp(crop_parm)
    final_xmp_dict = img.read_xmp()


copy2(temp_xmp_path, filepath_lr_xmp)


tempdir.cleanup()

if debug:
    im = xmp_editing_utils.draw_cropline(original_img, new_box)
    max_size = 800
    scale_factor = max_size / max([w, h])
    small_w, small_h = int(w * scale_factor), int(h * scale_factor)

    im = im.resize((small_w, small_h))

    debug_filename = pathlib.Path(debug_path, img_filename + ".jpg")
    im.save(debug_filename, quality=100, subsampling=0)
