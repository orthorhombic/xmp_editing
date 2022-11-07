-- originally inspired by https://www.dpreview.com/forums/post/62188768

-- DROP VIEW Img
CREATE VIEW Img AS
SELECT
AgLibraryRootFolder.name AS RootFolderName,
AgLibraryFolder.pathFromRoot AS PathFromRoot,
AgLibraryFile.baseName AS BaseName,
AgLibraryFile.extension AS FileType,
Adobe_images.captureTime as CaptureTime,
--AgLibraryFile.originalFilename AS OriginalFileName,
COALESCE(Adobe_images.rating,0) AS Rating,
Adobe_images.colorLabels AS ColorLabel,
Adobe_images.touchCount AS TouchCount,
AgHarvestedExifMetadata.focalLength AS FocalLength, -- focal length mm
ROUND(AgHarvestedExifMetadata.aperture,3) AS Aperture,
AgHarvestedExifMetadata.shutterSpeed AS ShutterSpeed, --format not understood
ROUND(AgHarvestedExifMetadata.isoSpeedRating,0) AS ISO,
COALESCE(AgInternedExifCameraModel.value,"Unknown camera") AS Camera,
COALESCE(AgInternedExifLens.value,"Unknown lens") AS Lens,
-- COALESCE(ModCount.EditCount,0) AS EditCount -- remove this to avoid depedency on ModCount view
Adobe_AdditionalMetadata.xmp as xmp,
Adobe_imageDevelopSettings.processversion as processversion,
Adobe_imageDevelopSettings.text as processtext

FROM
AgLibraryFile -- every image in catalog has an entry in this table
LEFT JOIN AgLibraryFolder ON AgLibraryFolder.id_local=AgLibraryFile.folder
LEFT JOIN AgLibraryRootFolder ON AgLibraryRootFolder.id_local=AgLibraryFolder.rootFolder
LEFT JOIN Adobe_images ON AgLibraryFile.id_local=Adobe_images.rootFile
LEFT JOIN AgHarvestedExifMetadata ON AgHarvestedExifMetadata.image = Adobe_images.id_local
LEFT JOIN AgInternedExifCameraModel ON AgInternedExifCameraModel.id_local = AgHarvestedExifMetadata.cameraModelRef
LEFT JOIN AgInternedExifLens ON AgInternedExifLens.id_local = AgHarvestedExifMetadata.lensRef
-- LEFT JOIN ModCount ON ModCount.image = Adobe_images.id_local -- remove this to avoid depedency on ModCount view
LEFT JOIN Adobe_AdditionalMetadata on Adobe_images.id_local = Adobe_AdditionalMetadata.image 
LEFT JOIN Adobe_imageDevelopSettings on Adobe_images.id_local = Adobe_imageDevelopSettings.image 
where copyName is Null -- to select only the first copy and avoid xml duplicates