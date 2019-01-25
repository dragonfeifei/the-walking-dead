from pyspark.sql import SQLContext
import pyspark
from pyspark import SparkContext, SparkConf
import os
import pyspark.sql.functions as F
from argparse import ArgumentParser
from datetime import datetime

os.environ["PYSPARK_PYTHON"]="/usr/bin/python3"
os.environ["PYSPARK_DRIVER_PYTHON"]="/usr/bin/python3"

parser = ArgumentParser()
parser.add_argument("-d", "--date", dest="date",
                    required=True, help="YYYYMMDD")
parser.add_argument("-c", "--category", dest="category",
                    help="specific category to query")

args = parser.parse_args()

date = datetime.strptime(args.date, '%Y%m%d')

conf = SparkConf()

conf = conf.setAppName("get_amazon_reviews")

conf = conf.setMaster("spark://ip-10-0-0-11.us-west-2.compute.internal:7077")


sc = SparkContext(conf = conf)
sql = SQLContext(sc)

if args.category:
    s3_path = "s3a://amazon-reviews-pds/parquet/product_category=" + args.category
else:
    s3_path = "s3a://amazon-reviews-pds/parquet/"

df = sql.read.parquet(s3_path)

df = df.filter(df.review_date <= date).groupBy('product_id').agg(F.avg('star_rating').alias("rating"))

df.show(20)
