import importlib

import pyexiv2
from logzero import logger
from slpp import slpp as lua

# these keys and start/stop blocks are extracted from a working xmp file for testing
start = """
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.5-c002 1.148022, 2012/07/15-18:06:45        ">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:tiff="http://ns.adobe.com/tiff/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
"""


end = """>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""


# this is an example string pulled from Adobe_imageDevelopSettings
test = """s = { AutoGrayscaleMix = true,
AutoLateralCA = 0,
AutoWhiteVersion = 134348800,
Blacks2012 = 0,
Brightness = 50,
CameraProfile = "Adobe Standard",
CameraProfileDigest = "87FB0EDC503E332309FB5DE5C5C65125",
Clarity2012 = 15,
ColorNoiseReduction = 25,
Contrast = 25,
Contrast2012 = 31,
ConvertToGrayscale = false,
CropAngle = -2.18554,
CropBottom = 0.945854,
CropConstrainAspectRatio = true,
CropLeft = 0.01504,
CropRight = 0.98496,
CropTop = 0.054146,
DefringeGreenAmount = 0,
DefringeGreenHueHi = 60,
DefringeGreenHueLo = 40,
DefringePurpleAmount = 0,
DefringePurpleHueHi = 70,
DefringePurpleHueLo = 30,
Exposure = 0,
Exposure2012 = 0.3,
GrainSize = 25,
Highlights2012 = -14,
LensManualDistortionAmount = 0,
LensProfileEnable = 0,
LensProfileSetup = "LensDefaults",
LuminanceNoiseReductionContrast = 0,
PerspectiveHorizontal = 0,
PerspectiveRotate = 0,
PerspectiveScale = 100,
PerspectiveVertical = 0,
PerspectiveX = 0,
PerspectiveY = 0,
ProcessVersion = "6.7",
RedEyeInfo = {  },
RetouchInfo = {  },
Shadows = 5,
Shadows2012 = 26,
SharpenDetail = 25,
SharpenEdgeMasking = 0,
SharpenRadius = 1,
Sharpness = 25,
Temperature = 5900,
Tint = 16,
ToneCurve = { 0,
0,
32,
22,
64,
56,
128,
128,
192,
196,
255,
255 },
ToneCurveBlue = { 0,
0,
255,
255 },
ToneCurveGreen = { 0,
0,
255,
255 },
ToneCurveName = "Medium Contrast",
ToneCurveName2012 = "Linear",
ToneCurvePV2012 = { 0,
0,
255,
255 },
ToneCurvePV2012Blue = { 0,
0,
255,
255 },
ToneCurvePV2012Green = { 0,
0,
255,
255 },
ToneCurvePV2012Red = { 0,
0,
255,
255 },
ToneCurveRed = { 0,
0,
255,
255 },
UprightCenterMode = 0,
UprightCenterNormX = 0.5,
UprightCenterNormY = 0.5,
UprightFocalLength35mm = 35,
UprightFocalMode = 0,
UprightFourSegmentsCount = 0,
UprightPreview = false,
UprightTransformCount = 6,
UprightVersion = 151388160,
Version = "9.12",
Vibrance = 10,
WhiteBalance = "As Shot",
Whites2012 = 0 }


"""

# a shortened version of the above for testing
test = """s = { AutoGrayscaleMix = true,
AutoLateralCA = 0,
CameraProfile = "Adobe Standard",
CameraProfileDigest = "87FB0EDC503E332309FB5DE5C5C65125",
Clarity2012 = 15,
ConvertToGrayscale = false,
CropAngle = -2.18554,

RetouchInfo = {  },
ToneCurveRed = { 0,
0,
255,
255 },
UprightCenterMode = 0,
WhiteBalance = "As Shot",
Whites2012 = 0 }
"""


# with importlib.resources.files("tags").joinpath("crs_tags.txt").open('r', encoding="utf8") as f:
with importlib.resources.files("tags").joinpath("tags_from_darktable.txt").open(
    "r", encoding="utf8"
) as f:
    tags = f.read().splitlines()


if test[0:4] == "s = ":
    data = lua.decode(test[4:])
else:
    logger.critical("unexpected start to lua string")
    raise (BaseException("unexpected start to lua string"))


# tagintersect=set(tags).intersection(set(data.keys()))

process_ver = 6.7
crs_items = []
crs_items.append(f'   crs:ProcessVersion="{process_ver}"\n')

# the crs keys need to be in order, therefore we iterate over that list
# the list may not be complete, but it is one that works.
for key in tags:
    # val=data[key]
    try:
        if key == "HasCrop" and ("CropTop" in data.keys()):
            logger.info("crop enabled")
            crs_items.append('   crs:HasCrop="True"\n')
            continue
        val = data[key]
    except KeyError:
        logger.debug(f"missing {key}")
        continue

    # for key,val in data.items():
    # print(key,val,type(key),type(val))
    if isinstance(val, int) or isinstance(val, str) or isinstance(val, float):
        temp_string = f'   crs:{key}="{val}"\n'
    else:
        logger.warning(f"not sure how to handle {key}")
        temp_string = f'   crs:{key}="{val}"\n'
        # temp_string=f'   crs:{key}={val}\n'

    crs_items.append(temp_string)

# if "CropTop" in data.keys():
#     crs_items.append('   crs:HasCrop="True"')


print(start + "".join(crs_items) + end)


tagintersect = set(tags).intersection(set(data.keys()))
intersect_dict = {f"Xmp.crs.{k}": data[k] for k in tagintersect}
if "Xmp.crs.CropTop" in intersect_dict.keys():
    intersect_dict["Xmp.crs.HasCrop"] = "True"


img = pyexiv2.Image(r"xmp/london.xmp")
exif = img.read_exif()
iptc = img.read_iptc()
xmp = img.read_xmp()

img.modify_xmp(intersect_dict)


for key in tags:
    # val=data[key]
    try:
        if "CropTop" in data.keys():
            logger.info("crop enabled")
            crs_items.append('   crs:HasCrop="True"\n')
            continue
        val = data[key]
    except KeyError:
        logger.debug(f"missing {key}")
        continue

    # for key,val in data.items():
    # print(key,val,type(key),type(val))
    if isinstance(val, int) or isinstance(val, str) or isinstance(val, float):
        temp_string = f'   crs:{key}="{val}"\n'
    else:
        logger.warning(f"not sure how to handle {key}")
        temp_string = f'   crs:{key}="{val}"\n'
        # temp_string=f'   crs:{key}={val}\n'

    crs_items.append(temp_string)

img.close()
