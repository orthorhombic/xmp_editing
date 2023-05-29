# xmp_editing

Initially focused on the migration of Lightroom database info into Darktable

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
```

To run:

```bash
python generate_crop_xmp.py
```

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
