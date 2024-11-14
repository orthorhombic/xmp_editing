# xmp_editing

Initially focused on the migration of Lightroom database info into Darktable

## Workflow for processing scanned photos

1. Load files into digikam
   1. Rotate, using the function to update exif tags.
   2. Add captions or tags like "no_mirror"
2. Apply crop with `python generate_crop_xmp.py`
3. Run import with darktable 4.8.0. Make sure thumbnails are set to small so it uses jpeg thumbnails and does not start processing. Enter darktable mode and look for the text to pop up that the crop has been applied. Iterate through each file by using `space` to move forward in the list of pictures. Use [input-remapper](https://github.com/sezanzeb/input-remapper) as a method to automate this process. A pause of 0.6 seconds seems to be sufficient for the image crop to process.
   1. Inspect files for any scanning defects
4. Using digikam, move files into folders organized by date (e.g 1970/12/31)
5. Update the xmp dates with `python update_xmp_dates.py `
6. Remove any extra files (e.g. crop debug) and back up to server

## Migration of xmp data

Loading order (inverse priority):

1. filename.ext
1. filename.xmp (generated from lightroom or captureone, consider whether to keep it.)
1. lightroom xmp object
1. lightroom Adobe_imageDevelopSettings

Prioritize only those fields which darktable can read in (tags/tags_from_darktable.txt). These were derived from https://github.com/darktable-org/darktable/blob/master/src/develop/lightroom.c

Other fields can be added if they are present in `tags/crs_tags.txt` which is derived from https://exiftool.org/TagNames/XMP.html#crs

Cleanup:
Remove `<xmp:Label>None</xmp:Label>` because it evaluates to a purple label.

## Requirements/Running

To function, this needs both exiv2 and exiftool installed. On Linux, this can be accomplished with apt:
`sudo apt install exiv2`
`sudo apt install exiftool`

Create a folder called `untracked` and add `config.yml` with your desired configuration. An example is below:

```yaml
root_path: "/media/my_files/Image Library"
update_file: True
catalog_file: "LightroomCatalog.lrcat"
RootFolderName: "Image Library"
```

The view described in `img_view.sql` must be created in the sqlite database (your catalog) before operation. Therefore it is recommended to make a separate copy in the `untracked` folder.

Before running, you must also select a single root directory on which you want to operate. Populate this in the config.yml file as in the example.

To run:

```bash
python extract_xmp.py
```

## Create crop xmp

Before running, you must also select a single root directory on which you want to operate. Populate this in the crop_config.yml file as in the example below.

Create a folder called `untracked` and add `config.yml` with your desired configuration. An example is below:

```yaml
root_path: "/media/my_files/Image Library"
debug: True
crop_addition: -5
threshold: 60
blur_radius: 6
max_workers: 6
mirror: False
# https://github.com/Beep6581/RawTherapee/blob/0bee94e4aa149e9bb6b31a52925b8dda9493223d/rtengine/camconst.json#L1263
# left crop, top crop, wholeframewidth, wholeframeheight
raw_crop: [128, 96, 8352, 5586] # R5
```

To run:

```bash
python generate_crop_xmp.py
```

The file workflow to handle rotated images is to process the rotation/tagging in digikam prior to loading files into darktable.

For importing into darktable (as of 4.8), the "preferences>storage>create xmp files" seting must be set to "on import" and the "preferences>lighttable>thumbnails>use raw file..." must be set to never for the settings to load from XMP. Upon opening the files in darktable, the files must be cycled through the darkroom module to update the darktable xmp with the appropriate metadata.

## Todo

- refine the sql query to avoid getting multiple rows if there are virtual copies
  - examine whether virtual copies could be carried over to Darktable

## Immediate next steps

- Test workflow of pulling image data, combine with file.xmp, combine with in-memory DB xmp. lastly update with developsettings - all in memory handling to avoid writes

## Testing needed:

- test spot adjustment handling

## Quick command reference

```bash
pre-commit run --all-files


exiftool -xmp -b -w xmp fileB.dng
exiftool -tagsfromfile file.dng -XMP:all -tagsfromfile file.xmp -XMP:all -tagsfromfile file.dng.xmp -XMP:all -o file.multiple.xmp

```
