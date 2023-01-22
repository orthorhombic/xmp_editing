import importlib.resources
import pathlib
import shutil
import sqlite3
import tempfile

import logzero
import pandas as pd
import pyexiv2
import yaml
from exiftool import ExifTool
from logzero import logger
from slpp import slpp as lua

from xmp_editing_utils import copy_xmp_temp

# NOTE: After import into darktable, the metadata "write sidecar files" button needs to be pressed
# This will write from the database (including imported Lightroom date) to the new darktable xmp files

pyexiv2.set_log_level(1)
logzero.logfile("rotating-logfile.log", maxBytes=1e8, backupCount=3)
logger.setLevel(level="DEBUG")
# load settings
config = importlib.resources.files("untracked").joinpath("config.yml")

with open(config) as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

root_path = pathlib.Path(config_data["root_path"])
update_file = config_data["update_file"]
catalog_file = config_data["catalog_file"]
RootFolderName = config_data["RootFolderName"]

# load tags darktable can process:
# with importlib.resources.files("tags").joinpath("crs_tags.txt").open('r', encoding="utf8") as f:
with importlib.resources.files("tags").joinpath("tags_from_darktable.txt").open(
    "r", encoding="utf8"
) as f:
    tags = f.read().splitlines()

# test query of the view created in img_view.sql
# limit this to only those filetypes supported by DarkTable
# https://docs.darktable.org/usermanual/development/en/overview/supported-file-formats/
sql_query = f"""
select *
from IMG
WHERE 
    --(
    --baseName like 'Crystal-0075%'
    --or baseName like 'Crystals-1600%'
    --or baseName like 'London-3471%'
    --or baseName like 'LWP42267%'
    --or baseName like 'wedding 583%'
    --or baseName like 'Star Trails-4%'
    --or baseName like 'Na3Bi-111345%'
    --) 
    --(PathFromRoot like '2006%' or PathFromRoot like '2021%' or PathFromRoot like '2013%' or PathFromRoot like '2014%' or PathFromRoot like '2018%' or PathFromRoot like '2010%')
    RootFolderName = '{RootFolderName}'
    and 
    upper(FileType) in (
    -- Regular formats
    '3FR', 'ARI', 'ARW', 'BAY', 'BMQ', 'CAP', 'CINE', 'CR2', 'CR3', 'CRW',
    'CS1', 'DC2', 'DCR', 'DNG', 'GPR', 'ERF', 'FFF', 'EXR', 'IA', 'IIQ',
    'JPEG', 'JPG', 'K25', 'KC2', 'KDC', 'MDC', 'MEF', 'MOS', 'MRW', 'NEF',
    'NRW', 'ORF', 'PEF', 'PFM', 'PNG', 'PXN', 'QTK', 'RAF', 'RAW', 'RDC',
    'RW1', 'RW2', 'SR2', 'SRF', 'SRW', 'STI', 'TIF', 'TIFF', 'X3F',
    -- Extended Formats
    'J2C', 'J2K', 'JP2', 'JPC',
    'BMP', 'DCM', 'GIF', 'JNG', 'JPC', 'JP2', 'MIFF',
    'MNG', 'PBM', 'PGM', 'PNM', 'PPM', 'WEBP'
    )
"""

# Creating the path to the lightroom catalog
catalog = importlib.resources.files("untracked").joinpath(catalog_file)

# Create your connection.
cnx = sqlite3.connect(catalog)
# Load all files and their xmp/processing data into memory
# not very efficient, but probably OK for 100k photos
df = pd.read_sql_query(sql_query, cnx)
cnx.close()


def reprocess_tuples(xmp_dict: dict) -> None:

    keys_of_interest = {
        "Xmp.crs.ToneCurvePV2012",
        "Xmp.crs.ToneCurve",
        "Xmp.crs.ToneCurveRed",
        "Xmp.crs.ToneCurveBlue",
        "Xmp.crs.ToneCurveGreen",
    }
    keys_set = set(xmp_dict.keys())
    keys_to_fix = keys_of_interest.intersection(keys_set)

    # based on the darktable code, it looks like this is expected to be a list of tuples/lists
    for key in keys_to_fix:
        temp_list = xmp_dict[key]
        if len(temp_list) % 2 == 1:
            raise ValueError(f"Unexpected length of {key}")

        new_list = []
        for i in range(len(temp_list) // 2):
            # pyexiv2 uses ", " as a separator for multiple values.
            # So it might automatically split the string you want to write.
            # https://github.com/LeoHsiao1/pyexiv2/blob/master/docs/Tutorial.md
            new_list.append(f"{temp_list[2*i]}, {temp_list[2*i+1]}")

        xmp_dict[key] = new_list


def parse_lightroom_processtext(
    lightroom_processtext: str, tags: list[str], process_ver: str
):
    """Process lightroom parameters compatible with darktable.
    See https://github.com/darktable-org/darktable/blob/master/src/develop/lightroom.c for info."""

    if len(lightroom_processtext) == 0:
        # if no process text, return empty dictionary
        return {}
    elif lightroom_processtext[0:4] == "s = ":
        data = lua.decode(lightroom_processtext[4:])
    else:
        logger.critical("unexpected start to lua string")
        raise (BaseException("unexpected start to lua string"))

    tagintersect = set(tags).intersection(set(data.keys()))
    intersect_dict = {f"Xmp.crs.{k}": data[k] for k in tagintersect}

    # Find keys that need to be reprocessed
    intersect_dict.keys()

    # reprocessing of the tone curve tuples will be handled right before updating xmp to avoid duplicate processing

    # keep process version for future reference, though this does not
    # appear to be used by darktable.
    lua_process_version = data.get("ProcessVersion")
    if lua_process_version is not None:
        intersect_dict["Xmp.crs.ProcessVersion"] = lua_process_version
    else:
        intersect_dict["Xmp.crs.ProcessVersion"] = process_ver

    return intersect_dict


def check_and_set_crop(xmp_dict: dict) -> None:
    required_crop_fields = {
        "Xmp.crs.CropTop",
        "Xmp.crs.CropRight",
        "Xmp.crs.CropLeft",
        "Xmp.crs.CropBottom",
        "Xmp.crs.CropAngle",
    }
    intersection_size = len(required_crop_fields.intersection(set(xmp_dict.keys())))
    # if any crop fields are specified, set the crop attribute to True
    if intersection_size > 0:
        xmp_dict["Xmp.crs.HasCrop"] = "True"
        logger.debug("Set HasCrop")


def check_drop_modify(file_to_modify, xmp_to_clean):
    extra_keys_to_drop = []

    with pyexiv2.Image(file_to_modify.as_posix()) as img:
        img_xmp = img.read_xmp()

        for k, v in img_xmp.items():
            if v in ['type="Struct"', 'type="Seq"', 'type="Bag"']:
                extra_keys_to_drop.append(k)

        # drop fields if anything was identified
        if len(extra_keys_to_drop) > 0:
            drop_fields(xmp_to_clean, extra_keys=extra_keys_to_drop)

        img.modify_xmp(xmp_to_clean)


def extract_xmp(xmp_file: pathlib.PosixPath) -> dict:
    with pyexiv2.Image(xmp_file.as_posix()) as img:
        file_xmp = img.read_xmp()

    drop_fields(file_xmp)
    return file_xmp


def drop_fields(xmp_dict: dict, extra_keys: list = None):
    """Operates in place on the provided XMP dictionary to remove problematic entries.
    These include accompanying tags for anything with 'type="Struct"' or 'type="Seq"'
    Drop bad tags like "Xmp.xmpMM.History[x]"
    history tags cannot be updated per documentation: https://github.com/LeoHsiao1/pyexiv2/blob/master/docs/Tutorial.md
    when reading in this or anything with ", " in them, it gets messed up
    """
    keys_list = list(xmp_dict.keys())
    bad_keys = []
    if extra_keys is not None:
        bad_keys = bad_keys + extra_keys
    drop_set = set()
    for k, v in xmp_dict.items():
        if v in ['type="Struct"', 'type="Seq"']:
            bad_keys.append(k)

    for key in bad_keys:
        bad_temp = [x for x in keys_list if x.startswith(key)]
        drop_set.update(bad_temp)

    # drop everything from the set
    [xmp_dict.pop(key) for key in drop_set]

    # return xmp_dict


def check_crop_fields(xmp_dict: dict):
    if str(xmp_dict.get("Xmp.crs.HasCrop")).lower() == "true":
        required_fields = {
            "CropTop",
            "CropRight",
            "CropLeft",
            "CropBottom",
            "CropAngle",
            # NOTE: While testing indicates the below image width/length/orientation
            # are needed, no missing tags have been observed.
            "ImageWidth",
            "ImageLength",
            "Orientation",
        }
        for key in xmp_dict.keys():
            short_key = key.split(".")[-1]
            required_fields.discard(short_key)

        if len(required_fields) > 0:
            logger.debug(f"XMP - Missing required crop fields: {required_fields}")
            return required_fields

    # return empty set if no problems
    return set()


def crop_fields_from_missing(missing_fields: dict):
    # look for crop fields in the provided xmp and return a dictionary of the missing fields
    crop_fix = {}

    if "CropTop" in missing_fields:
        crop_fix["Xmp.crs.CropTop"] = 0.0
    if "CropRight" in missing_fields:
        crop_fix["Xmp.crs.CropRight"] = 1.0
    if "CropLeft" in missing_fields:
        crop_fix["Xmp.crs.CropLeft"] = 0.0
    if "CropBottom" in missing_fields:
        crop_fix["Xmp.crs.CropBottom"] = 1.0
    if "CropAngle" in missing_fields:
        crop_fix["Xmp.crs.CropAngle"] = 0.0

    return crop_fix


def process_file(data_series, et, update_file: bool = True):

    path_from_root = data_series.loc["PathFromRoot"]
    temp_path = data_series.loc["BaseName"] + "." + data_series.loc["FileType"]
    lr_xmp_path = data_series.loc["BaseName"] + ".xmp"
    darktable_xmp_path = (
        data_series.loc["BaseName"] + "." + data_series.loc["FileType"] + ".xmp"
    )
    lightroom_processtext = data_series.loc["processtext"]
    process_ver = data_series.loc["processversion"]
    db_xmp = data_series.loc["xmp"]

    # combine path
    filepath = pathlib.Path(root_path, path_from_root, temp_path)
    filepath_lr_xmp = pathlib.Path(root_path, path_from_root, lr_xmp_path)
    filepath_darktable_xmp = pathlib.Path(root_path, path_from_root, darktable_xmp_path)

    # check the file first, abort if it isn't there
    if not filepath.is_file():
        logger.error(f"File {filepath} not found")
        return

    # set up temp folder in tmpfs to keep it in memory
    # /dev/shm is a ramdisk. Create files here for ephemeral transformations that require writing to disk
    tempdir = tempfile.TemporaryDirectory(dir="/dev/shm")
    temp_dir_path = pathlib.Path(tempdir.name)

    # paths: original file xmp copy, database xmp, sidecar file.xmp, sidecar file.ext.xmp,
    temp_files = {
        "orig": pathlib.Path(temp_dir_path, "orig.xmp"),
        "db": pathlib.Path(temp_dir_path, "db.xmp"),
        "sidecar_lr": pathlib.Path(temp_dir_path, "sidecar.xmp"),
        "sidecar_darktable": pathlib.Path(temp_dir_path, "sidecar.ext.xmp"),
    }

    # Create temp files from extracted data
    copy_xmp_temp(filepath, temp_files["orig"], et=et)

    # write database XMP to temp
    with open(temp_files["db"], "w") as f:
        f.write(db_xmp)

    # try sidecar files
    # # TODO: case insensitive implementation
    copy_xmp_temp(filepath_lr_xmp, temp_files["sidecar_lr"], et=et, warn=True)
    if filepath_darktable_xmp.is_file():
        logger.warning(
            f"DarkTable XMP Exists: Lightroom data will not be imported: {filepath_darktable_xmp}"
        )
        copy_xmp_temp(filepath_darktable_xmp, temp_files["sidecar_darktable"], et=et)

    # prepare data from database for stacking
    intersect_dict = parse_lightroom_processtext(
        lightroom_processtext=lightroom_processtext, tags=tags, process_ver=process_ver
    )

    # stack data
    temp_xmp = {}
    for k, v in temp_files.items():
        if v.is_file():
            logger.debug(f"loading {v}")
            temp_xmp[k] = extract_xmp(v)

    # combine dictionaries
    combined_xmp = {}
    order = [
        "orig",
        "db",
        "sidecar_lr",
        "sidecar_darktable",
    ]
    for key in order:
        xmp = temp_xmp.get(key)
        if xmp is not None:
            combined_xmp.update(xmp)

    # add data from database
    combined_xmp.update(intersect_dict)

    check_and_set_crop(combined_xmp)

    # fix any issues with tonecurves in them
    reprocess_tuples(combined_xmp)

    # if the label is none, remove it. This would otherwise get set as a purple label
    # field set to none so if modifying existing file the field is removed
    # to be successful, this must be applied after doing any "fixes" on the xmp
    field_to_delete = "Xmp.xmp.Label"
    if (
        field_to_delete in combined_xmp.keys()
        and str(combined_xmp[field_to_delete]) == "None"
    ):
        # new_xmp.modify_xmp({field_to_delete: None})
        combined_xmp[field_to_delete] = None
        logger.info(f"Problematic XMP: {field_to_delete} deleted")

    # before saving changes, check state of crop metadata
    required_fields = check_crop_fields(xmp_dict=combined_xmp)
    if len(required_fields) > 0:
        # create dictionary for missing fields
        crop_fix = crop_fields_from_missing(required_fields)

        if len(crop_fix) > 0:
            combined_xmp.update(crop_fix)
            logger.debug(f"Crop Data - Fixed: {crop_fix.keys()}")

    if update_file:
        # only execute updates if not in No-Op Mode
        if filepath_lr_xmp.is_file():
            # updating file
            # copy data back to LR format file
            check_drop_modify(file_to_modify=filepath_lr_xmp, xmp_to_clean=combined_xmp)

            logger.debug(f"updated {filepath_lr_xmp}")
        else:

            check_drop_modify(
                file_to_modify=temp_files["orig"], xmp_to_clean=combined_xmp
            )

            # copy "original" as this is the file corresponding to new_xmp
            shutil.copy(temp_files["orig"], filepath_lr_xmp)
            logger.debug(f"copied file to {filepath_lr_xmp}")

    if not filepath_lr_xmp.is_file() and not update_file:
        logger.error(f"No-Op Mode: File {filepath} not found to check")
        tempdir.cleanup()
        return

    final_xmp = pyexiv2.Image(filepath_lr_xmp.as_posix())
    final_xmp_dict = final_xmp.read_xmp()

    # Final check of output file
    label = final_xmp_dict.get("Xmp.xmp.Label")
    if label == "None" and update_file:
        logger.error(f"Final_XMP - Problematic Label: None")

    # check for all crop fields and alert. try one more time to fix
    required_fields = check_crop_fields(xmp_dict=final_xmp_dict)

    if len(required_fields) > 0:
        logger.warning(f"Final_XMP - Missing required fields: {required_fields}")

        # create dictionary for missing fields
        crop_fix = crop_fields_from_missing(required_fields)

        # disable update in No-Op Mode
        if update_file and len(crop_fix) > 0:
            final_xmp.modify_xmp(crop_fix)
            logger.warning(f"Final_XMP - Fixed: {crop_fix.keys()}")

    final_xmp.close()

    # clean up temp folder:
    tempdir.cleanup()


def main():
    with ExifTool() as et:
        for i, data_series in df.iterrows():
            logger.info(
                f"Index: {i}, name: {data_series.loc['PathFromRoot']}{data_series.loc['BaseName']}.{data_series.loc['FileType']}"
            )
            try:
                process_file(data_series=data_series, et=et, update_file=update_file)
            except Exception as e:
                logger.error(
                    f"Failed to process: {data_series.loc['PathFromRoot']}{data_series.loc['BaseName']}.{data_series.loc['FileType']}"
                )
                logger.error(f"Exception: {e}")


if __name__ == "__main__":
    logger.info("Running main()")
    main()
