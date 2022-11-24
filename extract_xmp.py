import importlib
import sqlite3

import pandas as pd
import pyexiv2
import seaborn as sns
from logzero import logger
from slpp import slpp as lua
import pathlib
import yaml

logger.setLevel(level="INFO")
#load settings
config = importlib.resources.files("untracked").joinpath("config.yml")

with open(config, 'r') as c_file:
    config_data = yaml.load(c_file, Loader=yaml.SafeLoader)

root_path=pathlib.Path(config_data["root_path"])

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






def parse_lightroom_processtext_to_xmp(lightroom_processtext:str, tags:list[str], process_ver:float=6.7):
    """Process lightroom parameters compatible with darktable. 
    See https://github.com/darktable-org/darktable/blob/master/src/develop/lightroom.c for info."""

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


    if lightroom_processtext[0:4] == "s = ":
        data = lua.decode(lightroom_processtext[4:])
    else:
        logger.critical("unexpected start to lua string")
        raise (BaseException("unexpected start to lua string"))

    # extract intersection with what darktable can handle
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
            logger.warning(f"not sure how to handle {key}, {val}")
            temp_string = f'   crs:{key}="{val}"\n'
            # temp_string=f'   crs:{key}={val}\n'

        crs_items.append(temp_string)
    
    generated_xmp=start + "".join(crs_items) + end


    return generated_xmp


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



def create_paths(root_path,relative_path,extension):
    raise NotImplementedError("In Progress")
    """From the relative path, root, and extension, create paths to the possible files"""
    pass
    relative_path=df.loc[0,"PathFromRoot"]+df.loc[0,"BaseName"]+"."+df.loc[0,"FileType"]
    
    # combine path
    filepath=pathlib.Path(root_path,relative_path)

    



def load_file():
    """read file XMP"""
    raise NotImplementedError("In Progress")

def load_sidecar():
    """read sidecar XMP"""
    raise NotImplementedError("In Progress")

    #start with lightroom format: file.xmp

    #also check darktable format: file.ext.xmp



# TODO:
# Read XMP from database
# convert process text to XMP
# Read Sidecar XMP
# read file XMP
# stack all XMP data file, sidecar, db_xmp, then processtext

i=3
temp_path=df.loc[i,"BaseName"]+"."+df.loc[i,"FileType"]
lightroom_temp_path=df.loc[i,"BaseName"]+".xmp"
lightroom_processtext=df.loc[i,"processtext"]
process_ver=df.loc[i,"processversion"]
db_xmp=df.loc[i,"xmp"]

# combine path
filepath=pathlib.Path(root_path,temp_path)
filepath_lr_xmp=pathlib.Path(root_path,lightroom_temp_path)

#open original file
# with pyexiv2.Image(filepath.as_posix()) as img:
#     file_xmp = img.read_xmp()
#     file_exif = img.read_exif()


intersect_dict=parse_lightroom_processtext(lightroom_processtext=lightroom_processtext, tags=tags, process_ver=process_ver)

#open sidecar and update
lr_xmp_file = pyexiv2.Image(filepath_lr_xmp.as_posix())
# exif = img.read_exif()
# iptc = img.read_iptc()
# xmp = img.read_xmp()
xmp = lr_xmp_file.read_xmp()
raw_xmp=lr_xmp_file.read_raw_xmp()
lr_xmp_file.modify_xmp(intersect_dict)
lr_xmp_file.close()




# TODO: /dev/shm is a ramdisk. Create files here for ephemeral transformations that require writing to disk
# generated_xmp=parse_lightroom_processtext_to_xmp(lightroom_processtext=lightroom_processtext, tags=tags, process_ver=process_ver)
# print(generated_xmp)

# Read XMP from database
# convert process text to XMP
# Read Sidecar XMP
# read file XMP
# stack all XMP data file, sidecar, db_xmp, then processtext


temp_dir=pathlib.Path("/dev/shm/xmp_editing")
temp_files={
    "orig":pathlib.Path(temp_dir,"orig.xmp"),
    "db":pathlib.Path(temp_dir,"db.xmp"),
    "sidecar1":pathlib.Path(temp_dir,"sidecar.xmp"),
    "sidecar2":pathlib.Path(temp_dir,"sidecar.ext.xmp"),
}

temp_files["orig"]


# paths: original file xmp copy, database xmp, sidecar file.xmp, sidecar file.ext.xmp, 
# create files
# stack data
# copy back
# delete files


temp_dir.mkdir(parents=True, exist_ok=True)
with open(temp_files["orig"], 'w') as f:
    f.write(raw_xmp)

with pyexiv2.Image(temp_files["orig"].as_posix()) as img:
    file_xmp = img.read_xmp()



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

