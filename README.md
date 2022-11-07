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
* Successfully generate a cropped image in darktable from a raw vuescan dng file.
* dry run by creating xmp files in a separate directory tree mirroring the lightroom database
* only write xmp file if base file exists in the expected directory
* refine the sql query to avoid getting multiple rows if there are virtual copies
  * examine whether virtual copies could be carried over to Darktable
  * otherwise
* add logging to measure progress and throw warnings
* 


## Testing needed:
* What happens when the tiff entries in the XMP file are missing (e.g. for jpeg)
* how does the cropping and data import work with jpegs?
* test spot adjustment handling
