import sqlite3

import pandas as pd
import seaborn as sns

# Create your connection.
cnx = sqlite3.connect("Lightroom Catalog.lrcat")


df = pd.read_sql_query("SELECT * FROM Img", cnx)
sns.histplot(data=df, x="FocalLength")


sns.histplot(data=df.loc[df.Lens == "EF24-105mm f/4L IS USM"], x="FocalLength")
sns.histplot(data=df.loc[df.Lens == "Canon EF 24-105mm f/4L IS"], x="FocalLength")
sns.histplot(data=df.loc[df.Lens == "EF70-200mm f/2.8L IS II USM"], x="FocalLength")
sns.histplot(
    data=df.loc[df.Lens == "EF70-200mm f/2.8L IS II USM +1.4x III"], x="FocalLength"
)


sns.histplot(data=df.loc[df.CaptureTime > "2015-01-01T12:48:25"], x="FocalLength")
sns.histplot(
    data=df.loc[
        (df.CaptureTime > "2015-01-01T12:48:25") & (df.Lens == "EF24-105mm f/4L IS USM")
    ],
    x="FocalLength",
)
