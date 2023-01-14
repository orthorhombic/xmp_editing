import importlib.resources
import pathlib
import re
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

# NOTE: After import into darktable, the metadata "refresh EXIF" button needs to be pressed
# This will sync the database with the new darktable xmp files

pyexiv2.set_log_level(1)
logzero.logfile("rotating-logfile.log", maxBytes=1e8, backupCount=3)
logger.setLevel(level="DEBUG")
# load settings
config = importlib.resources.files("untracked").joinpath("config.yml")

with open(config) as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

root_path = pathlib.Path(config_data["root_path"])

empty_xml = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 5.5.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/">
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""

# load tags darktable can process:
# with importlib.resources.files("tags").joinpath("crs_tags.txt").open('r', encoding="utf8") as f:
with importlib.resources.files("tags").joinpath("tags_from_darktable.txt").open(
    "r", encoding="utf8"
) as f:
    tags = f.read().splitlines()

# test query of the view created in img_view.sql
# limit this to only those filetypes supported by DarkTable
# https://docs.darktable.org/usermanual/development/en/overview/supported-file-formats/
sql_query = """
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
    (PathFromRoot like '2013%' or PathFromRoot like '2014%')
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
catalog = importlib.resources.files("untracked").joinpath("LightroomCatalog.lrcat")

# Create your connection.
cnx = sqlite3.connect(catalog)
# Load all files and their xmp/processing data into memory
# not very efficient, but probably OK for 100k photos
df = pd.read_sql_query(sql_query, cnx)
cnx.close()


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
    required_crop_fields = {
        "Xmp.crs.CropTop",
        "Xmp.crs.CropRight",
        "Xmp.crs.CropLeft",
        "Xmp.crs.CropBottom",
        "Xmp.crs.CropAngle",
    }
    intersection_size = len(
        required_crop_fields.intersection(set(intersect_dict.keys()))
    )
    # if any crop fields are specified, set the crop attribute to True
    if intersection_size > 0:
        intersect_dict["Xmp.crs.HasCrop"] = "True"

    if "Xmp.crs.ToneCurvePV2012" in intersect_dict.keys():
        # based on the darktable code, it looks like this is expected to be a list of tuples/lists
        temp_list = intersect_dict["Xmp.crs.ToneCurvePV2012"]
        if len(temp_list) % 2 == 1:
            raise ValueError("Unexpected length of ToneCurvePV2012")

        new_list = []
        for i in range(len(temp_list) // 2):
            # pyexiv2 uses ", " as a separator for multiple values.
            # So it might automatically split the string you want to write.
            # https://github.com/LeoHsiao1/pyexiv2/blob/master/docs/Tutorial.md
            new_list.append(f"{temp_list[2*i]},{temp_list[2*i+1]}")

        intersect_dict["Xmp.crs.ToneCurvePV2012"] = new_list

    # keep process version for future reference, though this does not
    # appear to be used by darktable.
    lua_process_version = data.get("ProcessVersion")
    if lua_process_version is not None:
        intersect_dict["Xmp.crs.ProcessVersion"] = lua_process_version
    else:
        intersect_dict["Xmp.crs.ProcessVersion"] = process_ver

    return intersect_dict


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


def check_drop_modify(file_to_modify, xmp_to_clean):
    extra_keys_to_drop = []

    with pyexiv2.Image(file_to_modify.as_posix()) as img:
        img_xmp = img.read_xmp()

        for k, v in img_xmp.items():
            if v in ['type="Struct"', 'type="Seq"']:
                extra_keys_to_drop.append(k)

        # drop fields if anything was identified
        if len(extra_keys_to_drop) > 0:
            drop_fields(xmp_to_clean, extra_keys=extra_keys_to_drop)

        img.modify_xmp(xmp_to_clean)


def extend_xmp(base: pyexiv2.core.Image, xmp_file: pathlib.PosixPath):

    with pyexiv2.Image(xmp_file.as_posix()) as img:
        file_xmp = img.read_xmp()

    # TODO: need to drop bad tags like "Xmp.xmpMM.History[x]"
    # history tags cannot be updated per documentation: https://github.com/LeoHsiao1/pyexiv2/blob/master/docs/Tutorial.md
    # when reading in this or anything with ", " in them, it gets messed up
    count = 0
    for k, v in file_xmp.items():
        if "," in v:
            logger.warning(f"found problematic key/value: {k}: {v}")
            count += 1

    # update xmp data
    if count > 0:
        logger.warning(f"fixing xmp")
        base.modify_xmp(_fix_xmp(file_xmp))
    else:
        base.modify_xmp(file_xmp)

    # return base


def extract_xmp(xmp_file: pathlib.PosixPath) -> dict:
    with pyexiv2.Image(xmp_file.as_posix()) as img:
        file_xmp = img.read_xmp()

    drop_fields(file_xmp)
    return file_xmp


ARRAY_IDX_PATTERN = re.compile(r"\[\d+\]")

# from https://github.com/pyinat/naturtag/pull/169/files


def _fix_xmp(xmp):
    """Fix some invalid XMP tags"""
    for k, v in xmp.items():
        # Flatten dict values, like {'lang="x-default"': value} -> value
        if isinstance(v, dict):
            xmp[k] = list(v.values())[0]
        # XMP won't accept both a single value and an array with the same key
        if k.endswith("]") and (nonarray_key := ARRAY_IDX_PATTERN.sub("", k)) in xmp:
            xmp[nonarray_key] = None
    xmp = {k: v for k, v in xmp.items() if v is not None}
    return xmp


def drop_fields(xmp_dict: dict, extra_keys: list = None):
    """Operates in place on the provided XMP dictionary to remove problematic entries.
    These include accompanying tags for anything with 'type="Struct"' or 'type="Seq"'
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
        # key="Xmp.xmpMM.History[1]"
        # r = re.compile(key+".*")
        # bad_key_iterator = filter(r.match, keys_list)

        bad_temp = [x for x in keys_list if x.startswith(key)]
        # print(f" from {key}, dropping: ", list(bad_temp))
        drop_set.update(bad_temp)

    # drop everything from the set
    [xmp_dict.pop(key) for key in drop_set]

    # return xmp_dict


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
        logger.warning(f"File {filepath} not found")
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
    copy_xmp_temp(filepath_lr_xmp, temp_files["sidecar_lr"], et=et)
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

    # if the label is none, remove it. This would otherwise get set as a purple label
    # field set to none so if modifying existing file the field is removed
    # to bes successful, this must be applied after doing any "fixes" on the xmp
    field_to_delete = "Xmp.xmp.Label"
    if (
        field_to_delete in combined_xmp.keys()
        and str(combined_xmp[field_to_delete]) == "None"
    ):
        # new_xmp.modify_xmp({field_to_delete: None})
        combined_xmp[field_to_delete] = None
        logger.info(f"Problematic XMP: {field_to_delete} deleted")

    # apply fixes to ensure clean write
    # new_xmp_dict = _fix_xmp(new_xmp_dict)

    if update_file:
        # only execute updates if not in No-Op Mode
    if filepath_lr_xmp.is_file():
        # update
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

    final_xmp = pyexiv2.Image(filepath_lr_xmp.as_posix())

    # need check to confirm there is an exif block with resolution in it
    # if HasCrop:
    #     needs:
    #         ImageWidth
    #         ImageLength
    #         Orientation

    if not filepath.is_file() and not update_file:
        logger.debug(f"No-Op Mode: File {filepath} not found to check")
        return

    final_xmp_dict = final_xmp.read_xmp()

    # Final check of output file
    label = final_xmp_dict.get("Xmp.xmp.Label")
    if label == "None" and update_file:
        logger.error(f"Final_XMP - Problematic Label: None")

    if str(final_xmp_dict.get("Xmp.crs.HasCrop")).lower() == "true":
        required_fields = {
            "CropTop",
            "CropRight",
            "CropLeft",
            "CropBottom",
            "CropAngle",
            "ImageWidth",
            "ImageLength",
            "Orientation",
        }
        for key in final_xmp_dict.keys():
            short_key = key.split(".")[-1]
            required_fields.discard(short_key)

        if len(required_fields) > 0:
            logger.warning(f"Final_XMP - Missing required fields: {required_fields}")

            # # fix exif data
            # exif_set = {"ImageWidth", "ImageLength", "Orientation"}
            # if len(required_fields.intersection(exif_set)) > 0:
            #     with pyexiv2.Image(filepath.as_posix()) as img:
            #         file_exif = img.read_exif()
            #     exif_update = {
            #         "Exif.Image.ImageWidth": file_exif["Exif.Image.ImageWidth"],
            #         "Exif.Image.ImageLength": file_exif["Exif.Image.ImageLength"],
            #         "Exif.Image.Orientation": file_exif["Exif.Image.Orientation"],
            #     }

            # fix_crop
            final_fix = {}
            if "CropTop" in required_fields:
                final_fix["Xmp.crs.CropTop"] = 0.0
            if "CropRight" in required_fields:
                final_fix["Xmp.crs.CropRight"] = 1.0
            if "CropLeft" in required_fields:
                final_fix["Xmp.crs.CropLeft"] = 0.0
            if "CropBottom" in required_fields:
                final_fix["Xmp.crs.CropBottom"] = 1.0
            if "CropAngle" in required_fields:
                final_fix["Xmp.crs.CropAngle"] = 0.0

            # disable update in No-Op Mode
            if update_file:
            final_xmp.modify_xmp(final_fix)
                logger.error(f"Final_XMP - Fixed: {final_fix.keys()}")

    final_xmp.close()

    # clean up temp folder:
    tempdir.cleanup()


def main():
    with ExifTool() as et:
    for i, data_series in df.iterrows():
        logger.info(
                f"Index: {i}, name: {data_series.loc['PathFromRoot']}{data_series.loc['BaseName']}.{data_series.loc['FileType']}"
        )
            process_file(data_series=data_series, et=et, update_file=False)


if __name__ == "__main__":
    logger.info("Running main()")
    main()
