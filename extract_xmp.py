import importlib
import pathlib
import re
import shutil
import sqlite3
import tempfile

import pandas as pd
import pyexiv2
import yaml
from logzero import logger
from slpp import slpp as lua

# NOTE: After import into darktable, the metadata "refresh EXIF" button needs to be pressed
# This will sync the database with the new darktable xmp files

pyexiv2.set_log_level(1)
logger.setLevel(level="DEBUG")
# load settings
config = importlib.resources.files("untracked").joinpath("config.yml")

with open(config) as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

root_path = pathlib.Path(config_data["root_path"])


# load tags darktable can process:
# with importlib.resources.files("tags").joinpath("crs_tags.txt").open('r', encoding="utf8") as f:
with importlib.resources.files("tags").joinpath("tags_from_darktable.txt").open(
    "r", encoding="utf8"
) as f:
    tags = f.read().splitlines()

# test query of the view created in img_view.sql
sql_query = """
select * from IMG
WHERE baseName like 'Crystal-0075%'
or baseName like 'Crystals-1600%'
or baseName like 'London-3471%'
or baseName like 'LWP42267%'


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
    lightroom_processtext: str, tags: list[str], process_ver: float = 6.7
):
    """Process lightroom parameters compatible with darktable.
    See https://github.com/darktable-org/darktable/blob/master/src/develop/lightroom.c for info."""

    if lightroom_processtext[0:4] == "s = ":
        data = lua.decode(lightroom_processtext[4:])
    else:
        logger.critical("unexpected start to lua string")
        raise (BaseException("unexpected start to lua string"))

    tagintersect = set(tags).intersection(set(data.keys()))
    intersect_dict = {f"Xmp.crs.{k}": data[k] for k in tagintersect}
    if "Xmp.crs.CropTop" in intersect_dict.keys():
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

    return intersect_dict


def copy_xmp_temp(from_file: pathlib.PosixPath, to_file: pathlib.PosixPath):
    try:
        # open source file
        with pyexiv2.Image(from_file.as_posix()) as img:
            file_raw_xmp = img.read_raw_xmp()
        # write data to temp
        with open(to_file, "w") as f:
            f.write(file_raw_xmp)
    except RuntimeError as e:
        logger.debug(f"Problem working on {from_file}: {e}")


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


def drop_fields(xmp_dict: dict):
    """Operates in place on the provided XMP dictionary to remove problematic entries.
    These include accompanying tags for anything with 'type="Struct"' or 'type="Seq"'
    """
    keys_list = list(xmp_dict.keys())
    bad_keys = []
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


def process_file(data_series):

    temp_path = data_series.loc["BaseName"] + "." + data_series.loc["FileType"]
    lr_xmp_path = data_series.loc["BaseName"] + ".xmp"
    darktable_xmp_path = (
        data_series.loc["BaseName"] + "." + data_series.loc["FileType"] + ".xmp"
    )
    lightroom_processtext = data_series.loc["processtext"]
    process_ver = data_series.loc["processversion"]
    db_xmp = data_series.loc["xmp"]

    # combine path
    filepath = pathlib.Path(root_path, temp_path)
    filepath_lr_xmp = pathlib.Path(root_path, lr_xmp_path)
    filepath_darktable_xmp = pathlib.Path(root_path, darktable_xmp_path)

    # check the file first, abort if it isn't there
    if not filepath.is_file():
        logger.info(f"File {filepath} not found")
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

    # temporarilty change the log level to allow reading of the xmp data
    pyexiv2.set_log_level(4)
    # Create temp files from extracted data
    copy_xmp_temp(filepath, temp_files["orig"])

    # write database XMP to temp
    with open(temp_files["db"], "w") as f:
        f.write(db_xmp)

    # try sidecar files
    # # TODO: case insensitive implementation
    copy_xmp_temp(filepath_lr_xmp, temp_files["sidecar_lr"])
    copy_xmp_temp(filepath_darktable_xmp, temp_files["sidecar_darktable"])

    # change back to normal log level to observe xmp updating
    pyexiv2.set_log_level(1)

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
        logger.error(f"Problematic XMP: {field_to_delete} deleted")

    # apply fixes to ensure clean write
    # new_xmp_dict = _fix_xmp(new_xmp_dict)

    if filepath_lr_xmp.is_file():
        # update
        # copy data back to LR format file
        with pyexiv2.Image(filepath_lr_xmp.as_posix()) as img:
            # img.read_xmp()
            img.modify_xmp(combined_xmp)
            img_xmp = img.read_xmp()
        logger.debug(f"updated {filepath_lr_xmp}")
    else:

        new_xmp = pyexiv2.Image(temp_files["orig"].as_posix())

        new_xmp.modify_xmp(combined_xmp)

        new_xmp.close()

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

    final_xmp_dict = final_xmp.read_xmp()

    # Final check of output file
    label = final_xmp_dict.get("Xmp.xmp.Label")
    if label == "None":
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
            logger.error(f"Final_XMP - Missing required fields: {required_fields}")

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

            # crop_set = {
            #     "CropTop",
            #     "CropRight",
            #     "CropLeft",
            #     "CropBottom",
            #     "CropAngle",
            # }

    # clean up temp folder:
    tempdir.cleanup()


for i, data_series in df.iterrows():
    logger.info(f"Index: {i}, name: {data_series.loc['BaseName']}")
    process_file(data_series)
