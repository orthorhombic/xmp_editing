import pathlib
from exiftool import ExifTool
from logzero import logger
import pyexiv2
import cv2
from PIL import ImageChops, Image, ImageDraw, ImageStat, ImageFilter
import numpy as np


empty_xml = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 5.5.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/">
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""


def copy_xmp_temp(
    from_file: pathlib.PosixPath,
    to_file: pathlib.PosixPath,
    et: ExifTool,
    warn: bool = False,
):

    # exiftool implementation. Does not contain much error handling
    # will not raise an error if the file does not exist
    if not from_file.is_file():
        if warn:
            logger.warning(f"File {from_file} not found")
        else:
            logger.debug(f"File {from_file} not found")
        return

    # run exiftool command on file to return xmp string
    file_raw_xmp = et.execute(
        *["-xmp", "-b", str(from_file.as_posix()), "-api", "LargeFileSupport=1"]
    )
    # strip null characters common in some languages
    file_raw_xmp = file_raw_xmp.strip("\x00")
    if file_raw_xmp == "":
        # raise ValueError(f"Empty XMP retrieved for {from_file}")
        logger.warning(f"Empty XMP retrieved for {from_file}. Using empty XML string")
        # logger.debug(f"Problem working on {from_file}: {e}")
        file_raw_xmp = empty_xml

    # write data to temp
    with open(to_file, "w") as f:
        f.write(file_raw_xmp)
    # confirm the raw xmp can be opened - this requires the log level is not at 4 (muted)
    with pyexiv2.Image(to_file.as_posix()) as img:
        file_xmp = img.read_xmp()


def convert_to_binary(image, lower_threshold, upper_threshold):
    """
    This function converts a image to a binary image
    :param image: OpenCV image array
    :return: Binary image as OpenCV image array
    """
    original_imgcv2 = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    grayImage_imgcv2 = cv2.cvtColor(original_imgcv2, cv2.COLOR_BGR2GRAY)
    (thresh, blackAndWhiteImage) = cv2.threshold(
        grayImage_imgcv2, lower_threshold, upper_threshold, cv2.THRESH_BINARY
    )
    # cv2.imwrite("binary.jpg", blackAndWhiteImage)
    image = Image.fromarray(
        cv2.cvtColor(blackAndWhiteImage, cv2.COLOR_BGR2RGB)
    )  # convert from cv2 image file to pil image file
    return image


def draw_cropline(im, bbox):
    """
    This function draws the bounding box in the picture
    :param im: PIL image
    :param bbox: PIL bbox array
    :return: PIL image with drawn bbox
    """
    draw = ImageDraw.Draw(im)
    draw.rectangle(((bbox[0], bbox[1]), (bbox[2], bbox[3])), outline="red", width=5)
    return im


def get_control_value(im, bbox):
    """
    This function gets the mean color value outside of the bounding box (bbox).
    The closer to 0 the darker is the section that will be removed. If the value is
    higher than a certain threshold this could indicate an wrong autocrop boundingbox
    and non black pixels are cropped.
    :param im: PIL Image
    :param bbox: PIL bbox array
    :return: mean color value (float)
    """
    control_img = im
    mask_layer = Image.new("L", control_img.size, 255)
    draw = ImageDraw.Draw(mask_layer)
    draw.rectangle(((bbox[0], bbox[1]), (bbox[2], bbox[3])), fill=0)
    avg_list = ImageStat.Stat(control_img, mask=mask_layer).mean
    avg = round(sum(avg_list) / 3, 2)
    return avg
