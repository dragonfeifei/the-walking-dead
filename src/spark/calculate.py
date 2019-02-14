from pyspark.sql import SQLContext
import pyspark
from pyspark import SparkContext, SparkConf
import os
import pyspark.sql.functions as F
from argparse import ArgumentParser
from datetime import datetime

# Make sure we are using python 3
os.environ["PYSPARK_PYTHON"]="/usr/bin/python3"
os.environ["PYSPARK_DRIVER_PYTHON"]="/usr/bin/python3"

# Get passed-in arguments
parser = ArgumentParser()
parser.add_argument("-d", "--date", dest="date",
                    required=True, help="YYYYMMDD")
parser.add_argument("-c", "--category", dest="category",
                    help="specific category to query")

args = parser.parse_args()

date = datetime.strptime(args.date, '%Y%m%d')


# Get Spark Context
conf = SparkConf() \
    .setAppName("get_amazon_reviews") \
    .setMaster("spark://ip-10-0-0-11.us-west-2.compute.internal:7077")

sc = SparkContext(conf = conf)
sql = SQLContext(sc)

if args.category:
    s3_path = "s3a://amazon-reviews-pds/parquet/product_category=" 
              + args.category
else:
    s3_path = "s3a://amazon-reviews-pds/parquet/"

# Pull review data from s3
df = sql.read.parquet(s3_path)

df = df.filter(df.review_date <= date) \
    .groupBy('product_id') \
    .agg(F.avg('star_rating').alias("rating")) \
    .withColumn("by_date", F.lit(date))

df.show(20)


# Write to result database
df.write.format('jdbc').options(
      url='jdbc:mysql://10.0.0.11/resultdb',
      driver='com.mysql.jdbc.Driver',
      dbtable='ratings',
      user='user',
      password='user').mode('append').save()
