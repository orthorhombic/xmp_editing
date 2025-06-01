import os
import re
import pyexiv2
import glob
from pathlib import Path
import logzero
from logzero import logger
import importlib.resources
import yaml
import datetime

logzero.logfile("update_xmp_logfile.log", maxBytes=1e8, backupCount=3)

# Goals
# - If filepath ends in Undated, do not attempt to add date
# - For each file, extract the year, month, day from the filepath
# - If the day is not available from the filepath, make the day 1
# - Read the exif data to get the timestamp of the capture (so we can keep the order of the pictures)
# - (ignore) If the year in the exif data is >2015, Write a new date to the file with the year,month,day from the folder, and timestamp from original file.
# - Only update date fields if they already exist.
# - Throw an error if there is a date field not already in the list of update fields or exempt fields.

# TODO: find all image files and add an xmp if it doesn't exist (not necessary if run after cropping because that creates an xmp file for every image)

DATE_FIELDS = [
    "Xmp.tiff.DateTime",
    "Xmp.exif.DateTimeOriginal",
    "Xmp.xmp.MetadataDate",
    "Xmp.xmp.CreateDate",
    "Xmp.xmp.ModifyDate",
    "Xmp.photoshop.DateCreated",
]
SKIP_FIELDS = [
    "Xmp.digiKam.CaptionsDateTimeStamps",
]
EXPECTED_FIELDS = DATE_FIELDS + SKIP_FIELDS


def update_xmp_dates(directory: Path, dry_run: bool = True):
    xmp_files = find_xmp_files(directory)
    for file in xmp_files:
        file = Path(file)
        date = get_date_from_path(file)
        if date:
            update_xmp_date(file=file, date=date, dry_run=dry_run)


def find_xmp_files(directory: Path) -> list[str]:
    xmp_files = glob.glob(os.path.join(directory, "**/*.xmp"), recursive=True)
    xmp_files2 = glob.glob(os.path.join(directory, "**/*.XMP"), recursive=True)
    return xmp_files + xmp_files2


def get_date_from_path(file: Path):
    # match = re.search(r"(\d{4})/(\d{2})(?:/(\d{2}))?", file.as_posix()) # requires 2-3
    match = re.search(
        r"(?:/)(\d{4})(?:/(\d{2})(?:/(\d{2}))?)?", file.as_posix()
    )  # requires 1-3
    if match:
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else 1
        day = int(match.group(3)) if match.group(3) else 1
        logger.info(f"{year},{month},{day},{file}")
        return year, month, day
    return None


def update_xmp_date(file: Path, date: tuple, dry_run: bool):
    with pyexiv2.Image(file.as_posix()) as xmp_file:
        xmp_data = xmp_file.read_xmp()
    parsed_time = None

    # get all date fields:
    date_fields = []
    for key, val in xmp_data.items():
        if key.lower().find("date") != -1:
            logger.debug(f"{key}, {val}")
            date_fields.append(key)
    # check for unexpected keys:
    if not set(EXPECTED_FIELDS).issuperset(set(date_fields)):
        error = f"Unexpected value(s) in date fields: {set(date_fields).difference(set(EXPECTED_FIELDS))}"
        logger.critical(error)
        raise ValueError(error)

    time = xmp_data.get("Xmp.exif.DateTimeOriginal")
    if not time:
        image_path_list = list(
            Path(file).parent.glob(f"{Path(file).name.split('.')[0]}.*[!xmp]")
        )
        if len(image_path_list) > 1:
            logger.warning(f"There are multiple images files corresponding to {file}")

        image_path = image_path_list[0]

        # open image file to get data from there
        with pyexiv2.Image(image_path.as_posix()) as image_file:
            image_data = image_file.read_exif()
        time = image_data.get("Exif.Photo.DateTimeOriginal")
        if not time:
            # fall back to file data
            epoch = os.path.getctime(image_path)
            parsed_time = datetime.datetime.fromtimestamp(epoch)
    if not parsed_time:
        try:
            parsed_time = datetime.datetime.fromisoformat(time)
        except ValueError:
            if len(time) > 19:
                parsed_time = datetime.datetime.strptime(time, "%Y:%m:%d %H:%M:%S.%f")
            else:
                parsed_time = datetime.datetime.strptime(time, "%Y:%m:%d %H:%M:%S")

    new_date_string = combine_date_and_time(date, parsed_time)
    metadata_update = {}
    # update all date fields found
    for key in date_fields:
        metadata_update[key] = new_date_string
    # make sure datetime original is set no matter what (may set it twice)
    metadata_update["Xmp.exif.DateTimeOriginal"] = new_date_string
    metadata_update["Xmp.xmp.MetadataDate"] = new_date_string
    metadata_update["Xmp.xmp.CreateDate"] = new_date_string
    metadata_update["Xmp.xmp.ModifyDate"] = new_date_string

    logger.info(f"Before: {time}, After: {new_date_string}")

    if not dry_run:
        # write metadata
        with pyexiv2.Image(file.as_posix()) as xmp_file:
            xmp_data = xmp_file.modify_xmp(metadata_update)


def combine_date_and_time(date: tuple[int, int, int], time) -> str:
    year, month, day = date
    hour, minute, second = time.hour, time.minute, time.second
    date_string = f"{year}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
    # test that iso format parsing works
    datetime.datetime.fromisoformat(date_string)
    return date_string


config = importlib.resources.files("untracked").joinpath("update_config.yml")

with open(config) as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

if config_data.get("root_path") is not None:
    root_path = Path(config_data["root_path"])  # default "untracked"
else:
    root_path = "untracked"

if config_data.get("dry_run") is not None:
    dry_run = config_data["dry_run"]
else:
    dry_run = True

update_xmp_dates(root_path, dry_run=dry_run)
