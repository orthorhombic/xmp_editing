import importlib
import sqlite3

import pandas as pd
import pyexiv2
import seaborn as sns
from logzero import logger
from slpp import slpp as lua
import pathlib
import yaml
import shutil

logger.setLevel(level="INFO")
#load settings
config = importlib.resources.files("untracked").joinpath("config.yml")

with open(config, 'r') as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

root_path=pathlib.Path(config_data["root_path"])

# set up temp folder in tmpfs to keep it in memory
# /dev/shm is a ramdisk. Create files here for ephemeral transformations that require writing to disk
temp_dir=pathlib.Path("/dev/shm/xmp_editing")
temp_dir.mkdir(parents=True, exist_ok=True)

# load tags darktable can process:
# with importlib.resources.files("tags").joinpath("crs_tags.txt").open('r', encoding="utf8") as f:
with importlib.resources.files("tags").joinpath("tags_from_darktable.txt").open(
    "r", encoding="utf8"
) as f:
    tags = f.read().splitlines()

# test query of the view created in img_view.sql
sql_query="""
select * from IMG
WHERE baseName like 'Crystal-0075%'
or baseName like 'Crystals-1600%'
or baseName like 'London-3471%'
or baseName like 'LWP42267%'


"""

#Creating the path to the lightroom catalog
catalog = importlib.resources.files("untracked").joinpath("LightroomCatalog.lrcat")

# Create your connection.
cnx = sqlite3.connect(catalog)
# Load all files and their xmp/processing data into memory
# not very efficient, but probably OK for 100k photos
df = pd.read_sql_query(sql_query, cnx)
cnx.close()





def parse_lightroom_processtext(lightroom_processtext:str, tags:list[str], process_ver:float=6.7):
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

    return intersect_dict



def copy_xmp_temp(from_file:pathlib.PosixPath, to_file:pathlib.PosixPath):
    try:
        # open source file
        with pyexiv2.Image(from_file.as_posix()) as img:
            file_raw_xmp = img.read_raw_xmp()
        # write data to temp
        with open(to_file, 'w') as f:
            f.write(file_raw_xmp)
    except RuntimeError:
        logger.debug(f"file not found: {from_file}")


def extend_xmp(base:pyexiv2.core.Image,xmp_file:pathlib.PosixPath):

    with pyexiv2.Image(xmp_file.as_posix()) as img:
        file_xmp = img.read_xmp()

    # update xmp data
    base.modify_xmp(file_xmp)

    return base

# TODO:
# Read XMP from database
# convert process text to XMP
# Read Sidecar XMP
# read file XMP
# stack all XMP data file, sidecar, db_xmp, then processtext

i=3
temp_path=df.loc[i,"BaseName"]+"."+df.loc[i,"FileType"]
lr_xmp_path=df.loc[i,"BaseName"]+".xmp"
darktable_xmp_path=df.loc[i,"BaseName"]+"."+df.loc[i,"FileType"]+".xmp"
lightroom_processtext=df.loc[i,"processtext"]
process_ver=df.loc[i,"processversion"]
db_xmp=df.loc[i,"xmp"]

# combine path
filepath=pathlib.Path(root_path,temp_path)
filepath_lr_xmp=pathlib.Path(root_path,lr_xmp_path)
filepath_darktable_xmp=pathlib.Path(root_path,darktable_xmp_path)



temp_files={
    "orig":pathlib.Path(temp_dir,"orig.xmp"),
    "db":pathlib.Path(temp_dir,"db.xmp"),
    "sidecar_lr":pathlib.Path(temp_dir,"sidecar.xmp"),
    "sidecar_darktable":pathlib.Path(temp_dir,"sidecar.ext.xmp"),
}


# Create temp files from extracted data

if filepath.is_file():
    copy_xmp_temp(filepath, temp_files["orig"])
else:
    raise FileNotFoundError(f"Not found: {filepath}")


# write database XMP to temp
with open(temp_files["db"], 'w') as f:
    f.write(db_xmp)

# try sidecar files
# # TODO: case insensitive implementation
copy_xmp_temp(filepath_lr_xmp, temp_files["sidecar_lr"])
copy_xmp_temp(filepath_darktable_xmp, temp_files["sidecar_darktable"])

# prepare data from database for stacking
intersect_dict=parse_lightroom_processtext(lightroom_processtext=lightroom_processtext, tags=tags, process_ver=process_ver)


# stack data
new_xmp = pyexiv2.Image(temp_files["orig"].as_posix())



new_xmp=extend_xmp(new_xmp,temp_files["db"])
if temp_files["sidecar_lr"].is_file():
    new_xmp=extend_xmp(new_xmp,temp_files["sidecar_lr"])
if temp_files["sidecar_darktable"].is_file():
    new_xmp=extend_xmp(new_xmp,temp_files["sidecar_darktable"])



new_xmp.modify_xmp(intersect_dict)



# copy data back to LR format file


if filepath_lr_xmp.is_file():
    # update
    with pyexiv2.Image(filepath_lr_xmp.as_posix()) as img:
        img.modify_xmp(new_xmp.read_xmp())

else:
    # copy
    shutil.copy(temp_files["orig"], filepath_lr_xmp)


new_xmp.close()




# paths: original file xmp copy, database xmp, sidecar file.xmp, sidecar file.ext.xmp, 
# create files
# stack data
# copy back
# delete files






# TODO: /dev/shm is a ramdisk. Create files here for ephemeral transformations that require writing to disk
# generated_xmp=parse_lightroom_processtext_to_xmp(lightroom_processtext=lightroom_processtext, tags=tags, process_ver=process_ver)
# print(generated_xmp)

# Read XMP from database
# convert process text to XMP
# Read Sidecar XMP
# read file XMP
# stack all XMP data file, sidecar, db_xmp, then processtext









# Cleanup temp files:
for key,val in temp_files.items():
    try:
        val.unlink()
    except FileNotFoundError:
        logger.debug(f"file not found for cleanup: {key}, {val}")
        pass


#need check to confirm there is an exif block with resolution in it
# if HasCrop:
#     needs:
#         ImageWidth
#         ImageLength
#         Orientation

def process_file(filepath:str,database_info):
    raise NotImplementedError("In Progress")
    #load the file first, abort if it isn't there
    try:
        img_xmp = load_file(filepath)
    except BaseException:
        logger.warning(f"File {filepath} not found")
        

    # keep going and load xmp file info if it's there
    sidecar_files=[filepath.ext.xmp, filepath.xmp]

    sidecar_xmp=""
    for sidecar_file in sidecar_files:
        try:
            sidecar_xmp = load_file(filepath)
            break #break after found item
        except BaseException:
            logger.warning(f"File {sidecar_file} not found")
        
    #combine xmp into single object/string


    #update existing xmp or write new file
    # if sidecar_file is path:
        # open and inject
    # else:
        # write new file



# clean up temp folder:
temp_dir.rmdir()