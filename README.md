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

## Todo:

- Successfully generate a cropped image in darktable from a raw vuescan dng file.
- dry run by creating xmp files in a separate directory tree mirroring the lightroom database
- only write xmp file if base file exists in the expected directory
- refine the sql query to avoid getting multiple rows if there are virtual copies
  - examine whether virtual copies could be carried over to Darktable
  - otherwise
- add logging to measure progress and throw warnings

## Immediate next steps:

- add ability to create an xmp file from scratch if none exists - look at exiftool
- convert to using `with pyexiv2.Image(...`)
- look at pyexiftool https://github.com/sylikc/pyexiftool
- Test workflow of pulling image data, combine with file.xmp, combine with in-memory DB xmp. lastly update with developsettings - all in memory handling to avoid writes

## Testing needed:

- What happens when the tiff entries in the XMP file are missing (e.g. for jpeg)
- how does the cropping and data import work with jpegs?
- test spot adjustment handling

## Quick command reference

```bash
pre-commit run --all-files


exiftool -xmp -b -w xmp fileB.dng
exiftool -tagsfromfile file.dng -XMP:all -tagsfromfile file.xmp -XMP:all -tagsfromfile file.dng.xmp -XMP:all -o file.multiple.xmp

```
